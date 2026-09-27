"""Integration — car hire end to end over HTTP (spec §4, §5, §6, §7, §25).

request → negotiate → agree → pay (authorization hold) → en route → arrived
(geofence) → PIN → complete → capture → wallet credit, plus the negative paths.
"""
import json
from datetime import datetime, timedelta

import pytest

from backend import jobs
from backend.models import db
from backend.models.money import RidePayment, Refund, DriverStrike
from backend.models.negotiation import Negotiation
from backend.models.notification import Notification, NotificationDelivery
from backend.models.platform import TripEvent, WebhookEvent
from backend.models.transaction import Transaction
from backend.services import realtime
from backend.services.payments.gateway import get_gateway
from tests.conftest import body

PICKUP = (43.6532, -79.3832)          # Toronto City Hall
DROPOFF = (43.6426, -79.3871)         # CN Tower


def events(neg_id):
    return [e.to_stage for e in TripEvent.query.filter_by(ride_type='carhire', ride_id=neg_id)
            .order_by(TripEvent.id)]


def register_v4_device(client, auth, user):
    r = client.post('/api/devices/register', headers=auth(user),
                    json={'device_id': f'dev-{user.id}', 'platform': 'android', 'app_version': '4.0.0'})
    assert body(r)['code'] == 1


def create_negotiation(client, auth, customer, driver, price_cents=2000):
    r = client.post('/api/negotiations-create', headers=auth(customer), json={
        'driver_id': driver.id, 'initial_price': price_cents,
        'pickup_lat': PICKUP[0], 'pickup_lng': PICKUP[1], 'pickup_address': 'City Hall',
        'dropoff_lat': DROPOFF[0], 'dropoff_lng': DROPOFF[1], 'dropoff_address': 'CN Tower'})
    assert r.status_code == 201, r.get_json()
    return body(r)['data']['id']


def agree(client, auth, customer, driver, neg_id, counter_dollars=22):
    r = client.post('/api/negotiations-records', headers=auth(driver),
                    json={'negotiation_id': neg_id, 'price': counter_dollars, 'message_type': 'Negotiation'})
    assert r.status_code == 201, r.get_json()
    r = client.post('/api/negotiations-accept', headers=auth(customer),
                    json={'negotiation_id': neg_id, 'message_type': 'Accept'})
    assert body(r)['code'] == 1, r.get_json()


def pay(client, auth, customer, neg_id):
    r = client.post(f'/api/rides/carhire/{neg_id}/pay', headers=auth(customer))
    assert body(r)['code'] == 1, r.get_json()
    rp = db.session.get(RidePayment, body(r)['data']['ride_payment_id'])
    event = get_gateway().simulate_customer_pays(rp.checkout_session_id)
    return rp, event


def deliver_webhook(client, sign_stripe, event):
    payload = json.dumps(event)
    return client.post('/api/webhooks/stripe', data=payload, content_type='application/json',
                       headers={'Stripe-Signature': sign_stripe(payload)})


