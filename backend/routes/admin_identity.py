"""Admin API — identity, accounts, onboarding, legal, support, admin roles
(spec §15, §19.1.5 Users, §19.1.6 Onboarding, §19.1.8 Support, §19.1.11 Legal,
§19.1.14 Admin users & roles).

Every mutating action and every view of personal data writes audit_logs.
Roles: super_admin passes everything; see each route's decorator.
"""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, request
from sqlalchemy import func

from backend.models import db
from backend.models.identity import (BackgroundCheck, DriverApplication, DriverDocument, LegalAcceptance,
                                     LegalDocument, PhoneVerification, SupportTicket)
from backend.models.platform import AuditLog
from backend.models.user import AdminUser
from backend.services import account_service as A
from backend.services import legal_service as L
from backend.services import onboarding_service as O
from backend.services import support_service as SS
from backend.services.audit import audit
from backend.utils.auth import admin_role_required
from backend.utils.response import error_response, paginated_response, success_response

admin_identity_bp = Blueprint('admin_identity', __name__)

ADMIN_ROLES = ('super_admin', 'ops', 'safety_reviewer', 'finance', 'support')
PEOPLE = ('super_admin', 'ops', 'safety_reviewer', 'support')
ONBOARDING = ('super_admin', 'ops', 'safety_reviewer')


def _body():
    return request.get_json(silent=True) or request.form or {}


def _page():
    page = max(1, request.args.get('page', 1, type=int))
    per = min(200, max(1, request.args.get('per_page', 25, type=int)))
    return page, per


def _iso(v):
    return v.strftime('%Y-%m-%dT%H:%M:%SZ') if v else None


def _err(message, code, status=400, **extra):
    return error_response(message, data={'error_code': code, **extra}, status_code=status)


def _user_card(u):
    if not u:
        return None
    return {'id': u.id, 'name': u.name, 'email': u.email, 'phone': u.phone_e164 or u.phone_number,
            'user_type': u.user_type, 'account_status': u.effective_account_status(), 'avatar': u.to_dict()['avatar']}


# ── Users: status actions ───────────────────────────────────────────────────

@admin_identity_bp.route('/api/admin/account-status/reasons', methods=['GET'])
@admin_role_required(*PEOPLE)
def status_reasons(admin):
    return success_response('Reasons', {
        'actions': [{'action': k, 'status': v} for k, v in A.ACTIONS.items()],
        'reasons': [{'code': k, 'category': v[0], 'label': v[1], 'label_fr': v[2]} for k, v in A.REASONS.items()]})


