"""Safety, live sharing, recordings (spec §8, §9, §10, §25)."""
import hashlib
import json
from datetime import datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from backend import jobs
from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.notification import Notification, NotificationDelivery
from backend.models.platform import AuditLog
from backend.models.safety import (HelpContact, Recording, RecordingChunk, RideLocation, RideShareLink, SafetyCheck,
                                   SafetyIncident, SafetyIncidentLocation, TrustedContact)
from backend.services import private_storage as PS
from backend.services import realtime
from backend.services import safety_jobs
from backend.services import safety_service as SS
from backend.services import trip_state_machine as TSM
from backend.services import twilio_client
from tests.conftest import body

PICKUP = (43.6532, -79.3832)
DROPOFF = (43.6426, -79.3871)


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    PS.configure(root=str(tmp_path / 'private'), key=Fernet.generate_key().decode())
    twilio_client.SENT.clear()
    SS.CALLS.clear()
    yield
    PS.configure(None)


@pytest.fixture()
def admins(make_user, monkeypatch):
    ops = make_user('admin', admin_roles='ops')
    reviewer = make_user('admin', admin_roles='safety_reviewer')
    monkeypatch.setattr(SS, 'admin_recipient_ids', lambda: [ops.id, reviewer.id])
    return ops, reviewer


def make_ride(customer, driver, stage='IN_PROGRESS', **kw):
    n = Negotiation(customer_id=customer.id, customer_name=customer.name, driver_id=driver.id,
                    driver_name=driver.name, status='Started', is_active='Yes',
                    pickup_lat=str(PICKUP[0]), pickup_lng=str(PICKUP[1]), pickup_address='City Hall',
                    dropoff_lat=str(DROPOFF[0]), dropoff_lng=str(DROPOFF[1]), dropoff_address='CN Tower',
                    initial_price=2000, agreed_price_cents=2000, trip_stage=stage,
                    stage_changed_at=datetime.utcnow(), ride_pin='4821', **kw)
    db.session.add(n)
    db.session.commit()
    return n


def add_contact(client, auth, user, phone='+14165550142', name='Mom', auto_share=False):
    r = client.post('/api/safety/trusted-contacts', headers=auth(user),
                    json={'name': name, 'phone': phone, 'auto_share': auto_share})
    assert r.status_code == 201, r.get_json()
    return body(r)['data']


def sos(client, auth, user, key=None, **payload):
    h = auth(user, **({'Idempotency-Key': key} if key else {}))
    return client.post('/api/safety/sos', headers=h, json={'lat': 43.65, 'lng': -79.38, 'accuracy': 12,
                                                            'battery': 55, **payload})


# ── SOS ─────────────────────────────────────────────────────────────────────

def test_sos_without_ride_alerts_admins_and_contacts(client, auth, make_user, admins, monkeypatch):
    user = make_user('customer')
    add_contact(client, auth, user)
    r = sos(client, auth, user, key='k-1')
    assert r.status_code == 201, r.get_json()
    d = body(r)['data']
    assert d['incident']['ride_id'] is None and d['incident']['status'] == 'open'
    assert d['high_frequency_interval_s'] == 3 and '/t/' in d['share_url']

    # realtime alarm on admin:sos + admin:ops, within the request
    rooms = [(e, room) for e, _, room in realtime.SENT if e == 'safety.sos']
    assert ('safety.sos', 'admin:sos') in rooms and ('safety.sos', 'admin:ops') in rooms

    # trusted contact SMS (simulated — Twilio not configured) + delivery row
    assert any(m['to'] == '+14165550142' and 'triggered SOS' in m['body'] and '/t/' in m['body']
               for m in twilio_client.SENT)
    note = Notification.query.filter_by(user_id=user.id, event_key='safety.sos_triggered').first()
    assert note and note.data['recipient'] == 'trusted_contact'
    dl = NotificationDelivery.query.filter_by(notification_id=note.id, channel='sms').one()
    assert dl.status in ('sent', 'failed') and dl.status != 'queued'

    # admins notified through the catalogue event
    ops, reviewer = admins
    assert Notification.query.filter_by(user_id=ops.id, event_key='safety.sos_triggered').count() == 1
    # escalation scheduled
    assert any(p.endswith('escalate_incident') for _, p, _, _ in jobs.DEFERRED)
    # audited
    inc_id = d['incident']['id']
    assert AuditLog.query.filter_by(action='safety.sos_triggered', entity_id=str(inc_id)).count() == 1


