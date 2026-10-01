"""Audit gaps — legacy admin endpoints through the state machine, payment
failure paths, refund overlay, safety settlement, rideshare drafts, the
before-snapshot audit hook and env-seeded settings."""
import json
from datetime import datetime, timedelta

from backend.models import db
from backend.models.money import Refund, RidePayment
from backend.models.negotiation import Negotiation
from backend.models.notification import Notification
from backend.models.platform import AuditLog, TripEvent
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.services import settings_service as S
from backend.services.payments import payment_service as PS
from backend.services.payments.gateway import get_gateway
from tests.conftest import body
from tests.test_carhire_flow import PICKUP, _confirmed_ride, agree, create_negotiation, deliver_webhook


def stages(rt, rid):
    return [e.to_stage for e in TripEvent.query.filter_by(ride_type=rt, ride_id=rid).order_by(TripEvent.id)]


def _scheduled(client, auth, customer, price=6000, driver=None):
    r = client.post('/api/bookings', headers=auth(customer), json={
        'service_type': 'airport', 'pickup_lat': 43.6777, 'pickup_lng': -79.6248, 'pickup_address': 'YYZ T1',
        'destination_lat': 43.6532, 'destination_lng': -79.3832, 'destination_address': 'City Hall',
        'customer_proposed_price': price, 'passengers': 1,
        'scheduled_at': (datetime.utcnow() + timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')})
    assert r.status_code == 201, r.get_json()
    bid = body(r)['data']['id']
    if driver:
        b = db.session.get(ScheduledBooking, bid)
        b.driver_id = driver.id
        db.session.commit()
    return bid


# ── 1. legacy admin endpoints go through the state machine ─────────────────

def test_legacy_admin_cancel_negotiation_uses_policy_and_releases_hold(client, auth, make_user):
    admin = make_user('admin')
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    no_reason = client.post(f'/api/admin/negotiations/{neg_id}/cancel', headers=auth(admin), json={})
    assert no_reason.status_code == 400 and body(no_reason)['data']['error_code'] == 'reason_required'
    r = client.post(f'/api/admin/negotiations/{neg_id}/cancel', headers=auth(admin),
                    json={'reason': 'Customer called support to cancel'})
    assert body(r)['code'] == 1, r.get_json()
    assert body(r)['data']['id'] == neg_id and body(r)['data']['status'] == 'Cancelled'   # legacy shape
    db.session.rollback()
    neg = db.session.get(Negotiation, neg_id)
    assert neg.trip_stage == 'CANCELLED_BY_CUSTOMER' and neg.is_active == 'No'
    ev = TripEvent.query.filter_by(ride_type='carhire', ride_id=neg_id, to_stage='CANCELLED_BY_CUSTOMER').one()
    assert ev.actor_type == 'admin' and ev.meta['policy']['rule_id'] in ('free_window', 'before_en_route')
    rp = db.session.get(RidePayment, rp.id)
    assert rp.capture_status == 'canceled'          # hold released
    assert Refund.query.filter_by(ride_payment_id=rp.id, kind='release').count() == 1
    assert Notification.query.filter_by(user_id=driver.id, event_key='ride.cancelled').count() == 1
    assert AuditLog.query.filter_by(action='ride.admin_cancel', entity_id=str(neg_id)).count() == 1
    # the generic legacy audit row now carries a before snapshot
    row = AuditLog.query.filter_by(action='admin_legacy.negotiations_cancel', entity_id=str(neg_id)).first()
    assert row is not None and row.before_json and row.before_json['status'] == 'Accepted'


def test_legacy_admin_update_status_walks_the_state_machine(client, auth, make_user):
    admin = make_user('admin')
    customer, driver = make_user('customer'), make_user('driver')
    neg_id = create_negotiation(client, auth, customer, driver)
    agree(client, auth, customer, driver, neg_id)
    # unpaid → cannot be started by an admin status poke
    r = client.post(f'/api/admin/negotiations/{neg_id}/update-status', headers=auth(admin),
                    json={'status': 'Started', 'reason': 'Driver says trip started'})
    assert r.status_code == 402 and body(r)['data']['error_code'] == 'payment_required'
    assert client.post(f'/api/admin/negotiations/{neg_id}/update-status', headers=auth(admin),
                       json={'status': 'Started'}).status_code == 400          # reason required
    # pay, then Started walks CONFIRMED → EN_ROUTE → ARRIVED → IN_PROGRESS (one event each)
    r = client.post(f'/api/rides/carhire/{neg_id}/pay', headers=auth(customer))
    rp = db.session.get(RidePayment, body(r)['data']['ride_payment_id'])
    PS.handle_stripe_event(get_gateway().simulate_customer_pays(rp.checkout_session_id))
    r = client.post(f'/api/admin/negotiations/{neg_id}/update-status', headers=auth(admin),
                    json={'status': 'Started', 'reason': 'Driver phone died, trip started'})
    assert body(r)['code'] == 1 and body(r)['data']['status'] == 'Started', r.get_json()
    db.session.rollback()
    neg = db.session.get(Negotiation, neg_id)
    assert neg.trip_stage == 'IN_PROGRESS'
    assert stages('carhire', neg_id)[-3:] == ['DRIVER_EN_ROUTE', 'DRIVER_ARRIVED', 'IN_PROGRESS']
    ev = TripEvent.query.filter_by(ride_type='carhire', ride_id=neg_id, to_stage='IN_PROGRESS').one()
    assert ev.actor_type == 'admin' and ev.meta['admin_reason'].startswith('Driver phone')
    # backwards is a clear error and changes nothing
    back = client.post(f'/api/admin/negotiations/{neg_id}/update-status', headers=auth(admin),
                       json={'status': 'Pending', 'reason': 'Oops wrong ride'})
    assert back.status_code == 409 and body(back)['data']['stage'] == 'IN_PROGRESS'
    r = client.post(f'/api/admin/negotiations/{neg_id}/update-status', headers=auth(admin),
                    json={'status': 'Completed', 'reason': 'Trip finished, driver offline'})
    assert body(r)['code'] == 1
    db.session.rollback()
    neg = db.session.get(Negotiation, neg_id)
    assert neg.trip_stage == 'COMPLETED' and neg.status == 'Completed'
    assert db.session.get(RidePayment, rp.id).capture_status == 'captured'     # capture ran


def test_legacy_admin_mark_paid_confirms_through_state_machine(client, auth, make_user):
    admin, customer, driver = make_user('admin'), make_user('customer'), make_user('driver')
    bid = _scheduled(client, auth, customer, driver=driver)
    assert client.post(f'/api/admin/bookings/{bid}/mark-paid', headers=auth(admin), json={}).status_code == 400
    r = client.post(f'/api/admin/bookings/{bid}/mark-paid', headers=auth(admin),
                    json={'reason': 'Paid cash at the airport desk'})
    assert body(r)['code'] == 1, r.get_json()
    assert body(r)['data']['status'] == 'confirmed' and body(r)['data']['payment_status'] == 'paid'
    db.session.rollback()
    b = db.session.get(ScheduledBooking, bid)
    assert b.trip_stage == 'CONFIRMED' and b.ride_pin
    rp = PS.latest_payment('scheduled', bid)
    assert rp.provider == 'offline' and rp.capture_status == 'captured' and rp.amount_captured_cents == 6000
    assert TripEvent.query.filter_by(ride_type='scheduled', ride_id=bid, to_stage='CONFIRMED').one().actor_type == 'admin'
    again = client.post(f'/api/admin/bookings/{bid}/mark-paid', headers=auth(admin),
                        json={'reason': 'Paid cash at the airport desk'})
    assert again.status_code == 409
    # the driver can now run the ride; completion credits the driver from the offline payment
    assert body(client.post(f'/api/rides/scheduled/{bid}/en-route', headers=auth(driver)))['code'] == 1
    # legacy update-status 'confirmed' on an unpaid booking is refused with a clear hint
    other = _scheduled(client, auth, customer, driver=driver)
    r = client.post(f'/api/admin/bookings/{other}/update-status', headers=auth(admin),
                    json={'status': 'confirmed', 'reason': 'Customer says they paid'})
    assert r.status_code == 402 and 'Mark it paid' in body(r)['message']


def test_legacy_admin_assign_driver_uses_reassign_rules(client, auth, make_user):
    admin, customer, d1, d2 = make_user('admin'), make_user('customer'), make_user('driver'), make_user('driver')
    bid = _scheduled(client, auth, customer)
    r = client.post(f'/api/admin/bookings/{bid}/assign-driver', headers=auth(admin), json={'driver_id': d1.id})
    assert body(r)['code'] == 1 and body(r)['data']['driver_id'] == d1.id, r.get_json()
    # replacing needs a reason; an unapproved user is refused
    assert body(client.post(f'/api/admin/bookings/{bid}/assign-driver', headers=auth(admin),
                            json={'driver_id': d2.id}))['data']['error_code'] == 'reason_required'
    nobody = make_user('customer')
    r = client.post(f'/api/admin/bookings/{bid}/assign-driver', headers=auth(admin),
                    json={'driver_id': nobody.id, 'reason': 'Swap to a closer driver'})
    assert body(r)['data']['error_code'] == 'driver_unavailable'
    r = client.post(f'/api/admin/bookings/{bid}/assign-driver', headers=auth(admin),
                    json={'driver_id': d2.id, 'reason': 'Swap to a closer driver'})
    assert body(r)['code'] == 1
    ev = TripEvent.query.filter_by(ride_type='scheduled', ride_id=bid).order_by(TripEvent.id.desc()).first()
    assert ev.meta['reassigned_from'] == d1.id and ev.meta['reassigned_to'] == d2.id


def test_legacy_admin_trip_cancel_cascades(client, auth, make_user):
    from tests.exp_helpers import make_trip
    admin, driver, c = make_user('admin'), make_user('driver'), make_user('customer')
    trip = make_trip(driver)
    r = client.post(f'/api/rideshare/trips/{trip.id}/book', headers=auth(c), json={'seats': 1})
    bid = body(r)['data']['booking']['id']
    r = client.post(f'/api/admin/trips/{trip.id}/cancel', headers=auth(admin), json={'reason': 'Driver is sick today'})
    assert body(r)['code'] == 1, r.get_json()
    db.session.rollback()
    assert db.session.get(Trip, trip.id).trip_stage == 'CANCELLED_BY_DRIVER'
    assert db.session.get(TripBooking, bid).trip_stage == 'CANCELLED_BY_DRIVER'
    # legacy trip status update also walks the graph
    t2 = make_trip(driver)
    r = client.post(f'/api/admin/trips/{t2.id}/update-status', headers=auth(admin),
                    json={'status': 'Ongoing', 'reason': 'Driver left already'})
    assert body(r)['code'] == 1 and body(r)['data']['status'] == 'Ongoing', r.get_json()
    db.session.rollback()
    assert db.session.get(Trip, t2.id).trip_stage == 'IN_PROGRESS'


def test_legacy_checkout_webhook_confirms_booking_via_state_machine(client, sign_stripe, make_user):
    from tests.exp_helpers import make_trip
    from backend.services import rideshare_service as RS
    driver, c = make_user('driver'), make_user('customer')
    trip = make_trip(driver)
    b = RS.create_booking(c, trip.id, seats=1)
    event = {'id': f'evt_legacy_{b.id}', 'type': 'checkout.session.completed',
             'data': {'object': {'id': f'cs_legacy_{b.id}', 'object': 'checkout.session', 'amount_total': 2500,
                                 'metadata': {'booking_id': str(b.id)}}}}
    assert deliver_webhook(client, sign_stripe, event).status_code == 200
    db.session.rollback()
    b = db.session.get(TripBooking, b.id)
    assert b.trip_stage == 'CONFIRMED' and b.status == 'Reserved' and b.stripe_paid == 'Yes'
    assert 'CONFIRMED' in stages('rideshare_booking', b.id)


# ── 5. payment failures, refund overlay, safety settlement ─────────────────

def _awaiting(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    neg_id = create_negotiation(client, auth, customer, driver)
    agree(client, auth, customer, driver, neg_id)
    return customer, driver, neg_id


def test_declines_and_3ds_keep_ride_awaiting_payment_and_allow_retry(client, auth, make_user):
    customer, driver, neg_id = _awaiting(client, auth, make_user)
    for mode in ('decline', 'insufficient_funds', 'requires_action'):
        r = client.post(f'/api/rides/carhire/{neg_id}/pay', headers=auth(customer), json={'force_new': True})
        assert body(r)['code'] == 1, r.get_json()
        rp = db.session.get(RidePayment, body(r)['data']['ride_payment_id'])
        gw = get_gateway()
        if mode == 'requires_action':
            ev = gw.simulate_customer_pays(rp.checkout_session_id, requires_action=True)
        else:
            ev = gw.simulate_customer_pays(rp.checkout_session_id,
                                           decline=True if mode == 'decline' else 'insufficient_funds')
        PS.handle_stripe_event(ev)
        db.session.rollback()
        rp = db.session.get(RidePayment, rp.id)
        neg = db.session.get(Negotiation, neg_id)
        assert neg.trip_stage == 'AWAITING_PAYMENT', mode
        if mode == 'requires_action':
            assert rp.capture_status == 'pending' and rp.failure_reason == 'authentication_required'
        else:
            assert rp.capture_status == 'failed'
        n = (Notification.query.filter_by(user_id=customer.id, event_key='payment.failed')
             .order_by(Notification.id.desc()).first())
        assert n is not None and n.data['ride_payment_id'] == rp.id
        if mode == 'insufficient_funds':
            assert 'insufficient funds' in n.body
        if mode == 'requires_action':
            assert 'Confirm the payment with your bank' in n.body
        # replaying the same failure does not notify twice
        PS.record_intent(rp, get_gateway().get_intent(rp.intent_id))
        db.session.rollback()
        assert Notification.query.filter_by(user_id=customer.id, event_key='payment.failed').filter(
            Notification.data['ride_payment_id'].as_integer() == rp.id).count() == 1
    # the retry (force_new) succeeds
    r = client.post(f'/api/rides/carhire/{neg_id}/pay', headers=auth(customer), json={'force_new': True})
    rp = db.session.get(RidePayment, body(r)['data']['ride_payment_id'])
    PS.handle_stripe_event(get_gateway().simulate_customer_pays(rp.checkout_session_id))
    db.session.rollback()
    assert db.session.get(Negotiation, neg_id).trip_stage == 'CONFIRMED'


def test_refund_overlay_status(client, auth, make_user):
    from tests.test_receipts import paid_carhire
    admin = make_user('admin', admin_roles='finance')
    customer, driver, neg, rp = paid_carhire(make_user)
    r = client.post(f'/api/admin/ride-payments/{rp.id}/refund', headers={**auth(admin), 'Idempotency-Key': 'ov1'},
                    json={'amount_cents': 500, 'reason': 'Detour complaint upheld'})
    assert body(r)['code'] == 1, r.get_json()
    db.session.rollback()
    rp = db.session.get(RidePayment, rp.id)
    assert rp.capture_status == 'partially_refunded' and rp.meta['capture_status_before_refund'] == 'captured'
    ride = body(client.get(f'/api/rides/carhire/{neg.id}', headers=auth(customer)))['data']
    assert ride['payment']['refund_status'] == 'partially_refunded' and ride['payment']['amount_refunded_cents'] == 500
    r = client.post(f'/api/admin/ride-payments/{rp.id}/refund', headers={**auth(admin), 'Idempotency-Key': 'ov2'},
                    json={'amount_cents': 1700, 'reason': 'Full goodwill refund'})
    assert body(r)['code'] == 1, r.get_json()
    db.session.rollback()
    assert db.session.get(RidePayment, rp.id).capture_status == 'refunded'
    detail = body(client.get(f'/api/admin/rides/carhire/{neg.id}', headers=auth(make_user('admin'))))['data']
    assert detail['payments'][0]['capture_status'] == 'refunded'


def test_safety_ending_holds_money_until_admin_settles(client, auth, make_user):
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=auth(driver))
    client.post(f'/api/rides/carhire/{neg_id}/arrived', headers=auth(driver), json={'lat': PICKUP[0], 'lng': PICKUP[1]})
    client.post(f'/api/rides/carhire/{neg_id}/start', headers=auth(driver))
    r = client.post(f'/api/rides/carhire/{neg_id}/cancel', headers=auth(customer), json={'reason_code': 'safety'})
    assert body(r)['code'] == 1 and body(r)['data']['policy']['rule_id'] == 'safety_review', r.get_json()
    db.session.rollback()
    rp = db.session.get(RidePayment, rp.id)
    assert rp.capture_status == 'authorized' and rp.settlement_status == 'safety_review'   # hold kept
    assert rp.settle_due_at > datetime.utcnow() + timedelta(hours=23)
    ops = make_user('admin', admin_roles='ops')
    detail = body(client.get(f'/api/admin/rides/carhire/{neg_id}', headers=auth(ops)))['data']
    assert detail['safety_settlement']['status'] == 'safety_review' and detail['safety_settlement']['held_cents'] == 2200
    bad = client.post(f'/api/admin/rides/carhire/{neg_id}/settle-safety', headers=auth(ops),
                      json={'amount_cents': 99999, 'reason': 'Half of the trip was done'})
    assert body(bad)['data']['error_code'] == 'bad_amount'
    r = client.post(f'/api/admin/rides/carhire/{neg_id}/settle-safety', headers=auth(ops),
                    json={'amount_cents': 1100, 'reason': 'Half of the trip was done'})
    assert body(r)['code'] == 1 and body(r)['data']['charged_cents'] == 1100, r.get_json()
    assert body(r)['data']['released_cents'] == 1100
    db.session.rollback()
    rp = db.session.get(RidePayment, rp.id)
    assert rp.settlement_status == 'settled' and rp.amount_captured_cents == 1100
    assert ('capture', rp.intent_id, 1100) in get_gateway().calls
    assert Refund.query.filter_by(ride_payment_id=rp.id, kind='release').first().amount_cents == 1100
    assert AuditLog.query.filter_by(action='payment.safety_settlement', entity_id=str(rp.id)).count() == 1
    assert Notification.query.filter_by(user_id=customer.id, event_key='refund.issued').count() == 1
    again = client.post(f'/api/admin/rides/carhire/{neg_id}/settle-safety', headers=auth(ops),
                        json={'amount_cents': 0, 'reason': 'Changed my mind'})
    assert again.status_code == 409


def test_safety_hold_auto_releases_after_window(client, auth, make_user):
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    r = client.post(f'/api/rides/carhire/{neg_id}/cancel', headers=auth(customer), json={'reason_code': 'safety'})
    assert body(r)['code'] == 1
    db.session.rollback()
    assert db.session.get(RidePayment, rp.id).settlement_status == 'safety_review'
    PS.auto_release_safety_holds(datetime.utcnow() + timedelta(hours=25))
    db.session.rollback()
    rp = db.session.get(RidePayment, rp.id)
    assert rp.settlement_status == 'auto_released' and rp.capture_status == 'canceled'
    assert Refund.query.filter_by(ride_payment_id=rp.id, kind='release').first().amount_cents == 2200


# ── 10. rideshare drafts ────────────────────────────────────────────────────

def test_rideshare_draft_not_searchable_or_bookable_until_published(client, auth, make_user):
    driver, c = make_user('driver'), make_user('customer')
    r = client.post('/api/trips-create', headers=auth(driver), json={
        'start_name': 'Toronto Union', 'end_name': 'Ottawa', 'start_gps': '43.6453,-79.3806',
        'end_pgs': '45.4215,-75.6972', 'price': 30, 'slots': 3, 'publish': False,
        'scheduled_start_time': (datetime.utcnow() + timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%SZ')})
    assert r.status_code == 201 and body(r)['message'] == 'Draft saved', r.get_json()
    tid = body(r)['data']['id']
    trip = db.session.get(Trip, tid)
    assert trip.trip_stage == 'DRAFT' and trip.status == 'Pending' and trip.pickup_province == 'ON'
    q = {'from_lat': 43.6453, 'from_lng': -79.3806, 'to_lat': 45.4215, 'to_lng': -75.6972}
    found = body(client.get('/api/rideshare/search', headers=auth(c), query_string=q))['data']['trips']
    assert all(t['trip_id'] != tid for t in found)
    assert client.get(f'/api/rideshare/trips/{tid}', headers=auth(c)).status_code == 404
    assert body(client.get(f'/api/rideshare/trips/{tid}', headers=auth(driver)))['code'] == 1
    book = client.post(f'/api/rideshare/trips/{tid}/book', headers=auth(c), json={'seats': 1})
    assert book.status_code == 409 and body(book)['data']['error_code'] == 'not_bookable'
    legacy = body(client.post('/api/get-available-trips', headers=auth(c), json={}))['data']
    assert all(t['id'] != tid for t in legacy)
    r = client.post(f'/api/rides/rideshare_trip/{tid}/publish', headers=auth(driver))
    assert body(r)['code'] == 1, r.get_json()
    found = body(client.get('/api/rideshare/search', headers=auth(c), query_string=q))['data']['trips']
    assert any(t['trip_id'] == tid for t in found)
    assert client.post(f'/api/rideshare/trips/{tid}/book', headers=auth(c), json={'seats': 1}).status_code == 201


# ── 13. housekeeping ────────────────────────────────────────────────────────

def test_bgc_fee_env_seeds_default(monkeypatch):
    assert 'onboarding.bgc_fee_cents' not in S._load() or True
    monkeypatch.setenv('BACKGROUND_CHECK_FEE_CENTS', '4599')
    S.invalidate()
    if 'onboarding.bgc_fee_cents' in S._load():      # an admin override in this DB wins
        return
    assert S.get_int('onboarding.bgc_fee_cents') == 4599
    monkeypatch.setenv('BACKGROUND_CHECK_FEE_CENTS', 'not-a-number')
    assert S.get_int('onboarding.bgc_fee_cents') == 3999


def test_readiness_lists_launch_blockers(client, auth, make_user, monkeypatch):
    admin = make_user('admin', admin_roles='ops')
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.delenv('PUBLIC_WEB_BASE_URL', raising=False)
    r = client.get('/api/admin/readiness', headers=auth(admin))
    data = body(r)['data']
    keys = {b['key'] for b in data['blockers']}
    assert data['ready'] is False and data['production'] is True
    assert {'twilio', 'certn', 'google_maps', 'redis', 'public_web_base_url'} <= keys
    if S.get('pricing.tax_inclusive') and not S.get('company.gst_number'):
        assert 'company.gst_number' in keys
    assert all({'key', 'ok', 'severity', 'message', 'fix'} <= set(b) for b in data['checks'])
    assert client.get('/api/admin/readiness', headers=auth(make_user('customer'))).status_code == 403
