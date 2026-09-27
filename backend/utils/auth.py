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


def issue_token(user):
    """Create an access token carrying the user's token_version (`tv`) so an
    admin deactivation (which bumps token_version) revokes every session."""
    return create_access_token(identity=str(user.id),
                               additional_claims={'tv': int(user.token_version or 0)})


def _token_version_ok(user, claims):
    return int(claims.get('tv', 0) or 0) == int(user.token_version or 0)


def user_from_token(token):
    """Decode a raw JWT (sockets / query tokens). Returns the user or None."""
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
    return user


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
        if not _token_version_ok(user, get_jwt()):
            return None
    except Exception:
        return None
    return user


def account_blocked_response(user):
    st = user.effective_account_status()
    return jsonify({
        'code': 0,
        'message': 'Your account is ' + st.replace('_', ' ') + '.',
        'data': {
            'account_status': st,
            'status_reason_code': user.status_reason_code,
            'suspended_until': user.suspended_until.strftime('%Y-%m-%dT%H:%M:%SZ') if user.suspended_until else None,
            'can_appeal': st in ('suspended', 'deactivated', 'banned'),
        },
    }), 403


def _inactive_allowed():
    path = request.path or ''
    return any(path.startswith(p) for p in INACTIVE_ALLOWED_PREFIXES)


def jwt_required_with_user(fn):
    """Decorator that provides the current user to the route function."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'code': 0, 'message': 'Unauthorized'}), 401
        if not user.is_account_active() and not _inactive_allowed():
            return account_blocked_response(user)
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
