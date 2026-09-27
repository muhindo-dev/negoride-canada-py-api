"""Phone verification through Twilio Verify (spec §11).

    start(phone, purpose, channel, user=…)  → sends a code (SMS / voice / WhatsApp)
    check(phone, purpose, code, user=…)     → short-lived single-use verification_token
    consume(token, purpose, phone=…)        → the approved PhoneVerification row (marks it used)

Scenarios (§11.2) are expressed as `purpose`:
    signup · login · change_phone · driver_onboarding · new_device ·
    password_reset · sensitive_action

Delivery modes, in order:
  test    number listed in TWILIO_TEST_NUMBERS ("+15555550100:123456,…") and
          FLASK_ENV != production → fixed code, nothing is sent (App Store / QA).
  twilio  TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_VERIFY_SERVICE_SID set.
  dev     Twilio not configured and FLASK_ENV != production → a random code is
          generated, only its SHA-256 is stored and the code is written to the log.
  In production without Twilio, start() fails with 503 `sms_unavailable`.

Only a SHA-256 hash of the verification_token is stored (phone_verifications.token_hash).
"""
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta

from backend.models import db
from backend.models.identity import PhoneVerification
from backend.models.user import AdminUser
from backend.services import settings_service as S
from backend.services import twilio_client
from backend.utils import phone as P

log = logging.getLogger('negoride.verify')

PURPOSES = ('signup', 'login', 'change_phone', 'driver_onboarding', 'new_device',
            'password_reset', 'sensitive_action')
CHANNELS = ('sms', 'call', 'whatsapp')
VOIP_TYPES = ('nonFixedVoip', 'fixedVoip', 'voip', 'nonfixedvoip', 'fixedvoip')
# Purposes whose phone is derived from an already-known account (never from the body).
ACCOUNT_BOUND = ('sensitive_action', 'new_device')
DEV_LOG = []   # dev/test introspection: (phone, purpose, code) for dev-fallback sends


class VerifyError(Exception):
    def __init__(self, message, code, status=400, data=None):
        super().__init__(message)
        self.message, self.code, self.status, self.data = message, code, status, data or {}

    def payload(self):
        d = dict(self.data)
        d['error_code'] = self.code
        return d


def is_production():
    return os.getenv('FLASK_ENV', '').strip().lower() == 'production'


def test_numbers():
    """{e164: code} from TWILIO_TEST_NUMBERS — never honoured in production."""
    if is_production():
        return {}
    out = {}
    for part in (os.getenv('TWILIO_TEST_NUMBERS') or '').split(','):
        if ':' not in part:
            continue
        num, code = part.rsplit(':', 1)
        e164 = P.safe_normalize(num.strip())
        if e164 and code.strip().isdigit():
            out[e164] = code.strip()
    return out


def test_voip_numbers():
    if is_production():
        return set()
    return {P.safe_normalize(n.strip()) for n in (os.getenv('TWILIO_TEST_VOIP_NUMBERS') or '').split(',') if n.strip()}


def verify_configured():
    return twilio_client.is_configured() and bool(os.getenv('TWILIO_VERIFY_SERVICE_SID'))


def _sha(s):
    return hashlib.sha256(str(s).encode()).hexdigest()


def _now():
    return datetime.utcnow()


# ── step-up tickets (new device) ────────────────────────────────────────────

def _serializer():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer
    secret = current_app.config.get('JWT_SECRET_KEY') or current_app.config.get('SECRET_KEY') or 'negoride'
    return URLSafeTimedSerializer(secret, salt='negoride-step-up')


def make_step_up_ticket(user, device_id):
    return _serializer().dumps({'u': int(user.id), 'd': device_id or ''})


def read_step_up_ticket(ticket, max_age=600):
    if not ticket:
        return None, None
    try:
        data = _serializer().loads(ticket, max_age=max_age)
    except Exception:
        return None, None
    user = db.session.get(AdminUser, int(data.get('u', 0)))
    return user, data.get('d') or None


