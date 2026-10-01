"""Identity / legal / account-status hardening (audit follow-up to spec §11, §12, §15)."""
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from backend import jobs
from backend.models import db
from backend.models.identity import (DriverApplication, LegalAcceptance, LegalDocument, MarketingConsent,
                                     PhoneVerification)
from backend.models.user import AdminUser
from backend.services import account_service as A
from backend.services import legal_service as L
from backend.services import phone_verification as PV
from backend.services import realtime, twilio_client
from backend.services.notify import email_provider
from backend.utils import phone as P
from tests.conftest import body
from tests.identity_utils import give_verified_phone, phones, rand_phone, setting, v4, verify  # noqa: F401


def _consent_ids():
    return {'accepted_terms_id': L.current('terms').id, 'accepted_privacy_id': L.current('privacy').id,
            'accepted_guidelines_id': L.current('community_guidelines').id}


def _register(client, created, headers, **fields):
    tag = uuid.uuid4().hex[:10]
    payload = {'first_name': 'Reg', 'last_name': 'Test', 'email': f'v4test_reg_{tag}@negoride.test',
               'password': 'Test1234!', 'username': f'v4test_reg_{tag}'}
    payload.update(fields)
    r = client.post('/api/users/register', json=payload, headers=headers)
    b = body(r)
    if b.get('code') == 1:
        created.append(b['data']['id'])
    return r, b


# ── 1 · legacy-client gating ───────────────────────────────────────────────

def test_is_v4_client_follows_legacy_setting(app, monkeypatch):
    from backend.utils.client_info import is_v4_client, sends_v4_header
    with app.test_request_context('/api/x'):
        setting(monkeypatch, 'app.legacy_clients_allowed', True)
        assert is_v4_client() is False and sends_v4_header() is False
        setting(monkeypatch, 'app.legacy_clients_allowed', False)
        assert is_v4_client() is True and sends_v4_header() is False
    with app.test_request_context('/api/x', headers={'X-App-Version': '4.1.0'}):
        assert is_v4_client() is True and sends_v4_header() is True


# ── 2 · sensitive actions ──────────────────────────────────────────────────

def test_stripe_links_require_sensitive_action(client, auth, phones, make_user):
    u = make_user('driver')
    give_verified_phone(u, phones.new())
    r = client.post('/api/payout-account/onboarding-link', json={}, headers=auth(u, **v4()))
    assert r.status_code == 403 and body(r)['data']['purpose'] == 'sensitive_action'
    r = client.get('/api/payout-account/dashboard-link', headers=auth(u, **v4()))
    assert r.status_code == 403 and body(r)['data']['requires_verification'] is True
    res = verify(client, None, 'sensitive_action', headers=auth(u, **v4()))
    r = client.get(f"/api/payout-account/dashboard-link?verification_token={res['verification_token']}",
                   headers=auth(u, **v4()))
    assert (body(r).get('data') or {}).get('error_code') != 'verification_required'   # got past the guard


def test_sensitive_action_required_for_unverified_phone(client, auth, phones, make_user):
    p = phones.new()
    u = make_user('customer', phone_e164=p, phone_number=p)   # phone on file but never verified
    r = client.post('/api/profile/delete-account', json={'password': 'Test1234!'}, headers=auth(u, **v4()))
    assert r.status_code == 403 and body(r)['data']['requires_verification'] is True
    res = verify(client, None, 'sensitive_action', headers=auth(u, **v4()))
    assert res['phone'] == p
    r = client.post('/api/profile/delete-account', json={'password': 'Test1234!',
                                                         'verification_token': res['verification_token']},
                    headers=auth(u, **v4()))
    assert body(r)['code'] == 1


# ── 3 · phone changes ──────────────────────────────────────────────────────

def test_legacy_update_phone_unverifies_and_notifies_old_number(client, auth, phones, make_user, monkeypatch):
    old, new = phones.new(), phones.new()
    u = make_user('customer')
    give_verified_phone(u, old)
    twilio_client.SENT.clear()
    setting(monkeypatch, 'app.legacy_clients_allowed', True)
    r = client.post('/api/profile/update-phone', json={'phone_number': new}, headers=auth(u))
    assert body(r)['code'] == 1
    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    assert u.phone_number == new and u.phone_e164 is None and u.phone_verified_at is None
    assert any(m['to'] == old and 'changed' in m['body'] for m in twilio_client.SENT)
    # no unverified fallback once legacy clients are disallowed
    setting(monkeypatch, 'app.legacy_clients_allowed', False)
    r = client.post('/api/profile/update-phone', json={'phone_number': phones.new()}, headers=auth(u))
    assert body(r)['data']['error_code'] == 'verification_required'


