import os
from datetime import datetime
from flask import Blueprint, request, current_app
from werkzeug.utils import secure_filename
from backend.models import db
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

profile_bp = Blueprint('profile', __name__)


@profile_bp.route('/api/profile/update', methods=['POST'])
@jwt_required_with_user
def update(user):
    """Update user profile."""
    data = request.get_json(silent=True) or request.form

    updatable_fields = [
        'first_name', 'last_name', 'name', 'email', 'phone_number', 'phone_number_2',
        'date_of_birth', 'place_of_birth', 'sex', 'home_address', 'current_address',
        'country_name', 'country_code', 'country_short_name',
    ]

    for field in updatable_fields:
        if field in data and data[field] is not None:
            setattr(user, field, data[field])

    user.updated_at = datetime.utcnow()
    db.session.commit()

    return success_response("Profile updated", user.to_dict())


@profile_bp.route('/api/profile/avatar', methods=['POST'])
@jwt_required_with_user
def upload_avatar(user):
    """Upload profile avatar."""
    if 'photo' not in request.files and 'avatar' not in request.files:
        return error_response("No file uploaded")

    file = request.files.get('photo') or request.files.get('avatar')
    if not file or file.filename == '':
        return error_response("No file selected")

    filename = secure_filename(f"{user.id}_{file.filename}")
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'images')
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    user.avatar = f"images/{filename}"
    user.updated_at = datetime.utcnow()
    db.session.commit()

    return success_response("Avatar updated", user.to_dict())


@profile_bp.route('/api/profile/update-email', methods=['POST'])
@jwt_required_with_user
def update_email(user):
    """Update user email."""
    data = request.get_json(silent=True) or request.form
    email = data.get('email')

    if not email:
        return error_response("Email is required")

    existing = AdminUser.query.filter(AdminUser.email == email, AdminUser.id != user.id).first()
    if existing:
        return error_response("Email already in use")

    user.email = email
    user.updated_at = datetime.utcnow()
    db.session.commit()

    return success_response("Email updated", user.to_dict())


@profile_bp.route('/api/profile/update-phone', methods=['POST'])
@jwt_required_with_user
def update_phone(user):
    """Update user phone number.

    v4 (spec §11.2 #3): send `verification_token` from
    /api/verify/phone/check with purpose=change_phone. The new number becomes the
    verified phone and the OLD number receives an SMS ("your number was changed").
    v4 clients must verify; v3 clients keep the legacy unverified update.
    """
    from backend.services import phone_verification as PV
    from backend.utils.client_info import is_v4_client
    data = request.get_json(silent=True) or request.form
    phone_number = data.get('phone_number') or data.get('phone')
    token = data.get('verification_token')

    if token or is_v4_client(data):
        try:
            row = PV.consume(token, 'change_phone', phone=phone_number, user=user)
        except PV.VerifyError as e:
            db.session.rollback()
            return error_response(e.message, data=e.payload(), status_code=e.status)
        if PV.find_verified_owner(row.phone, exclude_id=user.id) or \
                AdminUser.query.filter(AdminUser.phone_number == row.phone, AdminUser.id != user.id).first():
            db.session.rollback()
            return error_response("Phone number already in use", data={'error_code': 'phone_in_use'}, status_code=409)
        old = user.phone_e164 if user.phone_verified_at else None
        if not old:
            from backend.utils.phone import safe_normalize
            old = safe_normalize(user.phone_number)
        PV.apply_to_user(user, row, set_legacy_phone=True)
        user.updated_at = datetime.utcnow()
        from backend.services.audit import audit
        audit('user.phone_changed', user, 'user', user.id, before={'phone': old}, after={'phone': row.phone},
              actor_type='user')
        if old and old != row.phone:
            from backend import jobs
            jobs.enqueue_after_commit('backend.services.account_service.sms_phone_changed', old,
                                      user.preferred_language or 'en')
        db.session.commit()
        return success_response("Phone number updated", user.to_dict())

    if not phone_number:
        return error_response("Phone number is required")

    existing = AdminUser.query.filter(AdminUser.phone_number == phone_number, AdminUser.id != user.id).first()
    if existing:
        return error_response("Phone number already in use")

    user.phone_number = phone_number
    user.updated_at = datetime.utcnow()
    db.session.commit()

    return success_response("Phone number updated", user.to_dict())


