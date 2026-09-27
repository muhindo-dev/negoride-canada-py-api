"""Car hire pick-a-driver / favourite-first / broadcast (spec §18.2), privacy,
fair-price hint + demand heatmap (§21.2), instant-search support (§21.3) and
admin reports (§19.1.13)."""
import random
import uuid
from datetime import datetime, timedelta

import pytest

from backend.models import db
from backend.models.experience import RideRequest, RideRequestOffer
from backend.models.negotiation import Negotiation
from backend.models.negotiation_record import NegotiationRecord
from backend.models.notification import Notification
from backend.models.platform import AnalyticsEvent
from backend.services import experience_jobs, insights_service, realtime
from tests.conftest import body
from tests.exp_helpers import _experience_cleanup, make_carhire, override  # noqa: F401

# A random remote spot per test, so the shared dev database's real drivers (and
# leftovers of interrupted test runs) never interfere.
BASE = (62.5000, -100.5000)


@pytest.fixture(autouse=True)
def _remote_base():
    global BASE
    BASE = (round(random.uniform(56.0, 68.0), 4), round(random.uniform(-125.0, -85.0), 4))
    yield


def at(dlat=0.0, dlng=0.0):
    return BASE[0] + dlat, BASE[1] + dlng


def driver_at(make_user, point):
    return make_user('driver', current_latitude=point[0], current_longitude=point[1])


def request_body(mode='broadcast', offer=2000, **kw):
    return {'mode': mode, 'offer_cents': offer, 'service_type': 'car',
            'pickup': {'lat': BASE[0], 'lng': BASE[1], 'address': '1 Remote Rd'},
            'dropoff': {'lat': BASE[0] + 0.05, 'lng': BASE[1], 'address': '9 Far St'}, **kw}


def test_nearby_drivers_privacy(client, auth, make_user):
    c = make_user('customer')
    exact = at(0.0031, 0.0017)
    d = driver_at(make_user, exact)
    far = driver_at(make_user, at(1.0, 0))          # ~110 km away
    r = body(client.get('/api/carhire/nearby-drivers', headers=auth(c),
                        query_string={'lat': BASE[0], 'lng': BASE[1], 'service_type': 'car'}))
    ids = [x['id'] for x in r['data']['drivers']]
    assert d.id in ids and far.id not in ids
    card = next(x for x in r['data']['drivers'] if x['id'] == d.id)
    assert card['first_name'] == d.first_name
    for secret in ('phone_number', 'last_name', 'email', 'name', 'current_latitude'):
        assert secret not in card
    loc = card['approx_location']
    assert (loc['lat'], loc['lng']) != exact and abs(loc['lat'] - exact[0]) <= 0.0011
    assert card['eta_minutes'] >= 1 and card['distance_m'] % 100 == 0


def test_direct_request_creates_negotiation(client, auth, make_user):
    c = make_user('customer')
    d = driver_at(make_user, at(0.01))
    r = client.post('/api/carhire/requests', headers=auth(c), json=request_body('direct', driver_id=d.id))
    assert r.status_code == 201, r.get_json()
    data = body(r)['data']
    assert data['request']['status'] == 'matched' and data['negotiation']['driver_id'] == d.id
    neg = db.session.get(Negotiation, data['negotiation']['id'])
    assert neg.trip_stage == 'REQUESTED' and neg.request_mode == 'direct' and neg.initial_price == 2000
    assert Notification.query.filter_by(user_id=d.id, event_key='negotiation.new_request').count() == 1
    low = client.post('/api/carhire/requests', headers=auth(c), json=request_body('direct', offer=100, driver_id=d.id))
    assert body(low)['data']['error_code'] == 'offer_too_low'


