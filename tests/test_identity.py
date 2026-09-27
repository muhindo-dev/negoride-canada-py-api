"""Phone verification (spec §11) and legal consent (spec §12)."""
import hashlib
import uuid
from datetime import datetime, timedelta

import pytest

from backend import jobs
from backend.models import db
from backend.models.identity import LegalAcceptance, LegalDocument, PhoneVerification, UserDevice
from backend.models.platform import WebhookEvent
from backend.models.user import AdminUser
from backend.services import legal_service as L
from backend.services import twilio_client
from tests.conftest import body
from tests.identity_utils import give_verified_phone, phones, rand_ip, setting, v4, verify  # noqa: F401


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch):
    sent = []
    monkeypatch.setattr('backend.routes.auth.send_verification_email', lambda *a, **k: sent.append(a) or True)
    return sent


def _consent_ids():
    return {'accepted_terms_id': L.current('terms').id, 'accepted_privacy_id': L.current('privacy').id,
            'accepted_guidelines_id': L.current('community_guidelines').id}


def _register(client, _created_users, headers, **fields):
    tag = uuid.uuid4().hex[:10]
    payload = {'first_name': 'Reg', 'last_name': 'Test', 'email': f'v4test_reg_{tag}@negoride.test',
               'password': 'Test1234!', 'username': f'v4test_reg_{tag}'}
    payload.update(fields)
    r = client.post('/api/users/register', json=payload, headers=headers)
    b = body(r)
    if b.get('code') == 1:
        _created_users.append(b['data']['id'])
    return r, b


# ── verify flow ─────────────────────────────────────────────────────────────

def test_signup_verification_with_test_number_and_single_use_token(client, phones, _created_users):
    phone = phones.new('123456')
    h = v4()
    r = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup'}, headers=h)
    b = body(r)
    assert b['code'] == 1 and b['data']['test_mode'] is True and b['data']['phone'] == phone
    assert b['data']['resend_after_s'] == 30 and b['data']['expires_in_s'] == 600

    r = client.post('/api/verify/phone/check', json={'phone': phone, 'purpose': 'signup', 'code': '000000'}, headers=h)
    assert body(r)['data']['error_code'] == 'invalid_code' and body(r)['data']['attempts_left'] == 4

    r = client.post('/api/verify/phone/check', json={'phone': phone, 'purpose': 'signup', 'code': '123456'}, headers=h)
    tok = body(r)['data']['verification_token']
    assert tok.startswith('pvt_')
    row = PhoneVerification.query.filter_by(phone=phone, status='approved').one()
    assert row.token_hash == hashlib.sha256(tok.encode()).hexdigest() and tok not in (row.token_hash or '')

    r, b = _register(client, _created_users, h, phone_number=phone, phone_verification_token=tok, **_consent_ids())
    assert r.status_code == 201, b
    u = db.session.get(AdminUser, b['data']['id'])
    assert u.phone_e164 == phone and u.phone_verified_at is not None and u.phone_line_type == 'mobile'
    assert b['data']['requires_phone_verification'] is False

    # the token is single use
    r, b = _register(client, _created_users, h, phone_verification_token=tok, **_consent_ids())
    assert b['code'] == 0 and b['data']['error_code'] == 'verification_used'


def test_phone_required_signup_flag(client, phones, monkeypatch, _created_users):
    setting(monkeypatch, 'ff.phone_required_signup', True)
    r, b = _register(client, _created_users, v4(), **_consent_ids())
    assert b['code'] == 0 and b['data']['error_code'] == 'phone_verification_required'
    # v3 clients are unaffected
    r, b = _register(client, _created_users, {})
    assert r.status_code == 201


