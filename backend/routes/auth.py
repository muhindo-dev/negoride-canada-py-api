import secrets
from datetime import datetime, timedelta

from flask import Blueprint, request
from backend.utils.auth import issue_token
from backend.models import db
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response
from backend.utils.email_service import send_verification_email, send_password_reset_email
from backend.models.identity import LegalDocument, UserDevice
from backend.services import legal_service
from backend.services import phone_verification as PV
from backend.services import settings_service as S
from backend.utils.client_info import app_version, client_ip, device_id, is_v4_client, user_agent
from backend.utils.phone import mask, safe_normalize

auth_bp = Blueprint('auth', __name__)


def _build_auth_user_payload(user, token=None):
    payload = user.to_dict()
    if token:
        payload['token'] = token
        payload['remember_token'] = token
        payload['access_token'] = token
    return payload


@auth_bp.route('/api/users/login', methods=['POST'])
def login():
    """Login with email/phone + password. Returns JWT token + user data.

    v4 additions (spec §11, §15):
      • suspended/deactivated accounts: v4 clients (X-App-Version ≥ 4) still get a
        token so the app can show the account-status screen and the appeal flow
        (every other endpoint answers 403); v3 clients keep the old error.
      • new-device step-up (flag ff.step_up_new_device): an unseen X-Device-Id on
        an account with a verified phone gets `requires_step_up` + `step_up_ticket`;
        verify with purpose=new_device, then repeat the login with `verification_token`.
    """
    data = request.get_json(silent=True) or request.form
    login_field = data.get('email') or data.get('phone_number') or data.get('username') or data.get('phone')
    password = data.get('password')

    if not login_field or not password:
        return error_response("Email/phone and password are required")

    # Find user by email, phone, or username
    e164 = safe_normalize(login_field) if '@' not in str(login_field) else None
    cond = ((AdminUser.email == login_field) |
            (AdminUser.phone_number == login_field) |
            (AdminUser.username == login_field))
    if e164:
        cond = cond | (AdminUser.phone_e164 == e164) | (AdminUser.phone_number == e164)
    user = AdminUser.query.filter(cond).filter(AdminUser.deleted_at.is_(None)).first() or \
        AdminUser.query.filter(cond).first()

    if not user:
        return error_response("Invalid credentials")

    if not user.check_password(password):
        return error_response("Invalid credentials")

    if user.deleted_at is not None:
        return error_response("Account not found")

    v4 = is_v4_client(data)
    if not user.is_account_active() and not v4:
        return error_response("Your account has been blocked",
                              data={'account_status': user.effective_account_status()})

    # Block login if email is set but not yet verified
    if user.email and user.email_verified_at is None:
        return error_response(
            "Please verify your email address before logging in. "
            "Check your inbox or request a new verification link.",
            data={'requires_email_verification': True, 'email': user.email},
            status_code=403,
        )

    dev = device_id(data)
    step_up = _step_up_check(user, dev, data)
    if step_up is not None:
        return step_up

    _touch_device(user, dev, data)
    db.session.commit()

    # Generate JWT token
    token = issue_token(user)

    payload = _build_auth_user_payload(user, token)
    if v4:
        payload['legal_pending'] = legal_service.pending_for(user, user.preferred_language)
    return success_response("Login successful", payload)


def _touch_device(user, dev, data=None, trust=False):
    """Record the device in user_devices. The first device ever seen is trusted."""
    if not dev:
        return None
    now = datetime.utcnow()
    row = UserDevice.query.filter_by(user_id=user.id, device_id=dev).first()
    if not row:
        first = UserDevice.query.filter_by(user_id=user.id).first() is None
        row = UserDevice(user_id=user.id, device_id=dev, first_seen_at=now,
                         trusted_at=now if (first or trust) else None)
        db.session.add(row)
    elif trust and not row.trusted_at:
        row.trusted_at = now
    row.last_seen_at, row.last_ip = now, client_ip()
    if data is not None:
        row.platform = (data.get('platform') or request.headers.get('X-Platform') or row.platform or '')[:20] or None
        row.label = (data.get('device_name') or row.label or '')[:191] or None
    return row


