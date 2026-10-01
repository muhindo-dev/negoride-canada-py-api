"""Safety audit gaps (spec §8, §9, §10, §16): PIN lock, vehicle photo, planned
route deviation, check-timeout links, auto-share fallback, admin live rides,
recording transparency + streaming proxy + dispute retention, public tracking
hardening, batched breadcrumbs, readiness, on-call gaps, Live Activity hook,
help contacts, Roads snapping."""
import hashlib
import json
import sys
import threading
import types
from datetime import datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from backend import jobs
from backend.models import db
from backend.models.identity import DriverApplication, DriverDocument, SupportTicket
from backend.models.negotiation import Negotiation
from backend.models.notification import Notification
from backend.models.platform import AuditLog
from backend.models.safety import (HelpContact, Recording, RecordingChunk, RideLocation, RideRoute, RideShareLink,
                                   SafetyCheck, SafetyIncident, SafetyReport, TrustedContact)
from backend.models.trip import Trip
from backend.services import eta as ETA
from backend.services import geo_routes as G
from backend.services import private_storage as PS
from backend.services import realtime
from backend.services import rides as R
from backend.services import safety_detection as SD
from backend.services import safety_jobs
from backend.services import safety_service as SS
from backend.services import settings_service as S
from backend.services import tracking
from backend.services import trip_state_machine as TSM
from backend.services import twilio_client
from tests.conftest import body
from tests.test_safety import DROPOFF, PICKUP, add_contact, make_ride, sos


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    PS.configure(root=str(tmp_path / 'private'), key=Fernet.generate_key().decode())
    twilio_client.SENT.clear()
    SS.CALLS.clear()
    tracking.reset_memory()
    from backend.routes import tracking_share
    monkeypatch.setattr(tracking_share, '_rl', {})
    yield
    tracking.BATCH = None
    PS.configure(None)


@pytest.fixture()
def admins(make_user, monkeypatch):
    ops = make_user('admin', admin_roles='ops')
    reviewer = make_user('admin', admin_roles='safety_reviewer')
    monkeypatch.setattr(SS, 'admin_recipient_ids', lambda: [ops.id, reviewer.id])
    return ops, reviewer


def _override(monkeypatch, **values):
    """Override integer settings for one test (no DB writes)."""
    real = S.get_int

    def fake(key, default=0):
        k = key.replace('__', '.')
        return values[k] if k in values else real(key, default)
    monkeypatch.setattr(S, 'get_int', fake)


# ── 2. ride PIN brute force ─────────────────────────────────────────────────

def test_pin_brute_force_locks_audits_and_alerts(client, auth, make_user, admins, monkeypatch):
    monkeypatch.setattr(TSM, 'pin_required', lambda rt, ride: True)
    monkeypatch.setattr(TSM, 'payment_secured', lambda rt, ride: True)
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver, stage='DRIVER_ARRIVED')
    url = f'/api/rides/carhire/{ride.id}/start'
    for left in (4, 3, 2, 1):
        r = client.post(url, headers=auth(driver), json={'pin': '0000'})
        d = body(r)['data']
        assert d['error_code'] == 'pin_invalid' and d['attempts_left'] == left
    realtime.SENT.clear()
    r = client.post(url, headers=auth(driver), json={'pin': '0000'})
    assert r.status_code == 429
    d = body(r)['data']
    assert d['error_code'] == 'pin_locked' and 0 < d['retry_after'] <= 601
    # even the right PIN is refused while locked
    r = client.post(url, headers=auth(driver), json={'pin': '4821'})
    assert r.status_code == 429 and body(r)['data']['error_code'] == 'pin_locked'
    db.session.rollback()
    assert AuditLog.query.filter_by(action='ride.pin_locked', entity_type='carhire',
                                    entity_id=str(ride.id)).count() == 1
    assert any(e == 'alert' and dd.get('kind') == 'pin_locked' and room == 'admin:ops'
               for e, dd, room in realtime.SENT)
    ops, _ = admins
    assert Notification.query.filter_by(user_id=ops.id, event_key='safety.pin_locked').count() == 1
    assert db.session.get(Negotiation, ride.id).trip_stage == 'DRIVER_ARRIVED'
    # window passes → the right PIN starts the ride
    db.session.execute(db.text('UPDATE ride_pin_failures SET created_at = created_at - INTERVAL 11 MINUTE '
                               'WHERE ride_type=:t AND ride_id=:i'), {'t': 'carhire', 'i': ride.id})
    db.session.commit()
    r = client.post(url, headers=auth(driver), json={'pin': '4821'})
    assert r.status_code == 200, r.get_json()
    db.session.rollback()
    assert db.session.get(Negotiation, ride.id).trip_stage == 'IN_PROGRESS'


