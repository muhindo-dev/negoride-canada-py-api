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
    """Update user phone number."""
    data = request.get_json(silent=True) or request.form
    phone_number = data.get('phone_number')

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

    user.status = '0'
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
    db.session.commit()

    return success_response("Driver registration submitted. Waiting for approval.", user.to_dict())