# ── 4 · phone-required sign-up ─────────────────────────────────────────────

def test_phone_required_blocks_rides_until_verified(client, auth, phones, make_user, monkeypatch):
    u = make_user('customer', email_verified_at=datetime.utcnow())
    setting(monkeypatch, 'ff.phone_required_signup', False)
    r = client.post('/api/users/login', json={'email': u.email, 'password': 'Test1234!'}, headers=v4())
    assert body(r)['data']['requires_phone_verification'] is False
    setting(monkeypatch, 'ff.phone_required_signup', True)
    r = client.post('/api/users/login', json={'email': u.email, 'password': 'Test1234!'}, headers=v4())
    assert body(r)['code'] == 1 and body(r)['data']['requires_phone_verification'] is True
    for path, payload in (('/api/negotiations-create', {'driver_id': 1}), ('/api/negotiations', {'price': 10}),
                          ('/api/bookings', {'customer_proposed_price': 900}),
                          ('/api/bookings/courier-batch', {'service_type': 'courier'}),
                          ('/api/trips-bookings-create', {'trip_id': 1, 'seats': 1})):
        r = client.post(path, json=payload, headers=auth(u, **v4()))
        assert r.status_code == 403 and body(r)['data']['error_code'] == 'phone_verification_required', path
    # legacy clients are not blocked while they are allowed (they cannot verify in-app)
    setting(monkeypatch, 'app.legacy_clients_allowed', True)
    r = client.post('/api/negotiations-create', json={'driver_id': 1}, headers=auth(u))
    assert (body(r).get('data') or {}).get('error_code') != 'phone_verification_required'
    # verified phone → allowed
    give_verified_phone(u, phones.new())
    r = client.post('/api/negotiations-create', json={'driver_id': 1}, headers=auth(u, **v4()))
    assert (body(r).get('data') or {}).get('error_code') != 'phone_verification_required'


# ── 5 · VoIP / line type ───────────────────────────────────────────────────

def test_signup_voip_warning_and_driver_phone_step(client, auth, phones, make_user):
    voip = phones.new(voip=True)
    r = client.post('/api/verify/phone/start', json={'phone': voip, 'purpose': 'signup'}, headers=v4())
    assert body(r)['data']['line_type_warning'] == 'voip' and body(r)['data']['line_type_warning_message']
    mobile = phones.new()
    r = client.post('/api/verify/phone/start', json={'phone': mobile, 'purpose': 'signup'}, headers=v4())
    assert body(r)['data']['line_type_warning'] is None

    u = make_user('customer')
    give_verified_phone(u, phones.new(), line_type=None)
    step = {s['key']: s for s in body(client.get('/api/driver/onboarding', headers=auth(u)))['data']['steps']}
    assert step['phone_verified']['status'] == 'action_needed'
    assert step['phone_verified']['detail']['issue'] == 'line_type_unknown'
    u.phone_line_type = 'nonFixedVoip'
    db.session.commit()
    ov = body(client.get('/api/driver/onboarding', headers=auth(u)))['data']
    step = {s['key']: s for s in ov['steps']}
    assert step['phone_verified']['detail']['issue'] == 'voip'
    assert any(b['step'] == 'phone_verified' and b['issue'] == 'voip' for b in ov['submit_blockers'])
    # a fresh driver_onboarding verification (mobile) fixes it
    verify(client, phones.new(), 'driver_onboarding', headers=auth(u, **v4()))
    step = {s['key']: s for s in body(client.get('/api/driver/onboarding', headers=auth(u)))['data']['steps']}
    assert step['phone_verified']['status'] == 'done'


def test_driver_lookup_fails_closed_in_production(client, auth, make_user, monkeypatch):
    u = make_user('customer')
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setattr(PV, 'lookup_line_type', lambda *a, **k: None)
    r = client.post('/api/verify/phone/start', json={'phone': rand_phone(), 'purpose': 'driver_onboarding'},
                    headers=auth(u, **v4()))
    assert r.status_code == 503 and body(r)['data']['error_code'] == 'line_type_unknown'


# ── 6 · step-up without a device id ────────────────────────────────────────