# ── 3. vehicle photo on the verification card ───────────────────────────────

def _approved_vehicle(driver, photo=b'\xff\xd8\xff jpeg bytes'):
    app = DriverApplication(user_id=driver.id, status='approved', current_step='approved', vehicle_make='Toyota',
                            vehicle_model='Corolla', vehicle_color='Blue', vehicle_plate='ABCD 123',
                            vehicle_seats=4)
    db.session.add(app)
    db.session.flush()
    key = f'driver-docs/{driver.id}/{app.id}/vehicle_front-test.jpg'
    PS.put(key, photo, 'image/jpeg')
    db.session.add(DriverDocument(application_id=app.id, user_id=driver.id, type='vehicle_front', file_path=key,
                                  mime_type='image/jpeg', status='approved'))
    db.session.commit()
    return app


def test_vehicle_card_photo_only_for_parties_of_confirmed_ride(client, auth, make_user):
    customer, driver, stranger = make_user('customer'), make_user('driver'), make_user('customer')
    photo = b'\xff\xd8\xff' + b'p' * 50
    _approved_vehicle(driver, photo)
    ride = make_ride(customer, driver, stage='CONFIRMED')
    card = R.vehicle_card(driver, ride_type='carhire', ride=ride, viewer=customer)
    assert card['plate'] == 'ABCD 123' and '/api/private-files/' in card['photo_url']
    got = client.get(card['photo_url'][card['photo_url'].index('/api/'):])
    assert got.status_code == 200 and got.data == photo
    assert R.vehicle_card(driver, ride_type='carhire', ride=ride, viewer=driver)['photo_url']
    assert R.vehicle_card(driver, ride_type='carhire', ride=ride, viewer=stranger)['photo_url'] is None
    assert 'photo_url' not in R.vehicle_card(driver)                       # no ride context → never
    ride.trip_stage = 'NEGOTIATING'
    db.session.commit()
    assert R.vehicle_card(driver, ride_type='carhire', ride=ride, viewer=customer)['photo_url'] is None
    ride.trip_stage = 'COMPLETED'
    db.session.commit()
    assert R.vehicle_card(driver, ride_type='carhire', ride=ride, viewer=customer)['photo_url'] is None
    # safety toolkit card
    ride.trip_stage = 'IN_PROGRESS'
    db.session.commit()
    d = body(client.get('/api/safety/toolkit', headers=auth(customer)))['data']
    assert d['ride']['vehicle']['photo_url']


# ── 4. planned route deviation ──────────────────────────────────────────────

L_CORNER_1 = (43.6532, -79.3500)
L_CORNER_2 = (43.6426, -79.3500)


def test_planned_route_polyline_deviation(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    poly = G.encode_polyline([PICKUP, L_CORNER_1, L_CORNER_2, DROPOFF])
    assert [tuple(round(x, 5) for x in p) for p in G.decode_polyline(poly)] == \
        [PICKUP, L_CORNER_1, L_CORNER_2, DROPOFF]
    db.session.add(RideRoute(ride_type='carhire', ride_id=ride.id, target='dropoff', polyline=poly,
                             distance_m=6000, duration_s=900, source='google_routes', created_at=datetime.utcnow()))
    db.session.commit()
    # On the planned (L-shaped) route, ~2.7 km off the straight corridor → no check
    for pt in ((43.6532, -79.3505), (43.6500, -79.3502)):
        client.post('/api/update-location', headers=auth(driver), json={'latitude': pt[0], 'longitude': pt[1]})
    assert SafetyCheck.query.filter_by(ride_type='carhire', ride_id=ride.id).count() == 0
    # On the straight line but ~590 m from every planned segment → check after 2 points
    client.post('/api/update-location', headers=auth(driver), json={'latitude': 43.6479, 'longitude': -79.3851})
    assert SafetyCheck.query.filter_by(ride_type='carhire', ride_id=ride.id).count() == 0
    client.post('/api/update-location', headers=auth(driver), json={'latitude': 43.6478, 'longitude': -79.3852})
    chk = SafetyCheck.query.filter_by(ride_type='carhire', ride_id=ride.id).one()
    assert chk.kind == 'route_deviation' and chk.meta['reference'] == 'planned_route'
    assert chk.meta['tolerance_m'] == 500 and chk.meta['off_route_m'] > 500


def test_planned_route_stored_on_start_straight_and_google(make_user, monkeypatch):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver, stage='DRIVER_ARRIVED')
    admin = make_user('admin')
    TSM.transition('carhire', ride.id, 'IN_PROGRESS', actor=admin, actor_type='admin')
    db.session.rollback()
    row = RideRoute.query.filter_by(ride_type='carhire', ride_id=ride.id, target='dropoff').one()
    assert row.source == 'straight_line' and len(G.decode_polyline(row.polyline)) == 2
    # With a server key the Google polyline is requested (field mask includes it)
    ride2 = make_ride(customer, driver, stage='CONFIRMED')
    monkeypatch.setenv('GOOGLE_MAPS_SERVER_KEY', 'test-key')
    sent = {}

    class Resp:
        status_code = 200

        def json(self):
            return {'routes': [{'duration': '600s', 'distanceMeters': 2500,
                                'polyline': {'encodedPolyline': G.encode_polyline([PICKUP, L_CORNER_1, DROPOFF])}}]}
    import requests
    monkeypatch.setattr(requests, 'post', lambda url, data=None, timeout=None, headers=None:
                        sent.update(url=url, headers=headers, body=json.loads(data)) or Resp())
    rows = SD.on_route_stage('carhire', ride2, 'CONFIRMED')
    assert rows and rows[0].source == 'google_routes' and rows[0].duration_s == 600
    assert 'routes.polyline.encodedPolyline' in sent['headers']['X-Goog-FieldMask']
    targets = {r.target for r in RideRoute.query.filter_by(ride_type='carhire', ride_id=ride2.id)}
    assert targets == {'dropoff', 'pickup'}          # driver position → pickup as well