def _step_up_check(user, dev, data):
    """None when the login may proceed; otherwise the step-up response."""
    if not S.flag('step_up_new_device') or not dev or not user.phone_e164 or not user.phone_verified_at:
        return None
    row = UserDevice.query.filter_by(user_id=user.id, device_id=dev).first()
    if row and row.trusted_at:
        return None
    if row is None and UserDevice.query.filter_by(user_id=user.id).first() is None:
        return None  # first device ever: trusted on first use
    token = data.get('verification_token')
    if token:
        try:
            PV.consume(token, 'new_device', phone=user.phone_e164)
        except PV.VerifyError as e:
            db.session.rollback()
            return error_response(e.message, data=e.payload(), status_code=e.status)
        _touch_device(user, dev, data, trust=True)
        return None
    _touch_device(user, dev, data)   # registered, not trusted yet
    db.session.commit()
    return error_response(
        "For your security, confirm it's you with a code sent to your phone.",
        data={'error_code': 'step_up_required', 'requires_step_up': True,
              'step_up_ticket': PV.make_step_up_ticket(user, dev), 'phone_masked': mask(user.phone_e164),
              'purpose': 'new_device'},
        status_code=200)


def _consent_documents(data):
    """Map the registration consent fields to LegalDocument rows. Returns (docs, missing_types)."""
    ids_by_type = {
        'terms': data.get('accepted_terms_id'),
        'privacy': data.get('accepted_privacy_id'),
        'community_guidelines': data.get('accepted_guidelines_id') or data.get('accepted_community_guidelines_id'),
    }
    acc = data.get('acceptances') or []
    if isinstance(acc, str):
        try:
            import json as _json
            acc = _json.loads(acc)
        except ValueError:
            acc = []
    for a in acc:
        if isinstance(a, dict):
            t = a.get('type')
            if t in ids_by_type and not ids_by_type[t]:
                ids_by_type[t] = a.get('document_id') or a.get('id') or 'current'
        else:
            try:
                d = db.session.get(LegalDocument, int(a))
            except (TypeError, ValueError):
                d = None
            if d and d.type in ids_by_type and not ids_by_type[d.type]:
                ids_by_type[d.type] = d.id
    docs, missing = [], []
    for t, val in ids_by_type.items():
        if val is None or val is False or (not isinstance(val, bool) and isinstance(val, int) and val <= 0) or \
                (isinstance(val, str) and val.strip().lower() in ('', '0', 'false', 'no', 'off')):
            missing.append(t)
            continue
        if val is True or (isinstance(val, str) and val.strip().lower() in ('true', 'current', 'yes', 'on')):
            d = legal_service.current(t, data.get('language') or 'en')
        else:
            try:
                d = db.session.get(LegalDocument, int(val))
            except (TypeError, ValueError):
                d = None
            if d and (d.type != t or d.status != 'published'):
                raise legal_service.LegalError(
                    'A policy was updated while you were signing up. Please review the latest version.',
                    'document_outdated', 409, {'type': t})
        if not d:
            missing.append(t)
        else:
            docs.append(d)
    return docs, missing