# ── helpers ─────────────────────────────────────────────────────────────────

def find_verified_owner(e164, exclude_id=None):
    q = AdminUser.query.filter(AdminUser.phone_e164 == e164, AdminUser.phone_verified_at.isnot(None),
                               AdminUser.deleted_at.is_(None))
    if exclude_id:
        q = q.filter(AdminUser.id != exclude_id)
    return q.first()


def _normalize(raw):
    try:
        e164 = P.normalize(raw)
    except P.PhoneError as e:
        raise VerifyError(str(e), 'invalid_phone')
    if P.is_premium(e164):
        raise VerifyError('Premium-rate numbers cannot receive verification codes.', 'premium_blocked')
    if not P.is_allowed_country(e164, S.get('otp.allowed_countries')):
        raise VerifyError('Phone verification is available for Canadian and US numbers only.', 'country_not_allowed')
    return e164


def _resolve_phone(phone, purpose, user, step_up_ticket):
    """Returns (e164, account_user). Account-bound purposes ignore the body phone."""
    if purpose == 'new_device':
        u, _dev = read_step_up_ticket(step_up_ticket)
        u = u or user
        if not u:
            raise VerifyError('Your sign-in session expired. Please log in again.', 'step_up_expired', 401)
        if not u.phone_e164 or not u.phone_verified_at:
            raise VerifyError('This account has no verified phone number.', 'no_verified_phone')
        return u.phone_e164, u
    if purpose == 'sensitive_action':
        if not user:
            raise VerifyError('Please log in again.', 'unauthorized', 401)
        if not user.phone_e164 or not user.phone_verified_at:
            raise VerifyError('Add and verify a phone number first.', 'no_verified_phone')
        if phone and P.safe_normalize(phone) not in (None, user.phone_e164):
            raise VerifyError('Use the phone number on your account.', 'phone_mismatch')
        return user.phone_e164, user
    if not phone:
        raise VerifyError('Phone number is required.', 'invalid_phone')
    return _normalize(phone), user


def lookup_line_type(e164, test_mode=False):
    """Twilio Lookup line type, or a test value. None when unknown."""
    if test_mode or e164 in test_numbers():
        return 'nonFixedVoip' if e164 in test_voip_numbers() else 'mobile'
    if not twilio_client.is_configured():
        return 'nonFixedVoip' if e164 in test_voip_numbers() else None
    try:
        return twilio_client.lookup_line_type(e164)
    except Exception as exc:
        log.warning('Lookup failed for %s: %s', P.mask(e164), exc)
        return None


def _rate_limits(e164, ip, purpose):
    hour_ago = _now() - timedelta(hours=1)
    n_phone = PhoneVerification.query.filter(PhoneVerification.phone == e164,
                                             PhoneVerification.created_at >= hour_ago).count()
    if n_phone >= S.get_int('otp.max_sends_per_phone_h'):
        raise VerifyError('Too many codes were requested for this number. Please try again in an hour.',
                          'rate_limited_phone', 429, {'retry_after_s': 3600})
    if ip:
        n_ip = PhoneVerification.query.filter(PhoneVerification.ip == ip,
                                              PhoneVerification.created_at >= hour_ago).count()
        if n_ip >= S.get_int('otp.max_sends_per_ip_h'):
            raise VerifyError('Too many verification attempts from this network. Please try again later.',
                              'rate_limited_ip', 429, {'retry_after_s': 3600})
    last = (PhoneVerification.query.filter_by(phone=e164, purpose=purpose)
            .order_by(PhoneVerification.id.desc()).first())
    cooldown = S.get_int('otp.resend_after_s')
    if cooldown > 0 and last and last.created_at and (_now() - last.created_at).total_seconds() < cooldown:
        wait = min(cooldown, int(cooldown - (_now() - last.created_at).total_seconds()) + 1)
        raise VerifyError(f'Please wait {wait} seconds before requesting a new code.', 'resend_too_soon', 429,
                          {'retry_after_s': wait})