def test_resend_cooldown_and_rate_limits(client, phones, monkeypatch):
    phone = phones.new()
    h = v4()
    assert body(client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup'}, headers=h))['code'] == 1
    r = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup'}, headers=h)
    assert r.status_code == 429 and body(r)['data']['error_code'] == 'resend_too_soon'
    assert 0 < body(r)['data']['retry_after_s'] <= 30

    setting(monkeypatch, 'otp.resend_after_s', 0)
    for _ in range(4):
        assert body(client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup'},
                                headers=v4()))['code'] == 1
    r = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup'}, headers=v4())
    assert r.status_code == 429 and body(r)['data']['error_code'] == 'rate_limited_phone'

    ip = rand_ip()
    for _ in range(10):
        assert body(client.post('/api/verify/phone/start', json={'phone': phones.new(), 'purpose': 'signup'},
                                headers=v4(ip)))['code'] == 1
    r = client.post('/api/verify/phone/start', json={'phone': phones.new(), 'purpose': 'signup'}, headers=v4(ip))
    assert r.status_code == 429 and body(r)['data']['error_code'] == 'rate_limited_ip'


def test_attempt_limit_and_expiry(client, phones):
    phone = phones.new('654321')
    h = v4()
    client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup'}, headers=h)
    for i in range(4):
        r = client.post('/api/verify/phone/check', json={'phone': phone, 'purpose': 'signup', 'code': '111111'}, headers=h)
        assert body(r)['data']['attempts_left'] == 4 - i
    r = client.post('/api/verify/phone/check', json={'phone': phone, 'purpose': 'signup', 'code': '111111'}, headers=h)
    assert r.status_code == 429 and body(r)['data']['error_code'] == 'too_many_attempts'
    r = client.post('/api/verify/phone/check', json={'phone': phone, 'purpose': 'signup', 'code': '654321'}, headers=h)
    assert body(r)['code'] == 0 and body(r)['data']['error_code'] == 'no_pending_code'

    # expiry after 10 minutes
    phone2 = phones.new('654321')
    client.post('/api/verify/phone/start', json={'phone': phone2, 'purpose': 'signup'}, headers=h)
    row = PhoneVerification.query.filter_by(phone=phone2).one()
    row.created_at = datetime.utcnow() - timedelta(minutes=11)
    db.session.commit()
    r = client.post('/api/verify/phone/check', json={'phone': phone2, 'purpose': 'signup', 'code': '654321'}, headers=h)
    assert r.status_code == 410 and body(r)['data']['error_code'] == 'code_expired'


def test_voice_after_two_sms_whatsapp_off_country_and_premium(client, phones, monkeypatch):
    setting(monkeypatch, 'otp.resend_after_s', 0)
    phone = phones.new()
    r = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup', 'channel': 'call'}, headers=v4())
    assert body(r)['data']['error_code'] == 'voice_not_available'
    r1 = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup'}, headers=v4())
    assert body(r1)['data']['voice_available'] is False
    r2 = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup'}, headers=v4())
    assert body(r2)['data']['voice_available'] is True
    r = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup', 'channel': 'call'}, headers=v4())
    assert body(r)['code'] == 1 and body(r)['data']['channel'] == 'call'
    r = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup', 'channel': 'whatsapp'}, headers=v4())
    assert body(r)['data']['error_code'] == 'channel_unavailable'

    r = client.post('/api/verify/phone/start', json={'phone': '+447700900123', 'purpose': 'signup'}, headers=v4())
    assert body(r)['data']['error_code'] == 'country_not_allowed'
    r = client.post('/api/verify/phone/start', json={'phone': '+19005550123', 'purpose': 'signup'}, headers=v4())
    assert body(r)['data']['error_code'] == 'premium_blocked'


def test_dev_fallback_when_twilio_not_configured(client, monkeypatch):
    from backend.services import phone_verification as PV
    monkeypatch.setenv('TWILIO_TEST_NUMBERS', '')
    phone = '+1416' + '555' + f'{uuid.uuid4().int % 10000:04d}'
    try:
        r = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup'}, headers=v4())
        assert body(r)['code'] == 1 and body(r)['data']['test_mode'] is False
        code = [c for p, _, c in PV.DEV_LOG if p == phone][-1]
        row = PhoneVerification.query.filter_by(phone=phone).one()
        assert row.code_hash and code not in (row.code_hash or '')
        r = client.post('/api/verify/phone/check', json={'phone': phone, 'purpose': 'signup', 'code': code}, headers=v4())
        assert body(r)['code'] == 1
        # never in production
        monkeypatch.setenv('FLASK_ENV', 'production')
        r = client.post('/api/verify/phone/start', json={'phone': '+14165550188', 'purpose': 'signup'}, headers=v4())
        assert r.status_code == 503 and body(r)['data']['error_code'] == 'sms_unavailable'
    finally:
        db.session.rollback()
        PhoneVerification.query.filter(PhoneVerification.phone.in_((phone, '+14165550188'))).delete(synchronize_session=False)
        db.session.commit()


