"""Scheduled + rideshare lifecycles through legacy and v4 endpoints, and the
foundation admin API (spec §4.2, §4.4, §19)."""
from datetime import datetime, timedelta

from backend.models import db
from backend.models.money import RidePayment
from backend.models.platform import AuditLog, TripEvent
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.services.payments import payment_service as PS
from backend.services.payments.gateway import get_gateway
from tests.conftest import body


def stages(rt, rid):
    return [e.to_stage for e in TripEvent.query.filter_by(ride_type=rt, ride_id=rid).order_by(TripEvent.id)]


# ── scheduled booking (courier / airport / special car) ─────────────────────

def test_scheduled_booking_lifecycle(client, auth, make_user):
    customer, driver, admin = make_user('customer'), make_user('driver'), make_user('admin')
    r = client.post('/api/bookings', headers=auth(customer), json={
        'service_type': 'airport', 'pickup_lat': 43.6777, 'pickup_lng': -79.6248, 'pickup_address': 'YYZ T1',
        'destination_lat': 43.6532, 'destination_lng': -79.3832, 'destination_address': 'City Hall',
        'customer_proposed_price': 6000, 'passengers': 2,
        'scheduled_at': (datetime.utcnow() + timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')})
    assert r.status_code == 201, r.get_json()
    bid = body(r)['data']['id']
    assert body(r)['data']['trip_stage'] == 'REQUESTED'
    # a stranger can no longer cancel or price someone else's booking
    stranger = make_user('customer')
    assert client.post(f'/api/bookings/{bid}/cancel', headers=auth(stranger)).status_code == 403
    assert client.post(f'/api/bookings/{bid}/propose-price', headers=auth(stranger), json={'price': 100}).status_code == 403
    # admin assigns the driver; driver proposes; customer accepts
    assert body(client.post(f'/api/bookings/{bid}/assign-driver', headers=auth(admin), json={'driver_id': driver.id}))['code'] == 1
    assert body(client.post(f'/api/bookings/{bid}/propose-price', headers=auth(driver), json={'price': 6500}))['code'] == 1
    r = client.post(f'/api/bookings/{bid}/accept-price', headers=auth(customer))
    assert body(r)['code'] == 1, r.get_json()
    db.session.rollback()
    b = db.session.get(ScheduledBooking, bid)
    assert b.trip_stage == 'AWAITING_PAYMENT' and b.agreed_price == 6500
    # driver cannot start unpaid
    r = client.post(f'/api/bookings/{bid}/start', headers=auth(driver))
    assert body(r)['code'] == 0 and 'paid' in body(r)['message']
    # pay → confirmed
    r = client.post(f'/api/bookings/{bid}/refresh-payment', headers=auth(customer))
    assert body(r)['data']['checkout_url'], r.get_json()
    rp = db.session.get(RidePayment, body(r)['data']['ride_payment_id'])
    assert rp.capture_method == 'manual'
    PS.handle_stripe_event(get_gateway().simulate_customer_pays(rp.checkout_session_id))
    db.session.rollback()
    b = db.session.get(ScheduledBooking, bid)
    assert b.trip_stage == 'CONFIRMED' and b.status == 'confirmed' and b.ride_pin
    # v4 flow: en route → arrived (geofence) → start → complete
    assert body(client.post(f'/api/rides/scheduled/{bid}/en-route', headers=auth(driver)))['code'] == 1
    r = client.post(f'/api/rides/scheduled/{bid}/arrived', headers=auth(driver), json={'lat': 43.6777, 'lng': -79.6248})
    assert body(r)['code'] == 1, r.get_json()
    assert body(client.post(f'/api/bookings/{bid}/start', headers=auth(driver)))['code'] == 1   # legacy start (v3 customer: no PIN)
    assert body(client.post(f'/api/bookings/{bid}/complete', headers=auth(driver)))['code'] == 1
    db.session.rollback()
    b = db.session.get(ScheduledBooking, bid)
    assert b.trip_stage == 'COMPLETED' and b.status == 'completed'
    assert db.session.get(RidePayment, rp.id).capture_status == 'captured'
    assert stages('scheduled', bid) == ['REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT', 'CONFIRMED',
                                        'DRIVER_EN_ROUTE', 'DRIVER_ARRIVED', 'IN_PROGRESS', 'COMPLETED']


def test_far_future_scheduled_booking_charges_immediately(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    r = client.post('/api/bookings', headers=auth(customer), json={
        'service_type': 'airport', 'pickup_lat': 43.6, 'pickup_lng': -79.6, 'pickup_address': 'A',
        'destination_lat': 43.7, 'destination_lng': -79.4, 'destination_address': 'B', 'customer_proposed_price': 5000,
        'scheduled_at': (datetime.utcnow() + timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S')})
    bid = body(r)['data']['id']
    b = db.session.get(ScheduledBooking, bid)
    b.driver_id = driver.id
    db.session.commit()
    client.post(f'/api/bookings/{bid}/accept-original-price', headers=auth(driver))
    r = client.post(f'/api/bookings/{bid}/refresh-payment', headers=auth(customer))
    rp = db.session.get(RidePayment, body(r)['data']['ride_payment_id'])
    assert rp.capture_method == 'automatic'


# ── rideshare trip + seat bookings ─────────────────────────────────────────

def _publish_trip(client, auth, driver, seats=3, hours_ahead=5, price=25):
    r = client.post('/api/trips-create', headers=auth(driver), json={
        'start_name': 'Toronto Union', 'end_name': 'Ottawa', 'start_gps': '43.6453,-79.3806',
        'end_pgs': '45.4215,-75.6972', 'price': price, 'slots': seats,
        'scheduled_start_time': (datetime.utcnow() + timedelta(hours=hours_ahead)).strftime('%Y-%m-%dT%H:%M:%SZ')})
    assert r.status_code == 201, r.get_json()
    return body(r)['data']['id']


def _book_and_pay(client, auth, customer, trip_id, seats=1):
    r = client.post('/api/trips-bookings-create', headers=auth(customer), json={'trip_id': trip_id, 'slot_count': seats})
    assert r.status_code == 201, r.get_json()
    bid = body(r)['data']['id']
    assert body(r)['data']['trip_stage'] == 'PENDING_PAYMENT'
    r = client.post(f'/api/rides/rideshare_booking/{bid}/pay', headers=auth(customer))
    assert body(r)['code'] == 1, r.get_json()
    rp = db.session.get(RidePayment, body(r)['data']['ride_payment_id'])
    PS.handle_stripe_event(get_gateway().simulate_customer_pays(rp.checkout_session_id))
    db.session.rollback()
    return bid, rp


def test_customers_cannot_publish_trips(client, auth, make_user):
    customer = make_user('customer')
    r = client.post('/api/trips-create', headers=auth(customer), json={'start_name': 'A', 'end_name': 'B', 'price': 10})
    assert body(r)['code'] == 0


def test_rideshare_full_lifecycle_and_cascade(client, auth, make_user):
    driver, c1, c2 = make_user('driver'), make_user('customer'), make_user('customer')
    trip_id = _publish_trip(client, auth, driver)
    trip = db.session.get(Trip, trip_id)
    assert trip.trip_stage == 'PUBLISHED' and trip.price_per_seat_cents == 2500 and trip.departure_at
    b1, rp1 = _book_and_pay(client, auth, c1, trip_id, seats=2)
    b2, rp2 = _book_and_pay(client, auth, c2, trip_id, seats=1)
    assert db.session.get(TripBooking, b1).trip_stage == 'CONFIRMED'
    assert db.session.get(TripBooking, b1).status == 'Reserved'
    assert db.session.get(RidePayment, rp1.id).amount_authorized_cents == 5000
    # sold out
    c3 = make_user('customer')
    r = client.post('/api/trips-bookings-create', headers=auth(c3), json={'trip_id': trip_id, 'slot_count': 1})
    assert body(r)['data']['error_code'] == 'sold_out'
    # a stranger can't flip a booking to Completed any more
    assert client.post('/api/trips-booking-status-update', headers=auth(c3),
                       json={'booking_id': b1, 'status': 'Completed'}).status_code == 403
    # driver: boarding → per-passenger arrived → check-in → trip starts (c1 riding) → completes
    assert body(client.post(f'/api/rides/rideshare_trip/{trip_id}/boarding', headers=auth(driver)))['code'] == 1
    assert body(client.post(f'/api/rides/rideshare_booking/{b1}/arrived', headers=auth(driver)))['code'] == 1
    assert body(client.post(f'/api/rides/rideshare_booking/{b1}/start', headers=auth(driver)))['code'] == 1
    assert body(client.post(f'/api/rides/rideshare_trip/{trip_id}/start', headers=auth(driver)))['code'] == 1
    db.session.rollback()
    assert db.session.get(TripBooking, b1).trip_stage == 'RIDING'
    assert body(client.post(f'/api/rides/rideshare_trip/{trip_id}/complete', headers=auth(driver)))['code'] == 1
    db.session.rollback()
    assert db.session.get(TripBooking, b1).trip_stage == 'DROPPED_OFF'
    assert db.session.get(RidePayment, rp1.id).capture_status == 'captured'
    # c2 never boarded → no-show, seat not refunded (policy §7.2)
    assert db.session.get(TripBooking, b2).trip_stage == 'NO_SHOW'
    assert db.session.get(RidePayment, rp2.id).amount_captured_cents == 2500


def test_driver_cancels_trip_refunds_everyone(client, auth, make_user):
    driver, c1 = make_user('driver'), make_user('customer')
    trip_id = _publish_trip(client, auth, driver)
    b1, rp1 = _book_and_pay(client, auth, c1, trip_id)
    prev = body(client.get(f'/api/rides/rideshare_trip/{trip_id}/cancel-preview', headers=auth(driver)))['data']
    assert '100 %' in prev['explanation']
    r = client.post('/api/trips-update', headers=auth(driver), json={'trip_id': trip_id, 'status': 'Canceled'})
    assert body(r)['code'] == 1, r.get_json()
    db.session.rollback()
    assert db.session.get(Trip, trip_id).trip_stage == 'CANCELLED_BY_DRIVER'
    b = db.session.get(TripBooking, b1)
    assert b.trip_stage == 'CANCELLED_BY_DRIVER' and b.status == 'Canceled'
    assert db.session.get(RidePayment, rp1.id).capture_status == 'canceled'
    from backend.models.money import DriverStrike
    assert DriverStrike.query.filter_by(driver_id=driver.id).count() == 1   # one strike for the trip, not per seat


def test_customer_cancel_rideshare_half_refund_window(client, auth, make_user):
    driver, c1 = make_user('driver'), make_user('customer')
    trip_id = _publish_trip(client, auth, driver, hours_ahead=5)
    b1, rp1 = _book_and_pay(client, auth, c1, trip_id)
    prev = body(client.get(f'/api/rides/rideshare_booking/{b1}/cancel-preview', headers=auth(c1)))['data']
    assert prev['rule_id'] == 'rideshare_2_to_24h' and prev['fee_cents'] == 1250
    assert body(client.post(f'/api/rides/rideshare_booking/{b1}/cancel', headers=auth(c1)))['code'] == 1
    db.session.rollback()
    rp = db.session.get(RidePayment, rp1.id)
    assert rp.capture_status == 'partially_captured' and rp.amount_captured_cents == 1250


# ── admin foundation endpoints ──────────────────────────────────────────────

def test_admin_endpoints_require_admin(client, auth, make_user):
    u = make_user('customer')
    for path in ('/api/admin/settings', '/api/admin/rides', '/api/admin/command-center', '/api/admin/audit-logs'):
        assert client.get(path, headers=auth(u)).status_code == 403


def test_admin_settings_update_is_audited_and_validated(client, auth, make_user):
    from backend.services import settings_service as S
    a = make_user('admin')
    before = S.get_int('ride.wait_window_s')
    try:
        r = client.put('/api/admin/settings', headers=auth(a), json={'values': {'ride.wait_window_s': 420}})
        assert body(r)['code'] == 1
        S.invalidate()
        assert S.get_int('ride.wait_window_s') == 420
        assert AuditLog.query.filter_by(action='settings.update', entity_id='ride.wait_window_s', actor_id=a.id).count() == 1
        bad = client.put('/api/admin/settings', headers=auth(a), json={'values': {'ride.wait_window_s': 'abc'}})
        assert body(bad)['code'] == 0
    finally:
        S.set_value('ride.wait_window_s', before)
        db.session.commit()


def test_admin_ride_detail_and_refund(client, auth, make_user):
    from tests.test_carhire_flow import _confirmed_ride, DROPOFF
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    a = make_user('admin')
    d = body(client.get(f'/api/admin/rides/carhire/{neg_id}', headers=auth(a)))['data']
    assert d['stage'] == 'CONFIRMED' and d['payments'] and d['negotiation_history']
    assert AuditLog.query.filter_by(action='personal_data.view', actor_id=a.id).count() >= 1
    # finish the ride, then a partial manual refund with a reason
    for p, j in (('en-route', {}), ('arrived', {'lat': 43.6532, 'lng': -79.3832}), ('start', {}),
                 ('complete', {'lat': DROPOFF[0], 'lng': DROPOFF[1]})):
        assert body(client.post(f'/api/rides/carhire/{neg_id}/{p}', headers=auth(driver), json=j))['code'] == 1
    no_reason = client.post(f'/api/admin/ride-payments/{rp.id}/refund', headers=auth(a), json={'amount_cents': 500})
    assert body(no_reason)['code'] == 0
    r = client.post(f'/api/admin/ride-payments/{rp.id}/refund', headers=auth(a, **{'Idempotency-Key': 'rf1'}),
                    json={'amount_cents': 500, 'reason': 'Driver took a longer route'})
    assert body(r)['code'] == 1 and body(r)['data']['refunded_cents'] == 500, r.get_json()
    again = client.post(f'/api/admin/ride-payments/{rp.id}/refund', headers=auth(a, **{'Idempotency-Key': 'rf1'}),
                        json={'amount_cents': 500, 'reason': 'Driver took a longer route'})
    assert body(again)['data']['refunded_cents'] == 0          # same key → not refunded twice
    too_much = client.post(f'/api/admin/ride-payments/{rp.id}/refund', headers=auth(a),
                           json={'amount_cents': 999999, 'reason': 'Too much money'})
    assert body(too_much)['code'] == 0
    assert AuditLog.query.filter_by(action='payment.manual_refund', actor_id=a.id).count() == 1


def test_admin_command_center_and_lists(client, auth, make_user):
    a = make_user('admin')
    cc = body(client.get('/api/admin/command-center', headers=auth(a)))['data']
    for k in ('online_drivers', 'active_rides_by_stage', 'rides_today', 'gmv_today_cents', 'open_sos'):
        assert k in cc
    rides = body(client.get('/api/admin/rides?type=carhire&per_page=5', headers=auth(a)))['data']
    assert 'data' in rides and rides['per_page'] == 5
    assert body(client.get('/api/admin/alerts', headers=auth(a)))['code'] == 1
    assert body(client.get('/api/admin/notifications/stats', headers=auth(a)))['code'] == 1


def test_admin_transition_override_requires_reason(client, auth, make_user):
    from tests.test_carhire_flow import _confirmed_ride
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    a = make_user('admin')
    r = client.post(f'/api/admin/rides/carhire/{neg_id}/transition', headers=auth(a), json={'to_stage': 'DRIVER_EN_ROUTE'})
    assert body(r)['code'] == 0
    r = client.post(f'/api/admin/rides/carhire/{neg_id}/transition', headers=auth(a),
                    json={'to_stage': 'DRIVER_EN_ROUTE', 'reason': 'Driver phone died, confirmed by call'})
    assert body(r)['code'] == 1
    ev = TripEvent.query.filter_by(ride_type='carhire', ride_id=neg_id, to_stage='DRIVER_EN_ROUTE').first()
    assert ev.actor_type == 'admin'


def test_unified_history(client, auth, make_user):
    from tests.test_carhire_flow import _confirmed_ride
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    trip_id = _publish_trip(client, auth, driver)
    bid, _ = _book_and_pay(client, auth, customer, trip_id)
    d = body(client.get('/api/rides/history', headers=auth(customer)))['data']
    kinds = {(i['ride_type'], i['id']) for i in d['data']}
    assert ('carhire', neg_id) in kinds and ('rideshare_booking', bid) in kinds
    dd = body(client.get('/api/rides/history?type=rideshare_trip', headers=auth(driver)))['data']
    assert [i['id'] for i in dd['data']] == [trip_id] and dd['data'][0]['role'] == 'driver'
    assert body(client.get('/api/rides/history?status=completed', headers=auth(customer)))['data']['total'] == 0


def test_admin_reassign_chat_templates_view_as(client, auth, make_user):
    from tests.test_carhire_flow import _confirmed_ride
    from backend.models.negotiation import Negotiation
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    a, d2 = make_user('admin'), make_user('driver')
    # chat log refused unless disputed
    assert client.get(f'/api/admin/rides/carhire/{neg_id}/chat', headers=auth(a)).status_code == 403
    assert body(client.post(f'/api/rides/carhire/{neg_id}/dispute', headers=auth(customer),
                            json={'reason': 'Driver was rude on the phone'}))['code'] == 1
    r = client.get(f'/api/admin/rides/carhire/{neg_id}/chat', headers=auth(a))
    assert body(r)['code'] == 1 and body(r)['data']['negotiation']
    # reassign requires reason, then moves driver + payment, audited, no stage change
    assert body(client.post(f'/api/admin/rides/carhire/{neg_id}/reassign', headers=auth(a),
                            json={'driver_id': d2.id}))['code'] == 0
    r = client.post(f'/api/admin/rides/carhire/{neg_id}/reassign', headers=auth(a),
                    json={'driver_id': d2.id, 'reason': 'Original driver car broke down'})
    assert body(r)['code'] == 1, r.get_json()
    db.session.rollback()
    n = db.session.get(Negotiation, neg_id)
    assert n.driver_id == d2.id and n.trip_stage == 'CONFIRMED'
    assert db.session.get(RidePayment, rp.id).driver_id == d2.id
    assert AuditLog.query.filter_by(action='ride.reassign_driver', actor_id=a.id).count() == 1
    # templates + view-as
    t = body(client.get('/api/admin/notifications/templates', headers=auth(a)))['data']
    assert any(i['event_key'] == 'ride.driver_arrived' and i['critical'] for i in t['items'])
    v = body(client.get(f'/api/admin/users/{customer.id}/view-as', headers=auth(a)))['data']
    assert v['active_ride']['id'] == neg_id and v['active_ride']['viewer_role'] == 'customer'
    assert v['active_ride']['pin']  # shows exactly what the customer sees
    assert client.get(f'/api/admin/users/{customer.id}/view-as', headers=auth(customer)).status_code == 403