def _parse_until(d):
    if d.get('until'):
        try:
            return datetime.strptime(str(d['until']).replace('Z', '')[:19], '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            try:
                return datetime.strptime(str(d['until'])[:10], '%Y-%m-%d')
            except ValueError:
                return 'invalid'
    hours = d.get('duration_hours')
    days = d.get('duration_days')
    try:
        if hours not in (None, ''):
            return datetime.utcnow() + timedelta(hours=float(hours))
        if days not in (None, ''):
            return datetime.utcnow() + timedelta(days=float(days))
    except (TypeError, ValueError):
        return 'invalid'
    return None


@admin_identity_bp.route('/api/admin/users/<int:user_id>/account-status/preview', methods=['POST'])
@admin_role_required(*PEOPLE)
def status_preview(admin, user_id):
    u = db.session.get(AdminUser, user_id)
    if not u:
        return _err('User not found.', 'not_found', 404)
    d = _body()
    status = A.ACTIONS.get(d.get('action'), d.get('action'))
    if status not in A.STATUSES:
        return _err('Choose an action.', 'invalid_action')
    until = _parse_until(d)
    if until == 'invalid':
        return _err('Invalid suspension end.', 'invalid_until')
    rt, ride = A.active_ride(u)
    return success_response('Preview', {
        'message': A.preview_message(u, status, d.get('reason_code'), until if status == 'suspended' else None),
        'will_defer': bool(ride is not None and status != 'active'),
        'active_ride': {'ride_type': rt, 'ride_id': ride.id} if ride is not None else None})


@admin_identity_bp.route('/api/admin/users/<int:user_id>/account-status', methods=['POST'])
@admin_role_required(*PEOPLE)
def set_status(admin, user_id):
    u = db.session.get(AdminUser, user_id)
    if not u:
        return _err('User not found.', 'not_found', 404)
    d = _body()
    status = A.ACTIONS.get(d.get('action'), d.get('action') or d.get('status'))
    if status not in A.STATUSES:
        return _err('Choose an action: activate, suspend, deactivate, ban or reactivate.', 'invalid_action')
    reason_code = d.get('reason_code')
    reason_text = (d.get('reason_text') or d.get('reason') or '').strip()
    if reason_code not in A.REASONS:
        return _err('Choose a reason from the list.', 'reason_required')
    if not reason_text:
        return _err('Add a short explanation (free text).', 'reason_text_required')
    if u.id == admin.id:
        return _err('You cannot change your own account status.', 'self_action', 403)
    if 'super_admin' in u.get_admin_roles() and not admin.has_admin_role('super_admin'):
        return _err('Only a super admin can change another admin’s status.', 'forbidden', 403)
    until = _parse_until(d)
    if until == 'invalid':
        return _err('Invalid suspension end.', 'invalid_until')
    if status == 'suspended' and until is None:
        return _err('Choose how long the suspension lasts.', 'duration_required')
    notify_user = d.get('notify_user', True) not in (False, 'false', '0', 0)
    try:
        res = A.set_status(u, status, admin, reason_code, reason_text, until=until, notify_user=notify_user,
                           defer_if_active_ride=d.get('force') not in (True, 'true', '1'))
    except A.AccountError as e:
        db.session.rollback()
        return _err(e.message, e.code, e.status)
    msg = ('Saved — the change will apply when the current ride ends.' if res['deferred']
           else f'Account is now {res["account_status"].replace("_", " ")}.')
    return success_response(msg, {**res, 'user': _user_card(u)})


@admin_identity_bp.route('/api/admin/users/<int:user_id>/profile', methods=['GET'])
@admin_role_required(*PEOPLE)
def user_profile(admin, user_id):
    u = db.session.get(AdminUser, user_id)
    if not u:
        return _err('User not found.', 'not_found', 404)
    from backend.models.money import DriverStrike
    app = DriverApplication.query.filter_by(user_id=u.id).first()
    strikes = DriverStrike.query.filter_by(driver_id=u.id).order_by(DriverStrike.id.desc()).limit(50).all()
    docs = DriverDocument.query.filter_by(user_id=u.id).order_by(DriverDocument.id.desc()).limit(50).all()
    bgcs = BackgroundCheck.query.filter_by(user_id=u.id).order_by(BackgroundCheck.id.desc()).all()
    acc = LegalAcceptance.query.filter_by(user_id=u.id).order_by(LegalAcceptance.id.desc()).all()
    tickets = SupportTicket.query.filter_by(user_id=u.id).order_by(SupportTicket.id.desc()).limit(20).all()
    last_pv = PhoneVerification.query.filter_by(user_id=u.id).order_by(PhoneVerification.id.desc()).limit(10).all()
    window = datetime.utcnow() - timedelta(days=A.S.get_int('strikes.window_days'))
    audit('admin.view_user', admin, 'user', u.id, meta={'sections': 'profile'})
    db.session.commit()
    return success_response('User', {
        'user': u.to_dict(),
        'account': {**A.status_payload(u), 'status_reason': u.status_reason, 'status_changed_by': u.status_changed_by,
                    'pending_status_meta': u.pending_status_meta, 'token_version': u.token_version,
                    'sms_opt_out_at': _iso(u.sms_opt_out_at)},
        'verification': {'phone_e164': u.phone_e164, 'phone_verified_at': _iso(u.phone_verified_at),
                         'phone_line_type': u.phone_line_type, 'email_verified_at': _iso(u.email_verified_at),
                         'recent_phone_verifications': [p.to_dict() for p in last_pv]},
        'strikes': {'total': len(strikes), 'in_window': sum(1 for s in strikes if s.created_at >= window),
                    'items': [s.to_dict() for s in strikes]},
        'driver_application': O.application_public(app) if app else None,
        'documents': [O.document_public(x, admin=True) for x in docs],
        'background_checks': [O.bgc_public(b, admin=True) for b in bgcs],
        'legal_acceptances': [a.to_dict() for a in acc],
        'support_tickets': [SS.ticket_dict(t) for t in tickets],
    })


# ── User account controls ───────────────────────────────────────────────────
PROFILE_EDIT_FIELDS = {
    'name': 200, 'first_name': 100, 'last_name': 200, 'email': 254,
    'phone_number': 40, 'country_code': 5,
    'country_name': 40, 'country_short_name': 3, 'date_of_birth': 10,
    'sex': 30, 'current_address': 1000, 'province': 2,
    'preferred_language': 5, 'timezone': 60, 'legal_name': 200,
    'automobile': 55, 'driving_license_number': 100, 'nin': 100,
    'driving_license_issue_date': 20, 'driving_license_validity': 20,
    'driving_license_issue_authority': 150, 'max_passengers': 3,
}


def _reason(d):
    text = str(d.get('reason_text') or '').strip()
    return text if len(text) >= 5 else None


def _masked(value):
    if not value:
        return value
    value = str(value)
    if '@' in value:
        local, _, domain = value.partition('@')
        return (local[:1] + '***@' + domain) if local else '***@' + domain
    return ('*' * max(0, len(value) - 4)) + value[-4:]


@admin_identity_bp.route('/api/admin/users/<int:user_id>/profile', methods=['PUT'])
@admin_role_required('super_admin', 'ops')
def update_user_profile(admin, user_id):
    u = db.session.get(AdminUser, user_id)
    if not u:
        return _err('User not found.', 'not_found', 404)
    d = _body()
    reason = _reason(d)
    if not reason:
        return _err('A reason of at least 5 characters is required.', 'reason_required')
    changes = d.get('changes') if isinstance(d.get('changes'), dict) else {k: v for k, v in d.items() if k != 'reason_text'}
    unknown = set(changes) - set(PROFILE_EDIT_FIELDS) - {'marketing_opt_in'}
    if unknown:
        return _err('One or more fields cannot be edited here.', 'field_not_editable', fields=sorted(unknown))
    before, after = {}, {}
    for key, raw in changes.items():
        if key == 'marketing_opt_in':
            if not isinstance(raw, bool):
                return _err('Marketing opt-in must be true or false.', 'invalid_field', field=key)
            value = raw
        elif key == 'max_passengers':
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return _err('Maximum passengers must be a whole number.', 'invalid_field', field=key)
            if not 1 <= value <= 20:
                return _err('Maximum passengers must be between 1 and 20.', 'invalid_field', field=key)
        else:
            value = str(raw or '').strip() or None
            if value and len(value) > PROFILE_EDIT_FIELDS[key]:
                return _err(f'{key} is too long.', 'invalid_field', field=key)
            if key == 'email' and value:
                value = value.lower()
                if '@' not in value or '.' not in value.rsplit('@', 1)[-1]:
                    return _err('Enter a valid email address.', 'invalid_email')
                conflict = AdminUser.query.filter(func.lower(AdminUser.email) == value, AdminUser.id != u.id).first()
                if conflict:
                    return _err('That email address belongs to another account.', 'email_in_use', 409)
            if key == 'phone_number' and value:
                from backend.utils.phone import safe_normalize
                normalized = safe_normalize(value, default_country=(u.country_short_name or 'CA').upper())
                if not normalized:
                    return _err('Enter a valid phone number including its country code.', 'invalid_phone')
                conflict = AdminUser.query.filter(AdminUser.phone_e164 == normalized, AdminUser.id != u.id).first()
                if conflict:
                    return _err('That phone number belongs to another account.', 'phone_in_use', 409)
            if key == 'preferred_language' and value and value not in ('en', 'fr'):
                return _err('Language must be English or French.', 'invalid_field', field=key)
            if key == 'province' and value and value.upper() not in ('AB','BC','MB','NB','NL','NS','NT','NU','ON','PE','QC','SK','YT'):
                return _err('Choose a valid Canadian province or territory.', 'invalid_field', field=key)
            if key == 'date_of_birth' and value:
                try:
                    datetime.strptime(value, '%Y-%m-%d')
                except ValueError:
                    return _err('Date of birth must use YYYY-MM-DD.', 'invalid_field', field=key)
            if key in ('country_short_name', 'province') and value:
                value = value.upper()
        old = getattr(u, key)
        if old != value:
            sensitive = key in ('email', 'phone_number', 'phone_e164', 'nin', 'driving_license_number')
            before[key] = _masked(old) if sensitive else old
            after[key] = _masked(value) if sensitive else value
            setattr(u, key, value)
    if not after:
        return success_response('No profile changes to save.', {'user': u.to_dict()})
    if 'email' in after:
        u.email_verified_at = None
        u.email_verification_token = None
        u.verification_token_expires = None
    if 'phone_number' in after or 'phone_e164' in after:
        u.phone_verified_at = None
        u.phone_line_type = None
    if 'phone_number' in after:
        from backend.utils.phone import safe_normalize
        normalized = safe_normalize(u.phone_number, default_country=(u.country_short_name or 'CA').upper()) if u.phone_number else None
        old_e164 = u.phone_e164
        u.phone_e164 = normalized
        if old_e164 != normalized:
            before['phone_e164'] = _masked(old_e164)
            after['phone_e164'] = _masked(normalized)
    if 'marketing_opt_in' in after:
        u.marketing_opt_in_at = datetime.utcnow() if u.marketing_opt_in else None
    if {'email', 'phone_number', 'phone_e164'} & set(after):
        u.token_version = int(u.token_version or 0) + 1
    u.updated_at = datetime.utcnow()
    audit('admin.user_profile_update', admin, 'user', u.id, before=before, after=after,
          meta={'reason': reason, 'changed_fields': sorted(after)})
    db.session.commit()
    return success_response('User profile updated.', {'user': u.to_dict()})


@admin_identity_bp.route('/api/admin/users/<int:user_id>/sessions/revoke', methods=['POST'])
@admin_role_required('super_admin', 'ops')
def revoke_user_sessions(admin, user_id):
    u = db.session.get(AdminUser, user_id)
    if not u:
        return _err('User not found.', 'not_found', 404)
    reason = _reason(_body())
    if not reason:
        return _err('A reason of at least 5 characters is required.', 'reason_required')
    before = int(u.token_version or 0)
    u.token_version = before + 1
    u.password_reset_token = None
    u.password_reset_expires = None
    audit('admin.user_sessions_revoked', admin, 'user', u.id, before={'token_version': before},
          after={'token_version': u.token_version}, meta={'reason': reason})
    db.session.commit()
    from backend.services import realtime
    realtime.to_user(u.id, 'account.sessions_revoked', {'message': 'Your account sessions were ended by support.'})
    A.disconnect_user_sockets(u.id)
    return success_response('All existing sessions have been revoked.')


@admin_identity_bp.route('/api/admin/users/<int:user_id>/force-offline', methods=['POST'])
@admin_role_required('super_admin', 'ops')
def force_user_offline(admin, user_id):
    u = db.session.get(AdminUser, user_id)
    if not u:
        return _err('User not found.', 'not_found', 404)
    if u.user_type not in ('Driver', 'Pending Driver'):
        return _err('This action is only available for driver accounts.', 'not_a_driver', 409)
    reason = _reason(_body())
    if not reason:
        return _err('A reason of at least 5 characters is required.', 'reason_required')
    previous = u.ready_for_trip
    u.ready_for_trip = 'No'
    audit('admin.driver_forced_offline', admin, 'user', u.id, before={'ready_for_trip': previous},
          after={'ready_for_trip': 'No'}, meta={'reason': reason})
    db.session.commit()
    return success_response('Driver is offline and will not receive new requests.')


@admin_identity_bp.route('/api/admin/users/<int:user_id>/verification', methods=['POST'])
@admin_role_required('super_admin', 'ops', 'safety_reviewer')
def set_user_verification(admin, user_id):
    u = db.session.get(AdminUser, user_id)
    if not u:
        return _err('User not found.', 'not_found', 404)
    d = _body()
    reason = _reason(d)
    if not reason:
        return _err('A reason of at least 5 characters is required.', 'reason_required')
    field, action = d.get('field'), d.get('action')
    columns = {'email': ('email_verified_at', 'email_verification_token'),
               'phone': ('phone_verified_at', None)}
    if field not in columns or action not in ('verify', 'unverify'):
        return _err('Choose email or phone and verify or unverify.', 'invalid_action')
    timestamp, token_col = columns[field]
    if field == 'email' and not u.email:
        return _err('This account has no email address.', 'contact_missing', 409)
    if field == 'phone' and not (u.phone_e164 or u.phone_number):
        return _err('This account has no phone number.', 'contact_missing', 409)
    old = getattr(u, timestamp)
    setattr(u, timestamp, datetime.utcnow() if action == 'verify' else None)
    if token_col and action == 'verify':
        setattr(u, token_col, None)
        u.verification_token_expires = None
    if field == 'phone' and action == 'unverify':
        u.phone_line_type = None
    audit(f'admin.user_{field}_{action}', admin, 'user', u.id,
          before={f'{field}_verified': bool(old)}, after={f'{field}_verified': action == 'verify'},
          meta={'reason': reason, 'admin_attested': True})
    db.session.commit()
    verb = 'verified' if action == 'verify' else 'marked unverified'
    return success_response(f'{field.title()} {verb}.', {'verified_at': _iso(getattr(u, timestamp))})


@admin_identity_bp.route('/api/admin/users/<int:user_id>/password-reset-link', methods=['POST'])
@admin_role_required('super_admin', 'ops')
def admin_password_reset_link(admin, user_id):
    u = db.session.get(AdminUser, user_id)
    if not u:
        return _err('User not found.', 'not_found', 404)
    reason = _reason(_body())
    if not reason:
        return _err('A reason of at least 5 characters is required.', 'reason_required')
    if not u.email:
        return _err('This account has no email address for a reset link.', 'email_required', 409)
    import secrets
    from backend.utils.email_service import send_password_reset_email
    token = secrets.token_urlsafe(32)
    u.password_reset_token = token
    u.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
    u.token_version = int(u.token_version or 0) + 1
    audit('admin.user_password_reset_link_sent', admin, 'user', u.id,
          meta={'reason': reason, 'expires_in_minutes': 60})
    try:
        db.session.commit()
        sent = send_password_reset_email(u.email, u.name or u.email, token, lang=u.preferred_language)
        if not sent:
            u.password_reset_token = None
            u.password_reset_expires = None
            audit('admin.user_password_reset_email_failed', admin, 'user', u.id,
                  meta={'reason': reason, 'sessions_revoked': True})
            db.session.commit()
            return _err('The email service did not accept the reset email. Existing sessions were revoked; retry after mail service recovery.',
                        'email_send_failed', 502)
    except Exception:
        db.session.rollback()
        return _err('Could not send the password reset email. Check the mail service and try again.', 'email_send_failed', 502)
    return success_response('A one-hour password reset link was sent to the account email.')


def _user_history_clause(user_id):
    """Audit rows about the user, by the user, and about the user's driver application,
    driver documents, background checks, safety incidents and support tickets (§15)."""
    from backend.models.safety import SafetyIncident
    related = {
        'driver_application': [r[0] for r in db.session.query(DriverApplication.id).filter_by(user_id=user_id)],
        'driver_document': [r[0] for r in db.session.query(DriverDocument.id).filter_by(user_id=user_id)],
        'background_check': [r[0] for r in db.session.query(BackgroundCheck.id).filter_by(user_id=user_id)],
        'safety_incident': [r[0] for r in db.session.query(SafetyIncident.id).filter_by(user_id=user_id)],
        'support_ticket': [r[0] for r in db.session.query(SupportTicket.id).filter_by(user_id=user_id)],
    }
    conds = [(AuditLog.entity_type == 'user') & (AuditLog.entity_id == str(user_id)), AuditLog.actor_id == user_id]
    for etype, ids in related.items():
        if ids:
            conds.append((AuditLog.entity_type == etype) & (AuditLog.entity_id.in_([str(i) for i in ids])))
    return db.or_(*conds)


@admin_identity_bp.route('/api/admin/users/<int:user_id>/history', methods=['GET'])
@admin_role_required(*PEOPLE)
def user_history(admin, user_id):
    page, per = _page()
    q = AuditLog.query.filter(_user_history_clause(user_id))
    total = q.count()
    rows = q.order_by(AuditLog.id.desc()).offset((page - 1) * per).limit(per).all()
    names = {x.id: x.name for x in AdminUser.query.filter(AdminUser.id.in_({r.actor_id for r in rows if r.actor_id} or {0}))}
    audit('admin.view_user', admin, 'user', user_id, meta={'sections': 'history'})
    db.session.commit()
    return paginated_response([{**r.to_dict(), 'actor_name': names.get(r.actor_id)} for r in rows], total, page, per)


@admin_identity_bp.route('/api/admin/users/<int:user_id>/strikes', methods=['GET'])
@admin_role_required(*PEOPLE)
def user_strikes(admin, user_id):
    from backend.models.money import DriverStrike
    rows = DriverStrike.query.filter_by(driver_id=user_id).order_by(DriverStrike.id.desc()).limit(200).all()
    return success_response('Strikes', {'items': [r.to_dict() for r in rows],
                                        'window_days': A.S.get_int('strikes.window_days'),
                                        'warn_after': A.S.get_int('strikes.warn_after'),
                                        'suspend_after': A.S.get_int('strikes.suspend_after')})


# ── Onboarding queue ───────────────────────────────────────────────────────

@admin_identity_bp.route('/api/admin/onboarding/applications', methods=['GET'])
@admin_role_required(*ONBOARDING)
def applications(admin):
    page, per = _page()
    q = DriverApplication.query
    if request.args.get('status'):
        q = q.filter(DriverApplication.status.in_(request.args['status'].split(',')))
    if request.args.get('step'):
        q = q.filter_by(current_step=request.args['step'])
    if request.args.get('q'):
        like = f"%{request.args['q']}%"
        ids = [r[0] for r in db.session.query(AdminUser.id).filter(
            (AdminUser.name.like(like)) | (AdminUser.email.like(like)) | (AdminUser.phone_e164.like(like))).limit(500)]
        q = q.filter(DriverApplication.user_id.in_(ids or [0]))
    total = q.count()
    rows = q.order_by(DriverApplication.submitted_at.is_(None), DriverApplication.submitted_at.asc(),
                      DriverApplication.id.desc()).offset((page - 1) * per).limit(per).all()
    users = {u.id: u for u in AdminUser.query.filter(AdminUser.id.in_({r.user_id for r in rows} or {0}))}
    items = []
    for r in rows:
        b = O.latest_bgc(r.user_id)
        items.append({**O.application_public(r), 'user': _user_card(users.get(r.user_id)),
                      'background_check_status': b.status if b else None,
                      'documents_pending': DriverDocument.query.filter_by(application_id=r.id, status='pending').count()})
    return paginated_response(items, total, page, per)


@admin_identity_bp.route('/api/admin/onboarding/applications/<int:app_id>', methods=['GET'])
@admin_role_required(*ONBOARDING)
def application_detail(admin, app_id):
    app = db.session.get(DriverApplication, app_id)
    if not app:
        return _err('Application not found.', 'not_found', 404)
    u = db.session.get(AdminUser, app.user_id)
    all_docs = DriverDocument.query.filter_by(application_id=app.id).order_by(DriverDocument.id.desc()).all()
    audit('admin.view_driver_application', admin, 'driver_application', app.id, meta={'user_id': app.user_id})
    data = {'application': app.to_dict(), 'user': u.to_dict() if u else None,
            'steps': O.compute_steps(u, app) if u else [],
            'submit_blockers': O.submit_blockers(u, app) if u else [],
            'available_service_types': O.offered_service_types(),
            'documents': [O.document_public(d, admin=True) for d in all_docs],
            'background_checks': [O.bgc_public(b, admin=True) for b in
                                  BackgroundCheck.query.filter_by(user_id=app.user_id).order_by(BackgroundCheck.id.desc())],
            'legal_acceptances': [a.to_dict() for a in LegalAcceptance.query.filter_by(user_id=app.user_id)]}
    from backend.services import face_match
    data['face_match'] = face_match.summary(app.id)
    data['insurance_endorsement_required'] = O.endorsement_required(app, u)
    data['renewal_due'] = O.renewal_due(O.latest_bgc(app.user_id))
    db.session.commit()
    return success_response('Application', data)


@admin_identity_bp.route('/api/admin/onboarding/applications/<int:app_id>/profile', methods=['PUT'])
@admin_role_required(*ONBOARDING)
def update_application_profile(admin, app_id):
    """Correct applicant-provided onboarding fields without editing workflow evidence."""
    app = db.session.get(DriverApplication, app_id)
    if not app:
        return _err('Application not found.', 'not_found', 404)
    user = db.session.get(AdminUser, app.user_id)
    if not user:
        return _err('Applicant account not found.', 'not_found', 404)

    data = _body()
    reason = str(data.get('reason_text') or '').strip()
    if len(reason) < 5:
        return _err('A reason of at least 5 characters is required.', 'reason_required')
    changes = data.get('changes')
    if not isinstance(changes, dict):
        return _err('Application changes must be an object.', 'invalid_changes')

    editable = set(O.PROFILE_FIELDS) | {'vehicle_seats'}
    unknown = set(changes) - editable
    if unknown:
        return _err('One or more fields are managed by a dedicated onboarding workflow.',
                    'field_not_editable', fields=sorted(unknown))

    before = {key: getattr(app, key) for key in changes}
    missing = object()
    seats = changes.get('vehicle_seats', missing)
    if seats is not missing and seats not in (None, ''):
        try:
            seats_value = int(seats)
        except (TypeError, ValueError):
            return _err('Passenger seats must be a whole number.', 'invalid_field', field='vehicle_seats')
        if not 1 <= seats_value <= 14:
            return _err('Passenger seats must be between 1 and 14.', 'invalid_field', field='vehicle_seats')
        changes['vehicle_seats'] = seats_value

    try:
        O.save_profile(user, changes)
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e.message, e.code, e.status, **e.data)

    if 'vehicle_seats' in changes and changes['vehicle_seats'] in (None, ''):
        app.vehicle_seats = None
    changed_fields = sorted(key for key, old in before.items() if old != getattr(app, key))
    if changed_fields:
        steps = O.compute_steps(user, app)
        O._record_progress(app, steps)
        def audit_value(key, value):
            if value is None:
                return None
            if key == 'licence_number':
                value = str(value)
                return ('*' * max(0, len(value) - 4)) + value[-4:]
            return value.isoformat() if hasattr(value, 'isoformat') else value

        audit('onboarding.admin_application_profile_updated', admin, 'driver_application', app.id,
              before={'fields': {key: audit_value(key, before[key]) for key in changed_fields}},
              after={'fields': {key: audit_value(key, getattr(app, key)) for key in changed_fields}},
              meta={'reason': reason, 'user_id': user.id})
    db.session.commit()
    return success_response('Application details saved.', {
        'application': O.application_public(app),
        'steps': O.compute_steps(user, app),
        'submit_blockers': O.submit_blockers(user, app),
    })