# ── 5. check timeout: role + incident link ──────────────────────────────────

def test_check_timeout_uses_role_and_creates_live_link(client, auth, make_user, admins, monkeypatch):
    monkeypatch.setenv('SAFETY_ONCALL_PHONES', '+14165550198')
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    chk = SafetyCheck(ride_type='carhire', ride_id=ride.id, user_id=driver.id, kind='long_stop', status='pending',
                      lat=43.66, lng=-79.39, created_at=datetime.utcnow() - timedelta(seconds=120))
    db.session.add(chk)
    db.session.commit()
    inc_id = safety_jobs.check_timeout(chk.id)
    db.session.rollback()
    inc = db.session.get(SafetyIncident, inc_id)
    assert inc.role == 'driver'
    assert RideShareLink.query.filter_by(ride_type='incident', ride_id=inc_id, user_id=driver.id).count() == 1
    assert any(p.endswith('escalate_incident') for _, p, _, _ in jobs.DEFERRED)
    twilio_client.SENT.clear()
    assert safety_jobs.escalate_incident(inc_id) is True
    assert any(m['to'] == '+14165550198' and 'Live location: ' in m['body'] and '/t/' in m['body']
               for m in twilio_client.SENT)


# ── 6. auto-share defaults + contact limit race ─────────────────────────────