@auth_bp.route('/api/users/register', methods=['POST'])
def register():
    """Register a new user account.

    v4 clients (X-App-Version ≥ 4.0.0) with ff.legal_consent_required must send
    the three explicit consents (spec §12): `accepted_terms_id`,
    `accepted_privacy_id`, `accepted_guidelines_id` (or an `acceptances` array of
    {type, document_id} / document ids). They are stored in the same transaction
    with IP, user agent and app version. `marketing_opt_in` (CASL) is separate and
    false unless explicitly true. With ff.phone_required_signup a
    `phone_verification_token` (purpose=signup) is required. v3 clients keep the
    old contract.
    """
    data = request.get_json(silent=True) or request.form

    first_name = data.get('first_name', '')
    last_name = data.get('last_name', '')
    email = data.get('email')
    phone_number = data.get('phone_number')
    password = data.get('password')
    username = data.get('username')
    v4 = is_v4_client(data)

    if not password:
        return error_response("Password is required")

    if not email and not phone_number and not data.get('phone_verification_token'):
        return error_response("Email or phone number is required")

    # v4: explicit legal consent (three separate ticks)
    consent_docs = []
    if v4 and S.flag('legal_consent_required'):
        try:
            consent_docs, missing = _consent_documents(data)
        except legal_service.LegalError as e:
            return error_response(e.message, data={**e.data, 'error_code': e.code}, status_code=e.status)
        if missing:
            return error_response(
                "Please read and accept the Terms & Conditions, the Privacy Policy and the Community Guidelines.",
                data={'error_code': 'consent_required', 'missing': missing,
                      'documents': [legal_service.summary_of(d) for d in legal_service.current_all(None, 'en')
                                    if d.type in legal_service.SIGNUP_REQUIRED]})

    # Phone verification (Twilio Verify, purpose=signup)
    pv_token = data.get('phone_verification_token') or data.get('verification_token')
    if v4 and S.flag('phone_required_signup') and not pv_token:
        return error_response("Please verify your phone number first.",
                              data={'error_code': 'phone_verification_required', 'purpose': 'signup'})
    pv_row = None
    if pv_token:
        try:
            pv_row = PV.consume(pv_token, 'signup', phone=phone_number)
        except PV.VerifyError as e:
            db.session.rollback()
            return error_response(e.message, data=e.payload(), status_code=e.status)
        if PV.find_verified_owner(pv_row.phone):
            db.session.rollback()
            return error_response("This phone number is already registered. Log in instead.",
                                  data={'error_code': 'phone_in_use', 'login_instead': True}, status_code=409)
        phone_number = phone_number or pv_row.phone

    # Check for existing user
    if email and AdminUser.query.filter_by(email=email).first():
        db.session.rollback()
        return error_response("Email already registered")

    if phone_number and AdminUser.query.filter_by(phone_number=phone_number).first():
        db.session.rollback()
        return error_response("Phone number already registered",
                              data={'error_code': 'phone_in_use', 'login_instead': True})
    e164 = safe_normalize(phone_number) if phone_number else None
    if e164 and PV.find_verified_owner(e164):
        db.session.rollback()
        return error_response("This phone number is already registered. Log in instead.",
                              data={'error_code': 'phone_in_use', 'login_instead': True}, status_code=409)

    if username and AdminUser.query.filter_by(username=username).first():
        db.session.rollback()
        return error_response("Username already taken")

    # Auto-generate username if not provided
    if not username:
        username = email.split('@')[0] if email else phone_number
        if AdminUser.query.filter_by(username=username).first():
            username = f"{username}_{secrets.token_hex(3)}"

    # Create user
    user = AdminUser(
        username=username,
        name=f"{first_name} {last_name}".strip(),
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone_number=phone_number,
        user_type='Customer',
        status='1',
        country_name=data.get('country_name', 'Canada'),
        country_code=data.get('country_code', '+1'),
        country_short_name=data.get('country_short_name', 'CA'),
        sex=data.get('gender', ''),
        max_passengers=4,
        rating=0.00,
    )
    user.set_password(password)
    if v4:
        user.account_status = 'active'
    lang = (data.get('language') or data.get('preferred_language') or '').lower()[:2]
    if lang in ('en', 'fr'):
        user.preferred_language = lang
    if data.get('province'):
        user.province = str(data.get('province')).upper()[:2]
    # CASL: separate, never pre-ticked; only an explicit true counts.
    if data.get('marketing_opt_in') in (True, 'true', '1', 1, 'yes', 'on'):
        user.marketing_opt_in = True
        user.marketing_opt_in_at = datetime.utcnow()

    # Generate email verification token if email is provided
    if email:
        user.email_verification_token = secrets.token_urlsafe(32)
        user.verification_token_expires = datetime.utcnow() + timedelta(hours=24)
        # email_verified_at stays None until verified

    db.session.add(user)
    db.session.flush()
    if pv_row:
        PV.apply_to_user(user, pv_row, set_legacy_phone=False)
    elif e164:
        user.phone_e164 = e164   # unverified until a check succeeds
    if consent_docs:
        legal_service.accept(user, consent_docs, method='checkbox', app_version=app_version(data),
                             ip=client_ip(), user_agent=user_agent())
    _touch_device(user, device_id(data), data, trust=True)
    db.session.commit()

    # Send verification email (non-blocking — failure doesn't abort registration)
    if email:
        send_verification_email(email, user.name or first_name or email, user.email_verification_token)

    token = issue_token(user)

    payload = _build_auth_user_payload(user, token)
    payload['requires_email_verification'] = bool(email)
    payload['requires_phone_verification'] = not bool(user.phone_verified_at)
    payload['legal_accepted'] = [d.type for d in consent_docs]

    return success_response(
        "Registration successful. Please check your email to verify your account.",
        payload,
        status_code=201,
    )


