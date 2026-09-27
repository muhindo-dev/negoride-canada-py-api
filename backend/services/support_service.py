"""Support tickets and appeals (spec §15 appeal button, §19.1.8 Disputes & Support).

SLA: `sla_due_at` = creation + support.sla_<priority>_h (first response).
The first admin reply stamps `first_response_at`. Safety tickets default to
high priority, everything else to normal.
"""
from datetime import datetime, timedelta

from backend.models import db
from backend.models.identity import SupportTicket, SupportTicketMessage
from backend.models.user import AdminUser
from backend.services import settings_service as S

TYPES = ('general', 'appeal', 'dispute', 'lost_item', 'safety', 'billing')
PRIORITIES = ('low', 'normal', 'high', 'urgent')
STATUSES = ('open', 'pending', 'resolved', 'closed')
DEFAULT_PRIORITY = {'safety': 'high', 'appeal': 'normal', 'dispute': 'normal', 'billing': 'normal',
                    'lost_item': 'high', 'general': 'normal'}


class SupportError(Exception):
    def __init__(self, message, code='support_error', status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def sla_hours(priority):
    return S.get_int(f'support.sla_{priority}_h') or 24


def sla_due(priority, start=None):
    return (start or datetime.utcnow()) + timedelta(hours=sla_hours(priority))


def _iso(v):
    return v.strftime('%Y-%m-%dT%H:%M:%SZ') if v else None


def ticket_dict(t, with_messages=False, include_internal=False, user=None):
    d = t.to_dict()
    now = datetime.utcnow()
    responded = t.first_response_at is not None
    d['sla'] = {
        'due_at': _iso(t.sla_due_at), 'first_response_at': _iso(t.first_response_at),
        'breached': bool(t.sla_due_at and ((t.first_response_at or now) > t.sla_due_at)),
        'remaining_s': int((t.sla_due_at - now).total_seconds()) if (t.sla_due_at and not responded) else None,
    }
    if user is not None:
        d['user'] = {'id': user.id, 'name': user.name, 'user_type': user.user_type,
                     'account_status': user.effective_account_status()}
    if with_messages:
        q = SupportTicketMessage.query.filter_by(ticket_id=t.id)
        if not include_internal:
            q = q.filter(SupportTicketMessage.author_type != 'internal')
        d['messages'] = [m.to_dict() for m in q.order_by(SupportTicketMessage.id)]
    return d


def create_ticket(user, type_='general', subject=None, body=None, priority=None, ride_type=None, ride_id=None,
                  attachments=None):
    type_ = (type_ or 'general').lower()
    if type_ not in TYPES:
        raise SupportError('Unknown ticket type.', 'invalid_type')
    priority = (priority or DEFAULT_PRIORITY.get(type_, 'normal')).lower()
    if priority not in PRIORITIES:
        priority = 'normal'
    if priority == 'urgent' and type_ != 'safety':
        priority = 'high'   # users cannot self-assign urgent outside safety
    body = (body or '').strip()
    if not body:
        raise SupportError('Please describe the issue.', 'body_required')
    subject = (subject or '').strip()[:200] or {
        'appeal': 'Account appeal', 'dispute': 'Trip dispute', 'lost_item': 'Lost item', 'safety': 'Safety issue',
        'billing': 'Billing question'}.get(type_, 'Support request')
    now = datetime.utcnow()
    t = SupportTicket(user_id=user.id, type=type_, subject=subject, body=body, priority=priority, status='open',
                      ride_type=ride_type, ride_id=int(ride_id) if ride_id else None, sla_due_at=sla_due(priority, now),
                      created_at=now)
    db.session.add(t)
    db.session.flush()
    db.session.add(SupportTicketMessage(ticket_id=t.id, author_id=user.id, author_type='user', body=body,
                                        attachments=attachments or None, created_at=now))
    return t


def add_message(ticket, author, body, author_type='user', attachments=None):
    body = (body or '').strip()
    if not body:
        raise SupportError('Message cannot be empty.', 'body_required')
    now = datetime.utcnow()
    m = SupportTicketMessage(ticket_id=ticket.id, author_id=author.id, author_type=author_type, body=body,
                             attachments=attachments or None, created_at=now)
    db.session.add(m)
    ticket.updated_at = now
    if author_type == 'admin':
        if ticket.first_response_at is None:
            ticket.first_response_at = now
        if ticket.status == 'open':
            ticket.status = 'pending'
        from backend.services.notify import notify
        notify('support.reply', [ticket.user_id], {'subject': ticket.subject, 'ticket_id': ticket.id})
    elif author_type == 'user' and ticket.status in ('pending', 'resolved'):
        ticket.status = 'open'
    db.session.flush()
    return m


def open_appeal(user, body, subject=None):
    existing = (SupportTicket.query.filter_by(user_id=user.id, type='appeal')
                .filter(SupportTicket.status.in_(('open', 'pending'))).first())
    if existing:
        add_message(existing, user, body, 'user')
        return existing, False
    from backend.services.account_service import reason_label
    st = user.effective_account_status()
    subj = subject or f'Appeal: account {st.replace("_", " ")}' + (
        f' ({reason_label(user.status_reason_code)})' if user.status_reason_code else '')
    return create_ticket(user, 'appeal', subj, body), True


def user_of(ticket):
    return db.session.get(AdminUser, ticket.user_id)