def test_auto_share_defaults_to_all_contacts(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    c = add_contact(client, auth, customer, phone='+14165550181', auto_share=False)
    add_contact(client, auth, customer, phone='+14165550182', auto_share=False)
    r = client.post('/api/safety/trusted-contacts', headers=auth(customer), json={'name': 'Dad',
                                                                                  'phone': '+14165550183'})
    assert body(r)['data']['auto_share'] is True                            # new default
    client.put(f"/api/safety/trusted-contacts/{body(r)['data']['id']}", headers=auth(customer),
               json={'auto_share': False})
    client.put('/api/safety/settings', headers=auth(customer), json={'auto_share_all': True})
    ride = make_ride(customer, driver, stage='DRIVER_ARRIVED')
    twilio_client.SENT.clear()
    TSM.transition('carhire', ride.id, 'IN_PROGRESS', actor=make_user('admin'), actor_type='admin')
    to = {m['to'] for m in twilio_client.SENT if 'sharing a NegoRide trip' in m['body']}
    assert to == {'+14165550181', '+14165550182', '+14165550183'}           # nobody flagged → everyone
    assert c['auto_share'] is False


def test_trusted_contact_limit_is_race_safe(app, client, auth, make_user):
    user = make_user('customer')
    for i in range(4):
        add_contact(client, auth, user, phone=f'+1416555{7100 + i}', name=f'C{i}')
    h = auth(user)
    codes, barrier = [], threading.Barrier(3)

    def worker(n):
        with app.app_context():
            c = app.test_client()
            barrier.wait()
            codes.append(c.post('/api/safety/trusted-contacts', headers=h,
                                json={'name': f'R{n}', 'phone': f'+1416555{7200 + n}'}).status_code)
            db.session.remove()
    ts = [threading.Thread(target=worker, args=(n,)) for n in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    db.session.rollback()
    assert sorted(codes) == [201, 422, 422]
    assert TrustedContact.query.filter_by(user_id=user.id).count() == 5


# ── 7. admin live map ───────────────────────────────────────────────────────

def test_admin_live_rides_layers(client, auth, make_user, admins):
    from backend.models.experience import RideRequest
    ops, _ = admins
    customer, driver, walker = make_user('customer'), make_user('driver'), make_user('customer')
    rr = RideRequest(customer_id=customer.id, mode='broadcast', status='broadcasting', pickup_lat=43.65,
                     pickup_lng=-79.38, pickup_address='Union', offer_cents=1500,
                     expires_at=datetime.utcnow() + timedelta(minutes=5))
    db.session.add(rr)
    neg = make_ride(customer, driver, stage='REQUESTED')
    trip = Trip(driver_id=driver.id, status='ongoing', trip_stage='IN_PROGRESS', start_gps='43.65,-79.38',
                end_pgs='45.42,-75.69', start_name='Toronto', end_name='Ottawa', slots=3)
    db.session.add(trip)
    db.session.commit()
    try:
        tracking._set_latest(driver.id, {'lat': 43.7, 'lng': -79.4, 'heading': 90, 'at': '2026-09-28T10:00:00Z'})
        inc_id = body(sos(client, auth, walker, key='walk'))['data']['incident']['id']
        assert client.get('/api/admin/live/rides', headers=auth(customer)).status_code == 403
        d = body(client.get('/api/admin/live/rides', headers=auth(ops)))['data']
        kinds = {(x['kind'], x['id']) for x in d['requests']}
        assert ('ride_request', rr.id) in kinds and ('negotiation', neg.id) in kinds
        req = [x for x in d['requests'] if x['kind'] == 'ride_request' and x['id'] == rr.id][0]
        assert req['pickup']['lat'] == 43.65 and req['customer']['first_name']
        t = [x for x in d['rideshare_trips'] if x['trip_id'] == trip.id][0]
        assert t['position']['lat'] == 43.7 and t['driver']['id'] == driver.id
        s = [x for x in d['sos'] if x['incident_id'] == inc_id][0]
        assert s['ride_id'] is None and s['position']['lat'] == 43.65 and s['user']['role'] == 'customer'
        # SOS location updates reach the ops map room cheaply
        realtime.SENT.clear()
        client.post(f'/api/safety/incidents/{inc_id}/location', headers=auth(walker), json={'lat': 43.66, 'lng': -79.39})
        assert any(e == 'live.sos_location' and room == 'admin:ops' for e, _, room in realtime.SENT)
    finally:
        db.session.delete(db.session.get(RideRequest, rr.id))
        db.session.commit()


def test_live_drivers_include_offline_active(client, auth, make_user, admins):
    ops, _ = admins
    customer, driver = make_user('customer'), make_user('driver', ready_for_trip='No')
    make_ride(customer, driver, stage='DRIVER_EN_ROUTE')
    ids = lambda q: {x['driver_id'] for x in body(client.get('/api/admin/live/drivers' + q,  # noqa: E731
                                                             headers=auth(ops)))['data']['drivers']}
    assert driver.id in ids('') and driver.id in ids('?include_offline_active=1')
    assert driver.id not in ids('?include_offline_active=0')


# ── 8. recordings ───────────────────────────────────────────────────────────

def _upload(client, auth, user, rec_id, seq, data):
    import io
    return client.post(f'/api/recordings/{rec_id}/chunks', headers=auth(user), content_type='multipart/form-data',
                       data={'seq': str(seq), 'sha256': hashlib.sha256(data).hexdigest(),
                             'file': (io.BytesIO(data), f'{seq}.m4a', 'audio/mp4')})


def test_recording_status_after_stop_and_stream_proxy(client, auth, make_user, admins):
    ops, reviewer = admins
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    rec_id = body(client.post('/api/recordings', headers=auth(customer),
                              json={'ride_type': 'carhire', 'ride_id': ride.id}))['data']['recording']['id']
    audio = b'\x00\x00\x00\x18ftypM4A ' + bytes(range(256)) * 4
    assert _upload(client, auth, customer, rec_id, 0, audio).status_code == 201
    client.post(f'/api/recordings/{rec_id}/stop', headers=auth(customer))
    st = body(client.get(f'/api/rides/carhire/{ride.id}/recording-status', headers=auth(driver)))['data']
    assert st['recording_active'] is False and st['ever_recorded'] is True and st['other_party_ever_recorded']
    assert st['recordings'][0]['id'] == rec_id and st['recordings'][0]['stopped_at']
    assert 'url' not in json.dumps(st)
    # owner URL handout is audited
    client.get(f'/api/recordings/{rec_id}', headers=auth(customer))
    assert AuditLog.query.filter_by(action='recording.access', entity_id=str(rec_id), actor_id=customer.id).count() == 1
    # admin stream proxy: safety_reviewer only, every fetch audited, Range support
    det = body(client.get(f'/api/admin/safety/recordings/{rec_id}', headers=auth(reviewer)))['data']
    surl = det['chunks'][0]['stream_url']
    assert surl == f'/api/admin/safety/recordings/{rec_id}/chunks/0'
    assert client.get(surl, headers=auth(ops)).status_code == 403
    full = client.get(surl, headers=auth(reviewer))
    assert full.status_code == 200 and full.data == audio and 'no-store' in full.headers['Cache-Control']
    part = client.get(surl, headers=auth(reviewer, Range='bytes=0-9'))
    assert part.status_code == 206 and part.data == audio[:10]
    assert part.headers['Content-Range'] == f'bytes 0-9/{len(audio)}'
    assert client.get(surl, headers=auth(reviewer, Range='bytes=999999-')).status_code == 416
    assert client.get(f'/api/admin/safety/recordings/{rec_id}/chunks/7', headers=auth(reviewer)).status_code == 404
    assert AuditLog.query.filter_by(action='recording.chunk_streamed', entity_id=str(rec_id),
                                    actor_id=reviewer.id).count() == 3


def _old_rec(user, ride=None, days=10, **kw):
    old = datetime.utcnow() - timedelta(days=days)
    rec = Recording(user_id=user.id, role='customer', status='stopped', trigger_source='manual', started_at=old,
                    stopped_at=old, created_at=old, ride_type='carhire' if ride else None,
                    ride_id=ride.id if ride else None, **kw)
    db.session.add(rec)
    db.session.commit()
    return rec.id


def test_dispute_retention_and_mark_resolved(make_user):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver, stage='COMPLETED', disputed_at=datetime.utcnow() - timedelta(days=20))
    rid = _old_rec(customer, ride)
    safety_jobs.retention_cleanup(scope_user_ids=[customer.id])
    db.session.rollback()
    assert db.session.get(Recording, rid).status == 'stopped'               # open dispute
    assert SS.mark_dispute_resolved('carhire', ride.id, at=datetime.utcnow() - timedelta(days=5)) is True
    db.session.commit()
    assert SS.mark_dispute_resolved('carhire', ride.id) is False            # idempotent
    safety_jobs.retention_cleanup(scope_user_ids=[customer.id])
    db.session.rollback()
    assert db.session.get(Recording, rid).status == 'stopped'               # closed 5 d ago → +90 d hold
    n = db.session.get(Negotiation, ride.id)
    n.dispute_resolved_at = datetime.utcnow() - timedelta(days=91)
    db.session.commit()
    safety_jobs.retention_cleanup(scope_user_ids=[customer.id])
    db.session.rollback()
    assert db.session.get(Recording, rid).status == 'deleted'


def test_dispute_support_ticket_protects_recording(make_user):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver, stage='COMPLETED')
    rid = _old_rec(customer, ride)
    t = SupportTicket(user_id=customer.id, type='dispute', ride_type='carhire', ride_id=ride.id, subject='x',
                      status='open', priority='high')
    db.session.add(t)
    db.session.commit()
    safety_jobs.retention_cleanup(scope_user_ids=[customer.id])
    db.session.rollback()
    assert db.session.get(Recording, rid).status == 'stopped'
    t = db.session.get(SupportTicket, t.id)
    t.status, t.resolved_at = 'resolved', datetime.utcnow() - timedelta(days=100)
    db.session.commit()
    safety_jobs.retention_cleanup(scope_user_ids=[customer.id])
    db.session.rollback()
    assert db.session.get(Recording, rid).status == 'deleted'


