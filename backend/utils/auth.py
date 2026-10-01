from datetime import timedelta
from functools import wraps

from flask import jsonify, request
from flask_jwt_extended import create_access_token, decode_token, get_jwt, get_jwt_identity, verify_jwt_in_request

from backend.models import db
from backend.models.user import AdminUser

# Endpoints a suspended/deactivated user may still call (spec §15): read their
# own profile + status, appeal, read legal documents, fetch app config and
# finish a ride that was already in progress.
INACTIVE_ALLOWED_PREFIXES = (
    '/api/users/me', '/api/account/status', '/api/account/appeal', '/api/support', '/api/legal',
    '/api/app/config', '/api/rides/', '/api/notifications',
)


RESTRICTED_SCOPE = 'restricted'
RESTRICTED_TOKEN_TTL = timedelta(hours=2)


def issue_token(user):
    """Create an access token carrying the user's token_version (`tv`) so an
    admin deactivation (which bumps token_version) revokes every session."""
    return create_access_token(identity=str(user.id),
                               additional_claims={'tv': int(user.token_version or 0)})


def issue_restricted_token(user):
    """Short-lived token for a suspended / deactivated account (spec §15): only the
    INACTIVE_ALLOWED_PREFIXES endpoints accept it (status screen, appeal, legal, support)."""
    return create_access_token(identity=str(user.id), expires_delta=RESTRICTED_TOKEN_TTL,
                               additional_claims={'tv': int(user.token_version or 0), 'scope': RESTRICTED_SCOPE})


def _token_version_ok(user, claims):
    return int(claims.get('tv', 0) or 0) == int(user.token_version or 0)


def user_from_token(token, require_active=False):
    """Decode a raw JWT (sockets / query tokens). Returns the user or None.
    require_active=True also rejects suspended/deactivated accounts and restricted tokens."""
    if not token:
        return None
    if token.lower().startswith('bearer '):
        token = token[7:]
    try:
        claims = decode_token(token)
        user = db.session.get(AdminUser, int(claims['sub']))
    except Exception:
        return None
    if not user or user.deleted_at is not None or not _token_version_ok(user, claims):
        return None
    if require_active and (not user.is_account_active() or claims.get('scope') == RESTRICTED_SCOPE):
        return None
    return user


def token_rejection_code(token):
    """Why a raw JWT is not usable: None (usable), 'account_blocked' (valid
    signature but the account is now suspended/deactivated — including tokens
    revoked BY that status change), or 'session_revoked' (bad/expired/revoked).
    Mirrors the HTTP layer so socket clients can show the suspended screen."""
    if not token:
        return 'session_revoked'
    if token.lower().startswith('bearer '):
        token = token[7:]
    try:
        claims = decode_token(token)
        user = db.session.get(AdminUser, int(claims['sub']))
    except Exception:
        return 'session_revoked'
    if not user or user.deleted_at is not None:
        return 'session_revoked'
    if not user.is_account_active():
        return 'account_blocked'
    if not _token_version_ok(user, claims):
        return 'session_revoked'
    return None


def resolve_request_user():
    """(user, claims, problem) for the current request. problem ∈ None | 'unauthorized' |
    'session_revoked' | 'account_blocked'. A revoked token of an account that is now
    inactive reports 'account_blocked' (the app shows the suspended screen, not a login)."""
    try:
        verify_jwt_in_request()
        identity = get_jwt_identity()
        claims = get_jwt()
    except Exception:
        return None, None, 'unauthorized'
    if identity is None:
        return None, None, 'unauthorized'
    try:
        user = db.session.get(AdminUser, int(identity))
    except (TypeError, ValueError):
        return None, None, 'unauthorized'
    if not user:
        return None, None, 'unauthorized'
    if not _token_version_ok(user, claims):
        if user.deleted_at is None and not user.is_account_active():
            return user, claims, 'account_blocked'
        return user, claims, 'session_revoked'
    return user, claims, None


