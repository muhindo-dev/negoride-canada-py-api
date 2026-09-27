"""User support tickets (spec §19.1.8). Suspended users may use these (appeals).

GET  /api/support/tickets?status=           my tickets
POST /api/support/tickets                   {type, subject?, body, priority?, ride_type?, ride_id?}
GET  /api/support/tickets/<id>              ticket + messages
POST /api/support/tickets/<id>/reply        {body}
POST /api/support/tickets/<id>/close
"""
from datetime import datetime

from flask import Blueprint, request

from backend.models import db
from backend.models.identity import SupportTicket
from backend.services import support_service as SS
from backend.utils.auth import jwt_required_with_user
from backend.utils.idempotency import idempotent
from backend.utils.response import error_response, success_response

support_bp = Blueprint('support', __name__)


def _body():
    return request.get_json(silent=True) or request.form or {}


def _mine(user, ticket_id):
    t = db.session.get(SupportTicket, ticket_id)
    return t if t and t.user_id == user.id else None


@support_bp.route('/api/support/tickets', methods=['GET'])
@jwt_required_with_user
def my_tickets(user):
    q = SupportTicket.query.filter_by(user_id=user.id)
    if request.args.get('status'):
        q = q.filter_by(status=request.args['status'])
    rows = q.order_by(SupportTicket.id.desc()).limit(100).all()
    return success_response('Tickets', {'items': [SS.ticket_dict(t) for t in rows]})


@support_bp.route('/api/support/tickets', methods=['POST'])
@jwt_required_with_user
@idempotent
def create(user):
    d = _body()
    try:
        t = SS.create_ticket(user, d.get('type'), d.get('subject'), d.get('body') or d.get('message'),
                             d.get('priority'), d.get('ride_type'), d.get('ride_id'), d.get('attachments'))
    except SS.SupportError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    db.session.commit()
    return success_response('Thanks — our team will get back to you.', SS.ticket_dict(t, with_messages=True),
                            status_code=201)


@support_bp.route('/api/support/tickets/<int:ticket_id>', methods=['GET'])
@jwt_required_with_user
def detail(user, ticket_id):
    t = _mine(user, ticket_id)
    if not t:
        return error_response('Ticket not found.', status_code=404)
    return success_response('Ticket', SS.ticket_dict(t, with_messages=True))


@support_bp.route('/api/support/tickets/<int:ticket_id>/reply', methods=['POST'])
@jwt_required_with_user
def reply(user, ticket_id):
    t = _mine(user, ticket_id)
    if not t:
        return error_response('Ticket not found.', status_code=404)
    if t.status == 'closed':
        return error_response('This ticket is closed. Open a new one if you still need help.',
                              data={'error_code': 'ticket_closed'})
    d = _body()
    try:
        SS.add_message(t, user, d.get('body') or d.get('message'), 'user', d.get('attachments'))
    except SS.SupportError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code})
    db.session.commit()
    return success_response('Message sent.', SS.ticket_dict(t, with_messages=True))


@support_bp.route('/api/support/tickets/<int:ticket_id>/close', methods=['POST'])
@jwt_required_with_user
def close(user, ticket_id):
    t = _mine(user, ticket_id)
    if not t:
        return error_response('Ticket not found.', status_code=404)
    t.status, t.closed_by, t.resolved_at = 'closed', user.id, t.resolved_at or datetime.utcnow()
    db.session.commit()
    return success_response('Ticket closed.', SS.ticket_dict(t))