@admin_identity_bp.route('/api/admin/onboarding/documents/<int:doc_id>/file', methods=['GET'])
@admin_role_required(*ONBOARDING)
def document_file(admin, doc_id):
    """Signed short-lived URL (default) or the bytes (?inline=1). Audited."""
    doc = db.session.get(DriverDocument, doc_id)
    if not doc:
        return _err('Document not found.', 'not_found', 404)
    from backend.services import private_storage as PS
    audit('admin.view_driver_document', admin, 'driver_document', doc.id, meta={'user_id': doc.user_id, 'type': doc.type})
    db.session.commit()
    if request.args.get('inline') in ('1', 'true'):
        try:
            data = PS.get(doc.file_path)
        except PS.StorageError:
            return _err('File not found.', 'file_missing', 404)
        return Response(data, mimetype=doc.mime_type or 'application/octet-stream',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    url = PS.signed_url(doc.file_path, ttl_s=300, content_type=doc.mime_type, filename=f'{doc.type}-{doc.id}',
                        actor_id=admin.id)
    return success_response('Signed URL', {'url': url, 'expires_in_s': 300})


@admin_identity_bp.route('/api/admin/onboarding/documents/<int:doc_id>/review', methods=['POST'])
@admin_role_required(*ONBOARDING)
def document_review(admin, doc_id):
    doc = db.session.get(DriverDocument, doc_id)
    if not doc:
        return _err('Document not found.', 'not_found', 404)
    d = _body()
    try:
        O.review_document(doc, admin, d.get('decision') or '', d.get('note') or d.get('reviewer_note'))
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e.message, e.code, e.status)
    if d.get('expires_at'):
        doc.expires_at = O.parse_date(d['expires_at']) or doc.expires_at
    db.session.commit()
    return success_response('Document reviewed.', O.document_public(doc, admin=True))


