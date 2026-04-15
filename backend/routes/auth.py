from flask import Blueprint, request
from flask_jwt_extended import create_access_token
from backend.models import db
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

auth_bp = Blueprint('auth', __name__)


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

    # Generate JWT token
    token = create_access_token(identity=str(user.id))

    # Flatten: merge token + user fields at top level (Flutter app expects this)
    data = user.to_dict()
    data['token'] = token
    data['remember_token'] = token
    return success_response("Login successful", data)


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

    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id))

    # Flatten: merge token + user fields at top level (Flutter app expects this)
    data = user.to_dict()
    data['token'] = token
    data['remember_token'] = token
    return success_response("Registration successful", data, status_code=201)


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
    """Get current authenticated user. Returns a single-element list so Flutter's
    getOnlineItems() (which expects a List) can save the updated profile to local DB."""
    return success_response("Success", [user.to_dict()])