def test_duplicate_phone_offers_login_instead(client, phones, make_user):
    phone = phones.new()
    give_verified_phone(make_user('customer'), phone)
    r = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': 'signup'}, headers=v4())
    assert r.status_code == 409 and body(r)['data']['login_instead'] is True


def test_passwordless_login(client, phones, make_user):
    phone = phones.new()
    u = make_user('customer', email_verified_at=datetime.utcnow())
    give_verified_phone(u, phone)
    res = verify(client, phone, 'login')
    r = client.post('/api/auth/login/phone', json={'phone': phone, 'verification_token': res['verification_token'],
                                                   'device_id': 'dev-pwless'}, headers=v4())
    b = body(r)
    assert b['code'] == 1 and b['data']['id'] == u.id
    me = client.get('/api/users/me', headers={'Authorization': f"Bearer {b['data']['token']}"})
    assert body(me)['data']['id'] == u.id
    # unknown number → signup instead
    r = client.post('/api/verify/phone/start', json={'phone': phones.new(), 'purpose': 'login'}, headers=v4())
    assert r.status_code == 404 and body(r)['data']['signup_instead'] is True


def test_change_phone_notifies_old_number(client, auth, phones, make_user):
    old, new = phones.new(), phones.new()
    u = make_user('customer')
    give_verified_phone(u, old)
    twilio_client.SENT.clear()
    res = verify(client, new, 'change_phone', headers=auth(u, **v4()))
    # v4 clients cannot change the phone without verification
    r = client.post('/api/profile/update-phone', json={'phone_number': phones.new()}, headers=auth(u, **v4()))
    assert body(r)['data']['error_code'] == 'verification_required'
    r = client.post('/api/profile/update-phone', json={'phone_number': new, 'verification_token': res['verification_token']},
                    headers=auth(u, **v4()))
    assert body(r)['code'] == 1, body(r)
    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    assert u.phone_e164 == new and u.phone_number == new
    assert any(m['to'] == old and 'changed' in m['body'] for m in twilio_client.SENT)


def test_driver_onboarding_rejects_voip_and_auto_applies_mobile(client, auth, phones, make_user):
    u = make_user('customer')
    voip = phones.new(voip=True)
    r = client.post('/api/verify/phone/start', json={'phone': voip, 'purpose': 'driver_onboarding'}, headers=auth(u, **v4()))
    assert body(r)['data']['error_code'] == 'voip_not_allowed'
    mobile = phones.new()
    res = verify(client, mobile, 'driver_onboarding', headers=auth(u, **v4()))
    assert res['applied'] is True and res['verification_token'] is None
    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    assert u.phone_e164 == mobile and u.phone_verified_at and u.phone_line_type == 'mobile'