def test_sos_idempotent(client, auth, make_user, admins):
    user = make_user('customer')
    a = sos(client, auth, user, key='same-key')
    b = sos(client, auth, user, key='same-key')
    assert a.status_code == 201 and b.status_code == 200
    assert body(a)['data']['incident']['id'] == body(b)['data']['incident']['id']
    assert body(b)['data']['replayed'] is True
    assert SafetyIncident.query.filter_by(user_id=user.id).count() == 1


def test_sos_during_and_after_ride(client, auth, make_user, admins):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    # during the ride — ride auto-detected
    r = sos(client, auth, customer, key='during')
    inc = body(r)['data']['incident']
    assert inc['ride_type'] == 'carhire' and inc['ride_id'] == ride.id and inc['role'] == 'customer'
    # after the ride ended — explicit ride still accepted
    ride.trip_stage = 'COMPLETED'
    db.session.commit()
    r = sos(client, auth, customer, key='after', ride_type='carhire', ride_id=ride.id)
    assert r.status_code == 201 and body(r)['data']['incident']['ride_id'] == ride.id
    # drivers can SOS too
    r = sos(client, auth, driver, key='drv', ride_type='carhire', ride_id=ride.id)
    assert body(r)['data']['incident']['role'] == 'driver'
    # SOS never fails (§8.5): a stranger can't attach an SOS to someone else's
    # ride, but the SOS itself is still created (no ride) and the rejected ride
    # is recorded for the safety team.
    stranger = make_user('customer')
    r = sos(client, auth, stranger, key='x', ride_type='carhire', ride_id=ride.id)
    assert r.status_code == 201, r.get_json()
    inc = body(r)['data']['incident']
    assert inc['ride_id'] is None and inc['status'] == 'open'
    db.session.rollback()
    row = db.session.get(SafetyIncident, inc['id'])
    assert f'carhire#{ride.id}' in row.notes and 'forbidden' in row.notes
    # unknown ride / garbage ids / unknown type → fall back to the caller's active ride
    for i, (rt, rid) in enumerate((('carhire', 999999999), ('carhire', 'abc'), ('spaceship', 1), ('carhire', None))):
        r = sos(client, auth, customer, key=f'fb-{i}', ride_type=rt, ride_id=rid)
        assert r.status_code == 201, (rt, rid, r.get_json())
    ride.trip_stage = 'IN_PROGRESS'
    db.session.commit()
    r = sos(client, auth, customer, key='fb-active', ride_type='carhire', ride_id=999999999)
    assert body(r)['data']['incident']['ride_id'] == ride.id


def test_incident_location_updates_and_cancel(client, auth, make_user, admins):
    user = make_user('customer')
    inc_id = body(sos(client, auth, user, key='loc'))['data']['incident']['id']
    realtime.SENT.clear()
    for i in range(3):
        r = client.post(f'/api/safety/incidents/{inc_id}/location', headers=auth(user),
                        json={'lat': 43.651 + i * 0.001, 'lng': -79.38, 'accuracy': 8, 'battery': 50})
        assert body(r)['code'] == 1 and body(r)['data']['keep_sending_location'] is True
    assert SafetyIncidentLocation.query.filter_by(incident_id=inc_id).count() == 4
    assert sum(1 for e, _, room in realtime.SENT if e == 'safety.sos_updated' and room == 'admin:sos') == 3
    other = make_user('customer')
    assert client.get(f'/api/safety/incidents/{inc_id}', headers=auth(other)).status_code == 404
    r = client.post(f'/api/safety/incidents/{inc_id}/cancel', headers=auth(user), json={'reason': 'pocket'})
    assert body(r)['data']['status'] == 'false_alarm'
    r = client.post(f'/api/safety/incidents/{inc_id}/location', headers=auth(user), json={'lat': 43.6, 'lng': -79.3})
    assert body(r)['data']['keep_sending_location'] is False
    assert AuditLog.query.filter_by(action='safety.sos_cancelled_by_user', entity_id=str(inc_id)).count() == 1


