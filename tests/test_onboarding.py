"""Driver onboarding wizard + Certn background checks (spec §14)."""
import io
import json
import uuid
from datetime import date, datetime, timedelta

import pytest

from backend.models import db
from backend.models.identity import BackgroundCheck, DriverApplication, DriverDocument
from backend.models.money import RidePayment
from backend.models.notification import Notification
from backend.models.platform import AuditLog, WebhookEvent
from backend.models.user import AdminUser
from backend.services import certn_client as CC
from backend.services import onboarding_service as O
from backend.services import private_storage as PSTORE
from backend.services.payments.gateway import get_gateway
from tests.conftest import body
from tests.identity_utils import give_verified_phone, rand_phone, setting, v4

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 256
SECRET = 'certn_whsec_test'


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    setting(monkeypatch, 'onboarding.bgc_start_delay_min', 0)   # start Certn at once (cancel window tested separately)
    PSTORE.configure(root=str(tmp_path / 'private'), key='test-key')
    fake = CC.FakeCertnClient()
    CC.set_client(fake)
    monkeypatch.setenv('CERTN_WEBHOOK_SECRET', SECRET)
    yield fake
    CC.set_client(None)
    PSTORE.configure(None)


@pytest.fixture()
def certn(_isolated):
    return _isolated


def applicant(make_user, client, auth):
    u = make_user('customer', email_verified_at=datetime.utcnow())
    give_verified_phone(u, rand_phone())
    r = client.post('/api/legal/accept', json={'types': ['terms', 'privacy', 'community_guidelines']}, headers=auth(u))
    assert body(r)['code'] == 1
    return u


PROFILE = {'legal_first_name': 'Amara', 'legal_last_name': 'Okafor', 'date_of_birth': '1990-04-12',
           'address_line': '100 Queen St W', 'city': 'Toronto', 'province': 'ON', 'postal_code': 'm5h2n2',
           'service_types': ['car_hire', 'rideshare'], 'licence_class': 'G', 'licence_number': 'O1234-56789-01234',
           'licence_expires_at': (date.today() + timedelta(days=900)).isoformat(), 'vehicle_make': 'Toyota',
           'vehicle_model': 'Corolla', 'vehicle_year': 2019, 'vehicle_color': 'Grey', 'vehicle_plate': 'ABCD 123',
           'vehicle_seats': 4}


def upload(client, auth, u, doc_type, expires=None):
    data = {'type': doc_type, 'file': (io.BytesIO(PNG), f'{doc_type}.png', 'image/png')}
    if expires:
        data['expires_at'] = expires
    if doc_type == 'insurance':
        data['attestation_rideshare_endorsement'] = 'true'
    return client.post('/api/driver/onboarding/documents', data=data, headers=auth(u),
                       content_type='multipart/form-data')


def complete_until_bgc(client, auth, u):
    r = client.post('/api/driver/onboarding/prequal', json={'date_of_birth': '1990-04-12', 'licence_class': 'G',
                                                            'vehicle_year': 2019, 'province': 'ON'}, headers=auth(u))
    assert body(r)['data']['prequal']['passed'] is True
    r = client.post('/api/driver/onboarding/profile', json=PROFILE, headers=auth(u))
    assert body(r)['code'] == 1, body(r)
    r = client.post('/api/driver/onboarding/agreements', json={'signature_name': 'Amara Okafor'}, headers=auth(u, **v4()))
    assert body(r)['code'] == 1, body(r)
    exp = (date.today() + timedelta(days=400)).isoformat()
    for t in O.DOC_TYPES:
        r = upload(client, auth, u, t, exp if t in ('licence_front', 'insurance', 'registration') else None)
        assert r.status_code == 201, body(r)


def pay_bgc(client, auth, sign_stripe, u):
    from tests.test_carhire_flow import deliver_webhook
    r = client.post('/api/driver/onboarding/background-check/consent', json={'signature_name': 'Amara Okafor'},
                    headers=auth(u, **v4()))
    assert body(r)['code'] == 1, body(r)
    r = client.post('/api/driver/onboarding/background-check/pay', json={}, headers=auth(u))
    b = body(r)
    assert b['code'] == 1 and b['data']['checkout_url'] and b['data']['amount_cents'] == 3999
    rp = db.session.get(RidePayment, b['data']['ride_payment_id'])
    assert rp.purpose == 'background_check' and rp.capture_method == 'automatic'
    event = get_gateway().simulate_customer_pays(rp.checkout_session_id)
    assert deliver_webhook(client, sign_stripe, event).status_code == 200
    db.session.rollback()
    return O.latest_bgc(u.id)