def test_new_device_step_up(client, phones, make_user, monkeypatch):
    setting(monkeypatch, 'ff.step_up_new_device', True)
    phone = phones.new()
    u = make_user('customer', email_verified_at=datetime.utcnow())
    give_verified_phone(u, phone)
    creds = {'email': u.email, 'password': 'Test1234!'}
    r = client.post('/api/users/login', json={**creds, 'device_id': 'dev-A'}, headers=v4())
    assert body(r)['code'] == 1 and body(r)['data']['token']      # first device is trusted
    r = client.post('/api/users/login', json={**creds, 'device_id': 'dev-B'}, headers=v4())
    b = body(r)
    assert b['code'] == 0 and b['data']['requires_step_up'] is True and 'token' not in b['data']
    ticket = b['data']['step_up_ticket']
    assert UserDevice.query.filter_by(user_id=u.id, device_id='dev-B').one().trusted_at is None
    res = verify(client, None, 'new_device', step_up_ticket=ticket)
    r = client.post('/api/users/login', json={**creds, 'device_id': 'dev-B',
                                              'verification_token': res['verification_token']}, headers=v4())
    assert body(r)['code'] == 1 and body(r)['data']['token']
    db.session.rollback()
    assert UserDevice.query.filter_by(user_id=u.id, device_id='dev-B').one().trusted_at is not None
    r = client.post('/api/users/login', json={**creds, 'device_id': 'dev-B'}, headers=v4())
    assert body(r)['code'] == 1


def test_password_reset_by_phone_revokes_sessions(client, auth, phones, make_user):
    phone = phones.new()
    u = make_user('customer', email_verified_at=datetime.utcnow())
    give_verified_phone(u, phone)
    old = auth(u)
    res = verify(client, phone, 'password_reset')
    r = client.post('/api/auth/reset-password/phone', json={'phone': phone, 'password': 'NewPass123!',
                                                            'verification_token': res['verification_token']})
    assert body(r)['code'] == 1
    assert client.get('/api/users/me', headers=old).status_code == 401
    r = client.post('/api/users/login', json={'email': u.email, 'password': 'NewPass123!'})
    assert body(r)['code'] == 1
    # unknown number: same answer, nothing sent, no way to verify
    unknown = phones.new()
    r = client.post('/api/verify/phone/start', json={'phone': unknown, 'purpose': 'password_reset'}, headers=v4())
    assert body(r)['code'] == 1
    assert PhoneVerification.query.filter_by(phone=unknown).one().status == 'suppressed'


def test_sensitive_action_required_for_account_deletion(client, auth, phones, make_user):
    phone = phones.new()
    u = make_user('customer')
    give_verified_phone(u, phone)
    r = client.post('/api/profile/delete-account', json={'password': 'Test1234!'}, headers=auth(u, **v4()))
    assert r.status_code == 403 and body(r)['data']['requires_verification'] is True
    res = verify(client, None, 'sensitive_action', headers=auth(u, **v4()))
    r = client.post('/api/profile/delete-account', json={'password': 'Test1234!',
                                                         'verification_token': res['verification_token']},
                    headers=auth(u, **v4()))
    assert body(r)['code'] == 1
    db.session.rollback()
    assert db.session.get(AdminUser, u.id).deleted_at is not None


def test_sensitive_action_required_for_payout_change(client, auth, phones, make_user):
    phone = phones.new()
    u = make_user('driver')
    give_verified_phone(u, phone)
    r = client.post('/api/payout-account/deactivate', json={}, headers=auth(u, **v4()))
    assert r.status_code == 403 and body(r)['data']['purpose'] == 'sensitive_action'
    # v3 clients keep the old behaviour
    r = client.post('/api/payout-account/deactivate', json={}, headers=auth(u))
    assert (body(r).get('data') or {}).get('error_code') != 'verification_required'


def test_legacy_otp_aliases(client, phones):
    phone = phones.new('222333')
    r = client.post('/api/otp-request', json={'phone_number': phone})
    assert body(r)['code'] == 1
    r = client.post('/api/otp-verify', json={'phone_number': phone, 'otp': '222333'})
    assert body(r)['code'] == 1 and body(r)['data']['verification_token']
    assert body(client.post('/api/otp-request', json={}))['code'] == 0