def test_escalation_after_timeout(client, auth, make_user, admins, monkeypatch):
    monkeypatch.setenv('SAFETY_ONCALL_PHONES', '+14165550199')
    user = make_user('customer')
    inc_id = body(sos(client, auth, user, key='esc'))['data']['incident']['id']
    inc = db.session.get(SafetyIncident, inc_id)
    inc.created_at = datetime.utcnow() - timedelta(seconds=120)
    db.session.commit()
    twilio_client.SENT.clear()
    realtime.SENT.clear()
    assert safety_jobs.escalate_incident(inc_id) is True
    assert safety_jobs.escalate_incident(inc_id) is False   # idempotent
    db.session.rollback()
    inc = db.session.get(SafetyIncident, inc_id)
    assert inc.escalated_at is not None
    assert any(m['to'] == '+14165550199' and 'NOT ACKNOWLEDGED' in m['body'] for m in twilio_client.SENT)
    assert any(c['to'] == '+14165550199' for c in SS.CALLS)
    assert any(e == 'safety.sos_updated' and d.get('type') == 'escalated' for e, d, _ in realtime.SENT)
    # acknowledged incidents are never escalated
    inc2_id = body(sos(client, auth, user, key='esc2'))['data']['incident']['id']
    ops, _ = admins
    client.post(f'/api/admin/safety/incidents/{inc2_id}/acknowledge', headers=auth(ops))
    assert safety_jobs.escalate_incident(inc2_id) is False


# ── trusted contacts / settings / help ──────────────────────────────────────

def test_trusted_contacts_limits_and_validation(client, auth, make_user):
    user = make_user('customer')
    r = client.post('/api/safety/trusted-contacts', headers=auth(user), json={'name': 'X', 'phone': '123'})
    assert r.status_code == 422 and body(r)['data']['error_code'] == 'invalid_phone'
    for i in range(5):
        add_contact(client, auth, user, phone=f'(416) 555-01{i:02d}', name=f'C{i}')
    r = client.post('/api/safety/trusted-contacts', headers=auth(user), json={'name': 'Six', 'phone': '4165550199'})
    assert body(r)['data']['error_code'] == 'limit_reached'
    lst = body(client.get('/api/safety/trusted-contacts', headers=auth(user)))['data']
    assert lst['contacts'][0]['phone'] == '+14165550100' and lst['max'] == 5
    cid = lst['contacts'][0]['id']
    r = client.put(f'/api/safety/trusted-contacts/{cid}', headers=auth(user), json={'auto_share': True})
    assert body(r)['data']['auto_share'] is True
    other = make_user('customer')
    assert client.delete(f'/api/safety/trusted-contacts/{cid}', headers=auth(other)).status_code == 404
    assert client.delete(f'/api/safety/trusted-contacts/{cid}', headers=auth(user)).status_code == 200


def test_settings_and_help_contacts(client, auth, make_user):
    user = make_user('customer', province='ON')
    r = client.put('/api/safety/settings', headers=auth(user), json={'record_audio': 'always',
                                                                     'auto_share_night': True})
    assert body(r)['data']['record_audio'] == 'always' and body(r)['data']['auto_share_night'] is True
    assert client.put('/api/safety/settings', headers=auth(user), json={'record_audio': 'x'}).status_code == 422
    d = body(client.get('/api/safety/help-contacts', headers=auth(user)))['data']
    assert d['province'] == 'ON' and d['emergency_number'] == '911'
    names = [c['name'] for c in d['contacts']]
    assert any('911' == c['phone'] for c in d['contacts']) and any('Toronto' in n for n in names)
    assert not any(c['province'] == 'BC' for c in d['contacts'])
    # legacy endpoint keeps its shape and gains help_contacts
    r = body(client.get('/api/important-contacts?province=BC', headers=auth(user)))['data']
    assert {'contacts', 'user_location', 'total_count', 'filters_applied'} <= set(r)
    assert any(c['province'] == 'BC' for c in r['help_contacts'])