def test_full_happy_path(client, auth, make_user, sign_stripe):
    customer, driver = make_user('customer'), make_user('driver')
    register_v4_device(client, auth, customer)
    neg_id = create_negotiation(client, auth, customer, driver)

    # driver was told about the request
    assert Notification.query.filter_by(user_id=driver.id, event_key='negotiation.new_request').count() == 1

    agree(client, auth, customer, driver, neg_id)
    neg = db.session.get(Negotiation, neg_id)
    db.session.refresh(neg)
    assert neg.trip_stage == 'AWAITING_PAYMENT' and neg.status == 'Accepted'
    assert neg.agreed_price_cents == 2200

    # driver cannot head to pickup before payment (hard server rule)
    r = client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=auth(driver))
    assert r.status_code == 409 or body(r)['code'] == 0

    rp, event = pay(client, auth, customer, neg_id)
    assert rp.capture_method == 'manual'
    r = deliver_webhook(client, sign_stripe, event)
    assert r.status_code == 200
    # replayed webhook is a no-op
    r2 = deliver_webhook(client, sign_stripe, event)
    assert body(r2).get('duplicate') is True
    assert WebhookEvent.query.filter_by(provider='stripe', event_id=event['id']).count() == 1

    db.session.rollback()  # new snapshot (REPEATABLE READ)
    neg = db.session.get(Negotiation, neg_id)
    rp = db.session.get(RidePayment, rp.id)
    assert rp.capture_status == 'authorized' and rp.amount_authorized_cents == 2200
    assert neg.trip_stage == 'CONFIRMED' and neg.stripe_paid == 'Yes' and neg.ride_pin
    assert Notification.query.filter_by(user_id=customer.id, event_key='payment.authorized').count() == 1

    # customer sees the PIN, driver does not
    ride_c = body(client.get(f'/api/rides/carhire/{neg_id}', headers=auth(customer)))['data']
    ride_d = body(client.get(f'/api/rides/carhire/{neg_id}', headers=auth(driver)))['data']
    assert ride_c['pin'] == neg.ride_pin and ride_d['pin'] is None
    assert ride_c['vehicle'] is not None and ride_c['driver']['first_name']

    r = client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=auth(driver))
    assert body(r)['code'] == 1, r.get_json()

    # arrival outside the 150 m geofence is rejected and changes nothing
    far = client.post(f'/api/rides/carhire/{neg_id}/arrived', headers=auth(driver), json={'lat': 43.70, 'lng': -79.40})
    assert body(far)['code'] == 0 and body(far)['data']['error_code'] == 'outside_geofence'
    db.session.rollback()  # new snapshot (REPEATABLE READ)
    assert db.session.get(Negotiation, neg_id).trip_stage in ('DRIVER_EN_ROUTE', 'DRIVER_ARRIVING')

    near = client.post(f'/api/rides/carhire/{neg_id}/arrived', headers=auth(driver),
                       json={'lat': PICKUP[0] + 0.0005, 'lng': PICKUP[1]})
    assert body(near)['code'] == 1, near.get_json()
    arrived_note = Notification.query.filter_by(user_id=customer.id, event_key='ride.driver_arrived').first()
    assert arrived_note and neg.ride_pin in arrived_note.body and arrived_note.is_critical
    chans = {d.channel for d in NotificationDelivery.query.filter_by(notification_id=arrived_note.id)}
    assert {'push', 'socket', 'inbox'} <= chans
    # SMS fallback scheduled for the critical push
    assert any(p[1].endswith('escalate_if_unopened') for p in jobs.DEFERRED)

    # wrong PIN rejected, right PIN starts the trip
    bad = client.post(f'/api/rides/carhire/{neg_id}/start', headers=auth(driver), json={'pin': '0000' if neg.ride_pin != '0000' else '1111'})
    assert body(bad)['data']['error_code'] == 'pin_invalid'
    ok = client.post(f'/api/rides/carhire/{neg_id}/start', headers=auth(driver), json={'pin': neg.ride_pin})
    assert body(ok)['code'] == 1, ok.get_json()

    # invalid transition changes nothing
    done = client.post(f'/api/rides/carhire/{neg_id}/complete', headers=auth(driver),
                       json={'lat': DROPOFF[0], 'lng': DROPOFF[1]})
    assert body(done)['code'] == 1, done.get_json()
    again = client.post(f'/api/rides/carhire/{neg_id}/start', headers=auth(driver), json={'pin': neg.ride_pin})
    assert body(again)['code'] == 0
    assert body(again)['data']['error_code'] in ('invalid_transition',)

    db.session.rollback()  # new snapshot (REPEATABLE READ)
    neg = db.session.get(Negotiation, neg_id)
    rp = db.session.get(RidePayment, rp.id)
    assert neg.trip_stage == 'COMPLETED' and neg.status == 'Completed' and neg.is_active == 'No'
    assert rp.capture_status == 'captured' and rp.amount_captured_cents == 2200
    # driver credited net of 10 % commission (dollars ledger)
    tx = Transaction.query.filter_by(user_id=driver.id, reference=f'earning-neg-{neg_id}').first()
    assert tx is not None and float(tx.amount) == 19.80

    # exactly one trip_events row per transition
    assert events(neg_id) == ['REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT', 'CONFIRMED',
                              'DRIVER_EN_ROUTE', 'DRIVER_ARRIVED', 'IN_PROGRESS', 'COMPLETED'] or \
        events(neg_id) == ['REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT', 'CONFIRMED',
                           'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS', 'COMPLETED']
    stage_events = [s for s in realtime.SENT if s[0] == 'ride.stage_changed' and s[2] == f'ride:carhire:{neg_id}']
    assert len(stage_events) == len(events(neg_id))

    # timeline endpoint
    tl = body(client.get(f'/api/rides/carhire/{neg_id}/timeline', headers=auth(customer)))['data']
    assert [t['to_stage'] for t in tl] == events(neg_id)