def certn_webhook(client, case_id, case_status='COMPLETE', secret=SECRET, event_id=None):
    payload = json.dumps({'created': '2026-09-27T12:00:00Z', 'event_id': event_id or str(uuid.uuid4()),
                          'event_type': 'CASE_STATUS_CHANGED', 'object_id': case_id, 'object_type': 'CASE',
                          'case_status': case_status})
    return client.post('/api/webhooks/certn', data=payload, content_type='application/json',
                       headers={'X-Signature': CC.sign(payload, secret)})


def _cleanup_events(case_ids):
    db.session.rollback()
    for cid in case_ids:
        WebhookEvent.query.filter(WebhookEvent.provider == 'certn', WebhookEvent.payload.like(f'%{cid}%')) \
            .delete(synchronize_session=False)
    db.session.commit()


def test_full_wizard_to_approval_sets_legacy_flags(client, auth, make_user, sign_stripe, certn):
    u = applicant(make_user, client, auth)
    admin = make_user('admin')
    ov = body(client.get('/api/driver/onboarding', headers=auth(u)))['data']
    steps = {s['key']: s['status'] for s in ov['steps']}
    assert steps['account_created'] == 'done' and steps['phone_verified'] == 'done'
    assert steps['email_verified'] == 'done' and steps['profile_completed'] == 'in_progress'  # names prefilled
    assert ov['progress_pct'] == 38 and ov['can_submit'] is False
    assert ov['application']['referral_code'].startswith('NR')

    # background check cannot be paid before the pre-qualification passes
    r = client.post('/api/driver/onboarding/background-check/consent', json={'signature_name': 'A O'}, headers=auth(u))
    assert body(r)['data']['error_code'] == 'prequal_required'
    r = client.post('/api/driver/onboarding/prequal', json={'date_of_birth': (date.today() - timedelta(days=365 * 19)).isoformat(),
                                                            'licence_class': 'G2', 'vehicle_year': 2005, 'province': 'ON'},
                    headers=auth(u))
    pq = body(r)['data']['prequal']
    assert pq['passed'] is False and {x['field'] for x in pq['reasons']} == {'date_of_birth', 'licence_class', 'vehicle_year'}
    assert {s['key']: s['status'] for s in body(r)['data']['steps']}['profile_completed'] == 'action_needed'

    complete_until_bgc(client, auth, u)
    ov = body(client.get('/api/driver/onboarding', headers=auth(u)))['data']
    steps = {s['key']: s['status'] for s in ov['steps']}
    assert steps['profile_completed'] == 'done' and steps['documents_submitted'] == 'under_review'
    assert [b['step'] for b in ov['submit_blockers']] == ['background_check']
    doc = DriverDocument.query.filter_by(user_id=u.id, type='selfie').one()
    assert doc.file_path.startswith('driver-docs/') and '/uploads' not in doc.file_path
    assert PSTORE.get(doc.file_path) == PNG and 'file_path' not in body(client.get('/api/driver/onboarding/documents',
                                                                                    headers=auth(u)))['data']['items'][0]

    bgc = pay_bgc(client, auth, sign_stripe, u)
    assert bgc.status == 'initiated' and bgc.provider_application_id.startswith('fake-case-') and bgc.invite_url
    assert bgc.fee_payment_id and bgc.consent_acceptance_id
    ov = body(client.get('/api/driver/onboarding', headers=auth(u)))['data']
    assert ov['background_check']['invite_url'] == bgc.invite_url
    assert {s['key']: s['status'] for s in ov['steps']}['background_check'] == 'action_needed'

    r = client.post('/api/driver/onboarding/submit', headers=auth(u))
    assert body(r)['code'] == 1 and body(r)['data']['application']['status'] == 'submitted'
    db.session.rollback()
    assert db.session.get(AdminUser, u.id).user_type == 'Pending Driver'

    # admin cannot approve before the check is clear
    app = DriverApplication.query.filter_by(user_id=u.id).one()
    r = client.post(f'/api/admin/onboarding/applications/{app.id}/decision', json={'decision': 'approve'},
                    headers=auth(admin))
    assert body(r)['data']['error_code'] == 'background_check_not_clear'

    case_id = bgc.provider_application_id
    try:
        certn.set_case(case_id, 'IN_PROGRESS')
        assert certn_webhook(client, case_id, 'IN_PROGRESS').status_code == 200
        db.session.rollback()
        assert O.latest_bgc(u.id).status == 'pending'
        certn.set_case(case_id, 'COMPLETE', 'CLEAR')
        eid = str(uuid.uuid4())
        assert certn_webhook(client, case_id, event_id=eid).status_code == 200
        assert body(certn_webhook(client, case_id, event_id=eid))['duplicate'] is True
        db.session.rollback()
        b = O.latest_bgc(u.id)
        assert b.status == 'clear' and b.completed_at and b.expires_at > datetime.utcnow() + timedelta(days=300)
        assert db.session.get(DriverApplication, app.id).status == 'under_review'
        assert Notification.query.filter_by(user_id=u.id, event_key='background_check.completed').count() == 1
    finally:
        _cleanup_events([case_id])

    r = client.get(f'/api/admin/onboarding/applications/{app.id}', headers=auth(admin))
    assert body(r)['code'] == 1 and len(body(r)['data']['documents']) == 10
    doc_id = body(r)['data']['documents'][0]['id']
    r = client.get(f'/api/admin/onboarding/documents/{doc_id}/file?inline=1', headers=auth(admin))
    assert r.status_code == 200 and r.data == PNG
    r = client.post(f'/api/admin/onboarding/applications/{app.id}/decision', json={'decision': 'approve'},
                    headers=auth(admin))
    assert body(r)['code'] == 1, body(r)
    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    assert u.user_type == 'Driver' and u.is_car == 'Yes' and u.is_car_approved == 'Yes' and u.is_approved_driver()
    assert u.driving_license_number == PROFILE['licence_number'] and '2019 Toyota Corolla' == u.automobile
    assert DriverDocument.query.filter_by(user_id=u.id, status='approved').count() == 10
    assert Notification.query.filter_by(user_id=u.id, event_key='onboarding.approved').count() == 1
    assert AuditLog.query.filter_by(action='onboarding.application_approve', entity_id=str(app.id)).count() == 1
    assert AuditLog.query.filter_by(action='admin.view_driver_document', actor_id=admin.id).count() == 1

    # safety orientation gates going online
    r = client.post('/api/go-on-off', json={'latitude': 43.65, 'longitude': -79.38, 'status': 'online'}, headers=auth(u))
    assert body(r)['code'] == 0 and 'orientation' in body(r)['message']
    q = body(client.get('/api/driver/onboarding/orientation', headers=auth(u)))['data']
    assert len(q['cards']) == 5 and len(q['questions']) == 5 and 'answer' not in q['questions'][0]
    r = client.post('/api/driver/onboarding/orientation', json={'answers': [0, 0, 0, 0, 0]}, headers=auth(u))
    assert body(r)['data']['orientation_result']['passed'] is False
    r = client.post('/api/driver/onboarding/orientation', json={'answers': [1, 2, 2, 0, 1]}, headers=auth(u))
    assert body(r)['data']['orientation_result']['passed'] is True
    r = client.post('/api/go-on-off', json={'latitude': 43.65, 'longitude': -79.38, 'status': 'online'}, headers=auth(u))
    assert body(r)['code'] == 1, body(r)
    ov = body(client.get('/api/driver/onboarding', headers=auth(u)))['data']
    assert ov['progress_pct'] == 88 or ov['progress_pct'] == 100 or ov['progress_pct'] >= 75
    assert ov['can_go_online']['ok'] is True


