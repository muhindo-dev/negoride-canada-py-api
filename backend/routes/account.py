"""Account status for the user (spec §15). Reachable while suspended.

GET  /api/account/status     reason category, end date, can_appeal, go-online gate
POST /api/account/appeal     {message, subject?} → support ticket of type 'appeal'
"""
from flask import Blueprint, request

from backend.models import db
from backend.services import account_service as A  # noqa: F401 — registers the trip after-hook
from backend.services import support_service as SS
from backend.utils.auth import jwt_required_with_user
from backend.utils.idempotency import idempotent
from backend.utils.response import error_response, success_response

account_bp = Blueprint('account', __name__)


@account_bp.route('/api/account/status', methods=['GET'])
@jwt_required_with_user
def status(user):
    return success_response('Account status', A.status_payload(user))


@account_bp.route('/api/account/appeal', methods=['POST'])
@jwt_required_with_user
@idempotent
def appeal(user):
    d = request.get_json(silent=True) or request.form or {}
    message = (d.get('message') or d.get('body') or '').strip()
    if not message:
        return error_response('Tell us why you think this decision should be reviewed.',
                              data={'error_code': 'body_required'})
    try:
        t, created = SS.open_appeal(user, message, d.get('subject'))
    except SS.SupportError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code})
    db.session.commit()
    return success_response('Your appeal was sent. We usually reply within 24 hours.' if created
                            else 'Your message was added to your open appeal.',
                            {'ticket': SS.ticket_dict(t, with_messages=True), 'created': created},
                            status_code=201 if created else 200)