def test_twilio_inbound_stop_and_help(client, make_user, monkeypatch):
    monkeypatch.setenv('TWILIO_AUTH_TOKEN', 'tw_test_token')
    from backend.routes.verify import twilio_signature
    u = make_user('customer', marketing_opt_in=True)
    u.phone_e164 = u.phone_number
    db.session.commit()
    sid = 'SM' + uuid.uuid4().hex
    params = {'MessageSid': sid, 'From': u.phone_number, 'Body': 'STOP'}
    url = 'http://localhost/api/webhooks/twilio/inbound'
    try:
        r = client.post('/api/webhooks/twilio/inbound', data=params, headers={'X-Twilio-Signature': 'bad'})
        assert r.status_code == 403
        r = client.post('/api/webhooks/twilio/inbound', data=params,
                        headers={'X-Twilio-Signature': twilio_signature(url, params, 'tw_test_token')})
        assert r.status_code == 200 and b'<Response>' in r.data
        db.session.rollback()
        u = db.session.get(AdminUser, u.id)
        assert u.sms_opt_out_at is not None and u.marketing_opt_in is False
        assert WebhookEvent.query.filter_by(provider='twilio', event_id=sid).one().status == 'processed'
        help_params = {'MessageSid': sid + 'h', 'From': u.phone_number, 'Body': 'help'}
        r = client.post('/api/webhooks/twilio/inbound', data=help_params,
                        headers={'X-Twilio-Signature': twilio_signature(url, help_params, 'tw_test_token')})
        assert b'<Message>' in r.data and b'STOP' in r.data
    finally:
        db.session.rollback()
        WebhookEvent.query.filter(WebhookEvent.event_id.in_((sid, sid + 'h'))).delete(synchronize_session=False)
        db.session.commit()


# ── legal consent ───────────────────────────────────────────────────────────

def test_v4_registration_requires_three_explicit_ticks(client, _created_users):
    h = v4(ip='10.9.8.7')
    r, b = _register(client, _created_users, h)
    assert b['code'] == 0 and b['data']['error_code'] == 'consent_required'
    assert set(b['data']['missing']) == {'terms', 'privacy', 'community_guidelines'}
    ids = _consent_ids()
    r, b = _register(client, _created_users, h, accepted_terms_id=ids['accepted_terms_id'],
                     accepted_privacy_id=ids['accepted_privacy_id'])
    assert b['data']['missing'] == ['community_guidelines']
    assert not AdminUser.query.filter(AdminUser.username.like('v4test_reg_%'), AdminUser.id.notin_(_created_users or [0])).count()

    r, b = _register(client, _created_users, {**h, 'User-Agent': 'NegoRide/4.0.0 (Android 14)'}, **ids)
    assert r.status_code == 201, b
    rows = LegalAcceptance.query.filter_by(user_id=b['data']['id']).all()
    assert {x.document_type for x in rows} == {'terms', 'privacy', 'community_guidelines'}
    for x in rows:
        assert x.version == '1.0' and x.accepted_at and x.ip == '10.9.8.7' and x.app_version == '4.0.0'
        assert x.method == 'checkbox' and 'Android' in x.user_agent
    u = db.session.get(AdminUser, b['data']['id'])
    assert u.marketing_opt_in is False          # CASL: never pre-ticked
    assert b['data']['legal_accepted']

    r, b = _register(client, _created_users, h, marketing_opt_in=True,
                     acceptances=[{'type': 'terms', 'document_id': ids['accepted_terms_id']},
                                  {'type': 'privacy', 'document_id': ids['accepted_privacy_id']},
                                  {'type': 'community_guidelines', 'document_id': ids['accepted_guidelines_id']}])
    assert r.status_code == 201
    u = db.session.get(AdminUser, b['data']['id'])
    assert u.marketing_opt_in is True and u.marketing_opt_in_at is not None


def test_v3_registration_still_works_without_ticks(client, _created_users):
    r, b = _register(client, _created_users, {})
    assert r.status_code == 201 and b['code'] == 1
    assert LegalAcceptance.query.filter_by(user_id=b['data']['id']).count() == 0