def _sms_sends(e164, purpose):
    since = _now() - timedelta(hours=1)
    return PhoneVerification.query.filter(PhoneVerification.phone == e164, PhoneVerification.purpose == purpose,
                                          PhoneVerification.channel == 'sms',
                                          PhoneVerification.created_at >= since).count()


# ── start ───────────────────────────────────────────────────────────────────

def start(phone, purpose, channel='sms', user=None, step_up_ticket=None, device_id=None, ip=None, locale=None):
    purpose = (purpose or '').strip().lower()
    channel = (channel or 'sms').strip().lower()
    if purpose not in PURPOSES:
        raise VerifyError('Unknown verification purpose.', 'invalid_purpose')
    if channel not in CHANNELS:
        raise VerifyError('Unknown channel. Use sms, call or whatsapp.', 'invalid_channel')
    if not S.flag('twilio_verify'):
        raise VerifyError('Phone verification is temporarily unavailable.', 'feature_disabled', 503)
    if purpose == 'login' and not S.flag('passwordless_login'):
        raise VerifyError('Log in with phone is not available.', 'feature_disabled', 403)

    e164, account = _resolve_phone(phone, purpose, user, step_up_ticket)
    tests = test_numbers()
    test_mode = e164 in tests
    suppressed = False

    if purpose == 'signup':
        owner = find_verified_owner(e164, exclude_id=user.id if user else None)
        if owner:
            raise VerifyError('This phone number is already registered. Log in instead.', 'phone_in_use', 409,
                              {'login_instead': True})
    elif purpose == 'login':
        account = find_verified_owner(e164)
        if not account:
            raise VerifyError('No account uses this phone number yet. Sign up instead.', 'no_account', 404,
                              {'signup_instead': True})
    elif purpose == 'password_reset':
        account = find_verified_owner(e164)
        suppressed = account is None       # never reveal whether the number is registered
    elif purpose in ('change_phone', 'driver_onboarding'):
        if not user:
            raise VerifyError('Please log in again.', 'unauthorized', 401)
        if find_verified_owner(e164, exclude_id=user.id):
            raise VerifyError('This phone number is already used by another account.', 'phone_in_use', 409)
        if purpose == 'change_phone' and user.phone_e164 == e164 and user.phone_verified_at:
            raise VerifyError('This is already your verified phone number.', 'same_phone')

    if channel == 'whatsapp' and not S.get('otp.whatsapp_enabled'):
        raise VerifyError('WhatsApp codes are not available. Use SMS or a voice call.', 'channel_unavailable')
    if channel == 'call' and _sms_sends(e164, purpose) < S.get_int('otp.voice_after_failed_sms'):
        raise VerifyError('A voice call is offered after we have sent you a text message.', 'voice_not_available',
                          data={'voice_after_sms': S.get_int('otp.voice_after_failed_sms')})

    _rate_limits(e164, ip, purpose)

    line_type = None
    if purpose == 'driver_onboarding' or (purpose == 'signup' and S.get('otp.lookup_at_signup')):
        line_type = lookup_line_type(e164, test_mode)
        is_voip = (line_type or '') in VOIP_TYPES
        if is_voip and ((purpose == 'driver_onboarding' and S.get('otp.block_voip_drivers'))
                        or (purpose == 'signup' and S.get('otp.block_voip_signup'))):
            raise VerifyError('Drivers must use a mobile phone number (internet/VoIP numbers are not accepted).'
                              if purpose == 'driver_onboarding' else
                              'Please use a mobile phone number (internet/VoIP numbers are not accepted).',
                              'voip_not_allowed')

    # older pending codes for the same number+purpose are superseded
    PhoneVerification.query.filter_by(phone=e164, purpose=purpose, status='pending') \
        .update({'status': 'canceled'}, synchronize_session=False)
    row = PhoneVerification(user_id=(account or user).id if (account or user) else None, phone=e164,
                            purpose=purpose, channel=channel, status='pending', ip=ip, device_id=device_id,
                            test_mode=test_mode, line_type=line_type, locale=locale, created_at=_now())
    db.session.add(row)

    if suppressed:
        row.status = 'suppressed'
    elif test_mode:
        pass
    elif verify_configured():
        try:
            res = twilio_client.verify_start(e164, channel=channel, locale=locale)
            row.twilio_sid = res.get('sid')
        except twilio_client.TwilioError as e:
            row.status, row.error = 'failed', str(e)[:500]
            db.session.commit()
            if e.status == 429 or str(e.code) == '60203':
                raise VerifyError('Too many codes were requested for this number. Please try again later.',
                                  'rate_limited_phone', 429)
            raise VerifyError("We couldn't send the code. Check the number and try again.", 'send_failed', 502)
    elif not is_production():
        code = f'{secrets.randbelow(10 ** 6):06d}'
        row.code_hash = _sha(code)
        DEV_LOG.append((e164, purpose, code))
        log.warning('[verify:dev-fallback] %s (%s) code=%s — Twilio not configured', e164, purpose, code)
    else:
        db.session.rollback()
        raise VerifyError('Phone verification is temporarily unavailable.', 'sms_unavailable', 503)
    db.session.commit()

    sms_count = _sms_sends(e164, purpose)
    return {
        'verification_id': row.id,
        'phone': e164,
        'phone_masked': P.mask(e164),
        'purpose': purpose,
        'channel': channel,
        'expires_in_s': S.get_int('otp.code_ttl_s'),
        'resend_after_s': S.get_int('otp.resend_after_s'),
        'voice_available': sms_count >= S.get_int('otp.voice_after_failed_sms'),
        'whatsapp_available': bool(S.get('otp.whatsapp_enabled')),
        'max_attempts': S.get_int('otp.max_check_attempts'),
        'test_mode': bool(test_mode),
    }