@admin_identity_bp.route('/api/admin/onboarding/applications/<int:app_id>/decision', methods=['POST'])
@admin_role_required(*ONBOARDING)
def application_decision(admin, app_id):
    app = db.session.get(DriverApplication, app_id)
    if not app:
        return _err('Application not found.', 'not_found', 404)
    d = _body()
    try:
        O.decide(app, admin, d.get('decision') or '', d.get('reason'), d.get('service_types'),
                 d.get('override_background_check') in (True, 'true', '1'))
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e.message, e.code, e.status, **e.data)
    db.session.commit()
    u = db.session.get(AdminUser, app.user_id)
    return success_response(f'Application {app.status.replace("_", " ")}.',
                            {'application': app.to_dict(), 'user': u.to_dict()})


@admin_identity_bp.route('/api/admin/onboarding/background-checks/<int:bgc_id>/report', methods=['GET'])
@admin_role_required('super_admin', 'safety_reviewer', 'ops')
def bgc_report(admin, bgc_id):
    b = db.session.get(BackgroundCheck, bgc_id)
    if not b:
        return _err('Background check not found.', 'not_found', 404)
    from backend.services import certn_client as CC
    try:
        url = O.report_link(b)
    except (O.OnboardingError, CC.CertnError) as e:
        return _err(str(getattr(e, 'message', e)), 'report_unavailable', 409)
    audit('admin.view_background_report', admin, 'background_check', b.id, meta={'user_id': b.user_id})
    db.session.commit()
    return success_response('Report link (short-lived — do not share)', {'url': url})