def test_payment_bypass_is_impossible(client, auth, make_user):
    """Spec §6 acceptance: a driver can't move past CONFIRMED until payment is
    authorized — even calling every API directly, legacy or v4."""
    customer, driver = make_user('customer'), make_user('driver')
    neg_id = create_negotiation(client, auth, customer, driver)
    agree(client, auth, customer, driver, neg_id)
    for path, payload in [(f'/api/rides/carhire/{neg_id}/en-route', {}),
                          (f'/api/rides/carhire/{neg_id}/arrived', {'lat': PICKUP[0], 'lng': PICKUP[1]}),
                          (f'/api/rides/carhire/{neg_id}/start', {'pin': '1234'}),
                          (f'/api/rides/carhire/{neg_id}/complete', {})]:
        r = client.post(path, headers=auth(driver), json=payload)
        assert body(r)['code'] == 0, path
    # legacy v3 "Started" also refused
    r = client.post('/api/negotiations-accept', headers=auth(driver),
                    json={'negotiation_id': neg_id, 'message_type': 'Started'})
    assert body(r)['code'] == 0 and body(r)['data']['error_code'] == 'payment_required'
    db.session.rollback()  # new snapshot (REPEATABLE READ)
    assert db.session.get(Negotiation, neg_id).trip_stage == 'AWAITING_PAYMENT'


def test_legacy_v3_flow_still_works(client, auth, make_user, sign_stripe):
    """A v3 app: Accept → pay (refresh-payment) → 'Started' → Complete. No PIN
    (customer has no v4 device), no geofence; events are still recorded."""
    customer, driver = make_user('customer'), make_user('driver')
    neg_id = create_negotiation(client, auth, customer, driver)
    agree(client, auth, customer, driver, neg_id)
    r = client.post('/api/negotiations-refresh-payment', headers=auth(customer), json={'negotiation_id': neg_id})
    assert body(r)['code'] == 1 and body(r)['data']['stripe_url']
    rp = RidePayment.query.filter_by(ride_type='carhire', ride_id=neg_id).first()
    event = get_gateway().simulate_customer_pays(rp.checkout_session_id)
    # v3 app polls check-payment instead of waiting for the webhook
    r = client.post('/api/negotiations-check-payment', headers=auth(customer), json={'negotiation_id': neg_id})
    assert body(r)['data']['is_paid'] is True, r.get_json()
    r = client.post('/api/negotiations-accept', headers=auth(driver),
                    json={'negotiation_id': neg_id, 'message_type': 'Started'})
    assert body(r)['code'] == 1 and body(r)['data']['status'] == 'Started', r.get_json()
    r = client.post('/api/negotiations-complete', headers=auth(driver),
                    json={'negotiation_id': neg_id, 'message_type': 'Complete'})
    assert body(r)['code'] == 1 and body(r)['data']['status'] == 'Completed', r.get_json()
    ev = events(neg_id)
    assert ev[-4:] == ['DRIVER_EN_ROUTE', 'DRIVER_ARRIVED', 'IN_PROGRESS', 'COMPLETED']
    assert all((e.meta or {}).get('legacy') for e in TripEvent.query.filter_by(ride_type='carhire', ride_id=neg_id)
               .filter(TripEvent.to_stage.in_(['DRIVER_EN_ROUTE', 'IN_PROGRESS'])))