def test_missing_device_id_triggers_step_up(client, phones, make_user, monkeypatch):
    setting(monkeypatch, 'ff.step_up_new_device', True)
    u = make_user('customer', email_verified_at=datetime.utcnow())
    give_verified_phone(u, phones.new())
    creds = {'email': u.email, 'password': 'Test1234!'}
    assert body(client.post('/api/users/login', json={**creds, 'device_id': 'dev-A'}, headers=v4()))['code'] == 1
    b = body(client.post('/api/users/login', json=creds, headers=v4()))      # no X-Device-Id / device_id
    assert b['code'] == 0 and b['data']['error_code'] == 'step_up_required'
    res = verify(client, None, 'new_device', step_up_ticket=b['data']['step_up_ticket'])
    b = body(client.post('/api/users/login', json={**creds, 'verification_token': res['verification_token']},
                         headers=v4()))
    assert b['code'] == 1 and b['data']['token']


# ── 7 · fraud rules ────────────────────────────────────────────────────────

def test_caribbean_and_premium_nanp_blocked(client, monkeypatch):
    assert P.is_allowed_country('+14165550123') and P.is_allowed_country('+12125550123')
    assert not P.is_allowed_country('+18765550123') and not P.is_allowed_country('+17875550123')
    assert P.is_allowed_country('+18765550123', 'CA,US,JM') and P.is_allowed_country('+18765550123', 'CA,US', '876')
    assert P.is_premium('+15005550123') and P.is_premium('+17105550123') and P.is_premium('+19765550123')
    r = client.post('/api/verify/phone/start', json={'phone': '+18765550123', 'purpose': 'signup'}, headers=v4())
    assert body(r)['data']['error_code'] == 'country_not_allowed'
    r = client.post('/api/verify/phone/start', json={'phone': '+15335550123', 'purpose': 'signup'}, headers=v4())
    assert body(r)['data']['error_code'] == 'premium_blocked'
    setting(monkeypatch, 'otp.allowed_nanp_regions', 'JM')
    monkeypatch.setenv('TWILIO_TEST_MODE_ENABLED', '1')
    monkeypatch.setenv('TWILIO_TEST_NUMBERS', '+18765550123:123456')
    try:
        r = client.post('/api/verify/phone/start', json={'phone': '+18765550123', 'purpose': 'signup'}, headers=v4())
        assert body(r)['code'] == 1
    finally:
        db.session.rollback()
        PhoneVerification.query.filter_by(phone='+18765550123').delete(synchronize_session=False)
        db.session.commit()


# ── 8 · Android SMS Retriever hash ─────────────────────────────────────────

def test_app_hash_forwarded_to_twilio(client, monkeypatch):
    sent = []
    monkeypatch.setenv('TWILIO_TEST_NUMBERS', '')
    monkeypatch.setattr(PV, 'verify_configured', lambda: True)
    monkeypatch.setattr(twilio_client, 'verify_start',
                        lambda to, channel='sms', locale=None, app_hash=None: sent.append((to, app_hash)) or {'sid': 'VE1'})
    a, b, c = rand_phone(), rand_phone(), rand_phone()
    try:
        client.post('/api/verify/phone/start', json={'phone': a, 'purpose': 'signup', 'app_hash': 'FA+9qCX9VSu'},
                    headers=v4())
        monkeypatch.setenv('TWILIO_ANDROID_APP_HASH', 'AbCdEfGhIjK')
        client.post('/api/verify/phone/start', json={'phone': b, 'purpose': 'signup'}, headers=v4())
        client.post('/api/verify/phone/start', json={'phone': c, 'purpose': 'signup', 'app_hash': 'bad'}, headers=v4())
        assert sent == [(a, 'FA+9qCX9VSu'), (b, 'AbCdEfGhIjK'), (c, 'AbCdEfGhIjK')]
    finally:
        db.session.rollback()
        PhoneVerification.query.filter(PhoneVerification.phone.in_((a, b, c))).delete(synchronize_session=False)
        db.session.commit()


# ── 9 · DB-level uniqueness of verified phones ─────────────────────────────