def test_retention_protected_rows_cannot_starve_deletions(make_user, monkeypatch):
    monkeypatch.setattr(safety_jobs, 'PAGE', 2)
    user = make_user('customer')
    protected = []
    for _ in range(5):
        inc = SafetyIncident(user_id=user.id, role='customer', kind='sos', status='open',
                             created_at=datetime.utcnow())
        db.session.add(inc)
        db.session.commit()
        protected.append(_old_rec(user, incident_id=inc.id))
    plain = _old_rec(user)
    # breadcrumbs: 3 protected rides (open report) + 1 plain ride, all 200 days old
    old = datetime.utcnow() - timedelta(days=200)
    for rid in (900000001, 900000002, 900000003):
        db.session.add(SafetyReport(reporter_id=user.id, ride_type='carhire', ride_id=rid, category='other',
                                    status='open', created_at=old))
        db.session.add(RideLocation(ride_type='carhire', ride_id=rid, user_id=user.id, lat=1, lng=1,
                                    recorded_at=old))
    db.session.add(RideLocation(ride_type='carhire', ride_id=900000009, user_id=user.id, lat=1, lng=1,
                                recorded_at=old))
    db.session.commit()
    stats = safety_jobs.retention_cleanup(scope_user_ids=[user.id])
    db.session.rollback()
    assert db.session.get(Recording, plain).status == 'deleted'
    assert all(db.session.get(Recording, p).status == 'stopped' for p in protected)
    assert stats['recordings_kept_for_case'] == 5
    assert RideLocation.query.filter_by(ride_id=900000009).count() == 0
    assert RideLocation.query.filter(RideLocation.ride_id.in_([900000001, 900000002, 900000003])).count() == 3