@admin_identity_bp.route('/api/admin/onboarding/background-checks/<int:bgc_id>/refresh', methods=['POST'])
@admin_role_required(*ONBOARDING)
def bgc_refresh(admin, bgc_id):
    b = db.session.get(BackgroundCheck, bgc_id)
    if not b:
        return _err('Background check not found.', 'not_found', 404)
    from backend.services import certn_client as CC
    try:
        if b.status == 'paid' and not b.provider_application_id:
            db.session.commit()
            O.initiate_background_check(b.id)
            b = db.session.get(BackgroundCheck, bgc_id)
        else:
            O.refresh_from_provider(b)
    except CC.CertnError as e:
        db.session.rollback()
        return _err(str(e), 'certn_error', 502)
    audit('onboarding.bgc_refresh', admin, 'background_check', b.id, after={'status': b.status})
    db.session.commit()
    return success_response('Refreshed.', O.bgc_public(b, admin=True))


@admin_identity_bp.route('/api/admin/onboarding/background-checks/<int:bgc_id>/adjudicate', methods=['POST'])
@admin_role_required('super_admin', 'safety_reviewer', 'ops')
def bgc_adjudicate(admin, bgc_id):
    b = db.session.get(BackgroundCheck, bgc_id)
    if not b:
        return _err('Background check not found.', 'not_found', 404)
    d = _body()
    try:
        O.adjudicate(b, admin, d.get('decision') or '', d.get('note') or d.get('reason'))
    except O.OnboardingError as e:
        db.session.rollback()
        return _err(e.message, e.code, e.status)
    db.session.commit()
    return success_response('Decision recorded.', O.bgc_public(b, admin=True))


