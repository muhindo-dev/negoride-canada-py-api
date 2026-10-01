"""Driver onboarding hardening (audit follow-up to spec §14): cancel/refund window, fee
receipt, failed re-check, per-check consent evidence, renewal, pay-later recovery, reject
cleanup, insurance endorsement, face match, funnel progress, payout idempotency."""
import io
import uuid
from datetime import datetime, timedelta

import pytest

from backend import jobs
from backend.models import db
from backend.models.identity import BackgroundCheck, DriverApplication, DriverDocument
from backend.models.money import Refund, RidePayment
from backend.models.user import AdminUser
from backend.services import face_match
from backend.services import onboarding_service as O
from backend.services import wallet_service as W
from backend.services.notify import email_provider
from tests.conftest import body
from tests.identity_utils import setting, v4
from tests.test_onboarding import (PNG, PROFILE, _isolated, applicant, certn, complete_until_bgc,  # noqa: F401
                                   pay_bgc, upload)

INITIATE = 'backend.services.onboarding_service.initiate_background_check'


def _drop_deferred(path=INITIATE):
    jobs.DEFERRED[:] = [d for d in jobs.DEFERRED if d[1] != path]


def _prequal_ok(u):
    app = O.get_application(u)
    app.prequal = {'passed': True, 'reasons': [], 'at': '2026-09-28T00:00:00Z'}
    app.province = 'ON'
    db.session.commit()
    return app


# (a) + (b) — delayed Certn start, cancel + refund, fee receipt ─────────────

def test_cancel_before_submission_refunds_and_receipt_is_emailed(client, auth, make_user, sign_stripe, monkeypatch):
    setting(monkeypatch, 'onboarding.bgc_start_delay_min', 30)
    email_provider.OUTBOX.clear()
    u = applicant(make_user, client, auth)
    _prequal_ok(u)
    b = pay_bgc(client, auth, sign_stripe, u)
    try:
        assert b.status == 'paid' and b.provider_application_id is None
        assert b.start_after > datetime.utcnow() + timedelta(minutes=25)
        assert any(d[1] == INITIATE and d[0] == 1800 for d in jobs.DEFERRED)
        assert O.initiate_background_check(b.id) is None          # still inside the cancel window
        receipt = [m for m in email_provider.OUTBOX if m['to'] == u.email and m['tag'] == 'bgc-receipt']
        assert receipt and 'BGC-' in receipt[0]['html'] and '$39.99' in receipt[0]['html']
        db.session.rollback()
        assert O.latest_bgc(u.id).receipt_emailed_at is not None
        assert O.send_bgc_receipt(b.id) is None                    # idempotent

        ov = body(client.get('/api/driver/onboarding', headers=auth(u)))['data']
        assert ov['requirements']['bgc_start_delay_min'] == 30
        r = client.post('/api/driver/onboarding/background-check/cancel', json={'reason': 'Changed my mind'},
                        headers=auth(u, **{'Idempotency-Key': uuid.uuid4().hex}))
        assert body(r)['code'] == 1 and body(r)['data']['refunded_cents'] == 3999, body(r)
        db.session.rollback()
        b = db.session.get(BackgroundCheck, b.id)
        assert b.status == 'cancelled' and b.refunded_cents == 3999 and b.cancelled_at
        rp = db.session.get(RidePayment, b.fee_payment_id)
        assert rp.amount_refunded_cents == 3999
        assert Refund.query.filter_by(idempotency_key=f'bgc-{b.id}-cancel-refund').one().amount_cents == 3999
        r = client.post('/api/driver/onboarding/background-check/cancel', json={}, headers=auth(u))
        assert r.status_code == 409 and body(r)['data']['error_code'] == 'nothing_to_cancel'
        assert O.initiate_background_check(b.id) is None
    finally:
        _drop_deferred()