def test_verified_phone_unique_in_database(client, phones, make_user, monkeypatch, _created_users):
    p = phones.new()
    a, b = make_user('customer'), make_user('customer')
    give_verified_phone(a, p)
    b.phone_e164, b.phone_verified_at = p, datetime.utcnow()
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    # an unverified copy of the number is fine (only verified phones are unique)
    b = db.session.get(AdminUser, b.id)
    b.phone_e164 = p
    db.session.commit()
    # a race past the application checks → 409 phone_in_use from the constraint
    a = db.session.get(AdminUser, a.id)
    a.phone_number = '+14165550000'
    db.session.commit()
    monkeypatch.setattr(PV, 'find_verified_owner', lambda *a_, **k: None)
    tok = verify(client, p, 'signup')['verification_token']
    r, bd = _register(client, _created_users, v4(), phone_verification_token=tok, **_consent_ids())
    assert r.status_code == 409 and bd['data']['error_code'] == 'phone_in_use'


# ── 10 · production detection / test numbers ──────────────────────────────

def test_production_detection_and_test_mode_switch(monkeypatch):
    for env, prod in (('development', False), ('testing', False), ('local', False), ('production', True),
                      ('staging', True), ('', True)):
        monkeypatch.setenv('FLASK_ENV', env)
        assert PV.is_production() is prod, env
    monkeypatch.setenv('FLASK_ENV', 'testing')
    monkeypatch.setenv('TWILIO_TEST_NUMBERS', '+14165550142:123456')
    monkeypatch.delenv('TWILIO_TEST_MODE_ENABLED', raising=False)
    assert PV.test_numbers() == {}
    monkeypatch.setenv('TWILIO_TEST_MODE_ENABLED', '1')
    assert PV.test_numbers() == {'+14165550142': '123456'}
    monkeypatch.setenv('FLASK_ENV', 'staging')
    assert PV.test_numbers() == {}


# ── 11 · enumeration ───────────────────────────────────────────────────────

def test_rate_limits_apply_before_account_lookup(client, phones, make_user, monkeypatch):
    setting(monkeypatch, 'otp.resend_after_s', 0)
    unknown = phones.new()
    for _ in range(5):
        r = client.post('/api/verify/phone/start', json={'phone': unknown, 'purpose': 'login'}, headers=v4())
        assert body(r)['code'] == 1
    r = client.post('/api/verify/phone/start', json={'phone': unknown, 'purpose': 'login'}, headers=v4())
    assert r.status_code == 429 and body(r)['data']['error_code'] == 'rate_limited_phone'
    owned = phones.new()
    give_verified_phone(make_user('customer'), owned)
    for _ in range(5):
        r = client.post('/api/verify/phone/start', json={'phone': owned, 'purpose': 'signup'}, headers=v4())
        assert r.status_code == 409
    r = client.post('/api/verify/phone/start', json={'phone': owned, 'purpose': 'signup'}, headers=v4())
    assert r.status_code == 429


# ── 12 · legal re-acceptance gate ──────────────────────────────────────────

@pytest.fixture()
def legal_snapshot(monkeypatch):
    monkeypatch.setattr(L, 'notify_policy_update', lambda doc_id: None)
    published = [d.id for d in LegalDocument.query.filter_by(status='published')]
    before_max = db.session.query(db.func.max(LegalDocument.id)).scalar() or 0
    yield
    db.session.rollback()
    new_ids = [d.id for d in LegalDocument.query.filter(LegalDocument.id > before_max)]
    if new_ids:
        LegalAcceptance.query.filter(LegalAcceptance.document_id.in_(new_ids)).delete(synchronize_session=False)
        LegalDocument.query.filter(LegalDocument.id.in_(new_ids)).delete(synchronize_session=False)
    LegalDocument.query.filter(LegalDocument.id.in_(published)).update({'status': 'published'}, synchronize_session=False)
    db.session.commit()
    L.invalidate_gate_cache()


def test_reacceptance_gate_blocks_non_exempt_endpoints(client, auth, make_user, monkeypatch, legal_snapshot):
    u = make_user('customer')
    client.post('/api/legal/accept', json={'types': ['terms', 'privacy', 'community_guidelines']}, headers=auth(u))
    assert client.get('/api/wallet', headers=auth(u, **v4())).status_code != 403
    admin = make_user('admin')
    draft = L.create_draft(admin, 'privacy', f'p{uuid.uuid4().hex[:6]}', 'en')
    L.publish(draft, admin, requires_reacceptance=True, what_changed='New processor')
    db.session.commit()
    r = client.get('/api/wallet', headers=auth(u, **v4()))
    assert r.status_code == 403 and body(r)['data']['error_code'] == 'legal_pending'
    assert [p['type'] for p in body(r)['data']['items']] == ['privacy']
    for path in ('/api/legal/pending', '/api/users/me', '/api/account/status', '/api/app/config'):
        assert client.get(path, headers=auth(u, **v4())).status_code == 200, path
    setting(monkeypatch, 'app.legacy_clients_allowed', True)
    assert client.get('/api/wallet', headers=auth(u)).status_code != 403       # v3 cannot show the modal
    r = client.post('/api/legal/accept', json={'document_ids': [draft.id]}, headers=auth(u, **v4()))
    assert body(r)['code'] == 1
    assert client.get('/api/wallet', headers=auth(u, **v4())).status_code != 403