@admin_identity_bp.route('/api/admin/onboarding/background-checks/<int:bgc_id>/record', methods=['PATCH'])
@admin_role_required('super_admin', 'ops')
def bgc_update_record(admin, bgc_id):
    """Correct the operational record without issuing payments or contacting Certn."""
    b = db.session.get(BackgroundCheck, bgc_id)
    if not b:
        return _err('Background check not found.', 'not_found', 404)
    d = _body()
    changes = d.get('changes') if isinstance(d.get('changes'), dict) else {}
    reason = str(d.get('reason') or '').strip()
    if len(reason) < 5:
        return _err('Provide a reason of at least 5 characters.', 'reason_required')

    string_limits = {
        'provider': 20, 'provider_application_id': 191, 'package': 80,
        'result': 30, 'raw_status': 60, 'provider_score': 30,
        'adjudication_note': 4000,
    }
    datetime_fields = {
        'fee_paid_at', 'start_after', 'initiated_at', 'completed_at', 'expires_at',
        'last_polled_at', 'refunded_at', 'cancelled_at', 'deduction_settled_at',
        'recheck_reminded_at', 'receipt_emailed_at', 'adjudicated_at',
    }
    integer_fields = {'fee_cents', 'refunded_cents', 'deducted_cents'}
    allowed = set(string_limits) | datetime_fields | integer_fields | {'status', 'paid_by', 'deduction_status'}
    if not changes:
        return _err('Change at least one background-check field.', 'empty_changes')
    unknown = sorted(set(changes) - allowed)
    if unknown:
        return _err('One or more fields cannot be edited here.', 'invalid_fields', fields=unknown)

    statuses = {'awaiting_payment', 'paid', 'initiated', 'pending', 'clear', 'consider', 'failed', 'cancelled', 'expired'}
    normalized = {}
    try:
        for field, value in changes.items():
            if field == 'status':
                value = str(value or '').strip().lower()
                if value not in statuses:
                    raise ValueError('Choose a valid background-check status.')
            elif field == 'paid_by':
                value = str(value or '').strip().lower()
                if value not in {'driver', 'platform', 'earnings'}:
                    raise ValueError('Choose driver, platform or earnings for paid by.')
            elif field == 'deduction_status':
                value = None if value in (None, '') else str(value).strip().lower()
                if value not in (None, 'pending', 'settled', 'waived'):
                    raise ValueError('Choose a valid deduction status.')
            elif field in datetime_fields:
                if value in (None, ''):
                    value = None
                else:
                    value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                    if value.tzinfo is not None:
                        value = value.astimezone(timezone.utc).replace(tzinfo=None)
            elif field in integer_fields:
                if isinstance(value, bool) or value in (None, ''):
                    raise ValueError(f'{field} must be a non-negative whole number.')
                value = int(value)
                if value < 0:
                    raise ValueError(f'{field} must be a non-negative whole number.')
            elif field in string_limits:
                value = None if value in (None, '') else str(value).strip()
                if value is not None and len(value) > string_limits[field]:
                    raise ValueError(f'{field} must be {string_limits[field]} characters or fewer.')
            normalized[field] = value
    except (TypeError, ValueError, OverflowError) as exc:
        return _err(str(exc) or 'One or more values are invalid.', 'invalid_field_value')

    if normalized.get('provider', b.provider) in (None, ''):
        return _err('Provider is required.', 'provider_required')

    fee_cents = normalized.get('fee_cents', b.fee_cents)
    refunded_cents = normalized.get('refunded_cents', b.refunded_cents or 0)
    if refunded_cents > fee_cents:
        return _err('Refunded amount cannot exceed the background-check fee.', 'refund_exceeds_fee')

    before, after = {}, {}
    for field, value in normalized.items():
        old = getattr(b, field)
        if old != value:
            before[field], after[field] = old, value
            setattr(b, field, value)
    if not after:
        return _err('No values changed.', 'no_changes')
    audit('admin.bgc_record_updated', admin, 'background_check', b.id,
          before=before, after=after, meta={'reason': reason, 'user_id': b.user_id})
    db.session.commit()
    return success_response('Background-check record updated.', O.bgc_public(b, admin=True))


@admin_identity_bp.route('/api/admin/onboarding/funnel', methods=['GET'])
@admin_role_required(*ONBOARDING)
def onboarding_funnel(admin):
    return success_response('Onboarding funnel', O.funnel())


# ── Legal editor ────────────────────────────────────────────────────────────

LEGAL_ROLES = ('super_admin', 'ops')


@admin_identity_bp.route('/api/admin/legal/documents', methods=['GET'])
@admin_role_required(*ADMIN_ROLES)
def legal_list(admin):
    q = LegalDocument.query
    for f in ('type', 'language', 'status'):
        if request.args.get(f):
            q = q.filter(getattr(LegalDocument, f) == request.args[f])
    rows = q.order_by(LegalDocument.type, LegalDocument.language, LegalDocument.id.desc()).all()
    return success_response('Legal documents', {'items': [{**L.summary_of(d), 'status': d.status,
                                                           'published_at': _iso(d.published_at),
                                                           'updated_at': _iso(d.updated_at)} for d in rows],
                                                'types': list(L.TYPES)})


@admin_identity_bp.route('/api/admin/legal/documents/<int:doc_id>', methods=['GET'])
@admin_role_required(*ADMIN_ROLES)
def legal_get(admin, doc_id):
    d = db.session.get(LegalDocument, doc_id)
    if not d:
        return _err('Document not found.', 'not_found', 404)
    return success_response(d.title, L.render(d, raw=True))