def test_v3_driver_blocked_when_customer_on_v4(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    register_v4_device(client, auth, customer)
    neg_id = create_negotiation(client, auth, customer, driver)
    agree(client, auth, customer, driver, neg_id)
    rp, event = pay(client, auth, customer, neg_id)
    from backend.services.payments import payment_service as PS
    PS.handle_stripe_event(event)
    r = client.post('/api/negotiations-accept', headers=auth(driver),
                    json={'negotiation_id': neg_id, 'message_type': 'Started'})
    assert body(r)['code'] == 0 and body(r)['data']['error_code'] == 'pin_required'


def test_cannot_accept_own_offer(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    neg_id = create_negotiation(client, auth, customer, driver)
    client.post('/api/negotiations-records', headers=auth(driver),
                json={'negotiation_id': neg_id, 'price': 25, 'message_type': 'Negotiation'})
    r = client.post('/api/negotiations-accept', headers=auth(driver),
                    json={'negotiation_id': neg_id, 'message_type': 'Accept'})
    assert body(r)['code'] == 0 and body(r)['data']['error_code'] == 'own_offer'


def _confirmed_ride(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    neg_id = create_negotiation(client, auth, customer, driver)
    agree(client, auth, customer, driver, neg_id)
    rp, event = pay(client, auth, customer, neg_id)
    from backend.services.payments import payment_service as PS
    PS.handle_stripe_event(event)
    return customer, driver, neg_id, db.session.get(RidePayment, rp.id)


def test_cancel_free_window_releases_hold(client, auth, make_user):
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=auth(driver))
    prev = body(client.get(f'/api/rides/carhire/{neg_id}/cancel-preview', headers=auth(customer)))['data']
    assert prev['rule_id'] == 'free_window' and prev['fee_cents'] == 0
    r = client.post(f'/api/rides/carhire/{neg_id}/cancel', headers=auth(customer), json={'reason_code': 'changed_mind'})
    assert body(r)['code'] == 1, r.get_json()
    db.session.rollback()  # new snapshot (REPEATABLE READ)
    rp = db.session.get(RidePayment, rp.id)
    assert rp.capture_status == 'canceled'
    assert ('cancel', rp.intent_id) in get_gateway().calls
    rel = Refund.query.filter_by(ride_payment_id=rp.id, kind='release').first()
    assert rel and rel.amount_cents == 2200
    assert Notification.query.filter_by(user_id=driver.id, event_key='ride.cancelled').count() == 1
    assert Notification.query.filter_by(user_id=customer.id, event_key='refund.issued').count() == 1


def test_cancel_after_free_window_partial_capture(client, auth, make_user):
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=auth(driver))
    neg = db.session.get(Negotiation, neg_id)
    neg.confirmed_at = datetime.utcnow() - timedelta(minutes=6)
    neg.en_route_at = datetime.utcnow() - timedelta(minutes=5)
    db.session.commit()
    prev = body(client.get(f'/api/rides/carhire/{neg_id}/cancel-preview', headers=auth(customer)))['data']
    assert prev['rule_id'] == 'en_route_fee' and prev['fee_cents'] == 220   # 10 % of $22 < $5
    assert 'driving for 5 min' in prev['explanation']
    r = client.post(f'/api/rides/carhire/{neg_id}/cancel', headers=auth(customer))
    assert body(r)['data']['policy']['fee_cents'] == 220
    db.session.rollback()  # new snapshot (REPEATABLE READ)
    rp = db.session.get(RidePayment, rp.id)
    assert rp.capture_status == 'partially_captured' and rp.amount_captured_cents == 220
    assert ('capture', rp.intent_id, 220) in get_gateway().calls
    tx = Transaction.query.filter_by(user_id=driver.id, reference=f'cancel-fee-carhire-{neg_id}').first()
    assert tx is not None and float(tx.amount) == 1.98


def test_customer_no_show_after_wait_window(client, auth, make_user):
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=auth(driver))
    client.post(f'/api/rides/carhire/{neg_id}/arrived', headers=auth(driver), json={'lat': PICKUP[0], 'lng': PICKUP[1]})
    early = client.post(f'/api/rides/carhire/{neg_id}/no-show', headers=auth(driver))
    assert body(early)['data']['error_code'] == 'wait_window'
    neg = db.session.get(Negotiation, neg_id)
    neg.driver_arrived_at = datetime.utcnow() - timedelta(minutes=6)
    db.session.commit()
    r = client.post(f'/api/rides/carhire/{neg_id}/no-show', headers=auth(driver))
    assert body(r)['code'] == 1 and body(r)['data']['policy']['fee_cents'] == 700, r.get_json()
    db.session.rollback()  # new snapshot (REPEATABLE READ)
    assert db.session.get(Negotiation, neg_id).trip_stage == 'CUSTOMER_NO_SHOW'
    assert db.session.get(RidePayment, rp.id).amount_captured_cents == 700


