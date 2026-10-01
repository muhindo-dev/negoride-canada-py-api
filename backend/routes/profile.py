import os
from datetime import datetime
from flask import Blueprint, request, current_app
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError

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

    # phone_number is NOT editable here: a phone change must be verified through
    # /api/verify/phone/start (purpose change_phone) + /api/profile/update-phone.
    updatable_fields = [
        'first_name', 'last_name', 'name', 'email', 'phone_number_2',
        'date_of_birth', 'place_of_birth', 'sex', 'home_address', 'current_address',
        'country_name', 'country_code', 'country_short_name',
    ]

    # Email / phone changes must not collide with another account, and a changed
    # value is no longer verified (v4 identity rules — spec §11.2 #3, #12).
    new_email = (data.get('email') or '').strip() or None
    if new_email and new_email != user.email:
        if AdminUser.query.filter(AdminUser.email == new_email, AdminUser.id != user.id).first():
            return error_response("Email already in use", data={'error_code': 'email_in_use'}, status_code=409)
    new_phone = str(data.get('phone_number') or '').strip() or None
    if new_phone and new_phone != user.phone_number:
        from backend.utils.phone import safe_normalize
        e164 = safe_normalize(new_phone)
        current = {x for x in (user.phone_e164, safe_normalize(user.phone_number)) if x}
        if not (e164 and e164 in current):
            return error_response("To change your phone number, verify the new number first.",
                                  data={'error_code': 'use_update_phone', 'purpose': 'change_phone',
                                        'endpoint': '/api/profile/update-phone'}, status_code=400)

    email_changed = bool(new_email and new_email != user.email)
    for field in updatable_fields:
        if field in data and data[field] is not None:
            setattr(user, field, data[field])

    if email_changed:
        import secrets
        from datetime import timedelta
        user.email_verified_at = None
        user.email_verification_token = secrets.token_urlsafe(32)
        user.verification_token_expires = datetime.utcnow() + timedelta(hours=24)
        from backend.services.notify.email_status import clear_email_bounce
        clear_email_bounce(user)   # a new address: lift the old bounce suppression
    user.updated_at = datetime.utcnow()
    db.session.commit()
    if email_changed:
        from backend.utils.email_service import send_verification_email
        send_verification_email(user.email, user.name or user.email, user.email_verification_token,
                                lang=user.preferred_language)

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
        return error_response("Email already in use", data={'error_code': 'email_in_use'}, status_code=409)

    changed = email != user.email
    user.email = email
    user.updated_at = datetime.utcnow()
    if changed:   # a new address is unverified until the link is clicked
        import secrets
        from datetime import timedelta
        user.email_verified_at = None
        user.email_verification_token = secrets.token_urlsafe(32)
        user.verification_token_expires = datetime.utcnow() + timedelta(hours=24)
        from backend.services.notify.email_status import clear_email_bounce
        clear_email_bounce(user)
    db.session.commit()
    if changed:
        from backend.utils.email_service import send_verification_email
        send_verification_email(user.email, user.name or user.email, user.email_verification_token,
                                lang=user.preferred_language)

    return success_response("Email updated", user.to_dict())


@profile_bp.route('/api/profile/update-phone', methods=['POST'])
@jwt_required_with_user
def update_phone(user):
    """Update user phone number.

    v4 (spec §11.2 #3): send `verification_token` from
    /api/verify/phone/check with purpose=change_phone. The new number becomes the
    verified phone and the OLD number receives an SMS ("your number was changed").
    v4 clients (and every client once app.legacy_clients_allowed is off) must verify.
    Legacy (v3) clients may still set an UNVERIFIED number: phone_e164 /
    phone_verified_at are cleared and the old number gets the same SMS.
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
        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            if PV.is_verified_phone_conflict(exc):
                return PV.phone_in_use_response()
            raise
        return success_response("Phone number updated", user.to_dict())

    # ── legacy (v3) unverified change — only while app.legacy_clients_allowed ──
    if not phone_number:
        return error_response("Phone number is required")

    from backend.utils.phone import safe_normalize
    new_e164 = safe_normalize(phone_number)
    conds = [AdminUser.phone_number == phone_number] + ([AdminUser.phone_number == new_e164,
                                                         AdminUser.phone_e164 == new_e164] if new_e164 else [])
    existing = AdminUser.query.filter(AdminUser.id != user.id, db.or_(*conds)).first()
    if existing:
        return error_response("Phone number already in use", data={'error_code': 'phone_in_use'}, status_code=409)

    old = user.phone_e164 or safe_normalize(user.phone_number)
    user.phone_number = phone_number
    user.phone_e164 = None            # unverified until a Twilio Verify check succeeds
    user.phone_verified_at = None
    user.phone_line_type = None
    user.updated_at = datetime.utcnow()
    from backend.services.audit import audit
    audit('user.phone_changed', user, 'user', user.id, before={'phone': old}, after={'phone': phone_number},
          meta={'verified': False, 'client': 'legacy'}, actor_type='user')
    if old and old != new_e164:
        from backend import jobs
        jobs.enqueue_after_commit('backend.services.account_service.sms_phone_changed', old,
                                  user.preferred_language or 'en')
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
    reason = (data.get('reason') or '').strip()[:500]
    user.status_reason = reason or user.status_reason
    from backend.services.audit import audit
    audit('account.self_delete', user, 'user', user.id, meta={'reason': reason or None}, actor_type='user')
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