def test_favourite_first_then_broadcast_first_acceptor_wins(client, auth, make_user):
    c = make_user('customer')
    fav = driver_at(make_user, at(0.02))
    b, e = driver_at(make_user, at(0.01)), driver_at(make_user, at(-0.01))

    # favourites CRUD
    assert body(client.post('/api/favourite-drivers', headers=auth(c), json={'driver_id': fav.id}))['code'] == 1
    favs = body(client.get('/api/favourite-drivers', headers=auth(c)))['data']['drivers']
    assert [f['driver_id'] for f in favs] == [fav.id] and 'phone_number' not in favs[0]

    r = client.post('/api/carhire/requests', headers=auth(c), json=request_body('favourite_first'))
    assert r.status_code == 201, r.get_json()
    req = body(r)['data']['request']
    assert req['status'] == 'favourite' and req['favourite_driver']['id'] == fav.id and body(r)['data']['offers_sent'] == 1
    # only the favourite sees it during the exclusivity window
    inc_fav = body(client.get('/api/carhire/requests/incoming', headers=auth(fav)))['data']['requests']
    assert [x['request_id'] for x in inc_fav] == [req['id']] and inc_fav[0]['is_favourite'] is True
    assert 'phone_number' not in inc_fav[0]['customer'] and inc_fav[0]['customer']['first_name'] == c.first_name
    assert body(client.get('/api/carhire/requests/incoming', headers=auth(b)))['data']['requests'] == []

    # 45 s later → broadcast to the nearest online drivers
    res = experience_jobs.tick(datetime.utcnow() + timedelta(seconds=50))
    assert res['broadcast'] >= 1
    db.session.rollback()
    row = db.session.get(RideRequest, req['id'])
    assert row.status == 'broadcasting'
    offered = {o.driver_id for o in RideRequestOffer.query.filter_by(request_id=row.id)}
    assert {fav.id, b.id, e.id} <= offered

    realtime.SENT.clear()
    win = client.post(f"/api/carhire/requests/{req['id']}/accept", headers=auth(b), json={})
    assert body(win)['code'] == 1, win.get_json()
    neg = body(win)['data']['negotiation']
    assert neg['driver_id'] == b.id and neg['trip_stage'] in ('PRICE_AGREED', 'AWAITING_PAYMENT')
    assert neg['agreed_price_cents'] == 2000
    lose = client.post(f"/api/carhire/requests/{req['id']}/accept", headers=auth(e), json={})
    assert lose.status_code == 409 and body(lose)['data']['error_code'] == 'already_taken'

    db.session.rollback()
    statuses = {o.driver_id: o.status for o in RideRequestOffer.query.filter_by(request_id=req['id'])}
    assert statuses[b.id] == 'accepted' and statuses[e.id] == 'withdrawn' and statuses[fav.id] == 'withdrawn'
    assert any(ev == 'carhire.request_matched' and room == f'user:{c.id}' for ev, _, room in realtime.SENT)
    assert any(ev == 'carhire.request_withdrawn' and room == f'user:{e.id}' for ev, _, room in realtime.SENT)
    got = body(client.get(f"/api/carhire/requests/{req['id']}", headers=auth(c)))['data']
    assert got['status'] == 'matched' and got['negotiation_id'] == neg['id'] and got['matched_driver']['id'] == b.id
    # a driver who was never offered can't see it
    outsider = driver_at(make_user, at(5, 5))
    assert client.get(f"/api/carhire/requests/{req['id']}", headers=auth(outsider)).status_code == 404

    assert body(client.delete(f'/api/favourite-drivers/{fav.id}', headers=auth(c)))['data']['drivers'] == []


def test_favourite_decline_broadcasts_at_once_and_counter_offer(client, auth, make_user):
    c = make_user('customer')
    fav, b = driver_at(make_user, at(0.02)), driver_at(make_user, at(0.01))
    client.post('/api/favourite-drivers', headers=auth(c), json={'driver_id': fav.id})
    req = body(client.post('/api/carhire/requests', headers=auth(c),
                           json=request_body('favourite_first', driver_id=fav.id)))['data']['request']
    assert body(client.post(f"/api/carhire/requests/{req['id']}/decline", headers=auth(fav)))['code'] == 1
    db.session.rollback()
    assert db.session.get(RideRequest, req['id']).status == 'broadcasting'

    r = client.post(f"/api/carhire/requests/{req['id']}/accept", headers=auth(b), json={'counter_cents': 2600})
    assert body(r)['code'] == 1, r.get_json()
    neg = body(r)['data']['negotiation']
    assert neg['trip_stage'] == 'NEGOTIATING' and neg['last_offer_price'] == 2600
    assert NegotiationRecord.query.filter_by(negotiation_id=neg['id']).count() == 2
    assert Notification.query.filter_by(user_id=c.id, event_key='negotiation.counter_offer').count() == 1
    # the driver was not pinged with a redundant "new request" for a ride they already answered
    assert Notification.query.filter_by(user_id=b.id, event_key='negotiation.new_request').count() == 1


def test_broadcast_expiry_cancel_and_no_drivers(client, auth, make_user):
    c = make_user('customer')
    d = driver_at(make_user, at(0.01))
    req = body(client.post('/api/carhire/requests', headers=auth(c), json=request_body()))['data']['request']
    assert req['status'] == 'broadcasting' and req['offers']['sent'] >= 1
    experience_jobs.tick(datetime.utcnow() + timedelta(seconds=200))
    db.session.rollback()
    assert db.session.get(RideRequest, req['id']).status == 'expired'
    assert Notification.query.filter_by(user_id=c.id, event_key='ride.expired').count() == 1
    late = client.post(f"/api/carhire/requests/{req['id']}/accept", headers=auth(d), json={})
    assert late.status_code == 409

    req2 = body(client.post('/api/carhire/requests', headers=auth(c), json=request_body()))['data']['request']
    assert body(client.post(f"/api/carhire/requests/{req2['id']}/cancel", headers=auth(c)))['data']['status'] == 'cancelled'

    nobody = request_body()
    nobody['pickup'] = {'lat': 69.5, 'lng': -140.0 + random.uniform(-5, 5)}
    r = client.post('/api/carhire/requests', headers=auth(c), json=nobody)
    assert r.status_code == 409 and body(r)['data']['error_code'] == 'no_drivers'