def test_cannot_cancel_after_submission_to_certn(client, auth, make_user, sign_stripe, monkeypatch, certn):
    setting(monkeypatch, 'onboarding.bgc_start_delay_min', 30)
    u = applicant(make_user, client, auth)
    _prequal_ok(u)
    b = pay_bgc(client, auth, sign_stripe, u)
    _drop_deferred()
    assert O.poll_pending()['started'] == 0          # the poll respects the window too
    b.start_after = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert O.poll_pending()['started'] >= 1
    db.session.rollback()
    assert O.latest_bgc(u.id).status == 'initiated'
    r = client.post('/api/driver/onboarding/background-check/cancel', json={}, headers=auth(u))
    assert r.status_code == 409 and body(r)['data']['error_code'] == 'nothing_to_cancel'


# (c) failed background check of an approved driver → pending_review ────────

def test_failed_recheck_puts_approved_driver_in_review(make_user):
    admin, drv = make_user('admin'), make_user('driver')
    app = DriverApplication(user_id=drv.id, status='approved', current_step='orientation', steps={},
                            referral_code='NR' + uuid.uuid4().hex[:6].upper(), service_types=['car_hire'])
    db.session.add(app)
    db.session.flush()
    b = BackgroundCheck(user_id=drv.id, application_id=app.id, status='initiated', provider_application_id='case-x',
                        fee_cents=3999, paid_by='driver')
    db.session.add(b)
    db.session.commit()
    O.adjudicate(b, admin, 'failed', 'Record found on re-screening')
    db.session.commit()
    db.session.rollback()
    drv = db.session.get(AdminUser, drv.id)
    assert drv.account_status == 'pending_review' and drv.status_reason_code == 'failed_background_check'
    assert db.session.get(DriverApplication, app.id).status == 'approved'
    assert drv.ready_for_trip == 'No'


# (d) + (e) re-check consent evidence and renewal_due ──────────────────────

def test_recheck_records_new_consent_evidence_and_renewal_due(client, auth, make_user):
    u = applicant(make_user, client, auth)
    _prequal_ok(u)
    r = client.post('/api/driver/onboarding/background-check/consent', json={'signature_name': 'Amara Okafor'},
                    headers=auth(u, **v4(ip='10.20.30.40')))
    b1 = body(r)['data']['background_check']
    first = db.session.get(BackgroundCheck, b1['id'])
    assert first.consent_evidence['ip'] == '10.20.30.40' and first.consent_evidence['acceptance_reused'] is False
    assert first.consent_evidence['background_check_id'] == first.id and first.consent_evidence['signature_name']
    first.status, first.expires_at = 'clear', datetime.utcnow() + timedelta(days=10)
    db.session.commit()
    ov = body(client.get('/api/driver/onboarding', headers=auth(u)))['data']
    assert ov['renewal_due'] is True
    r = client.post('/api/driver/onboarding/background-check/consent', json={'signature_name': 'Amara N. Okafor'},
                    headers=auth(u, **v4(ip='10.20.30.41')))
    b2 = db.session.get(BackgroundCheck, body(r)['data']['background_check']['id'])
    assert b2.id != first.id and b2.status == 'awaiting_payment'
    ev = b2.consent_evidence
    assert ev['acceptance_reused'] is True and ev['is_recheck'] is True and ev['ip'] == '10.20.30.41'
    assert ev['signature_name'] == 'Amara N. Okafor' and ev['background_check_id'] == b2.id


# (f) + (k) pay-later partial recovery, payout gate + idempotency ──────────