# ── 13 · CASL proof ────────────────────────────────────────────────────────

def test_marketing_consent_evidence(client, auth, _created_users):
    h = {**v4(ip='10.1.2.3'), 'User-Agent': 'NegoRide/4.0.0 (iOS 18)'}
    r, b = _register(client, _created_users, h, marketing_opt_in=True, **_consent_ids())
    assert r.status_code == 201
    uid = b['data']['id']
    row = MarketingConsent.query.filter_by(user_id=uid).one()
    assert row.action == 'grant' and row.source == 'registration' and row.ip == '10.1.2.3'
    assert 'iOS' in row.user_agent and row.wording_version and 'unsubscribe' in row.wording_text
    u = db.session.get(AdminUser, uid)
    r = client.put('/api/notification-preferences', json={'marketing_opt_in': False}, headers=auth(u, **v4()))
    assert body(r)['code'] == 1
    rows = MarketingConsent.query.filter_by(user_id=uid).order_by(MarketingConsent.id).all()
    assert [x.action for x in rows] == ['grant', 'withdraw'] and rows[1].source == 'preferences'
    client.put('/api/notification-preferences', json={'marketing_opt_in': False}, headers=auth(u, **v4()))
    assert MarketingConsent.query.filter_by(user_id=uid).count() == 2      # no change → no new proof row


# ── 14 · acceptance stats denominator ──────────────────────────────────────

def test_acceptance_stats_uses_audience_and_language(make_user):
    make_user('driver', preferred_language='fr')
    stats = L.acceptance_stats('driver_agreement')['items']
    fr = next(s for s in stats if s['language'] == 'fr' and s['status'] == 'published')
    expected = AdminUser.query.filter(AdminUser.deleted_at.is_(None), AdminUser.preferred_language == 'fr',
                                      AdminUser.user_type.in_(('Driver', 'Pending Driver'))).count()
    assert fr['audience_users'] == expected and expected >= 1
    assert fr['acceptance_rate_pct'] == round(100.0 * fr['acceptances'] / expected, 1)


# ── 15 · account status UX ─────────────────────────────────────────────────

def test_session_revoked_vs_blocked_and_pending_review_login(client, auth, make_user):
    u = make_user('customer', email_verified_at=datetime.utcnow())
    old = auth(u)
    u.token_version = int(u.token_version or 0) + 1       # e.g. password reset elsewhere
    db.session.commit()
    r = client.get('/api/wallet', headers=old)
    assert r.status_code == 401 and body(r)['data']['error_code'] == 'session_revoked'

    realtime.SENT.clear()
    A.set_status(u, 'pending_review', None, 'low_rating', 'Average below 4.0')
    ev = [d for e, d, room in realtime.SENT if e == 'account.status_changed' and room == f'user:{u.id}']
    assert ev and ev[-1]['account_status'] == 'pending_review' and ev[-1]['can_appeal'] is True
    assert ev[-1]['reason_code'] == 'low_rating' and ev[-1]['reason_category'] == 'quality'
    r = client.post('/api/users/login', json={'email': u.email, 'password': 'Test1234!'}, headers=v4())
    b = body(r)
    assert r.status_code == 403 and b['data']['account_status'] == 'pending_review' and b['data']['can_appeal'] is True
    tok = {'Authorization': f"Bearer {b['data']['token']}"}
    assert client.get('/api/account/status', headers=tok).status_code == 200
    r = client.get('/api/wallet', headers=tok)
    assert r.status_code == 403 and body(r)['data']['error_code'] == 'account_blocked'


# ── 16 · sockets + SSE ─────────────────────────────────────────────────────

