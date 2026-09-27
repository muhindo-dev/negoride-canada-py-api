"""Driver onboarding wizard API (spec §14) + Certn webhook (§14.2).

All driver endpoints require a JWT (any user may apply). Responses use the
standard envelope; validation errors carry data.error_code (+ data.fields /
data.blockers).
"""
import json
from datetime import datetime

from flask import Blueprint, request

from backend import jobs
from backend.models import db
from backend.models.platform import WebhookEvent
from backend.services import certn_client as CC
from backend.services import onboarding_service as O
from backend.utils.auth import jwt_required_with_user
from backend.utils.client_info import app_version, client_ip, user_agent
from backend.utils.idempotency import idempotent
from backend.utils.response import error_response, success_response

onboarding_bp = Blueprint('onboarding', __name__)


def _body():
    return request.get_json(silent=True) or request.form or {}


def _lang(user):
    return (request.args.get('lang') or user.preferred_language or 'en')[:2]


def _err(e):
    return error_response(e.message, data={**e.data, 'error_code': e.code}, status_code=e.status)


def _ok(message, user, extra=None, status_code=200):
    db.session.commit()
    data = O.overview(user, _lang(user))
    db.session.commit()
    if extra:
        data.update(extra)
    return success_response(message, data, status_code=status_code)


@onboarding_bp.route('/api/driver/onboarding', methods=['GET'])
@jwt_required_with_user
def overview(user):
    data = O.overview(user, _lang(user))
    db.session.commit()
    return success_response('Driver onboarding', data)


@onboarding_bp.route('/api/driver/onboarding/prequal', methods=['POST'])
@jwt_required_with_user
def prequal(user):
    try:
        res = O.prequal(user, _body())
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e)
    return _ok('You’re eligible — let’s continue.' if res['passed']
               else 'Sorry — you don’t meet the requirements yet.', user, {'prequal': res})


@onboarding_bp.route('/api/driver/onboarding/profile', methods=['POST', 'PUT'])
@jwt_required_with_user
def profile(user):
    try:
        O.save_profile(user, _body())
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e)
    return _ok('Details saved.', user)


@onboarding_bp.route('/api/driver/onboarding/agreements', methods=['POST'])
@jwt_required_with_user
def agreements(user):
    d = _body()
    try:
        rows = O.sign_agreements(user, d.get('signature_name'), app_version(d), client_ip(), user_agent())
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e)
    return _ok('Driver Agreement and Safety Policy signed.', user, {'accepted': [r.to_dict() for r in rows]})


@onboarding_bp.route('/api/driver/onboarding/documents', methods=['GET'])
@jwt_required_with_user
def documents(user):
    app = O.get_application(user)
    db.session.commit()
    return success_response('Documents', {'items': [O.document_public(d) for d in O.latest_documents(app).values()],
                                          'requirements': O.requirements()['required_documents']})


@onboarding_bp.route('/api/driver/onboarding/documents', methods=['POST'])
@jwt_required_with_user
def upload(user):
    f = request.files.get('file') or request.files.get('document') or request.files.get('photo')
    try:
        doc = O.upload_document(user, (request.form.get('type') or '').strip(), f, request.form.get('expires_at'))
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e)
    return _ok('Document uploaded — we’ll review it shortly.', user, {'document': O.document_public(doc)},
               status_code=201)


@onboarding_bp.route('/api/driver/onboarding/background-check', methods=['GET'])
@jwt_required_with_user
def bgc_get(user):
    b = O.latest_bgc(user.id)
    return success_response('Background check', {'background_check': O.bgc_public(b),
                                                  'fee_cents': O.requirements()['bgc_fee_cents'],
                                                  'pay_later_available': O.requirements()['bgc_pay_later_available']})