def test_public_documents_render_settings_and_french(client):
    r = client.get('/api/legal/documents/cancellation_policy')
    d = body(r)['data']
    assert d['type'] == 'cancellation_policy' and d['version'] == '1.0' and '{{' not in d['body_markdown']
    assert '$5.00' in d['body_markdown'] and '$7.00' in d['body_markdown']
    assert d['summary_markdown'] and d['effective_at'] and d['language'] == 'en'
    fr = body(client.get('/api/legal/documents/terms?lang=fr'))['data']
    assert fr['language'] == 'fr' and fr['title'] != body(client.get('/api/legal/documents/terms'))['data']['title']
    lst = body(client.get('/api/legal/documents?audience=customer'))['data']['items']
    types = {x['type'] for x in lst}
    assert {'terms', 'privacy', 'community_guidelines', 'cancellation_policy'} <= types and 'driver_agreement' not in types
    assert body(client.get('/api/legal/documents/guidelines'))['data']['type'] == 'community_guidelines'
    assert client.get('/api/legal/documents/nope').status_code == 404


@pytest.fixture()
def legal_snapshot():
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


def test_reacceptance_pending_after_new_version(client, auth, make_user, monkeypatch, legal_snapshot):
    notified = []
    monkeypatch.setattr(L, 'notify_policy_update', lambda doc_id: notified.append(doc_id))
    u = make_user('customer')
    admin = make_user('admin')
    # a user who never accepted sees the three sign-up documents
    pend = body(client.get('/api/legal/pending', headers=auth(u)))['data']
    assert pend['blocking'] is True and {p['type'] for p in pend['items']} == {'terms', 'privacy', 'community_guidelines'}
    r = client.post('/api/legal/accept', json={'types': ['terms', 'privacy', 'community_guidelines'], 'method': 'modal',
                                               'app_version': '4.0.0'}, headers=auth(u))
    assert body(r)['code'] == 1 and body(r)['data']['pending'] == []

    ver = f't{uuid.uuid4().hex[:6]}'
    r = client.post('/api/admin/legal/documents', json={'type': 'terms', 'version': ver, 'language': 'en'},
                    headers=auth(admin))
    draft = body(r)['data']
    assert r.status_code == 201 and draft['status'] == 'draft' and draft['body_markdown']
    r = client.put(f"/api/admin/legal/documents/{draft['id']}", json={'body_markdown': draft['body_markdown'] + '\n\n## New clause'},
                   headers=auth(admin))
    assert body(r)['code'] == 1
    assert '{{' not in body(client.get(f"/api/admin/legal/documents/{draft['id']}/preview", headers=auth(admin)))['data']['body_markdown']
    r = client.post(f"/api/admin/legal/documents/{draft['id']}/publish",
                    json={'requires_reacceptance': True, 'what_changed': 'Clarified cancellation fees.'}, headers=auth(admin))
    assert body(r)['code'] == 1
    assert notified == [draft['id']]
    assert 'backend.services.legal_service.notify_policy_update' in jobs.EXECUTED

    pend = body(client.get('/api/legal/pending', headers=auth(u)))['data']['items']
    assert [p['type'] for p in pend] == ['terms'] and pend[0]['version'] == ver and pend[0]['reason'] == 'updated'
    assert pend[0]['what_changed'] == 'Clarified cancellation fees.'
    assert body(client.get('/api/legal/documents/terms'))['data']['version'] == ver
    client.post('/api/legal/accept', json={'document_ids': [draft['id']]}, headers=auth(u))
    assert body(client.get('/api/legal/pending', headers=auth(u)))['data']['items'] == []
    stats = body(client.get('/api/admin/legal/stats?type=terms', headers=auth(admin)))['data']['items']
    assert any(s['id'] == draft['id'] and s['acceptances'] == 1 for s in stats)
    # published versions are immutable
    r = client.put(f"/api/admin/legal/documents/{draft['id']}", json={'title': 'x'}, headers=auth(admin))
    assert body(r)['data']['error_code'] == 'not_draft'


def test_legal_editor_requires_role(client, auth, make_user):
    support = make_user('customer', admin_roles='support')
    r = client.post('/api/admin/legal/documents', json={'type': 'terms', 'version': '9.9'}, headers=auth(support))
    assert r.status_code == 403
    assert client.get('/api/admin/legal/documents', headers=auth(support)).status_code == 200
    assert client.get('/api/admin/legal/documents', headers=auth(make_user('customer'))).status_code == 403