# ── check ───────────────────────────────────────────────────────────────────

def check(phone, purpose, code, user=None, step_up_ticket=None):
    purpose = (purpose or '').strip().lower()
    if purpose not in PURPOSES:
        raise VerifyError('Unknown verification purpose.', 'invalid_purpose')
    e164, _account = _resolve_phone(phone, purpose, user, step_up_ticket)
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if not 4 <= len(code) <= 10:
        raise VerifyError('Enter the 6-digit code we sent you.', 'invalid_code_format')

    row = (PhoneVerification.query.filter_by(phone=e164, purpose=purpose, status='pending')
           .order_by(PhoneVerification.id.desc()).with_for_update().first())
    if not row:
        db.session.rollback()
        raise VerifyError('That code is incorrect or has expired. Request a new code.', 'no_pending_code')
    ttl = S.get_int('otp.code_ttl_s')
    if row.created_at + timedelta(seconds=ttl) < _now():
        row.status = 'expired'
        db.session.commit()
        raise VerifyError('This code has expired. Request a new one.', 'code_expired', 410)
    max_attempts = S.get_int('otp.max_check_attempts')
    if (row.attempts or 0) >= max_attempts:
        row.status = 'failed'
        db.session.commit()
        raise VerifyError('Too many wrong attempts. Request a new code.', 'too_many_attempts', 429)

    row.attempts = (row.attempts or 0) + 1
    ok = False
    if row.test_mode:
        ok = test_numbers().get(e164) == code
    elif row.code_hash:
        ok = secrets.compare_digest(row.code_hash, _sha(code))
    else:
        try:
            res = twilio_client.verify_check(e164, code)
            ok = (res.get('status') == 'approved')
        except twilio_client.TwilioError as e:
            if e.status == 404:
                row.status = 'expired'
                db.session.commit()
                raise VerifyError('This code has expired. Request a new one.', 'code_expired', 410)
            if e.status == 429:
                row.status = 'failed'
                db.session.commit()
                raise VerifyError('Too many wrong attempts. Request a new code.', 'too_many_attempts', 429)
            db.session.commit()
            raise VerifyError("We couldn't check the code right now. Please try again.", 'check_failed', 502)

    if not ok:
        left = max(0, max_attempts - row.attempts)
        if left == 0:
            row.status = 'failed'
        db.session.commit()
        if left == 0:
            raise VerifyError('Too many wrong attempts. Request a new code.', 'too_many_attempts', 429,
                              {'attempts_left': 0})
        raise VerifyError(f'That code is incorrect. {left} attempt{"s" if left != 1 else ""} left.',
                          'invalid_code', 400, {'attempts_left': left})

    token = 'pvt_' + secrets.token_urlsafe(32)
    row.status = 'approved'
    row.verified_at = _now()
    row.token_hash = _sha(token)
    row.token_expires_at = _now() + timedelta(seconds=S.get_int('otp.token_ttl_s'))
    if user and not row.user_id:
        row.user_id = user.id
    db.session.commit()
    return {'verification_token': token, 'expires_in_s': S.get_int('otp.token_ttl_s'), 'phone': e164,
            'phone_masked': P.mask(e164), 'purpose': purpose, 'line_type': row.line_type}