def test_fair_range_estimate_and_history(client, auth, make_user):
    c, d = make_user('customer'), make_user('driver')
    q = {'from_lat': BASE[0], 'from_lng': BASE[1], 'to_lat': BASE[0] + 0.06, 'to_lng': BASE[1]}
    base = body(client.get('/api/pricing/fair-range', headers=auth(c), query_string=q))['data']
    assert base['low_cents'] <= base['typical_cents'] <= base['high_cents']
    assert base['basis']['distance_source'] == 'estimate' and base['distance_m'] > 6000
    assert base['text'].startswith('Typical fare for this route: $')

    for _ in range(8):   # similar completed rides agreed at $60
        make_carhire(c, d, pickup=BASE, dropoff=(BASE[0] + 0.06, BASE[1]), price_cents=6000)
    blended = body(client.get('/api/pricing/fair-range', headers=auth(c), query_string=q))['data']
    assert blended['basis']['history_count'] >= 8 and blended['basis']['history_weight'] > 0
    assert blended['typical_cents'] > base['typical_cents']


def test_driver_demand_heatmap(client, auth, make_user):
    c = make_user('customer')
    d = driver_at(make_user, at(0.01))
    client.post('/api/carhire/requests', headers=auth(c), json=request_body())
    hm = body(client.get('/api/driver/demand-heatmap', headers=auth(d),
                         query_string={'lat': BASE[0], 'lng': BASE[1], 'radius_km': 5}))['data']
    cell = min(hm['cells'], key=lambda x: abs(x['lat'] - BASE[0]) + abs(x['lng'] - BASE[1]))
    assert cell['count'] >= 1 and set(cell) == {'lat', 'lng', 'count', 'intensity'}
    assert client.get('/api/driver/demand-heatmap', headers=auth(c),
                      query_string={'lat': BASE[0], 'lng': BASE[1]}).status_code == 403


def test_popular_places(client):
    r = body(client.get('/api/places/popular?province=ON'))['data']
    codes = {p['id'] for p in r['places']}
    assert {'YYZ', 'YOW', 'YKF', 'YXU', 'union-station-toronto'} <= codes
    assert all(p['province'] == 'ON' for p in r['places'])
    allp = {p['id'] for p in body(client.get('/api/places/popular'))['data']['places']}
    assert {'YVR', 'YUL', 'YYC', 'YEG', 'YWG', 'YHZ', 'YQB', 'YXE', 'YQR', 'YYJ'} <= allp
    assert client.get('/api/places/popular?province=ZZ').status_code == 400


def test_analytics_events_rate_limit_and_latency(client, auth, make_user, override):
    insights_service.reset_rate_limits()
    admin, c = make_user('admin'), make_user('customer')
    name = f'test_latency_{uuid.uuid4().hex[:8]}'
    try:
        for chunk in range(2):
            evs = [{'name': name, 'value_num': v} for v in range(chunk * 50 + 1, chunk * 50 + 51)]
            r = client.post('/api/analytics/events', headers=auth(c), json={'events': evs})
            assert r.status_code == 202 and body(r)['data']['accepted'] == 50, r.get_json()
        bad = client.post('/api/analytics/events', json={'events': [{'name': 'Bad Name!'}, {'name': name, 'value_num': 'x'}]})
        assert body(bad)['data'] == {'accepted': 0, 'dropped': 2}

        stats = body(client.get(f'/api/admin/analytics/latency?name={name}&days=7', headers=auth(admin)))['data']
        assert stats['count'] == 100 and stats['p50'] == 50 and stats['p95'] == 95
        assert client.get(f'/api/admin/analytics/latency?name={name}', headers=auth(c)).status_code == 403

        override['analytics.max_events_per_min'] = 3
        insights_service.reset_rate_limits()
        r = client.post('/api/analytics/events', json={'events': [{'name': name}] * 4})
        assert r.status_code == 429
    finally:
        AnalyticsEvent.query.filter_by(name=name).delete()
        db.session.commit()


def test_admin_reports(client, auth, make_user):
    admin, c = make_user('admin'), make_user('customer')
    d = driver_at(make_user, at(0.01))
    client.post('/api/carhire/requests', headers=auth(c), json=request_body())
    make_carhire(c, d)
    experience_jobs.tick()
    today = datetime.utcnow().strftime('%Y-%m-%d')
    for path in ('demand-heatmap', 'supply-demand', 'negotiations', 'cohorts', 'earnings-distribution'):
        r = client.get(f'/api/admin/reports/{path}?to={today}', headers=auth(admin))
        assert body(r)['code'] == 1, (path, r.get_json())
        assert client.get(f'/api/admin/reports/{path}', headers=auth(c)).status_code == 403
    sd = body(client.get('/api/admin/reports/supply-demand?tz=America/Toronto', headers=auth(admin)))['data']
    assert sd['totals']['requests'] >= 1 and len(sd['by_hour_of_day']) == 24
    neg = body(client.get('/api/admin/reports/negotiations', headers=auth(admin)))['data']
    assert neg['negotiations'] >= 1 and 'avg_discount_from_driver_initial_ask_pct' in neg
    coh = body(client.get('/api/admin/reports/cohorts?weeks=4', headers=auth(admin)))['data']
    assert coh['weeks'] == 4
    assert client.get('/api/admin/reports/negotiations?from=2026-13-01', headers=auth(admin)).status_code == 400