# ── 9. public tracking hardening ────────────────────────────────────────────

def _share(client, auth, user, ride):
    return body(client.post(f'/api/rides/carhire/{ride.id}/share', headers=auth(user), json={}))['data']['token']


def test_public_track_ip_from_proxy_and_per_token_limit(client, auth, make_user, monkeypatch):
    # Rotating a spoofed left-most X-Forwarded-For doesn't dodge the per-IP limit:
    # ProxyFix trusts only the right-most hop (added by nginx).
    codes = [client.get('/api/public/track/nope', headers={'X-Forwarded-For': f'1.2.3.{i}, 10.7.7.7'},
                        environ_base={'REMOTE_ADDR': '127.0.0.1'}).status_code for i in range(62)]
    assert codes[0] == 404 and codes[-1] == 429
    _override(monkeypatch, **{'tracking.public_rate_limit_per_token_per_min': 3})
    customer, driver = make_user('customer'), make_user('driver')
    token = _share(client, auth, customer, make_ride(customer, driver))
    got = [client.get(f'/api/public/track/{token}', environ_base={'REMOTE_ADDR': f'10.6.0.{i}'}).status_code
           for i in range(4)]
    assert got == [200, 200, 200, 429]
    r = client.get(f'/t/{token}', environ_base={'REMOTE_ADDR': '10.6.1.1'})
    assert r.status_code == 429 and r.headers['Retry-After'] == '60'


def test_public_page_redirects_to_website_and_localized_eta(client, auth, make_user, monkeypatch):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    token = _share(client, auth, customer, ride)
    monkeypatch.setenv('PUBLIC_WEB_BASE_URL', 'https://negoride.ca')
    r = client.get(f'/t/{token}?lang=fr')
    assert r.status_code == 302 and r.headers['Location'] == f'https://negoride.ca/t/{token}?lang=fr'
    monkeypatch.setenv('PUBLIC_WEB_BASE_URL', 'http://localhost')          # same host → fallback page
    r = client.get(f'/t/{token}')
    assert r.status_code == 200 and b'noindex' in r.data
    client.post('/api/update-location', headers=auth(driver), json={'latitude': 43.650, 'longitude': -79.385})
    d = body(client.get(f'/api/public/track/{token}?lang=fr'))['data']
    assert d['status_text'] == 'En trajet' and d['eta']['arrives_at'].endswith('Z')
    assert d['eta']['text'].startswith(f"{d['eta']['minutes']} min") and ('km' in d['eta']['text']
                                                                         or ' m' in d['eta']['text'])
    # the live position comes from the latest-position store first
    tracking._set_latest(driver.id, {'lat': 43.6499, 'lng': -79.3849, 'heading': 45, 'at': '2026-09-28T10:00:00Z'})
    d = body(client.get(f'/api/public/track/{token}'))['data']
    assert d['driver_location']['lat'] == 43.6499 and d['driver_location']['heading'] == 45
    # …but never after the trip ended (only its last breadcrumb)
    ride.trip_stage = 'COMPLETED'
    db.session.commit()
    d = body(client.get(f'/api/public/track/{token}'))['data']
    assert d['driver_location']['lat'] == 43.65


# ── 10. location pipeline ───────────────────────────────────────────────────