def test_certn_polling_fallback_and_admin_adjudication(client, auth, make_user, sign_stripe, certn):
    u = applicant(make_user, client, auth)
    admin = make_user('admin')
    complete_until_bgc(client, auth, u)
    bgc = pay_bgc(client, auth, sign_stripe, u)
    certn.set_case(bgc.provider_application_id, 'COMPLETE', 'REVIEW')
    from backend.services import onboarding_jobs
    res = onboarding_jobs.poll_background_checks()
    assert res['polled'] >= 1
    db.session.rollback()
    b = db.session.get(BackgroundCheck, bgc.id)
    assert b.status == 'consider' and b.provider_score == 'REVIEW'
    r = client.post(f'/api/admin/onboarding/background-checks/{b.id}/adjudicate', json={'decision': 'clear'},
                    headers=auth(admin))
    assert body(r)['data']['error_code'] == 'reason_required'
    r = client.post(f'/api/admin/onboarding/background-checks/{b.id}/adjudicate',
                    json={'decision': 'clear', 'note': 'Old minor offence, not relevant to driving.'}, headers=auth(admin))
    assert body(r)['code'] == 1
    db.session.rollback()
    b = db.session.get(BackgroundCheck, bgc.id)
    assert b.status == 'clear' and b.adjudicated_by == admin.id
    # later provider snapshots never override the admin decision
    certn.set_case(b.provider_application_id, 'COMPLETE', 'REJECT')
    O.refresh_from_provider(b)
    db.session.commit()
    assert db.session.get(BackgroundCheck, bgc.id).status == 'clear'
    r = client.get(f'/api/admin/onboarding/background-checks/{b.id}/report', headers=auth(admin))
    assert body(r)['data']['url'].endswith('.pdf')
    assert AuditLog.query.filter_by(action='admin.view_background_report', entity_id=str(b.id)).count() == 1