def test_reports_with_attachment_and_flag_passenger(client, auth, make_user):
    import io
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    png = b'\x89PNG\r\n\x1a\n' + b'0' * 100
    r = client.post('/api/safety/reports', headers=auth(customer), content_type='multipart/form-data',
                    data={'category': 'unsafe_driving', 'description': 'Speeding', 'ride_type': 'carhire',
                          'ride_id': str(ride.id), 'attachments': (io.BytesIO(png), 'p.png', 'image/png')})
    assert r.status_code == 201, r.get_json()
    rep = body(r)['data']
    assert rep['reported_user_id'] == driver.id and rep['attachments'][0]['bytes'] == len(png)
    assert 'key' not in rep['attachments'][0]
    assert client.post('/api/safety/reports', headers=auth(customer), json={'category': 'nope'}).status_code == 422
    # only the driver can flag the passenger
    r = client.post('/api/safety/flag-passenger', headers=auth(customer),
                    json={'ride_type': 'carhire', 'ride_id': ride.id, 'reason': 'harassment'})
    assert r.status_code == 403
    r = client.post('/api/safety/flag-passenger', headers=auth(driver),
                    json={'ride_type': 'carhire', 'ride_id': ride.id, 'reason': 'harassment', 'description': 'rude'})
    assert r.status_code == 201 and body(r)['data']['reported_user_id'] == customer.id
    assert body(r)['data']['category'] == 'passenger_flag'


