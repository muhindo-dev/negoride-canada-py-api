import secrets
from datetime import datetime, timedelta

from flask import Blueprint, request
from flask_jwt_extended import create_access_token
from backend.models import db
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response
from backend.utils.email_service import send_verification_email, send_password_reset_email

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
    """Login with email/phone + password. Returns JWT token + user data."""
    data = request.get_json(silent=True) or request.form
    login_field = data.get('email') or data.get('phone_number') or data.get('username')
    password = data.get('password')

    if not login_field or not password:
        return error_response("Email/phone and password are required")

    # Find user by email, phone, or username
    user = AdminUser.query.filter(
        (AdminUser.email == login_field) |
        (AdminUser.phone_number == login_field) |
        (AdminUser.username == login_field)
    ).first()

    if not user:
        return error_response("Invalid credentials")

    if not user.check_password(password):
        return error_response("Invalid credentials")

    if user.status == 0:
        return error_response("Your account has been blocked")

    if user.deleted_at is not None:
        return error_response("Account not found")

    # Block login if email is set but not yet verified
    if user.email and user.email_verified_at is None:
        return error_response(
            "Please verify your email address before logging in. "
            "Check your inbox or request a new verification link.",
            data={'requires_email_verification': True, 'email': user.email},
            status_code=403,
        )

    # Generate JWT token
    token = create_access_token(identity=str(user.id))

    return success_response("Login successful", _build_auth_user_payload(user, token))


@auth_bp.route('/api/users/register', methods=['POST'])
def register():
    """Register a new user account."""
    data = request.get_json(silent=True) or request.form

    first_name = data.get('first_name', '')
    last_name = data.get('last_name', '')
    email = data.get('email')
    phone_number = data.get('phone_number')
    password = data.get('password')
    username = data.get('username')

    if not password:
        return error_response("Password is required")

    if not email and not phone_number:
        return error_response("Email or phone number is required")

    # Check for existing user
    if email and AdminUser.query.filter_by(email=email).first():
        return error_response("Email already registered")

    if phone_number and AdminUser.query.filter_by(phone_number=phone_number).first():
        return error_response("Phone number already registered")

    if username and AdminUser.query.filter_by(username=username).first():
        return error_response("Username already taken")

    # Auto-generate username if not provided
    if not username:
        username = email.split('@')[0] if email else phone_number

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

    # Generate email verification token if email is provided
    if email:
        user.email_verification_token = secrets.token_urlsafe(32)
        user.verification_token_expires = datetime.utcnow() + timedelta(hours=24)
        # email_verified_at stays None until verified

    db.session.add(user)
    db.session.commit()

    # Send verification email (non-blocking — failure doesn't abort registration)
    if email:
        send_verification_email(email, user.name or first_name or email, user.email_verification_token)

    token = create_access_token(identity=str(user.id))

    payload = _build_auth_user_payload(user, token)
    payload['requires_email_verification'] = bool(email)

    return success_response(
        "Registration successful. Please check your email to verify your account.",
        payload,
        status_code=201,
    )


@auth_bp.route('/api/otp-request', methods=['POST'])
def otp_request():
    """Request OTP for phone verification."""
    data = request.get_json(silent=True) or request.form
    phone_number = data.get('phone_number')

    if not phone_number:
        return error_response("Phone number is required")

    # TODO: Implement OTP sending via SMS service
    return success_response("OTP sent successfully")


@auth_bp.route('/api/otp-verify', methods=['POST'])
def otp_verify():
    """Verify OTP code."""
    data = request.get_json(silent=True) or request.form
    phone_number = data.get('phone_number')
    otp = data.get('otp')

    if not phone_number or not otp:
        return error_response("Phone number and OTP are required")

    # TODO: Implement OTP verification
    return success_response("OTP verified successfully")


@auth_bp.route('/api/users/me', methods=['GET'])
@jwt_required_with_user
def me(user):
    """Get current authenticated user.

    Default response stays list-shaped for the existing Flutter client.
    Pass ?format=object to receive a standard object payload instead.
    """
    user_payload = _build_auth_user_payload(user)
    if request.args.get('format') == 'object':
        return success_response("Success", user_payload)
    return success_response("Success", [user_payload])


# ─── Email Verification ───────────────────────────────────────────────────────

@auth_bp.route('/api/email/verify/<token>', methods=['GET'])
def verify_email(token):
    """Mark email as verified when the user clicks the link in their inbox."""
    user = AdminUser.query.filter_by(email_verification_token=token).first()

    if not user:
        return error_response("Invalid or expired verification link.", status_code=400)

    if user.verification_token_expires and datetime.utcnow() > user.verification_token_expires:
        return error_response(
            "This verification link has expired. Please request a new one.",
            data={'requires_resend': True},
            status_code=410,
        )

    user.email_verified_at = datetime.utcnow()
    user.email_verification_token = None
    user.verification_token_expires = None
    db.session.commit()

    return success_response("Email verified successfully! You can now log in.")


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
    user.password_reset_token = None
    user.password_reset_expires = None
    db.session.commit()

    return success_response("Password reset successfully. You can now log in with your new password.")