@auth_bp.route('/api/auth/login/phone', methods=['POST'])
def login_with_phone():
    """Passwordless login (spec §11.2 #2, flag ff.passwordless_login):
    POST /api/verify/phone/start {phone, purpose:'login'} → check → this endpoint
    with {phone, verification_token}. The device is trusted (the OTP is the step-up)."""
    data = request.get_json(silent=True) or request.form
    if not S.flag('passwordless_login'):
        return error_response("Log in with phone is not available.", data={'error_code': 'feature_disabled'},
                              status_code=403)
    try:
        row = PV.consume(data.get('verification_token'), 'login', phone=data.get('phone'))
    except PV.VerifyError as e:
        db.session.rollback()
        return error_response(e.message, data=e.payload(), status_code=e.status)
    user = PV.find_verified_owner(row.phone)
    if not user:
        db.session.rollback()
        return error_response("No account uses this phone number yet. Sign up instead.",
                              data={'error_code': 'no_account', 'signup_instead': True}, status_code=404)
    if not user.is_account_active() and not is_v4_client(data):
        db.session.rollback()
        return error_response("Your account has been blocked",
                              data={'account_status': user.effective_account_status()})
    row.user_id = row.user_id or user.id
    _touch_device(user, device_id(data), data, trust=True)
    db.session.commit()
    token = issue_token(user)
    payload = _build_auth_user_payload(user, token)
    payload['legal_pending'] = legal_service.pending_for(user, user.preferred_language)
    return success_response("Login successful", payload)


@auth_bp.route('/api/auth/reset-password/phone', methods=['POST'])
def reset_password_phone():
    """Password reset by phone (spec §11.2 #6): verify purpose=password_reset, then
    {phone, verification_token, password}. Revokes every existing session."""
    data = request.get_json(silent=True) or request.form
    new_password = data.get('password') or data.get('new_password')
    if not new_password or len(new_password) < 6:
        return error_response("Password must be at least 6 characters long")
    try:
        row = PV.consume(data.get('verification_token'), 'password_reset', phone=data.get('phone'))
    except PV.VerifyError as e:
        db.session.rollback()
        return error_response(e.message, data=e.payload(), status_code=e.status)
    user = PV.find_verified_owner(row.phone)
    if not user:
        db.session.rollback()
        return error_response("Invalid or expired reset request.", data={'error_code': 'no_account'})
    user.set_password(new_password)
    user.token_version = int(user.token_version or 0) + 1
    user.password_reset_token = None
    user.password_reset_expires = None
    from backend.services.audit import audit
    audit('user.password_reset', user, 'user', user.id, meta={'method': 'phone'}, actor_type='user')
    db.session.commit()
    return success_response("Password reset successfully. You can now log in with your new password.")


@auth_bp.route('/api/otp-request', methods=['POST'])
def otp_request():
    """Legacy alias of POST /api/verify/phone/start (phone_number → phone,
    purpose defaults to signup)."""
    from backend.routes.verify import start_response, _optional_user
    data = dict(request.get_json(silent=True) or request.form or {})
    if not (data.get('phone_number') or data.get('phone')):
        return error_response("Phone number is required")
    data['phone'] = data.get('phone') or data.get('phone_number')
    data.setdefault('purpose', 'signup')
    return start_response(data, _optional_user())


@auth_bp.route('/api/otp-verify', methods=['POST'])
def otp_verify():
    """Legacy alias of POST /api/verify/phone/check (phone_number → phone, otp → code)."""
    from backend.routes.verify import check_response, _optional_user
    data = dict(request.get_json(silent=True) or request.form or {})
    phone_number = data.get('phone_number') or data.get('phone')
    otp = data.get('otp') or data.get('code')
    if not phone_number or not otp:
        return error_response("Phone number and OTP are required")
    data.update(phone=phone_number, code=otp)
    data.setdefault('purpose', 'signup')
    return check_response(data, _optional_user())


@auth_bp.route('/api/users/me', methods=['GET'])
@jwt_required_with_user
def me(user):
    """Get current authenticated user.

    Returns a single object (the standard shape for a single-resource endpoint).
    Pass ?format=list to get the legacy list-wrapped payload if a very old
    client needs it; the current app accepts both shapes.
    """
    user_payload = _build_auth_user_payload(user)
    if request.args.get('format') == 'list':
        return success_response("Success", [user_payload])
    return success_response("Success", user_payload)