@profile_bp.route('/api/profile/change-password', methods=['POST'])
@jwt_required_with_user
def change_password(user):
    """Change user password."""
    data = request.get_json(silent=True) or request.form
    current_password = data.get('current_password')
    new_password = data.get('new_password')

    if not current_password or not new_password:
        return error_response("Current and new password are required")

    if not user.check_password(current_password):
        return error_response("Current password is incorrect")

    user.set_password(new_password)
    user.updated_at = datetime.utcnow()
    db.session.commit()

    return success_response("Password changed successfully")


@profile_bp.route('/api/profile/delete-account', methods=['POST'])
@jwt_required_with_user
def delete_account(user):
    """Soft-delete user account."""
    data = request.get_json(silent=True) or request.form
    password = data.get('password')

    if not password:
        return error_response("Password is required")

    if not user.check_password(password):
        return error_response("Invalid password")

    # v4: re-verify the phone before deleting (spec §11.2 #7)
    from backend.services import phone_verification as PV
    blocked = PV.require_sensitive_action(user, data.get('verification_token'), data)
    if blocked is not None:
        return blocked

    user.status = '0'
    user.account_status = 'deactivated'
    user.status_reason_code = 'self_deleted'
    user.token_version = int(user.token_version or 0) + 1
    user.deleted_at = datetime.utcnow()
    user.updated_at = datetime.utcnow()
    db.session.commit()

    return success_response("Account deleted successfully")


@profile_bp.route('/api/become-driver', methods=['POST'])
@jwt_required_with_user
def become_driver(user):
    """Register user as a pending driver. Accepts multipart form data with optional file."""
    # Accept either multipart form or JSON
    data = request.form if request.form else (request.get_json(silent=True) or {})

    # Don't allow Admin/Super Admin accounts to be demoted to Pending Driver
    if user.user_type not in ('Admin', 'Super Admin'):
        user.user_type = 'Pending Driver'

    # Standard profile fields that exist in DB
    for field in ('first_name', 'last_name', 'date_of_birth', 'sex'):
        val = data.get(field)
        if val:
            setattr(user, field, val)

    # Driver-specific fields that exist in DB
    for field in ('driving_license_number', 'nin',
                  'driving_license_issue_date', 'driving_license_validity',
                  'driving_license_issue_authority', 'automobile',
                  'is_car', 'is_boda', 'is_ambulance',
                  'is_police', 'is_delivery', 'is_breakdown', 'is_firebrugade'):
        val = data.get(field)
        if val is not None:
            setattr(user, field, val)

    # Handle driving license photo — Flutter sends it as "file" or "driving_license"
    photo_file = request.files.get('file') or request.files.get('driving_license') or request.files.get('photo')
    if photo_file and photo_file.filename:
        filename = secure_filename(f"license_{user.id}_{photo_file.filename}")
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'images')
        os.makedirs(upload_dir, exist_ok=True)
        photo_file.save(os.path.join(upload_dir, filename))
        user.driving_license_photo = f"images/{filename}"

    user.updated_at = datetime.utcnow()
    # v4: mirror the legacy form into a driver application so the admin
    # onboarding queue sees v3 applicants too (spec §14).
    try:
        from backend.services import onboarding_service
        with db.session.begin_nested():
            onboarding_service.from_legacy_become_driver(user, data)
    except Exception:  # never fail the legacy flow
        import logging
        logging.getLogger('negoride.onboarding').exception('become-driver mirror failed')
    db.session.commit()

    return success_response("Driver registration submitted. Waiting for approval.", user.to_dict())