def get_current_user():
    """Return the authenticated user from a cryptographically verified JWT, or None.

    Identity is derived ONLY from a verified `Authorization: Bearer <token>`
    JWT. There is deliberately NO request-parameter fallback: trusting a
    `user_id` from the query string or body would let any unauthenticated
    caller impersonate any user simply by passing `?user_id=1`.

    Tokens issued before the user's current token_version (revoked by an admin
    status change or a password reset) are rejected.
    """
    try:
        verify_jwt_in_request()
    except Exception:
        return None

    identity = get_jwt_identity()
    if identity is None:
        return None

    try:
        user = db.session.get(AdminUser, int(identity))
    except (TypeError, ValueError):
        return None
    if not user:
        return None
    try:
        claims = get_jwt()
        if not _token_version_ok(user, claims):
            return None
        if claims.get('scope') == RESTRICTED_SCOPE and user.is_account_active():
            return None   # a restricted (suspended-screen) token is void once the account is active again
    except Exception:
        return None
    return user


def account_blocked_payload(user):
    """The account_blocked `data` shape (403 responses and suspended-user login)."""
    from backend.services import account_service as A
    st = user.effective_account_status()
    lang = (user.preferred_language or 'en')[:2]
    until = user.suspended_until if st == 'suspended' else None
    return {
        'error_code': 'account_blocked',
        'account_status': st,
        'status_reason_code': user.status_reason_code,
        'reason_code': user.status_reason_code,
        'reason_category': A.reason_category(user.status_reason_code),
        'reason_label': A.reason_label(user.status_reason_code, lang),
        'suspended_until': until.strftime('%Y-%m-%dT%H:%M:%SZ') if until else None,
        'can_appeal': st in A.APPEALABLE,
    }


def account_blocked_response(user):
    st = user.effective_account_status()
    return jsonify({
        'code': 0,
        'message': 'Your account is ' + st.replace('_', ' ') + '.',
        'data': account_blocked_payload(user),
    }), 403


def session_revoked_response():
    return jsonify({'code': 0, 'message': 'Your session has ended. Please log in again.',
                    'data': {'error_code': 'session_revoked'}}), 401


def _inactive_allowed():
    path = request.path or ''
    return any(path.startswith(p) for p in INACTIVE_ALLOWED_PREFIXES)


def jwt_required_with_user(fn):
    """Decorator that provides the current user to the route function.

    401 `Unauthorized` (no/invalid token) · 401 `data.error_code=session_revoked`
    (token revoked by a password reset / role change / reactivation) · 403
    `data.error_code=account_blocked` (inactive account — also for a revoked
    token of an account that is now inactive) · 403 `data.error_code=legal_pending`
    (v4: a policy version requiring re-acceptance is pending — spec §12).
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user, claims, problem = resolve_request_user()
        if problem == 'unauthorized':
            return jsonify({'code': 0, 'message': 'Unauthorized'}), 401
        if problem == 'account_blocked':
            return account_blocked_response(user)
        if problem == 'session_revoked':
            return session_revoked_response()
        restricted = (claims or {}).get('scope') == RESTRICTED_SCOPE
        if not user.is_account_active() and not _inactive_allowed():
            return account_blocked_response(user)
        if restricted and user.is_account_active():
            return session_revoked_response()   # reactivated: log in again for a full token
        if restricted and not _inactive_allowed():
            return account_blocked_response(user)
        from backend.services import legal_service
        gate = legal_service.gate_response(user)
        if gate is not None:
            return gate
        return fn(user, *args, **kwargs)
    return wrapper


def admin_required(fn):
    """Decorator that requires the current user to be an Admin."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'code': 0, 'message': 'Unauthorized'}), 401
        if user.user_type not in ('Admin', 'Super Admin') and not user.get_admin_roles():
            return jsonify({'code': 0, 'message': 'Admin access required'}), 403
        if not user.is_account_active():
            return account_blocked_response(user)
        return fn(user, *args, **kwargs)
    return wrapper


def admin_role_required(*roles):
    """Role-based admin access (spec §19.14): super_admin, ops, safety_reviewer,
    finance, support. super_admin passes every check."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({'code': 0, 'message': 'Unauthorized'}), 401
            if not user.get_admin_roles():
                return jsonify({'code': 0, 'message': 'Admin access required'}), 403
            if roles and not user.has_admin_role(*roles):
                return jsonify({'code': 0, 'message': 'Your admin role does not allow this action'}), 403
            if not user.is_account_active():
                return account_blocked_response(user)
            return fn(user, *args, **kwargs)
        return wrapper
    return decorator
