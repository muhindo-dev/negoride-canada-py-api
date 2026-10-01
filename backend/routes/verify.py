"""Phone verification API (spec §11) + Twilio inbound SMS webhook (STOP/HELP, §11.2 #13).

POST /api/verify/phone/start   {phone, purpose, channel?, step_up_ticket?, locale?, app_hash?}
                               app_hash = Android SMS Retriever hash (11 chars); falls back to
                               TWILIO_ANDROID_APP_HASH; forwarded to Twilio Verify as AppHash (SMS only)
POST /api/verify/phone/check   {phone, purpose, code, step_up_ticket?}
POST /api/webhooks/twilio/inbound   (Twilio, X-Twilio-Signature)

Auth is optional on start/check; it is required for change_phone,
driver_onboarding and sensitive_action. When an authenticated user checks a
`driver_onboarding` or `signup` code, the number is applied to the account at
once (`data.applied = true`) and no further call is needed.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime

from flask import Blueprint, Response, request
from sqlalchemy.exc import IntegrityError

from backend import jobs
from backend.models import db
from backend.models.platform import WebhookEvent
from backend.models.user import AdminUser
from backend.services import phone_verification as PV
from backend.utils import phone as P
from backend.utils.auth import get_current_user
from backend.utils.client_info import client_ip, device_id
from backend.utils.response import error_response, success_response

log = logging.getLogger('negoride.verify')
verify_bp = Blueprint('verify', __name__)

AUTO_APPLY = ('driver_onboarding', 'signup')


def _body():
    return request.get_json(silent=True) or request.form or {}


def _err(e):
    return error_response(e.message, data=e.payload(), status_code=e.status)


def _optional_user():
    if not request.headers.get('Authorization'):
        return None
    user = get_current_user()
    if user and user.deleted_at is None:
        return user
    return None


def start_response(data, user):
    try:
        res = PV.start(data.get('phone') or data.get('phone_number'), data.get('purpose') or 'signup',
                       data.get('channel') or 'sms', user=user, step_up_ticket=data.get('step_up_ticket'),
                       device_id=device_id(data), ip=client_ip(),
                       locale=(data.get('locale') or (user.preferred_language if user else None) or None),
                       app_hash=data.get('app_hash') or request.headers.get('X-App-Hash'))
    except PV.VerifyError as e:
        return _err(e)
    msg = {'call': 'We are calling you with your code.', 'whatsapp': 'We sent your code on WhatsApp.'}.get(
        res['channel'], f"We sent a code to {res['phone_masked']}.")
    return success_response(msg, res)


def check_response(data, user):
    try:
        res = PV.check(data.get('phone') or data.get('phone_number'), data.get('purpose') or 'signup',
                       data.get('code') or data.get('otp'), user=user, step_up_ticket=data.get('step_up_ticket'))
    except PV.VerifyError as e:
        return _err(e)
    res['applied'] = False
    if user and res['purpose'] in AUTO_APPLY:
        try:
            row = PV.consume(res['verification_token'], res['purpose'], user=user)
            if PV.find_verified_owner(row.phone, exclude_id=user.id):
                db.session.rollback()
                return error_response('This phone number is already used by another account.',
                                      data={'error_code': 'phone_in_use'}, status_code=409)
            PV.apply_to_user(user, row, set_legacy_phone=not user.phone_number or res['purpose'] == 'signup')
            from backend.services.audit import audit
            audit('user.phone_verified', user, 'user', user.id, after={'phone': row.phone, 'purpose': row.purpose},
                  actor_type='user')
            from backend.services import onboarding_service
            onboarding_service.queue_progress_refresh(user.id)
            try:
                db.session.commit()
            except IntegrityError as exc:
                db.session.rollback()
                if PV.is_verified_phone_conflict(exc):
                    return PV.phone_in_use_response()
                raise
            res['applied'] = True
            res['verification_token'] = None
            res['user'] = user.to_dict()
        except PV.VerifyError as e:
            db.session.rollback()
            return _err(e)
    return success_response('Phone number verified.', res)


@verify_bp.route('/api/verify/phone/start', methods=['POST'])
def verify_start():
    return start_response(_body(), _optional_user())


@verify_bp.route('/api/verify/phone/check', methods=['POST'])
def verify_check():
    return check_response(_body(), _optional_user())


# ── Twilio inbound SMS (STOP / HELP / START) ────────────────────────────────

STOP_WORDS = {'STOP', 'STOPALL', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT', 'ARRET', 'ARRÊT'}
START_WORDS = {'START', 'UNSTOP', 'YES', 'SUBSCRIBE'}
HELP_WORDS = {'HELP', 'INFO', 'AIDE'}


def twilio_signature(url, params, token):
    s = url + ''.join(f'{k}{v}' for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(token.encode(), s.encode(), hashlib.sha1).digest()).decode()


def _twiml(message=None):
    body = '<?xml version="1.0" encoding="UTF-8"?><Response>'
    if message:
        from xml.sax.saxutils import escape
        body += f'<Message>{escape(message)}</Message>'
    body += '</Response>'
    return Response(body, status=200, mimetype='application/xml')


@verify_bp.route('/api/webhooks/twilio/inbound', methods=['POST'])
def twilio_inbound():
    token = os.getenv('TWILIO_AUTH_TOKEN', '')
    if not token:
        return error_response('Twilio is not configured.', status_code=503)
    params = request.form.to_dict()
    url = os.getenv('TWILIO_INBOUND_URL') or request.url
    if not hmac.compare_digest(twilio_signature(url, params, token), request.headers.get('X-Twilio-Signature', '')):
        return error_response('Invalid signature', status_code=403)
    sid = params.get('MessageSid') or params.get('SmsSid') or ''
    if not sid:
        return error_response('Missing MessageSid')
    if not WebhookEvent.query.filter_by(provider='twilio', event_id=sid).first():
        row = WebhookEvent(provider='twilio', event_id=sid, event_type='sms.inbound', payload=json.dumps(params),
                           signature_valid=True, status='received', received_at=datetime.utcnow())
        db.session.add(row)
        try:
            db.session.commit()
            jobs.enqueue(process_twilio_inbound, row.id)
        except Exception:
            db.session.rollback()
    word = (params.get('Body') or '').strip().split(' ')[0].upper() if params.get('Body') else ''
    if word in HELP_WORDS:
        from backend.services import settings_service as S
        return _twiml(f"NegoRide Canada: ride updates & security codes. Help: {S.get('safety.support_email')}. "
                      "Msg&data rates may apply. Reply STOP to opt out. / Aide : répondez STOP pour vous désabonner.")
    return _twiml()   # Twilio Advanced Opt-Out sends the STOP/START confirmations itself


def process_twilio_inbound(webhook_event_id):
    """Job: record STOP / START against the user (sms_opt_out_at, marketing opt-in)."""
    row = db.session.get(WebhookEvent, webhook_event_id)
    if not row or row.status == 'processed':
        return
    row.attempts = (row.attempts or 0) + 1
    params = json.loads(row.payload or '{}')
    word = (params.get('Body') or '').strip().split(' ')[0].upper() if params.get('Body') else ''
    frm = P.safe_normalize(params.get('From'))
    if frm and (word in STOP_WORDS or word in START_WORDS):
        users = AdminUser.query.filter((AdminUser.phone_e164 == frm) | (AdminUser.phone_number == frm)).all()
        from backend.services.audit import audit
        for u in users:
            if word in STOP_WORDS:
                u.sms_opt_out_at = datetime.utcnow()
                if u.marketing_opt_in:
                    from backend.services import legal_service
                    legal_service.record_marketing_consent(u, False, 'sms_stop', channels='sms,email')
                u.marketing_opt_in = False
            else:
                u.sms_opt_out_at = None
            audit('user.sms_' + ('opt_out' if word in STOP_WORDS else 'opt_in'), None, 'user', u.id,
                  meta={'keyword': word, 'message_sid': row.event_id})
    row.status, row.processed_at = 'processed', datetime.utcnow()
    db.session.commit()
