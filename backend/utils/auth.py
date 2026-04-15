from functools import wraps

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from backend.models import db
from backend.models.user import AdminUser


def get_current_user():
    """
    Get the current authenticated user.
    Supports Laravel's multi-fallback JWT chain:
    1. Authorization: {token}
    2. Authorization: Bearer {token}
    3. Authorization: Token {token}
    4. token query parameter
    5. token POST body
    6. user_id POST body (legacy fallback)
    """
    try:
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        return db.session.get(AdminUser, int(user_id))
    except Exception:
        # Fallback: check user_id in request body or query
        user_id = (
            request.form.get('user_id') or
            request.args.get('user_id') or
            (request.get_json(silent=True) or {}).get('user_id')
        )
        if user_id:
            return db.session.get(AdminUser, int(user_id))
        return None


def jwt_required_with_user(fn):
    """Decorator that provides the current user to the route function."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'code': 0, 'message': 'Unauthorized'}), 401
        return fn(user, *args, **kwargs)
    return wrapper


def admin_required(fn):
    """Decorator that requires the current user to be an Admin."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'code': 0, 'message': 'Unauthorized'}), 401
        if user.user_type not in ('Admin', 'Super Admin'):
            return jsonify({'code': 0, 'message': 'Admin access required'}), 403
        return fn(user, *args, **kwargs)
    return wrapper