# ── consume ─────────────────────────────────────────────────────────────────

def consume(token, purpose, phone=None, user=None):
    """Validate + mark a verification_token used (single use). Caller commits."""
    purposes = (purpose,) if isinstance(purpose, str) else tuple(purpose)
    if not token:
        raise VerifyError('Phone verification is required.', 'verification_required', 400)
    row = PhoneVerification.query.filter_by(token_hash=_sha(str(token).strip())).with_for_update().first()
    if not row or row.status != 'approved':
        raise VerifyError('Your phone verification is invalid. Please verify again.', 'invalid_verification_token')
    if row.consumed_at is not None:
        raise VerifyError('This verification was already used. Please verify again.', 'verification_used')
    if row.token_expires_at and row.token_expires_at < _now():
        raise VerifyError('Your phone verification expired. Please verify again.', 'verification_expired')
    if row.purpose not in purposes:
        raise VerifyError('This verification was for a different action.', 'verification_wrong_purpose')
    if phone:
        e164 = P.safe_normalize(phone)
        if e164 and e164 != row.phone:
            raise VerifyError('This verification was for a different number.', 'phone_mismatch')
    if user is not None and row.purpose in ('sensitive_action', 'change_phone', 'driver_onboarding') \
            and row.user_id and row.user_id != user.id:
        raise VerifyError('This verification belongs to another account.', 'verification_wrong_user', 403)
    row.consumed_at = _now()
    db.session.flush()
    return row


def apply_to_user(user, row, set_legacy_phone=True):
    """Mark the verified number as the user's phone."""
    user.phone_e164 = row.phone
    user.phone_verified_at = _now()
    if row.line_type:
        user.phone_line_type = row.line_type
    if set_legacy_phone:
        user.phone_number = row.phone
    if row.user_id is None:
        row.user_id = user.id


def require_sensitive_action(user, token, data=None):
    """Spec §11.2 #7. v4 clients must present a `sensitive_action` verification_token
    for payout-account changes and account deletion (when the user has a verified phone).
    Returns an error tuple for the route, or None when allowed."""
    from backend.utils.client_info import is_v4_client
    from backend.utils.response import error_response
    if not S.flag('sensitive_action_reverify') or not is_v4_client(data):
        return None
    if not user.phone_e164 or not user.phone_verified_at:
        return None
    try:
        consume(token, 'sensitive_action', user=user)
        return None
    except VerifyError as e:
        db.session.rollback()
        data = e.payload()
        data.update({'requires_verification': True, 'purpose': 'sensitive_action'})
        return error_response(e.message if e.code != 'verification_required'
                              else 'Please confirm it’s you with a code sent to your phone.', data=data,
                              status_code=403)