def test_call_socket_rejects_inactive_and_is_dropped_on_suspension(app, make_user, auth):
    from backend.app import socketio
    from backend.sockets import call_events as CE
    from backend.utils.auth import issue_token
    u = make_user('customer')
    c = socketio.test_client(app)
    c.emit('authenticate', {'token': issue_token(u)})
    assert any(m['name'] == 'authenticated' for m in c.get_received())
    assert CE.user_sockets.get(u.id)
    A.set_status(u, 'suspended', None, 'harassment', 'x', until=datetime.utcnow() + timedelta(days=1))
    assert u.id not in CE.user_sockets
    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    c2 = socketio.test_client(app)
    c2.emit('authenticate', {'token': issue_token(u)})      # fresh token, suspended account
    msgs = c2.get_received()
    assert any(m['name'] == 'auth_error' and m['args'][0]['error_code'] == 'account_blocked' for m in msgs)
    c.disconnect() if c.is_connected() else None
    c2.disconnect() if c2.is_connected() else None


def test_sse_stream_ends_when_account_is_suspended(client, auth, make_user, monkeypatch):
    from backend.routes import stream
    monkeypatch.setattr(stream, '_POLL_INTERVAL', 0)
    monkeypatch.setattr(stream, '_AUTH_RECHECK_EVERY', 1)
    u = make_user('customer')
    r = client.get('/api/stream/events', headers=auth(u), buffered=False)
    gen = iter(r.response)
    assert b'connected' in next(gen)
    A.set_status(u, 'suspended', None, 'harassment', 'x', until=datetime.utcnow() + timedelta(days=1))
    chunks = []
    for _ in range(10):
        try:
            chunks.append(next(gen))
        except StopIteration:
            break
    assert any(b'auth_revoked' in c and b'account_blocked' in c for c in chunks)
    r.close()


# ── 17 · legacy admin status changes ───────────────────────────────────────

def test_legacy_admin_status_changes_need_reason(client, auth, make_user):
    admin, u = make_user('admin'), make_user('driver')
    r = client.post(f'/api/admin/users/{u.id}/toggle-status', json={}, headers=auth(admin))
    assert body(r)['data']['error_code'] == 'reason_required'
    r = client.post(f'/api/admin/users/{u.id}/toggle-status', json={'reason_code': 'fraud'}, headers=auth(admin))
    assert body(r)['data']['error_code'] == 'reason_text_required'
    r = client.post(f'/api/admin/users/{u.id}/update', json={'status': 0}, headers=auth(admin))
    assert body(r)['data']['error_code'] == 'reason_required'
    r = client.post(f'/api/admin/users/{u.id}/toggle-status',
                    json={'reason_code': 'fraud', 'reason_text': 'Chargebacks'}, headers=auth(admin))
    assert body(r)['code'] == 1
    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    assert u.account_status == 'deactivated' and u.status_reason_code == 'fraud'
    # ready_for_trip is not editable from the legacy editor (go-online gate)
    u2 = make_user('driver', ready_for_trip='No')
    client.post(f'/api/admin/users/{u2.id}/update', json={'ready_for_trip': 'Yes', 'first_name': 'Edited'},
                headers=auth(admin))
    db.session.rollback()
    u2 = db.session.get(AdminUser, u2.id)
    assert u2.first_name == 'Edited' and u2.ready_for_trip == 'No'


# ── 18 · matching uses the effective account status ───────────────────────

def test_matching_uses_effective_account_status(make_user):
    from backend.services import matching_service as M
    lat, lng = 62.4540, -114.3718     # Yellowknife — isolated from other test drivers
    now = datetime.utcnow()
    common = dict(current_latitude=lat, current_longitude=lng, last_location_update=now)
    lapsed = make_user('driver', account_status='suspended', status=0, suspended_until=now - timedelta(hours=1), **common)
    active = make_user('driver', account_status='suspended', status=0, suspended_until=now + timedelta(days=1), **common)
    pending = make_user('driver', pending_account_status='suspended', **common)
    ok = make_user('driver', **common)
    ids = {d.id for _dist, d in M.online_drivers(lat, lng, 'car', radius_km=5)}
    assert lapsed.id in ids and ok.id in ids
    assert active.id not in ids and pending.id not in ids


# ── 20 · admin history ─────────────────────────────────────────────────────