@admin_identity_bp.route('/api/admin/legal/documents', methods=['POST'])
@admin_role_required(*LEGAL_ROLES)
def legal_create(admin):
    b = _body()
    try:
        d = L.create_draft(admin, b.get('type'), b.get('version'), b.get('language') or 'en', b.get('title'),
                           b.get('body_markdown'), b.get('summary_markdown'), b.get('audience'), b.get('from_id'),
                           b.get('what_changed'))
    except L.LegalError as e:
        db.session.rollback()
        return _err(e.message, e.code, e.status)
    db.session.commit()
    return success_response('Draft created.', L.render(d, raw=True), status_code=201)


@admin_identity_bp.route('/api/admin/legal/documents/<int:doc_id>', methods=['PUT', 'PATCH'])
@admin_role_required(*LEGAL_ROLES)
def legal_update(admin, doc_id):
    d = db.session.get(LegalDocument, doc_id)
    if not d:
        return _err('Document not found.', 'not_found', 404)
    if d.status != 'draft':
        return _err('Published versions cannot be edited — create a new version.', 'not_draft', 409)
    b = _body()
    before = {k: getattr(d, k) for k in ('title', 'audience', 'what_changed')}
    for f in ('title', 'summary_markdown', 'body_markdown', 'what_changed'):
        if f in b and b[f] is not None:
            setattr(d, f, b[f])
    if b.get('audience') in ('all', 'customer', 'driver'):
        d.audience = b['audience']
    audit('legal.draft_updated', admin, 'legal_document', d.id, before=before,
          after={k: getattr(d, k) for k in ('title', 'audience', 'what_changed')},
          meta={'body_chars': len(d.body_markdown or '')})
    db.session.commit()
    return success_response('Draft saved.', L.render(d, raw=True))


@admin_identity_bp.route('/api/admin/legal/documents/<int:doc_id>/preview', methods=['GET', 'POST'])
@admin_role_required(*ADMIN_ROLES)
def legal_preview(admin, doc_id):
    d = db.session.get(LegalDocument, doc_id)
    if not d:
        return _err('Document not found.', 'not_found', 404)
    b = _body() if request.method == 'POST' else {}
    ctx = L.render_context()
    out = L.render(d, ctx)
    if b.get('body_markdown') is not None:
        out['body_markdown'] = L.render_text(b['body_markdown'], ctx)
    if b.get('summary_markdown') is not None:
        out['summary_markdown'] = L.render_text(b['summary_markdown'], ctx)
    out['variables'] = ctx
    return success_response('Preview', out)