def test_driver_cancel_full_release_and_strike(client, auth, make_user):
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    r = client.post(f'/api/rides/carhire/{neg_id}/cancel', headers=auth(driver))
    assert body(r)['code'] == 1 and body(r)['data']['policy']['strike'] is True
    db.session.rollback()  # new snapshot (REPEATABLE READ)
    assert db.session.get(RidePayment, rp.id).capture_status == 'canceled'
    assert DriverStrike.query.filter_by(driver_id=driver.id, ride_id=neg_id).count() == 1


def test_expiry_job_expires_unpaid_rides(client, auth, make_user):
    from backend.services import ride_jobs
    customer, driver = make_user('customer'), make_user('driver')
    neg_id = create_negotiation(client, auth, customer, driver)
    agree(client, auth, customer, driver, neg_id)
    neg = db.session.get(Negotiation, neg_id)
    neg.stage_changed_at = datetime.utcnow() - timedelta(minutes=6)
    db.session.commit()
    ride_jobs.tick_lifecycle()
    db.session.rollback()  # new snapshot (REPEATABLE READ)
    neg = db.session.get(Negotiation, neg_id)
    assert neg.trip_stage == 'EXPIRED' and neg.status == 'Cancelled'


def test_driver_no_show_detection(client, auth, make_user):
    from backend.services import ride_jobs
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    neg = db.session.get(Negotiation, neg_id)
    neg.confirmed_at = datetime.utcnow() - timedelta(minutes=16)
    db.session.commit()
    ride_jobs.tick_lifecycle()
    db.session.rollback()  # new snapshot (REPEATABLE READ)
    assert db.session.get(Negotiation, neg_id).trip_stage == 'DRIVER_NO_SHOW'
    assert Transaction.query.filter_by(user_id=customer.id, reference=f'credit-carhire-{neg_id}').count() == 1


def test_active_ride_endpoint_restores_state(client, auth, make_user):
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    for u in (customer, driver):
        d = body(client.get('/api/rides/active', headers=auth(u)))['data']
        assert d['id'] == neg_id and d['stage'] == 'CONFIRMED'


def test_idempotency_key_replays(client, auth, make_user):
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    h = auth(driver, **{'Idempotency-Key': 'tap-123'})
    r1 = client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=h)
    r2 = client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=h)
    assert body(r1)['code'] == 1 and body(r2)['code'] == 1
    assert r2.headers.get('Idempotent-Replayed') == 'true'
    assert events(neg_id).count('DRIVER_EN_ROUTE') == 1


def test_outsider_cannot_touch_ride(client, auth, make_user):
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    stranger = make_user('customer')
    assert client.get(f'/api/rides/carhire/{neg_id}', headers=auth(stranger)).status_code == 403
    r = client.post(f'/api/rides/carhire/{neg_id}/cancel', headers=auth(stranger))
    assert r.status_code == 403


def test_unsigned_webhook_rejected(client):
    r = client.post('/api/webhooks/stripe', data='{"id":"evt_x","type":"checkout.session.completed"}',
                    content_type='application/json', headers={'Stripe-Signature': 't=1,v1=bad'})
    assert r.status_code == 400