def test_user_history_includes_related_entities(client, auth, make_user):
    from backend.services.audit import audit
    admin, u = make_user('admin'), make_user('customer')
    app_row = DriverApplication(user_id=u.id, status='in_progress', current_step='account_created', steps={},
                                referral_code='NR' + uuid.uuid4().hex[:6].upper())
    db.session.add(app_row)
    db.session.flush()
    audit('onboarding.application_needs_changes', admin, 'driver_application', app_row.id)
    db.session.commit()
    r = client.get(f'/api/admin/users/{u.id}/history', headers=auth(admin))
    items = body(r)['data']['data']
    assert any(x['entity_type'] == 'driver_application' and x['entity_id'] == str(app_row.id) for x in items)


# ── 21 · account emails ────────────────────────────────────────────────────

def test_reset_and_verify_emails_use_website_links_and_language(client, make_user, monkeypatch):
    monkeypatch.setenv('PUBLIC_WEB_BASE_URL', 'https://web.negoride.test')
    u = make_user('customer', preferred_language='fr')
    email_provider.OUTBOX.clear()
    assert body(client.post('/api/auth/forgot-password', json={'email': u.email}))['code'] == 1
    mail = email_provider.OUTBOX[-1]
    assert mail['to'] == u.email and 'Réinitialisez' in mail['subject']
    assert 'https://web.negoride.test/reset-password?token=' in mail['html'] and '&amp;email=' in mail['html']
    assert 'reset-password-page' not in mail['html'] and 'ugnews24' not in mail['html']
    db.session.rollback()
    token = db.session.get(AdminUser, u.id).password_reset_token
    r = client.post('/api/auth/reset-password', json={'token': token[:8].upper(), 'password': 'NewPass123!'})
    assert r.status_code == 400 and body(r)['data']['error_code'] == 'invalid_token'
    r = client.post('/api/auth/reset-password', json={'token': token, 'email': 'other@x.test', 'password': 'NewPass123!'})
    assert r.status_code == 400
    r = client.post('/api/auth/reset-password', json={'token': token, 'email': u.email, 'password': 'NewPass123!'})
    assert body(r)['code'] == 1

    v = make_user('customer')      # English
    v.email_verification_token, v.verification_token_expires = f'tok{uuid.uuid4().hex}', datetime.utcnow() + timedelta(hours=1)
    db.session.commit()
    assert body(client.post('/api/email/resend-verification', json={'email': v.email}))['code'] == 1
    mail = email_provider.OUTBOX[-1]
    assert mail['subject'].startswith('Verify') and 'https://web.negoride.test/verify-email?token=' in mail['html']
    db.session.rollback()
    tok = db.session.get(AdminUser, v.id).email_verification_token
    assert body(client.post('/api/email/verify', json={'token': tok, 'email': 'nope@x.test'}))['data']['error_code'] == 'invalid_token'
    r = client.post('/api/email/verify', json={'token': tok, 'email': v.email})
    assert body(r)['data'] == {'verified': True, 'already_verified': False}
    page = client.get('/api/email/verify/does-not-exist').get_data(as_text=True)
    assert 'ugnews24' not in page and 'https://web.negoride.test' in page


# ── 22 · production secrets ────────────────────────────────────────────────

def test_config_refuses_default_secrets_in_production():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, 'FLASK_ENV': 'production', 'SECRET_KEY': '', 'JWT_SECRET_KEY': ''}
    p = subprocess.run([sys.executable, '-c', 'import backend.config'], cwd=root, env=env, capture_output=True, text=True)
    assert p.returncode != 0 and 'SECRET_KEY must be set' in p.stderr
    env.update(FLASK_ENV='development')
    p = subprocess.run([sys.executable, '-c', 'import backend.config'], cwd=root, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_resolving_dispute_ticket_marks_ride_dispute_resolved(client, auth, make_user):
    from backend.models.identity import SupportTicket
    from backend.models.negotiation import Negotiation
    from tests.test_safety import make_ride
    admin, customer, driver = make_user('admin'), make_user('customer'), make_user('driver')
    ride = make_ride(customer, driver, stage='COMPLETED', disputed_at=datetime.utcnow() - timedelta(days=2))
    t = SupportTicket(user_id=customer.id, type='dispute', ride_type='carhire', ride_id=ride.id,
                      subject='Fare dispute', body='Charged twice', status='open', priority='normal')
    db.session.add(t)
    db.session.commit()
    r = client.post(f'/api/admin/support/tickets/{t.id}/status', json={'status': 'resolved', 'resolution': 'Refunded'},
                    headers=auth(admin))
    assert body(r)['code'] == 1
    db.session.rollback()
    assert db.session.get(Negotiation, ride.id).dispute_resolved_at is not None