@admin_identity_bp.route('/api/admin/legal/documents/<int:doc_id>/publish', methods=['POST'])
@admin_role_required(*LEGAL_ROLES)
def legal_publish(admin, doc_id):
    d = db.session.get(LegalDocument, doc_id)
    if not d:
        return _err('Document not found.', 'not_found', 404)
    b = _body()
    eff = None
    if b.get('effective_at'):
        try:
            eff = datetime.strptime(str(b['effective_at']).replace('Z', '')[:19], '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            return _err('effective_at must be ISO-8601.', 'invalid_date')
    try:
        prev = L.publish(d, admin, b.get('requires_reacceptance') in (True, 'true', '1', 1), b.get('what_changed'), eff)
    except L.LegalError as e:
        db.session.rollback()
        return _err(e.message, e.code, e.status)
    db.session.commit()
    return success_response('Published.' + (' Users will be asked to accept it.' if d.requires_reacceptance else ''),
                            {'document': L.summary_of(d), 'archived_id': prev.id if prev else None})


@admin_identity_bp.route('/api/admin/legal/stats', methods=['GET'])
@admin_role_required(*ADMIN_ROLES)
def legal_stats(admin):
    return success_response('Acceptance stats', L.acceptance_stats(request.args.get('type')))


@admin_identity_bp.route('/api/admin/legal/documents/<int:doc_id>/acceptances', methods=['GET'])
@admin_role_required(*PEOPLE)
def legal_acceptances(admin, doc_id):
    page, per = _page()
    q = LegalAcceptance.query.filter_by(document_id=doc_id)
    total = q.count()
    rows = q.order_by(LegalAcceptance.id.desc()).offset((page - 1) * per).limit(per).all()
    users = {u.id: u for u in AdminUser.query.filter(AdminUser.id.in_({r.user_id for r in rows} or {0}))}
    audit('admin.view_legal_acceptances', admin, 'legal_document', doc_id, meta={'page': page})
    db.session.commit()
    return paginated_response([{**r.to_dict(), 'user': _user_card(users.get(r.user_id))} for r in rows],
                              total, page, per)


# ── Support queue ───────────────────────────────────────────────────────────

SUPPORT = ('super_admin', 'ops', 'support', 'safety_reviewer', 'finance')


@admin_identity_bp.route('/api/admin/support/tickets', methods=['GET'])
@admin_role_required(*SUPPORT)
def tickets(admin):
    page, per = _page()
    q = SupportTicket.query
    for f in ('status', 'type', 'priority'):
        if request.args.get(f):
            q = q.filter(getattr(SupportTicket, f).in_(request.args[f].split(',')))
    if request.args.get('assigned_to'):
        v = request.args['assigned_to']
        q = q.filter(SupportTicket.assigned_to.is_(None) if v == 'none' else SupportTicket.assigned_to == (admin.id if v == 'me' else int(v)))
    if request.args.get('overdue') in ('1', 'true'):
        q = q.filter(SupportTicket.first_response_at.is_(None), SupportTicket.sla_due_at < datetime.utcnow(),
                     SupportTicket.status.in_(('open', 'pending')))
    if request.args.get('user_id'):
        q = q.filter_by(user_id=int(request.args['user_id']))
    total = q.count()
    rows = q.order_by(SupportTicket.status.in_(('resolved', 'closed')), SupportTicket.sla_due_at.asc()) \
        .offset((page - 1) * per).limit(per).all()
    users = {u.id: u for u in AdminUser.query.filter(AdminUser.id.in_({r.user_id for r in rows} or {0}))}
    counts = dict(db.session.query(SupportTicket.status, func.count(SupportTicket.id)).group_by(SupportTicket.status).all())
    resp = paginated_response([SS.ticket_dict(t, user=users.get(t.user_id)) for t in rows], total, page, per)
    body = resp[0].get_json()
    body['data']['counts'] = {k: int(v) for k, v in counts.items()}
    from flask import jsonify
    return jsonify(body), 200


@admin_identity_bp.route('/api/admin/support/tickets/<int:ticket_id>', methods=['GET'])
@admin_role_required(*SUPPORT)
def ticket_detail(admin, ticket_id):
    t = db.session.get(SupportTicket, ticket_id)
    if not t:
        return _err('Ticket not found.', 'not_found', 404)
    audit('admin.view_ticket', admin, 'support_ticket', t.id, meta={'user_id': t.user_id})
    db.session.commit()
    return success_response('Ticket', SS.ticket_dict(t, with_messages=True, include_internal=True, user=SS.user_of(t)))


@admin_identity_bp.route('/api/admin/support/tickets/<int:ticket_id>/assign', methods=['POST'])
@admin_role_required(*SUPPORT)
def ticket_assign(admin, ticket_id):
    t = db.session.get(SupportTicket, ticket_id)
    if not t:
        return _err('Ticket not found.', 'not_found', 404)
    d = _body()
    to = d.get('admin_id')
    to = admin.id if to in (None, '', 'me') else int(to)
    target = db.session.get(AdminUser, to)
    if not target or not target.get_admin_roles():
        return _err('Assign to an admin user.', 'invalid_assignee')
    before = t.assigned_to
    t.assigned_to = to
    if d.get('priority') in SS.PRIORITIES and d['priority'] != t.priority:
        t.priority = d['priority']
        t.sla_due_at = SS.sla_due(t.priority, t.created_at)
    audit('support.assigned', admin, 'support_ticket', t.id, before={'assigned_to': before},
          after={'assigned_to': to, 'priority': t.priority})
    db.session.commit()
    return success_response('Assigned.', SS.ticket_dict(t))


@admin_identity_bp.route('/api/admin/support/tickets/<int:ticket_id>/reply', methods=['POST'])
@admin_role_required(*SUPPORT)
def ticket_reply(admin, ticket_id):
    t = db.session.get(SupportTicket, ticket_id)
    if not t:
        return _err('Ticket not found.', 'not_found', 404)
    d = _body()
    internal = d.get('internal') in (True, 'true', '1')
    try:
        SS.add_message(t, admin, d.get('body') or d.get('message'), 'internal' if internal else 'admin',
                       d.get('attachments'))
    except SS.SupportError as e:
        db.session.rollback()
        return _err(e.message, e.code)
    if t.assigned_to is None:
        t.assigned_to = admin.id
    audit('support.reply', admin, 'support_ticket', t.id, meta={'internal': internal})
    db.session.commit()
    return success_response('Reply sent.' if not internal else 'Note added.',
                            SS.ticket_dict(t, with_messages=True, include_internal=True))


@admin_identity_bp.route('/api/admin/support/tickets/<int:ticket_id>/status', methods=['POST'])
@admin_role_required(*SUPPORT)
def ticket_status(admin, ticket_id):
    t = db.session.get(SupportTicket, ticket_id)
    if not t:
        return _err('Ticket not found.', 'not_found', 404)
    d = _body()
    st = d.get('status')
    if st not in SS.STATUSES:
        return _err('Invalid status.', 'invalid_status')
    before = t.status
    t.status = st
    if st in ('resolved', 'closed'):
        t.resolved_at = t.resolved_at or datetime.utcnow()
        t.resolution = (d.get('resolution') or t.resolution or '')[:5000] or None
        if st == 'closed':
            t.closed_by = admin.id
        if t.type == 'dispute' and t.ride_type and t.ride_id and before not in ('resolved', 'closed'):
            # evidence retention clock (recordings / breadcrumbs) starts when the dispute is resolved
            from backend.services import safety_service
            safety_service.mark_dispute_resolved(t.ride_type, t.ride_id, actor=admin)
    audit('support.status', admin, 'support_ticket', t.id, before={'status': before},
          after={'status': st, 'resolution': t.resolution})
    if st == 'resolved' and d.get('resolution'):
        from backend.services.notify import notify
        notify('support.reply', [t.user_id], {'subject': f'Resolved: {t.subject}', 'ticket_id': t.id})
    db.session.commit()
    return success_response('Ticket updated.', SS.ticket_dict(t))


# ── Admin users & roles (super_admin only) ─────────────────────────────────

@admin_identity_bp.route('/api/admin/admin-users', methods=['GET'])
@admin_role_required('super_admin')
def admin_users(admin):
    rows = AdminUser.query.filter((AdminUser.admin_roles.isnot(None) & (AdminUser.admin_roles != '')) |
                                  AdminUser.user_type.in_(('Admin', 'Super Admin'))).order_by(AdminUser.id).all()
    return success_response('Admin users', {'roles': list(ADMIN_ROLES),
                                            'items': [{**_user_card(u), 'roles': u.get_admin_roles()} for u in rows]})


@admin_identity_bp.route('/api/admin/admin-users/<int:user_id>/roles', methods=['PUT', 'POST'])
@admin_role_required('super_admin')
def set_roles(admin, user_id):
    u = db.session.get(AdminUser, user_id)
    if not u:
        return _err('User not found.', 'not_found', 404)
    roles = _body().get('roles')
    if isinstance(roles, str):
        roles = [r.strip() for r in roles.split(',') if r.strip()]
    roles = list(dict.fromkeys(roles or []))
    bad = [r for r in roles if r not in ADMIN_ROLES]
    if bad:
        return _err(f'Unknown role(s): {", ".join(bad)}.', 'invalid_role')
    if u.id == admin.id and 'super_admin' not in roles:
        return _err('You cannot remove your own super admin role.', 'self_demotion', 403)
    before = u.get_admin_roles()
    u.admin_roles = ','.join(roles) if roles else ''
    if not roles and u.user_type in ('Admin', 'Super Admin'):
        u.user_type = 'Customer'   # legacy admin flag would otherwise re-grant super_admin
    u.token_version = int(u.token_version or 0) + 1   # new permissions on next login
    audit('admin.roles_changed', admin, 'user', u.id, before={'roles': before}, after={'roles': roles})
    db.session.commit()
    return success_response('Roles updated.', {**_user_card(u), 'roles': u.get_admin_roles()})