def test_pay_later_partial_recovery_and_payout_gate(client, auth, make_user, monkeypatch):
    from backend.models.payout_account import PayoutAccount
    from backend.models.payout_request import PayoutRequest
    setting(monkeypatch, 'ff.bgc_pay_later', True)
    u = applicant(make_user, client, auth)
    _prequal_ok(u)
    client.post('/api/driver/onboarding/background-check/consent', json={'signature_name': 'Amara Okafor'},
                headers=auth(u))
    assert body(client.post('/api/driver/onboarding/background-check/pay', json={'pay_later': True},
                            headers=auth(u)))['code'] == 1
    acct = PayoutAccount(user_id=u.id, status='active', payouts_enabled=True, minimum_payout_amount=10)
    db.session.add(acct)
    db.session.commit()
    try:
        W.credit(u.id, W.cents_to_dollars(1000), 'bonus', f'test-{uuid.uuid4().hex}', 'test credit')
        db.session.commit()
        assert O.settle_bgc_deductions(u.id) == 0
        db.session.rollback()
        b = O.latest_bgc(u.id)
        assert b.deducted_cents == 1000 and b.deduction_status == 'pending'
        assert O.outstanding_deduction_cents(u.id) == 2999 and float(W.balance_of(u.id)) == 0.0
        r = client.post('/api/payout-requests', json={'amount': 5}, headers=auth(u))
        assert r.status_code == 409 and body(r)['data']['error_code'] == 'bgc_fee_outstanding'
        assert body(r)['data']['outstanding_cents'] == 2999

        W.credit(u.id, W.cents_to_dollars(5000), 'bonus', f'test-{uuid.uuid4().hex}', 'test credit')
        db.session.commit()
        key = {'Idempotency-Key': uuid.uuid4().hex}
        r1 = client.post('/api/payout-requests', json={'amount': 15}, headers=auth(u, **key))
        r2 = client.post('/api/payout-requests', json={'amount': 15}, headers=auth(u, **key))
        assert r1.status_code == 201 and body(r2)['data']['id'] == body(r1)['data']['id']
        db.session.rollback()
        assert PayoutRequest.query.filter_by(user_id=u.id).count() == 1
        assert O.latest_bgc(u.id).deduction_status == 'settled' and O.latest_bgc(u.id).deducted_cents == 3999
        assert float(W.balance_of(u.id)) == pytest.approx(50.00 - 29.99 - 15.00)
    finally:
        db.session.rollback()
        PayoutRequest.query.filter_by(user_id=u.id).delete(synchronize_session=False)
        PayoutAccount.query.filter_by(user_id=u.id).delete(synchronize_session=False)
        db.session.commit()


# (g) rejecting clears the applied flags ────────────────────────────────────

def test_reject_clears_applied_service_flags(client, auth, make_user):
    admin = make_user('admin')
    u = make_user('customer', user_type='Pending Driver', is_car='Yes', is_delivery='Yes')
    app = DriverApplication(user_id=u.id, status='submitted', current_step='review', steps={},
                            referral_code='NR' + uuid.uuid4().hex[:6].upper(), service_types=['car_hire', 'courier'])
    db.session.add(app)
    db.session.commit()
    r = client.post(f'/api/admin/onboarding/applications/{app.id}/decision',
                    json={'decision': 'reject', 'reason': 'Licence class not accepted'}, headers=auth(admin))
    assert body(r)['code'] == 1, body(r)
    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    assert u.is_car == 'No' and u.is_delivery == 'No' and u.user_type == 'Customer'
    hist = body(client.get(f'/api/admin/users/{u.id}/history', headers=auth(admin)))['data']['data']
    assert any(h['entity_type'] == 'driver_application' and h['action'] == 'onboarding.application_reject' for h in hist)


# (h) insurance rideshare endorsement ───────────────────────────────────────

def test_insurance_requires_endorsement_attestation_in_listed_provinces(client, auth, make_user):
    u = applicant(make_user, client, auth)
    client.post('/api/driver/onboarding/profile', json=PROFILE, headers=auth(u))       # province ON
    exp = (datetime.utcnow() + timedelta(days=300)).date().isoformat()
    data = {'type': 'insurance', 'expires_at': exp, 'file': (io.BytesIO(PNG), 'ins.png', 'image/png')}
    r = client.post('/api/driver/onboarding/documents', data=data, headers=auth(u), content_type='multipart/form-data')
    assert r.status_code == 422 and body(r)['data']['error_code'] == 'endorsement_attestation_required'
    assert body(r)['data']['province'] == 'ON'
    r = upload(client, auth, u, 'insurance', exp)        # helper attests
    doc = body(r)['data']['document']
    assert r.status_code == 201 and doc['meta']['attestation_rideshare_endorsement'] is True
    assert doc['meta']['province'] == 'ON' and body(r)['data']['insurance_endorsement_required'] is True
    # a province without the requirement
    app = O.get_application(u)
    app.province = 'MB'
    db.session.commit()
    data = {'type': 'insurance', 'expires_at': exp, 'file': (io.BytesIO(PNG), 'ins.png', 'image/png')}
    r = client.post('/api/driver/onboarding/documents', data=data, headers=auth(u), content_type='multipart/form-data')
    assert r.status_code == 201 and body(r)['data']['document']['meta']['endorsement_required'] is False