def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def test_batch_points_offline_catch_up_and_dedupe(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    now = datetime.utcnow()
    pts = [{'lat': 43.640 + i * 0.001, 'lng': -79.38, 'recorded_at': _iso(now - timedelta(minutes=15 - i))}
           for i in range(3)]                                                 # stale (> 10 min)
    pts += [{'lat': 43.650, 'lng': -79.385, 'speed': 9, 'heading': 90, 'accuracy': 5,
             'recorded_at': _iso(now - timedelta(seconds=20))},
            {'lat': 43.651, 'lng': -79.385, 'recorded_at': _iso(now - timedelta(seconds=5))}]
    realtime.SENT.clear()
    r = client.post('/api/update-location', headers=auth(driver), json={'points': list(reversed(pts))})
    d = body(r)['data']
    assert d['points_received'] == 5 and d['points_stored'] == 5 and d['live'] is True
    db.session.rollback()
    assert RideLocation.query.filter_by(ride_type='carhire', ride_id=ride.id, user_id=driver.id).count() == 5
    locs = [dd for e, dd, _ in realtime.SENT if e == 'ride.driver_location']
    assert len(locs) == 1 and locs[0]['lat'] == 43.651                        # only the newest point is live
    assert float(db.session.get(type(driver), driver.id).current_latitude) == 43.651
    # re-sent batch → deduped on (user, recorded_at); nothing live (not newer)
    d = body(client.post('/api/update-location', headers=auth(driver), json={'points': pts}))['data']
    assert d['points_stored'] == 0 and d['live'] is False
    # an out-of-order (older than the last live point) point is stored, not live
    d = body(client.post('/api/update-location', headers=auth(driver),
                         json={'lat': 43.7, 'lng': -79.3, 'recorded_at': _iso(now - timedelta(seconds=60))}))['data']
    assert d['points_stored'] == 1 and d['live'] is False
    db.session.rollback()
    assert float(db.session.get(type(driver), driver.id).current_latitude) == 43.651
    # bad points in a batch are skipped, an all-bad batch is rejected
    d = body(client.post('/api/update-location', headers=auth(driver),
                         json={'points': [{'lat': 999, 'lng': 1}, {'lat': 43.652, 'lng': -79.385}]}))['data']
    assert d['points_rejected'] == 1 and d['live'] is True
    assert body(client.post('/api/update-location', headers=auth(driver),
                            json={'points': [{'lat': 999, 'lng': 1}]}))['code'] == 0


def test_breadcrumbs_are_buffered_and_bulk_inserted(client, auth, make_user, monkeypatch):
    monkeypatch.setattr(tracking, '_ensure_flusher', lambda: None)
    tracking.BATCH = True
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    now = datetime.utcnow()
    for i in range(3):
        client.post('/api/update-location', headers=auth(driver),
                    json={'lat': 43.650 - i * 0.0005, 'lng': -79.385,
                          'recorded_at': _iso(now - timedelta(seconds=30 - i * 5))})
    db.session.rollback()
    q = RideLocation.query.filter_by(ride_type='carhire', ride_id=ride.id)
    assert q.count() == 0 and len(tracking._buffer) == 3
    # the detectors still see the trail before the flush
    assert len(tracking.recent_points('carhire', ride.id, driver.id)) == 3
    assert tracking.flush() == 3
    db.session.rollback()
    assert q.count() == 3 and tracking._buffer == []


def test_socket_location_batch(app, make_user):
    from backend.app import socketio
    from backend.utils.auth import issue_token
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    c = socketio.test_client(app, namespace='/rt', auth={'token': issue_token(driver)})
    now = datetime.utcnow()
    ack = c.emit('location:update', {'points': [
        {'lat': 43.650, 'lng': -79.385, 'recorded_at': _iso(now - timedelta(minutes=12))},
        {'lat': 43.651, 'lng': -79.385, 'recorded_at': _iso(now - timedelta(seconds=3))}]},
        namespace='/rt', callback=True)
    assert ack == {'ok': True, 'live': True, 'stored': 2, 'received': 2, 'rejected': 0}
    db.session.rollback()
    assert RideLocation.query.filter_by(ride_type='carhire', ride_id=ride.id).count() == 2


# ── 11 / 12. readiness + empty on-call list ─────────────────────────────────

def test_readiness_checks(monkeypatch):
    monkeypatch.setattr(SS, 'oncall_phones', lambda: [])
    items = {i['key']: i for i in SS.readiness_checks()}
    assert items['safety.oncall_phones']['level'] == 'critical'
    assert items['safety.redis']['level'] in ('warning', 'critical')
    assert {'safety.support_phone', 'safety.twilio'} <= set(items)
    assert all(i['area'] == 'safety' and i['message'] for i in items.values())
    monkeypatch.setattr(SS, 'oncall_phones', lambda: ['+14165550100'])
    assert {i['key']: i for i in SS.readiness_checks()}['safety.oncall_phones']['level'] == 'ok'


def test_escalation_with_empty_oncall_alerts_admins(client, auth, make_user, admins, monkeypatch):
    monkeypatch.setattr(SS, 'oncall_phones', lambda: [])
    user = make_user('customer')
    inc_id = body(sos(client, auth, user, key='no-oncall'))['data']['incident']['id']
    realtime.SENT.clear()
    assert safety_jobs.escalate_incident(inc_id) is True
    alerts = [(d, room) for e, d, room in realtime.SENT if e == 'alert' and d.get('kind') == 'oncall_not_configured']
    assert {room for _, room in alerts} == {'admin:ops', 'admin:sos'}
    assert AuditLog.query.filter_by(action='safety.oncall_missing', entity_id=str(inc_id)).count() == 1
    ops, _ = admins
    assert Notification.query.filter_by(user_id=ops.id, event_key='safety.sos_escalated').count() == 1


# ── 13. ETA → Live Activity hook ────────────────────────────────────────────

def test_eta_calls_live_activity_hook_when_present(make_user, monkeypatch):
    from tests.exp_helpers import make_carhire
    ETA.reset_state()
    c, d = make_user('customer'), make_user('driver')
    ride = make_carhire(c, d, stage='DRIVER_EN_ROUTE', pickup=PICKUP, stripe_paid='Yes', payment_status='paid')
    calls = []
    fake = types.ModuleType('backend.services.notify.live_activity')
    fake.push_update = lambda rt, rid, payload: calls.append((rt, rid, payload))
    import backend.services.notify as notify_pkg
    monkeypatch.setitem(sys.modules, 'backend.services.notify.live_activity', fake)
    monkeypatch.setattr(notify_pkg, 'live_activity', fake, raising=False)
    data = ETA.refresh_job('carhire', ride.id, 43.68, -79.3832)
    assert calls and calls[0][0] == 'carhire' and calls[0][1] == ride.id and calls[0][2]['seconds'] == data['seconds']
    fake.push_update = lambda *a: 1 / 0                                   # a broken hook never breaks ETA
    assert ETA.push_live_activity('carhire', ride.id, data) is False


# ── 14. help contacts ───────────────────────────────────────────────────────

def test_help_contacts_all_provinces_and_support(client, auth, make_user):
    user = make_user('customer')
    for prov in ('ON', 'QC', 'BC', 'AB', 'MB', 'NS', 'SK', 'NB', 'PE', 'NL', 'YT', 'NT', 'NU'):
        d = body(client.get(f'/api/safety/help-contacts?province={prov}', headers=auth(user)))['data']
        police = [c for c in d['contacts'] if c['category'] == 'police_non_emergency' and c['province'] == prov]
        assert police and all(c['phone'] for c in police), prov
    assert HelpContact.query.filter_by(province='NU', is_emergency=True).count() >= 1
    sup = SS.support_contact()
    assert sup['chat_route'] == 'support_chat' and 'phone' in sup and 'email' in sup
    add_contact(client, auth, user, phone='+14165550191')
    tk = body(client.get('/api/safety/toolkit', headers=auth(user)))['data']
    assert tk['trusted_contacts'][0]['phone'] == '+14165550191' and tk['support']['chat_route']


# ── 15. Roads API snapping for admin replay ─────────────────────────────────

def test_replay_snapping_optional_and_cached(client, auth, make_user, admins, monkeypatch):
    ops, _ = admins
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    for lat in (43.650, 43.649, 43.648):
        client.post('/api/update-location', headers=auth(driver), json={'latitude': lat, 'longitude': -79.385})
    d = body(client.get(f'/api/admin/rides/carhire/{ride.id}/route?snap=1', headers=auth(ops)))['data']
    assert d['snapped']['snapped'] is False                                  # no server key
    monkeypatch.setenv('GOOGLE_MAPS_SERVER_KEY', 'test-key')
    hits = []

    class Resp:
        status_code = 200

        def json(self):
            return {'snappedPoints': [{'location': {'latitude': 43.6, 'longitude': -79.4}},
                                      {'location': {'latitude': 43.61, 'longitude': -79.41}}]}
    import requests
    monkeypatch.setattr(requests, 'get', lambda url, timeout=None, params=None: hits.append(params) or Resp())
    for _ in range(2):
        d = body(client.get(f'/api/admin/rides/carhire/{ride.id}/route?snap=1', headers=auth(ops)))['data']
        assert d['snapped']['snapped'] is True and d['snapped']['points'][0] == [43.6, -79.4]
    assert len(hits) == 1                                                    # cached
