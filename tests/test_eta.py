"""Live ETA (spec §16): throttle, deviation, Google Routes request format,
haversine fallback, DRIVER_ARRIVING trigger, realtime event, polling endpoint."""
import json

import pytest

from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.platform import TripEvent
from backend.services import eta as ETA
from backend.services import geo_routes as G
from backend.services import realtime
from tests.conftest import body
from tests.exp_helpers import _experience_cleanup, make_carhire  # noqa: F401

PICKUP = (43.6532, -79.3832)
FAR = (43.6800, -79.3832)        # ~3 km north of the pickup
NEARER_FAR = (43.6750, -79.3832)


@pytest.fixture(autouse=True)
def _reset_eta():
    ETA.reset_state()
    G.CALLS.clear()
    yield
    ETA.reset_state()


def en_route(make_user):
    c, d = make_user('customer'), make_user('driver')
    ride = make_carhire(c, d, stage='DRIVER_EN_ROUTE', pickup=PICKUP, stripe_paid='Yes', payment_status='paid')
    return c, d, ride


def eta_events():
    return [(e, data, room) for e, data, room in realtime.SENT if e == 'ride.eta_updated']


def test_fallback_estimate_persists_and_emits(make_user):
    c, d, ride = en_route(make_user)
    assert ETA.maybe_refresh('carhire', ride.id, FAR) is True
    db.session.rollback()
    n = db.session.get(Negotiation, ride.id)
    assert n.eta_target == 'pickup' and n.eta_seconds > 120 and n.eta_distance_m > 2500
    assert n.initial_eta_at is not None and n.eta_updated_at is not None
    assert G.CALLS == []                        # no key → never calls Google
    rooms = {room for _, _, room in eta_events()}
    assert f'ride:carhire:{ride.id}' in rooms and f'user:{c.id}' in rooms
    data = eta_events()[0][1]
    assert set(data) >= {'ride_type', 'ride_id', 'seconds', 'minutes', 'distance_m', 'target', 'arrives_at'}
    assert data['source'] == 'estimate'
    assert n.trip_stage == 'DRIVER_EN_ROUTE'    # still far away


def test_throttle_and_deviation(make_user, monkeypatch):
    c, d, ride = en_route(make_user)
    assert ETA.maybe_refresh('carhire', ride.id, FAR) is True
    assert ETA.maybe_refresh('carhire', ride.id, NEARER_FAR) is False      # within 30 s
    assert ETA.maybe_refresh('carhire', ride.id, (43.7200, -79.3832)) is True   # drove 4 km away → deviation
    assert len(eta_events()) == 4                # 2 computations × (ride room + customer room)
    # after the interval it refreshes again
    st = ETA._get_state(ETA._key('carhire', ride.id))
    st['at'] -= 31
    ETA._set_state(ETA._key('carhire', ride.id), st)
    assert ETA.maybe_refresh('carhire', ride.id, NEARER_FAR) is True


def test_google_routes_request_and_arriving_trigger(make_user, monkeypatch):
    c, d, ride = en_route(make_user)
    monkeypatch.setenv('GOOGLE_MAPS_SERVER_KEY', 'test-server-key')
    sent = {}

    class Resp:
        status_code = 200

        def json(self):
            return {'routes': [{'duration': '95s', 'distanceMeters': 700}]}

    def fake_post(url, data=None, headers=None, timeout=None):
        sent.update(url=url, body=json.loads(data), headers=headers)
        return Resp()
    monkeypatch.setattr('requests.post', fake_post)

    assert ETA.maybe_refresh('carhire', ride.id, (43.6590, -79.3832)) is True
    assert sent['url'] == 'https://routes.googleapis.com/directions/v2:computeRoutes'
    assert sent['headers']['X-Goog-Api-Key'] == 'test-server-key'
    assert sent['headers']['X-Goog-FieldMask'] == 'routes.duration,routes.distanceMeters'
    assert sent['body']['routingPreference'] == 'TRAFFIC_AWARE' and sent['body']['travelMode'] == 'DRIVE'
    assert sent['body']['destination']['location']['latLng'] == {'latitude': PICKUP[0], 'longitude': PICKUP[1]}

    db.session.rollback()
    n = db.session.get(Negotiation, ride.id)
    assert n.eta_seconds == 95 and n.eta_distance_m == 700
    assert n.trip_stage == 'DRIVER_ARRIVING'     # ETA ≤ 2 min
    ev = TripEvent.query.filter_by(ride_type='carhire', ride_id=ride.id, to_stage='DRIVER_ARRIVING').one()
    assert ev.actor_type == 'system' and ev.meta.get('by') == 'eta'


def test_google_failure_falls_back(make_user, monkeypatch):
    c, d, ride = en_route(make_user)
    monkeypatch.setenv('GOOGLE_MAPS_SERVER_KEY', 'k')

    class Bad:
        status_code = 403
        text = 'denied'
    monkeypatch.setattr('requests.post', lambda *a, **k: Bad())
    ETA.maybe_refresh('carhire', ride.id, FAR)
    assert eta_events()[0][1]['source'] == 'estimate'


def test_dropoff_target_in_progress(make_user):
    c, d = make_user('customer'), make_user('driver')
    ride = make_carhire(c, d, stage='IN_PROGRESS', pickup=PICKUP, dropoff=(43.7000, -79.4000))
    ETA.maybe_refresh('carhire', ride.id, PICKUP)
    db.session.rollback()
    n = db.session.get(Negotiation, ride.id)
    assert n.eta_target == 'dropoff' and n.initial_eta_at is None


def test_location_update_drives_eta_and_polling_endpoint(client, auth, make_user):
    c, d, ride = en_route(make_user)
    r = client.post('/api/update-location', headers=auth(d), json={'latitude': FAR[0], 'longitude': FAR[1]})
    assert body(r)['code'] == 1
    got = body(client.get(f'/api/rides/carhire/{ride.id}/eta', headers=auth(c)))['data']
    assert got['eta']['target'] == 'pickup' and got['eta']['seconds'] > 0
    assert got['driver_location']['lat'] == pytest.approx(FAR[0])
    stranger = make_user('customer')
    assert client.get(f'/api/rides/carhire/{ride.id}/eta', headers=auth(stranger)).status_code == 403


def test_snap_to_roads_without_key_returns_input():
    pts = [(43.1, -79.1), (43.2, -79.2)]
    assert G.snap_to_roads(pts) == pts