# (i) face match ───────────────────────────────────────────────────────────

class _FakeFaces:
    name = 'fake'

    def __init__(self, score):
        self.score, self.calls = score, 0

    def compare(self, src, tgt):
        self.calls += 1
        return self.score, 'fake compare'


def test_face_match_runs_when_selfie_and_licence_exist(client, auth, make_user, monkeypatch):
    admin = make_user('admin')
    fake = _FakeFaces(97.4)
    face_match.set_provider(fake)
    try:
        u = applicant(make_user, client, auth)
        exp = (datetime.utcnow() + timedelta(days=300)).date().isoformat()
        upload(client, auth, u, 'selfie')
        assert fake.calls == 0                       # no licence yet
        upload(client, auth, u, 'licence_front', exp)
        assert fake.calls == 1
        db.session.rollback()
        app = O.get_application(u, create=False)
        selfie = O.latest_documents(app)['selfie']
        assert selfie.face_match_status == 'match' and float(selfie.face_match_score) == 97.4
        assert selfie.status == 'pending'            # never auto-approved
        d = body(client.get(f'/api/admin/onboarding/applications/{app.id}', headers=auth(admin)))['data']
        assert d['face_match']['status'] == 'match' and d['face_match']['score'] == 97.4
        assert d['face_match']['advisory_only'] is True
        # low similarity → no_match; no provider → manual_review
        fake.score = 41.0
        upload(client, auth, u, 'selfie')
        db.session.rollback()
        assert O.latest_documents(app)['selfie'].face_match_status == 'no_match'
        face_match.set_provider(None)
        monkeypatch.delenv('AWS_REKOGNITION_REGION', raising=False)
        upload(client, auth, u, 'selfie')
        db.session.rollback()
        assert O.latest_documents(app)['selfie'].face_match_status == 'manual_review'
    finally:
        face_match.set_provider(None)


# (j) funnel progress recorded outside the wizard ───────────────────────────

def test_funnel_progress_recorded_when_email_is_verified(client, make_user):
    u = make_user('customer', email_verified_at=None,
                  email_verification_token=f'tok{uuid.uuid4().hex}', verification_token_expires=datetime.utcnow() + timedelta(hours=2))
    O.get_application(u)
    db.session.commit()
    r = client.post('/api/email/verify', json={'token': u.email_verification_token, 'email': u.email})
    assert body(r)['code'] == 1
    db.session.rollback()
    app = DriverApplication.query.filter_by(user_id=u.id).one()
    assert (app.steps or {}).get('email_verified', {}).get('done_at')


def test_admin_notified_services_from_settings_and_local_suspension_time(client, auth, make_user, monkeypatch):
    from backend.services import account_service as A
    from backend.services import realtime
    from backend.services import settings_service as S
    admin, drv = make_user('admin'), make_user('driver', timezone='America/Vancouver')
    b = BackgroundCheck(user_id=drv.id, status='initiated', provider_application_id='case-y', fee_cents=0,
                        paid_by='platform')
    db.session.add(b)
    db.session.commit()
    realtime.SENT.clear()
    O.adjudicate(b, admin, 'failed', 'Record found')
    db.session.commit()
    assert any(ev == 'onboarding.bgc_failed' and d.get('check_id') == b.id for ev, d, _room in realtime.SENT)
    # onboarding offers only the enabled service types
    setting(monkeypatch, 'services.enabled', 'car_hire,courier')
    assert O.requirements()['service_types'] == S.enabled_services() == ['car_hire', 'courier']
    # suspension end shown in the user's time zone, not UTC
    ctx = A.message_context(drv, 'suspended', 'harassment', None, datetime(2026, 10, 2, 1, 0))
    assert ctx['until'] == '2026-10-01 18:00 PDT'