def test_toolkit(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    add_contact(client, auth, customer)
    d = body(client.get('/api/safety/toolkit', headers=auth(customer)))['data']
    assert d['ride']['ride_id'] == ride.id and d['ride']['driver']['first_name']
    assert d['ride']['pickup']['address'] == 'City Hall' and d['emergency_number'] == '911'
    assert len(d['trusted_contacts']) == 1 and d['share']['can_share'] is True
    assert d['recording']['other_party_recording'] is False and d['open_incident'] is None


# ── share links / public tracking ───────────────────────────────────────────

def _share(client, auth, user, ride, **payload):
    return client.post(f'/api/rides/carhire/{ride.id}/share', headers=auth(user), json=payload)


def test_share_only_parties_and_stages(client, auth, make_user):
    customer, driver, stranger = make_user('customer'), make_user('driver'), make_user('customer')
    ride = make_ride(customer, driver, stage='REQUESTED')
    assert body(_share(client, auth, customer, ride))['data']['error_code'] == 'share_not_available'
    ride.trip_stage = 'DRIVER_EN_ROUTE'
    db.session.commit()
    assert _share(client, auth, stranger, ride).status_code == 403
    r = _share(client, auth, customer, ride)
    assert r.status_code == 201
    d = body(r)['data']
    assert len(d['token']) == 32 and d['url'].endswith('/t/' + d['token']) and d['expires_at']
    # reused while live
    assert body(_share(client, auth, customer, ride))['data']['token'] == d['token']


def test_public_track_payload_privacy_revoke_and_expiry(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    contact = add_contact(client, auth, customer)
    r = _share(client, auth, customer, ride, contact_ids=[contact['id']])
    token = body(r)['data']['token']
    assert any(m['to'] == contact['phone'] and token in m['body'] for m in twilio_client.SENT)
    # driver streams location → breadcrumbs
    for i in range(3):
        client.post('/api/update-location', headers=auth(driver),
                    json={'latitude': PICKUP[0] - 0.001 * i, 'longitude': PICKUP[1], 'heading': 180})
    r = client.get(f'/api/public/track/{token}')
    assert r.status_code == 200 and 'no-store' in r.headers['Cache-Control']
    d = body(r)['data']
    assert d['driver']['first_name'] and d['driver_location']['heading'] == 180
    assert len(d['breadcrumbs']) == 3 and d['polyline'] and d['trip_ended'] is False
    assert d['eta']['minutes'] >= 0 and d['pickup']['address'] == 'City Hall'
    text = json.dumps(d).lower()
    for forbidden in ('phone', 'email', 'price', 'fare', 'payment', 'cents', 'stripe', 'pin'):
        assert forbidden not in text, forbidden
    for p in (customer.phone_number, driver.phone_number):
        assert p[-7:] not in text
    # public page renders and is noindex
    page = client.get(f'/t/{token}')
    assert page.status_code == 200 and b'noindex' in page.data
    # revoke → 404
    other = client.delete(f'/api/rides/carhire/{ride.id}/share/{token}', headers=auth(driver))
    assert other.status_code == 404
    assert client.delete(f'/api/rides/carhire/{ride.id}/share/{token}', headers=auth(customer)).status_code == 200
    assert client.get(f'/api/public/track/{token}').status_code == 404
    assert client.get(f'/t/{token}').status_code == 404
    # expiry → 404
    ride2 = make_ride(customer, driver, stage='DRIVER_EN_ROUTE')
    t2 = body(_share(client, auth, customer, ride2))['data']['token']
    link = RideShareLink.query.filter_by(token=t2).one()
    link.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert client.get(f'/api/public/track/{t2}').status_code == 404


def test_public_track_rate_limited(client, monkeypatch):
    from backend.routes import tracking_share
    monkeypatch.setattr(tracking_share, '_rl', {})
    codes = [client.get('/api/public/track/nope', environ_base={'REMOTE_ADDR': '10.9.9.9'}).status_code
             for _ in range(62)]
    assert codes[0] == 404 and codes[-1] == 429


def test_trip_end_expires_links_and_stops_recordings(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    token = body(_share(client, auth, customer, ride))['data']['token']
    rec_id = body(client.post('/api/recordings', headers=auth(customer),
                              json={'ride_type': 'carhire', 'ride_id': ride.id}))['data']['recording']['id']
    admin = make_user('admin')
    TSM.transition('carhire', ride.id, 'COMPLETED', actor=admin, actor_type='admin')
    db.session.rollback()
    link = RideShareLink.query.filter_by(token=token).one()
    assert link.expires_at <= datetime.utcnow() + timedelta(minutes=31)
    assert db.session.get(Recording, rec_id).status == 'stopped'
    d = body(client.get(f'/api/public/track/{token}'))['data']
    assert d['trip_ended'] is True and d['eta'] is None


def test_auto_share_on_trip_start(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    add_contact(client, auth, customer, phone='+14165550177', auto_share=True)
    add_contact(client, auth, customer, phone='+14165550178', auto_share=False)
    client.put('/api/safety/settings', headers=auth(customer), json={'auto_share_all': True})
    ride = make_ride(customer, driver, stage='DRIVER_ARRIVED')
    twilio_client.SENT.clear()
    admin = make_user('admin')
    TSM.transition('carhire', ride.id, 'IN_PROGRESS', actor=admin, actor_type='admin')
    to = {m['to'] for m in twilio_client.SENT if 'sharing a NegoRide trip' in m['body']}
    assert to == {'+14165550177'}
    assert RideShareLink.query.filter_by(ride_type='carhire', ride_id=ride.id, user_id=customer.id).count() == 1


def test_night_window():
    class U:
        timezone = 'America/Toronto'
        province = 'ON'
    st = SS.get_settings(0)
    st.auto_share_night = True
    # 03:00 UTC = 23:00 Toronto (EDT) → night; 17:00 UTC = 13:00 → day
    assert SS.should_auto_share(U(), st, datetime(2026, 7, 1, 3, 0)) is True
    assert SS.should_auto_share(U(), st, datetime(2026, 7, 1, 17, 0)) is False


# ── route deviation / "Are you OK?" ─────────────────────────────────────────

def test_route_deviation_check_and_help_creates_incident(client, auth, make_user, admins):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    far = (43.70, -79.30)   # ~8 km off the City Hall → CN Tower corridor
    for _ in range(2):
        r = client.post('/api/update-location', headers=auth(driver), json={'latitude': far[0], 'longitude': far[1]})
        assert body(r)['code'] == 1
    chk = SafetyCheck.query.filter_by(ride_type='carhire', ride_id=ride.id).one()
    assert chk.kind == 'route_deviation' and chk.user_id == customer.id and chk.status == 'pending'
    n = Notification.query.filter_by(user_id=customer.id, event_key='safety.route_deviation').one()
    assert n.data['check_id'] == chk.id
    # throttled: no second check within 10 min
    client.post('/api/update-location', headers=auth(driver), json={'latitude': far[0], 'longitude': far[1]})
    assert SafetyCheck.query.filter_by(ride_type='carhire', ride_id=ride.id).count() == 1
    # the driver cannot answer the customer's check
    assert client.post(f'/api/safety/checks/{chk.id}/respond', headers=auth(driver),
                       json={'response': 'ok'}).status_code == 404
    r = client.post(f'/api/safety/checks/{chk.id}/respond', headers=auth(customer), json={'response': 'help'})
    d = body(r)['data']
    assert d['incident']['kind'] == 'sos' and d['incident']['ride_id'] == ride.id and d['share_url']
    db.session.rollback()
    assert db.session.get(SafetyCheck, chk.id).status == 'help'


def test_on_route_points_do_not_trigger(client, auth, make_user):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    for lat in (43.650, 43.648, 43.646):
        client.post('/api/update-location', headers=auth(driver), json={'latitude': lat, 'longitude': -79.385})
    assert SafetyCheck.query.filter_by(ride_type='carhire', ride_id=ride.id).count() == 0


def test_unanswered_check_escalates(client, auth, make_user, admins):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    chk = SafetyCheck(ride_type='carhire', ride_id=ride.id, user_id=customer.id, kind='long_stop',
                      status='pending', lat=43.66, lng=-79.39,
                      created_at=datetime.utcnow() - timedelta(seconds=120))
    db.session.add(chk)
    db.session.commit()
    inc_id = safety_jobs.check_timeout(chk.id)
    assert inc_id
    db.session.rollback()
    assert db.session.get(SafetyCheck, chk.id).status == 'escalated'
    inc = db.session.get(SafetyIncident, inc_id)
    assert inc.kind == 'check_in_timeout' and inc.ride_id == ride.id
    ops, _ = admins
    assert Notification.query.filter_by(user_id=ops.id, event_key='safety.check_unanswered').count() == 1


# ── recordings ──────────────────────────────────────────────────────────────

def _chunk(client, auth, user, rec_id, seq, data, sha=None):
    import io
    return client.post(f'/api/recordings/{rec_id}/chunks', headers=auth(user), content_type='multipart/form-data',
                       data={'seq': str(seq), 'sha256': sha or hashlib.sha256(data).hexdigest(),
                             'file': (io.BytesIO(data), f'{seq}.m4a', 'audio/mp4')})


def test_recording_flow_integrity_and_privacy(client, auth, make_user, admins):
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    # 'always' requires the opt-in setting
    r = client.post('/api/recordings', headers=auth(customer), json={'ride_type': 'carhire', 'ride_id': ride.id,
                                                                     'trigger': 'always'})
    assert body(r)['data']['error_code'] == 'not_opted_in'
    realtime.SENT.clear()
    r = client.post('/api/recordings', headers=auth(customer), json={'ride_type': 'carhire', 'ride_id': ride.id})
    assert r.status_code == 201
    rec_id = body(r)['data']['recording']['id']
    assert body(r)['data']['upload']['url'] == f'/api/recordings/{rec_id}/chunks'
    assert any(e == 'recording.status' and room == f'ride:carhire:{ride.id}' and d['active']
               for e, d, room in realtime.SENT)
    # the other party sees the banner
    st = body(client.get(f'/api/rides/carhire/{ride.id}/recording-status', headers=auth(driver)))['data']
    assert st['other_party_recording'] is True and 'Audio recording is on' in st['banner']

    audio = b'\x00\x00\x00\x18ftypM4A ' + b'a' * 2000
    assert _chunk(client, auth, customer, rec_id, 0, audio).status_code == 201
    bad = _chunk(client, auth, customer, rec_id, 1, audio, sha='0' * 64)
    assert bad.status_code == 422 and body(bad)['data']['error_code'] == 'checksum_mismatch'
    assert _chunk(client, auth, customer, rec_id, 0, audio).status_code == 200            # idempotent retry
    assert _chunk(client, auth, customer, rec_id, 0, audio + b'x').status_code == 409     # seq conflict
    assert _chunk(client, auth, driver, rec_id, 1, audio).status_code == 404              # not the owner
    chunk = RecordingChunk.query.filter_by(recording_id=rec_id, seq=0).one()
    # encrypted at rest
    raw = open(PS.backend()._path(chunk.storage_key), 'rb').read()
    assert audio not in raw and PS.get(chunk.storage_key) == audio

    # the other party can never download
    assert client.get(f'/api/recordings/{rec_id}', headers=auth(driver)).status_code == 403
    own = body(client.get(f'/api/recordings/{rec_id}', headers=auth(customer)))['data']
    url = own['chunks'][0]['url']
    got = client.get(url[url.index('/api/'):])
    assert got.status_code == 200 and got.data == audio
    assert client.get('/api/private-files/garbage.sig').status_code == 403

    r = client.post(f'/api/recordings/{rec_id}/stop', headers=auth(customer))
    assert body(r)['data']['status'] == 'stopped'
    st = body(client.get(f'/api/rides/carhire/{ride.id}/recording-status', headers=auth(driver)))['data']
    assert st['recording_active'] is False

    # admin access: safety_reviewer only, audited
    ops, reviewer = admins
    assert client.get(f'/api/admin/safety/recordings/{rec_id}', headers=auth(ops)).status_code == 403
    r = client.get(f'/api/admin/safety/recordings/{rec_id}', headers=auth(reviewer))
    assert r.status_code == 200 and len(body(r)['data']['chunks']) == 1
    assert AuditLog.query.filter_by(action='recording.access', entity_id=str(rec_id), actor_id=reviewer.id).count() == 1
    u = body(r)['data']['chunks'][0]['url']
    client.get(u[u.index('/api/'):])
    assert AuditLog.query.filter_by(action='private_file.download', actor_id=reviewer.id).count() >= 1


def test_retention_deletes_old_unheld_recordings(client, auth, make_user):
    user = make_user('customer')
    old = datetime.utcnow() - timedelta(days=10)

    def mk(hold=False):
        rec = Recording(user_id=user.id, role='customer', status='stopped', trigger_source='manual',
                        started_at=old, stopped_at=old, created_at=old, legal_hold=hold, chunk_count=1)
        db.session.add(rec)
        db.session.flush()
        key = f'recordings/{user.id}/{rec.id}/00000.m4a'
        PS.put(key, b'audio', 'audio/mp4')
        db.session.add(RecordingChunk(recording_id=rec.id, seq=0, storage_key=key, bytes=5, sha256='x'))
        db.session.commit()
        return rec.id, key

    plain_id, plain_key = mk()
    held_id, held_key = mk(hold=True)
    inc = SafetyIncident(user_id=user.id, role='customer', kind='sos', status='open', created_at=old)
    db.session.add(inc)
    db.session.commit()
    case_rec = Recording(user_id=user.id, role='customer', status='stopped', started_at=old, created_at=old,
                         incident_id=inc.id)
    db.session.add(case_rec)
    old_loc = RideLocation(ride_type='carhire', ride_id=987654321, user_id=user.id, lat=1, lng=1,
                           recorded_at=datetime.utcnow() - timedelta(days=200))
    db.session.add(old_loc)
    db.session.commit()

    started = datetime.utcnow() - timedelta(seconds=5)
    stats = safety_jobs.retention_cleanup(scope_user_ids=[user.id])
    db.session.rollback()
    assert db.session.get(Recording, plain_id).status == 'deleted' and not PS.exists(plain_key)
    assert RecordingChunk.query.filter_by(recording_id=plain_id).count() == 0
    assert db.session.get(Recording, held_id).status == 'stopped' and PS.exists(held_key)
    assert db.session.get(Recording, case_rec.id).status == 'stopped'   # open case
    assert stats['ride_locations_deleted'] >= 1
    assert RideLocation.query.filter_by(ride_id=987654321).count() == 0
    # Scoped to this run: recording ids can be re-issued (MySQL 5.7 AUTO_INCREMENT
    # reset) and audit rows of earlier runs are — correctly — never deleted.
    assert AuditLog.query.filter(AuditLog.action == 'recording.retention_deleted',
                                 AuditLog.entity_id == str(plain_id),
                                 AuditLog.created_at >= started).count() == 1


# ── admin ───────────────────────────────────────────────────────────────────

def test_admin_safety_center(client, auth, make_user, admins):
    ops, reviewer = admins
    customer, driver = make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver)
    client.post('/api/update-location', headers=auth(driver), json={'latitude': 43.652, 'longitude': -79.384})
    inc_id = body(sos(client, auth, driver, key='adm'))['data']['incident']['id']

    assert client.get('/api/admin/safety/incidents', headers=auth(customer)).status_code == 403
    lst = body(client.get('/api/admin/safety/incidents?status=open', headers=auth(ops)))['data']
    assert lst['items'][0]['status'] == 'open' and lst['open_count'] >= 1

    det = body(client.get(f'/api/admin/safety/incidents/{inc_id}', headers=auth(ops)))['data']
    assert det['ride']['ride_id'] == ride.id and det['locations'] and det['timeline']
    assert 'phone' not in json.dumps(det['user'])

    realtime.SENT.clear()
    r = client.post(f'/api/admin/safety/incidents/{inc_id}/acknowledge', headers=auth(ops), json={'note': 'calling'})
    assert body(r)['data']['status'] == 'acknowledged'
    assert any(e == 'safety.sos_updated' and room == 'admin:sos' for e, _, room in realtime.SENT)
    assert client.post(f'/api/admin/safety/incidents/{inc_id}/notes', headers=auth(ops),
                       json={'note': 'police on site'}).status_code == 200

    c = body(client.get(f'/api/admin/safety/incidents/{inc_id}/contact', headers=auth(ops)))['data']
    assert {p['relation'] for p in c['people']} == {'reporter', 'customer'}
    assert AuditLog.query.filter_by(action='personal_data.access', entity_id=str(inc_id), actor_id=ops.id).count() == 1

    pdf = client.get(f'/api/admin/safety/incidents/{inc_id}/report.pdf', headers=auth(ops))
    assert pdf.status_code == 200 and pdf.data[:4] == b'%PDF'

    live = body(client.get('/api/admin/live/drivers', headers=auth(ops)))['data']
    me = [x for x in live['drivers'] if x['driver_id'] == driver.id][0]
    assert me['state'] == 'sos' and me['ride']['ride_id'] == ride.id and me['position']

    route = body(client.get(f'/api/admin/rides/carhire/{ride.id}/route', headers=auth(ops)))['data']
    assert len(route['points']) == 1 and route['points'][0]['at']

    r = client.post(f'/api/admin/safety/incidents/{inc_id}/resolve', headers=auth(ops))
    assert body(r)['data']['status'] == 'resolved'
    assert client.post(f'/api/admin/safety/incidents/{inc_id}/resolve', headers=auth(ops)).status_code == 409
    actions = {a.action for a in AuditLog.query.filter_by(entity_type='safety_incident', entity_id=str(inc_id))}
    assert {'safety.sos_triggered', 'safety.sos_acknowledged', 'safety.incident_note', 'safety.sos_resolved',
            'safety.incident_report_exported'} <= actions

    # help contacts CRUD (audited)
    r = client.post('/api/admin/safety/help-contacts', headers=auth(ops),
                    json={'name': 'v4test Saskatoon Police', 'phone': '306-975-8300',
                          'category': 'police_non_emergency', 'province': 'SK'})
    hid = body(r)['data']['id']
    try:
        assert client.put(f'/api/admin/safety/help-contacts/{hid}', headers=auth(ops),
                          json={'province': 'ZZ'}).status_code == 422
        sk = body(client.get('/api/safety/help-contacts?province=SK', headers=auth(customer)))['data']['contacts']
        assert any(c['id'] == hid for c in sk)
        assert client.get('/api/admin/safety/help-contacts', headers=auth(customer)).status_code == 403
    finally:
        client.delete(f'/api/admin/safety/help-contacts/{hid}', headers=auth(ops))
    assert db.session.get(HelpContact, hid) is None


def test_trusted_contacts_never_exposed_in_bulk_to_admin(client, auth, make_user, admins):
    ops, _ = admins
    user = make_user('customer')
    add_contact(client, auth, user, phone='+14165550166')
    inc_id = body(sos(client, auth, user, key='tc'))['data']['incident']['id']
    det = client.get(f'/api/admin/safety/incidents/{inc_id}', headers=auth(ops)).get_data(as_text=True)
    assert '4165550166' not in det
    assert TrustedContact.query.filter_by(user_id=user.id).count() == 1