def test_failed_check_rejects_with_dispute_info(client, auth, make_user, sign_stripe, certn):
    u = applicant(make_user, client, auth)
    complete_until_bgc(client, auth, u)
    bgc = pay_bgc(client, auth, sign_stripe, u)
    client.post('/api/driver/onboarding/submit', headers=auth(u))
    certn.set_case(bgc.provider_application_id, 'COMPLETE', 'REJECT')
    try:
        assert certn_webhook(client, bgc.provider_application_id).status_code == 200
    finally:
        _cleanup_events([bgc.provider_application_id])
    db.session.rollback()
    assert db.session.get(BackgroundCheck, bgc.id).status == 'failed'
    app = DriverApplication.query.filter_by(user_id=u.id).one()
    assert app.status == 'rejected' and 'dispute' in app.rejection_reason and 'Certn' in app.rejection_reason
    n = Notification.query.filter_by(user_id=u.id, event_key='onboarding.rejected').one()
    assert 'dispute' in n.body
    from backend.services import account_service as A
    assert A.can_go_online(db.session.get(AdminUser, u.id))[0] is False


def test_certn_webhook_signature_and_challenge(client):
    assert client.get('/api/webhooks/certn?challenge=abc123').data == b'abc123'
    payload = json.dumps({'event_id': 'x', 'object_id': 'y'})
    r = client.post('/api/webhooks/certn', data=payload, content_type='application/json',
                    headers={'X-Signature': CC.sign(payload, 'wrong-secret')})
    assert r.status_code == 403
    r = client.post('/api/webhooks/certn', data=payload, content_type='application/json')
    assert r.status_code == 403


def test_pay_later_from_earnings(client, auth, make_user, monkeypatch, certn):
    setting(monkeypatch, 'ff.bgc_pay_later', True)
    u = applicant(make_user, client, auth)
    complete_until_bgc(client, auth, u)
    client.post('/api/driver/onboarding/background-check/consent', json={'signature_name': 'Amara Okafor'}, headers=auth(u))
    r = client.post('/api/driver/onboarding/background-check/pay', json={'pay_later': True}, headers=auth(u))
    assert body(r)['code'] == 1 and 'checkout_url' not in body(r)['data']
    db.session.rollback()
    b = O.latest_bgc(u.id)
    assert b.paid_by == 'earnings' and b.deduction_status == 'pending' and b.status == 'initiated'
    assert O.outstanding_deduction_cents(u.id) == 3999
    assert O.settle_bgc_deductions(u.id) == 0      # wallet empty
    from backend.services import wallet_service as W
    W.credit(u.id, W.cents_to_dollars(5000), 'bonus', f'test-{uuid.uuid4().hex}', 'test credit')
    db.session.commit()
    assert O.settle_bgc_deductions(u.id) == 1
    db.session.rollback()
    assert O.latest_bgc(u.id).deduction_status == 'settled' and float(W.balance_of(u.id)) == pytest.approx(10.01)