@onboarding_bp.route('/api/driver/onboarding/background-check/consent', methods=['POST'])
@jwt_required_with_user
def bgc_consent(user):
    d = _body()
    if d.get('consent') is False or str(d.get('consent')).lower() == 'false':
        return error_response('You must consent to the background check to continue.',
                              data={'error_code': 'consent_required'})
    try:
        b = O.bgc_consent(user, d.get('signature_name'), app_version(d), client_ip(), user_agent())
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e)
    return _ok('Consent recorded.', user, {'background_check': O.bgc_public(b)})


@onboarding_bp.route('/api/driver/onboarding/background-check/pay', methods=['POST'])
@jwt_required_with_user
@idempotent
def bgc_pay(user):
    d = _body()
    pay_later = d.get('pay_later') in (True, 'true', '1', 1)
    try:
        b, rp = O.bgc_pay(user, pay_later=pay_later)
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e)
    extra = {'background_check': O.bgc_public(b), 'pay_later': pay_later}
    if rp is not None:
        extra.update({'checkout_url': rp.checkout_url, 'ride_payment_id': rp.id, 'amount_cents': b.fee_cents})
    return _ok('The fee will be deducted from your first earnings.' if pay_later
               else 'Complete the payment to start your check.', user, extra)


@onboarding_bp.route('/api/driver/onboarding/background-check/sync', methods=['POST'])
@jwt_required_with_user
def bgc_sync(user):
    b = O.bgc_sync(user)
    return _ok('Background check status', user, {'background_check': O.bgc_public(b)})


@onboarding_bp.route('/api/driver/onboarding/submit', methods=['POST'])
@jwt_required_with_user
@idempotent
def submit(user):
    try:
        O.submit(user)
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e)
    return _ok('Application submitted — we’ll review it within 2 business days.', user)


@onboarding_bp.route('/api/driver/onboarding/orientation', methods=['GET'])
@jwt_required_with_user
def orientation_get(user):
    return success_response('Safety orientation', O.orientation_content(_lang(user)))


@onboarding_bp.route('/api/driver/onboarding/orientation', methods=['POST'])
@jwt_required_with_user
def orientation_post(user):
    try:
        res = O.complete_orientation(user, _body().get('answers'))
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e)
    return _ok('Orientation complete — you’re ready to drive!' if res['passed']
               else 'Not quite — review the cards and try again.', user, {'orientation_result': res})


@onboarding_bp.route('/api/driver/onboarding/referral', methods=['POST'])
@jwt_required_with_user
def referral(user):
    try:
        O.apply_referral(user, _body().get('code'))
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e)
    return _ok('Referral code applied.', user)


# ── Certn webhook ───────────────────────────────────────────────────────────

@onboarding_bp.route('/api/webhooks/certn', methods=['GET'])
def certn_challenge():
    """CertnCentric endpoint verification: echo ?challenge= as text/plain."""
    from flask import Response
    return Response(request.args.get('challenge', ''), status=200, mimetype='text/plain',
                    headers={'X-Content-Type-Options': 'nosniff'})


@onboarding_bp.route('/api/webhooks/certn', methods=['POST'])
def certn_webhook():
    raw = request.get_data()
    if not CC.webhook_secret():
        return error_response('Certn webhook secret not configured.', status_code=503)
    if not CC.verify_signature(raw, request.headers.get('X-Signature', '')):
        return error_response('Invalid signature', status_code=403)
    try:
        ev = json.loads(raw or b'{}')
    except ValueError:
        return error_response('Invalid JSON')
    event_id = str(ev.get('event_id') or '')
    if not event_id:
        return error_response('Missing event_id')
    if WebhookEvent.query.filter_by(provider='certn', event_id=event_id).first():
        return {'success': True, 'duplicate': True}, 200
    row = WebhookEvent(provider='certn', event_id=event_id, event_type=ev.get('event_type'),
                       payload=raw.decode('utf-8', 'replace'), signature_valid=True, status='received',
                       received_at=datetime.utcnow())
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return {'success': True, 'duplicate': True}, 200
    try:
        jobs.enqueue('backend.services.onboarding_service.process_certn_event', row.id)
    except Exception:
        pass   # stored; platform_jobs.retry_failed_webhooks picks it up
    return {'success': True}, 200
