"""State machine — full (from, to) matrix for all four graphs through
transition() on real rows, cancellation at the API level (before payment,
after arrival with waiting time) and one end-to-end ride:
request → counter-offer → accept → pay → en route → arrived → PIN → complete
→ capture → receipt → both rated → CLOSED."""
import random
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from backend.models import db
from backend.models.money import Receipt, RidePayment
from backend.models.negotiation import Negotiation
from backend.models.platform import TripEvent
from backend.models.scheduled_booking import ScheduledBooking
from backend.services import rides as R
from backend.services import trip_state_machine as TSM
from backend.services.notify import email_provider
from backend.services.payments import payment_service as PS
from backend.services.payments.gateway import get_gateway
from tests.conftest import body
from tests.exp_helpers import _experience_cleanup, make_carhire, make_trip  # noqa: F401
from tests.test_carhire_flow import PICKUP, agree, create_negotiation, register_v4_device


def _all_stages(graph):
    out = set(graph)
    for v in graph.values():
        out |= set(v)
    return sorted(out)


def _ride_for(rt, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    if rt == 'carhire':
        return make_carhire(customer, driver, stage='REQUESTED')
    if rt == 'scheduled':
        b = ScheduledBooking(customer_id=customer.id, driver_id=driver.id, service_type='airport',
                             pickup_lat=43.6, pickup_lng=-79.4, pickup_address='A', destination_lat=43.7,
                             destination_lng=-79.3, destination_address='B', customer_proposed_price=5000,
                             agreed_price=5000, status='pending', trip_stage='REQUESTED',
                             scheduled_at=datetime.utcnow() + timedelta(hours=2))
        db.session.add(b)
        db.session.commit()
        return b
    trip = make_trip(driver)
    if rt == 'rideshare_trip':
        return trip
    from backend.services import rideshare_service as RS
    return RS.create_booking(customer, trip.id, seats=1)


@pytest.mark.parametrize('rt', ['carhire', 'scheduled', 'rideshare_trip', 'rideshare_booking'])
def test_full_transition_matrix(rt, make_user):
    graph = TSM.GRAPHS[rt]
    stages = _all_stages(graph)
    admin = make_user('admin')
    ride = _ride_for(rt, make_user)
    rid = ride.id
    checked = allowed = 0
    for frm in stages:
        for to in stages:
            for attempt in range(4):       # the shared dev DB may deadlock with parallel runs
                try:
                    allowed += _check_pair(rt, rid, graph, frm, to, admin)
                    checked += 1
                    break
                except OperationalError as e:
                    db.session.rollback()
                    if '1213' not in str(e) or attempt == 3:
                        raise
    assert checked == len(stages) ** 2
    assert allowed == sum(len(v) for v in graph.values())
    # nothing leaked: no event rows were committed by the matrix
    assert TripEvent.query.filter(TripEvent.ride_type == rt, TripEvent.ride_id == rid,
                                  TripEvent.meta.isnot(None)).filter(
        TripEvent.meta['matrix'].as_boolean().is_(True)).count() == 0


def _check_pair(rt, rid, graph, frm, to, admin):
    """One (from, to) cell. Returns 1 for a legal pair, else 0."""
    allowed = 0
    row = R.load(rt, rid)
    row.trip_stage = frm
    db.session.flush()
    legal = to in graph.get(frm, ())
    try:
        if frm == to:
            with pytest.raises(TSM.TransitionError) as ei:
                TSM.transition(rt, rid, to, actor=admin, actor_type='admin', commit=False)
            assert ei.value.code == 'already_in_stage'
        elif legal:
            res = TSM.transition(rt, rid, to, actor=admin, actor_type='admin', commit=False,
                                 meta={'matrix': True})
            assert res.to_stage == to and res.ride.trip_stage == to
            assert res.ride.status == TSM.legacy_status(rt, to, res.ride.status)
            allowed += 1
            # a non-admin actor that the table doesn't list is refused
            db.session.rollback()
            row = R.load(rt, rid)
            row.trip_stage = frm
            db.session.flush()
            for role in ('customer', 'driver', 'system'):
                if role not in TSM.ACTORS[rt].get(to, ()):
                    with pytest.raises(TSM.TransitionError) as ei:
                        TSM.transition(rt, rid, to, actor=None if role == 'system' else admin,
                                       actor_type=None if role == 'system' else role, commit=False)
                    assert ei.value.code == 'forbidden_actor', (rt, frm, to, role)
        else:
            with pytest.raises(TSM.TransitionError) as ei:
                TSM.transition(rt, rid, to, actor=admin, actor_type='admin', commit=False)
            assert ei.value.code == 'invalid_transition', (rt, frm, to)
            assert ei.value.status == 409 and ei.value.data['stage'] == frm
    finally:
        db.session.rollback()
    return allowed


def test_terminal_stages_have_no_exits():
    for rt, terms in TSM.TERMINAL.items():
        for st in terms:
            assert not TSM.allowed_next(rt, st), (rt, st)


# ── cancellation at the API level ──────────────────────────────────────────

def test_cancel_before_payment_costs_nothing(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    neg_id = create_negotiation(client, auth, customer, driver)
    agree(client, auth, customer, driver, neg_id)
    r = client.post(f'/api/rides/carhire/{neg_id}/pay', headers=auth(customer))
    rp = db.session.get(RidePayment, body(r)['data']['ride_payment_id'])
    prev = body(client.get(f'/api/rides/carhire/{neg_id}/cancel-preview', headers=auth(customer)))['data']
    assert prev['fee_cents'] == 0 and prev['rule_id'] in ('before_payment', 'before_en_route')
    r = client.post(f'/api/rides/carhire/{neg_id}/cancel', headers=auth(customer), json={'reason_code': 'changed_mind'})
    assert body(r)['code'] == 1 and body(r)['data']['policy']['fee_cents'] == 0, r.get_json()
    db.session.rollback()
    assert db.session.get(Negotiation, neg_id).trip_stage == 'CANCELLED_BY_CUSTOMER'
    rp = db.session.get(RidePayment, rp.id)
    assert rp.capture_status == 'canceled' and get_gateway().sessions[rp.checkout_session_id]['status'] == 'expired'


def test_cancel_after_arrival_charges_fee_plus_waiting(client, auth, make_user):
    from tests.test_carhire_flow import _confirmed_ride
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=auth(driver))
    assert body(client.post(f'/api/rides/carhire/{neg_id}/arrived', headers=auth(driver),
                            json={'lat': PICKUP[0], 'lng': PICKUP[1]}))['code'] == 1
    neg = db.session.get(Negotiation, neg_id)
    neg.driver_arrived_at = datetime.utcnow() - timedelta(minutes=5, seconds=30)   # 3.5 min over the free 2 → 4 billed
    db.session.commit()
    prev = body(client.get(f'/api/rides/carhire/{neg_id}/cancel-preview', headers=auth(customer)))['data']
    assert prev['rule_id'] == 'after_arrival' and prev['fee_cents'] == 500 + 4 * 35
    r = client.post(f'/api/rides/carhire/{neg_id}/cancel', headers=auth(customer))
    assert body(r)['data']['policy']['fee_cents'] == 640, r.get_json()
    db.session.rollback()
    rp = db.session.get(RidePayment, rp.id)
    assert rp.capture_status == 'partially_captured' and rp.amount_captured_cents == 640
    assert ('capture', rp.intent_id, 640) in get_gateway().calls


# ── one end-to-end ride ─────────────────────────────────────────────────────

def test_end_to_end_request_to_closed(client, auth, make_user):
    base = (round(random.uniform(56.0, 68.0), 4), round(random.uniform(-125.0, -85.0), 4))
    customer = make_user('customer')
    driver = make_user('driver', current_latitude=base[0] + 0.01, current_longitude=base[1])
    register_v4_device(client, auth, customer)          # v4 rider → PIN required
    req = body(client.post('/api/carhire/requests', headers=auth(customer), json={
        'mode': 'broadcast', 'offer_cents': 2000, 'service_type': 'car',
        'pickup': {'lat': base[0], 'lng': base[1], 'address': '1 Remote Rd'},
        'dropoff': {'lat': base[0] + 0.05, 'lng': base[1], 'address': '9 Far St'}}))['data']['request']
    assert body(client.post(f"/api/carhire/requests/{req['id']}/accept", headers=auth(driver),
                            json={'counter_cents': 2400}))['code'] == 1
    live = body(client.get(f"/api/carhire/requests/{req['id']}", headers=auth(customer)))['data']['live_offers']
    r = client.post(f"/api/carhire/requests/{req['id']}/offers/{live[0]['offer_id']}/accept", headers=auth(customer))
    neg_id = body(r)['data']['negotiation']['id']
    db.session.rollback()
    assert db.session.get(Negotiation, neg_id).trip_stage == 'AWAITING_PAYMENT'

    r = client.post(f'/api/rides/carhire/{neg_id}/pay', headers=auth(customer))
    rp = db.session.get(RidePayment, body(r)['data']['ride_payment_id'])
    PS.handle_stripe_event(get_gateway().simulate_customer_pays(rp.checkout_session_id))
    db.session.rollback()
    neg = db.session.get(Negotiation, neg_id)
    assert neg.trip_stage == 'CONFIRMED' and neg.ride_pin
    pin = neg.ride_pin

    assert body(client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=auth(driver)))['code'] == 1
    assert body(client.post(f'/api/rides/carhire/{neg_id}/arrived', headers=auth(driver),
                            json={'lat': base[0], 'lng': base[1]}))['code'] == 1
    assert body(client.post(f'/api/rides/carhire/{neg_id}/start', headers=auth(driver)))['data']['error_code'] == 'pin_required'
    assert body(client.post(f'/api/rides/carhire/{neg_id}/start', headers=auth(driver), json={'pin': pin}))['code'] == 1
    email_provider.OUTBOX.clear()
    assert body(client.post(f'/api/rides/carhire/{neg_id}/complete', headers=auth(driver),
                            json={'lat': base[0] + 0.05, 'lng': base[1]}))['code'] == 1
    db.session.rollback()
    rp = db.session.get(RidePayment, rp.id)
    assert rp.capture_status == 'captured' and rp.amount_captured_cents == 2400
    receipt = Receipt.query.filter_by(ride_type='carhire', ride_id=neg_id).one()
    assert receipt.total_cents == 2400 and receipt.emailed_at is not None
    assert any(m['to'] == customer.email and m['tag'] == 'ride.receipt' for m in email_provider.OUTBOX)

    assert body(client.post(f'/api/rides/carhire/{neg_id}/rating', headers=auth(customer), json={'stars': 5}))['code'] == 1
    db.session.rollback()
    assert db.session.get(Negotiation, neg_id).trip_stage == 'COMPLETED'
    assert body(client.post(f'/api/rides/carhire/{neg_id}/rating', headers=auth(driver), json={'stars': 5}))['code'] == 1
    db.session.rollback()
    assert db.session.get(Negotiation, neg_id).trip_stage == 'CLOSED'
    got = [e.to_stage for e in TripEvent.query.filter_by(ride_type='carhire', ride_id=neg_id).order_by(TripEvent.id)]
    assert got == ['NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT', 'CONFIRMED', 'DRIVER_EN_ROUTE',
                   'DRIVER_ARRIVED', 'IN_PROGRESS', 'COMPLETED', 'CLOSED']