def test_document_expiry_reminders_and_block_online(client, auth, make_user):
    driver = make_user('driver')
    app = O.get_application(driver)
    doc = DriverDocument(application_id=app.id, user_id=driver.id, type='insurance', file_path='driver-docs/x/ins.png',
                         status='approved', expires_at=date.today() + timedelta(days=10), reminders_sent=[],
                         created_at=datetime.utcnow())
    db.session.add(doc)
    db.session.commit()
    from backend.services import onboarding_jobs
    assert onboarding_jobs.document_expiry_check()['reminded'] >= 1
    onboarding_jobs.document_expiry_check()
    db.session.rollback()
    n = Notification.query.filter_by(user_id=driver.id, event_key='document.expiring').all()
    assert len(n) == 1 and '10 days' in n[0].body
    assert sorted(db.session.get(DriverDocument, doc.id).reminders_sent) == [14, 30]
    ok = client.post('/api/go-on-off', json={'latitude': 43.65, 'longitude': -79.38, 'status': 'online'}, headers=auth(driver))
    assert body(ok)['code'] == 1

    d = db.session.get(DriverDocument, doc.id)
    d.expires_at = date.today() + timedelta(days=2)
    db.session.commit()
    onboarding_jobs.document_expiry_check()
    d.expires_at = date.today() - timedelta(days=1)
    db.session.commit()
    onboarding_jobs.document_expiry_check()
    db.session.rollback()
    assert Notification.query.filter_by(user_id=driver.id, event_key='document.expiring').count() == 2
    assert db.session.get(DriverDocument, doc.id).status == 'expired'
    assert Notification.query.filter_by(user_id=driver.id, event_key='document.expired').count() == 1
    assert db.session.get(AdminUser, driver.id).ready_for_trip == 'No'
    r = client.post('/api/go-on-off', json={'latitude': 43.65, 'longitude': -79.38, 'status': 'online'}, headers=auth(driver))
    assert body(r)['code'] == 0 and 'insurance' in body(r)['message']


def test_legacy_become_driver_creates_application(client, auth, make_user):
    u = make_user('customer')
    r = client.post('/api/become-driver', data={'first_name': 'Leg', 'last_name': 'Acy', 'driving_license_number': 'L-1',
                                                'is_car': 'Yes', 'automobile': 'Honda Civic'}, headers=auth(u))
    assert body(r)['code'] == 1
    app = DriverApplication.query.filter_by(user_id=u.id).one()
    assert app.status == 'submitted' and app.licence_number == 'L-1' and app.service_types == ['car_hire']


def test_admin_roles_and_funnel(client, auth, make_user):
    u = make_user('customer')
    O.get_application(u)
    db.session.commit()
    app = DriverApplication.query.filter_by(user_id=u.id).one()
    finance = make_user('customer', admin_roles='finance')
    ops = make_user('customer', admin_roles='ops')
    assert client.get('/api/admin/onboarding/applications', headers=auth(finance)).status_code == 403
    r = client.get('/api/admin/onboarding/applications?status=in_progress', headers=auth(ops))
    assert body(r)['code'] == 1 and any(i['id'] == app.id for i in body(r)['data']['data'])
    r = client.post(f'/api/admin/onboarding/applications/{app.id}/decision', json={'decision': 'needs_changes'},
                    headers=auth(ops))
    assert body(r)['data']['error_code'] == 'reason_required'
    r = client.post(f'/api/admin/onboarding/applications/{app.id}/decision',
                    json={'decision': 'needs_changes', 'reason': 'Please upload a clearer licence photo.'}, headers=auth(ops))
    assert body(r)['data']['application']['status'] == 'needs_changes'
    assert Notification.query.filter_by(user_id=u.id, event_key='onboarding.needs_changes').count() == 1
    f = body(client.get('/api/admin/onboarding/funnel', headers=auth(ops)))['data']
    assert f['total_applications'] >= 1 and [s['step'] for s in f['steps']][0] == 'account_created'


def test_document_validation(client, auth, make_user):
    u = make_user('customer')
    r = client.post('/api/driver/onboarding/documents', data={'type': 'licence_front', 'file': (io.BytesIO(PNG), 'a.png', 'image/png')},
                    headers=auth(u), content_type='multipart/form-data')
    assert body(r)['data']['error_code'] == 'expiry_required'
    r = client.post('/api/driver/onboarding/documents', data={'type': 'selfie', 'file': (io.BytesIO(b'MZ'), 'a.exe', 'application/x-msdownload')},
                    headers=auth(u), content_type='multipart/form-data')
    assert body(r)['data']['error_code'] == 'invalid_file_type'
    r = client.post('/api/driver/onboarding/documents', data={'type': 'passport', 'file': (io.BytesIO(PNG), 'a.png', 'image/png')},
                    headers=auth(u), content_type='multipart/form-data')
    assert body(r)['data']['error_code'] == 'invalid_type'
    r = client.post('/api/driver/onboarding/profile', json={'postal_code': '12345', 'province': 'XX'}, headers=auth(u))
    assert body(r)['data']['error_code'] == 'validation_failed' and set(body(r)['data']['fields']) == {'postal_code', 'province'}