# ─── Email Verification ───────────────────────────────────────────────────────

_VERIFY_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>%(heading)s · NegoRide Canada</title>
<style>
  :root{--brand:#EF9B11;--brand-ink:#111;--ink:#0f172a;--muted:#64748b;--bg:#f1f5f9;--card:#ffffff;--accent:%(accent)s;--line:#e2e8f0;}
  :root:not([data-theme="light"]) {}
  @media (prefers-color-scheme: dark){:root{--ink:#e5e7eb;--muted:#94a3b8;--bg:#0b0f17;--card:#151d2b;--line:#26314a;}}
  *{box-sizing:border-box;}
  html,body{margin:0;height:100%%;}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink);min-height:100%%;display:flex;align-items:center;justify-content:center;padding:24px;}
  .card{background:var(--card);width:100%%;max-width:430px;border-radius:22px;padding:38px 30px;box-shadow:0 18px 50px rgba(2,6,23,.18);text-align:center;border:1px solid var(--line);}
  .brand{display:inline-flex;align-items:center;gap:10px;margin-bottom:26px;}
  .brand .mark{width:42px;height:42px;border-radius:11px;background:var(--brand);color:var(--brand-ink);font-weight:900;display:flex;align-items:center;justify-content:center;font-size:15px;letter-spacing:.5px;}
  .brand .name{font-weight:800;font-size:18px;}
  .icon{width:82px;height:82px;border-radius:50%%;margin:2px auto 20px;display:flex;align-items:center;justify-content:center;font-size:42px;line-height:1;color:#fff;background:var(--accent);box-shadow:0 8px 22px %(accent)s55;}
  h1{font-size:23px;margin:0 0 10px;letter-spacing:-.2px;}
  p{color:var(--muted);font-size:15.5px;line-height:1.6;margin:0 0 28px;}
  .btn{display:flex;align-items:center;justify-content:center;gap:9px;width:100%%;padding:16px 18px;border:0;border-radius:15px;background:var(--brand);color:var(--brand-ink);font-weight:800;font-size:16px;text-decoration:none;cursor:pointer;transition:transform .05s ease;}
  .btn:active{transform:translateY(1px);}
  .sub{margin-top:16px;font-size:13.5px;color:var(--muted);}
  .sub a{color:var(--brand);text-decoration:none;font-weight:700;}
  .foot{margin-top:28px;font-size:12px;color:var(--muted);opacity:.85;}
</style>
</head>
<body>
  <div class="card">
    <div class="brand"><span class="mark">NR</span><span class="name">NegoRide&nbsp;Canada</span></div>
    <div class="icon">%(icon)s</div>
    <h1>%(heading)s</h1>
    <p>%(message)s</p>
    <a href="#" class="btn" onclick="openApp();return false;">Open the NegoRide App &nbsp;&rarr;</a>
    <div class="sub" id="sub">Don't have the app installed? <a id="storeLink" href="%(play)s">Get it here</a>.</div>
    <div class="foot">NegoRide Canada &middot; Ride, negotiate, save.</div>
  </div>
<script>
  var PKG="negoride.canada.app";
  var PLAY="%(play)s";
  var SITE="%(site)s";
  (function(){
    var ua=navigator.userAgent||"";
    if(/iphone|ipad|ipod/i.test(ua)){var s=document.getElementById("storeLink"); if(s){s.href=SITE; s.textContent="visit our website";}}
  })();
  function openApp(){
    var ua=navigator.userAgent||"";
    if(/android/i.test(ua)){
      window.location.href="intent://open/#Intent;scheme=negoride;package="+PKG+";S.browser_fallback_url="+encodeURIComponent(PLAY)+";end";
    }else if(/iphone|ipad|ipod/i.test(ua)){
      var t=Date.now();
      window.location.href="negoride://open";
      setTimeout(function(){ if(Date.now()-t<1600){ window.location.href=SITE; } },1200);
    }else{
      window.location.href=SITE;
    }
  }
</script>
</body>
</html>"""


def _verification_page(state, heading, message, status_code=200):
    """Render a branded HTML page for the email-verification browser flow."""
    icons = {'success': '✓', 'error': '✕', 'expired': '⏳'}
    accents = {'success': '#16a34a', 'error': '#dc2626', 'expired': '#d97706'}
    html = _VERIFY_PAGE % {
        'heading': heading,
        'message': message,
        'icon': icons.get(state, 'ℹ'),
        'accent': accents.get(state, '#EF9B11'),
        'play': 'https://play.google.com/store/apps/details?id=negoride.canada.app',
        'site': 'https://negoride.ugnews24.info',
    }
    return html, status_code, {'Content-Type': 'text/html; charset=utf-8'}


@auth_bp.route('/api/email/verify/<token>', methods=['GET'])
def verify_email(token):
    """Mark email as verified when the user clicks the link in their inbox.

    Returns a friendly HTML page (this link is opened in a browser), with a
    button to launch the mobile app.
    """
    user = AdminUser.query.filter_by(email_verification_token=token).first()

    if not user:
        return _verification_page(
            'error',
            'Verification failed',
            'This verification link is invalid or has already been used. '
            'If you already verified, just open the app and sign in.',
            status_code=400,
        )

    if user.verification_token_expires and datetime.utcnow() > user.verification_token_expires:
        return _verification_page(
            'expired',
            'Link expired',
            'This verification link has expired. Open the NegoRide app and '
            'request a new verification email from the sign-in screen.',
            status_code=410,
        )

    already = user.email_verified_at is not None
    if not already:
        user.email_verified_at = datetime.utcnow()
        user.email_verification_token = None
        user.verification_token_expires = None
        db.session.commit()

    return _verification_page(
        'success',
        'Email verified!' if not already else 'Already verified',
        'Your email address has been confirmed. You can now open NegoRide '
        'Canada and sign in to start riding.',
        status_code=200,
    )


@auth_bp.route('/api/email/resend-verification', methods=['POST'])
def resend_verification():
    """Resend verification email to a registered but unverified user."""
    data = request.get_json(silent=True) or request.form
    email = data.get('email')

    if not email:
        return error_response("Email is required")

    user = AdminUser.query.filter_by(email=email).first()

    if not user:
        # Return success to avoid revealing whether the email exists
        return success_response("If that email is registered, a new verification link has been sent.")

    if user.email_verified_at is not None:
        return success_response("Your email is already verified. Please log in.")

    # Refresh token
    user.email_verification_token = secrets.token_urlsafe(32)
    user.verification_token_expires = datetime.utcnow() + timedelta(hours=24)
    db.session.commit()

    send_verification_email(email, user.name or email, user.email_verification_token)

    return success_response("A new verification link has been sent to your email.")


# ─── Forgot & Reset Password ──────────────────────────────────────────────────

@auth_bp.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    """Generate a password reset token and email it to the user."""
    data = request.get_json(silent=True) or request.form
    email = data.get('email')

    if not email:
        return error_response("Email is required")

    user = AdminUser.query.filter_by(email=email).first()

    # Always respond with success to avoid email enumeration
    if not user:
        return success_response(
            "If an account with that email exists, a password reset link has been sent."
        )

    # Generate reset token (store only first 8 chars + full token for lookup)
    token = secrets.token_urlsafe(32)
    user.password_reset_token = token
    user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
    db.session.commit()

    send_password_reset_email(email, user.name or email, token)

    return success_response(
        "If an account with that email exists, a password reset link has been sent."
    )


@auth_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    """Validate reset token and set a new password."""
    data = request.get_json(silent=True) or request.form
    token = data.get('token')
    new_password = data.get('password')

    if not token or not new_password:
        return error_response("Token and new password are required")

    if len(new_password) < 6:
        return error_response("Password must be at least 6 characters long")

    # Allow lookup by full token OR by the 8-char short code shown in email
    user = AdminUser.query.filter_by(password_reset_token=token).first()
    if not user:
        # Try matching by the first 8 chars (upper-cased in email for readability)
        users = AdminUser.query.filter(
            AdminUser.password_reset_token.isnot(None)
        ).all()
        user = next(
            (u for u in users if u.password_reset_token.upper().startswith(token.upper()[:8])),
            None,
        )

    if not user:
        return error_response("Invalid or expired reset token.", status_code=400)

    if user.password_reset_expires and datetime.utcnow() > user.password_reset_expires:
        return error_response(
            "This reset link has expired. Please request a new one.",
            status_code=410,
        )

    user.set_password(new_password)
    user.token_version = int(user.token_version or 0) + 1   # revoke existing sessions
    user.password_reset_token = None
    user.password_reset_expires = None
    db.session.commit()

    return success_response("Password reset successfully. You can now log in with your new password.")
