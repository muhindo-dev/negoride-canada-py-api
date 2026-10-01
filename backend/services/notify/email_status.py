"""Delivery-status webhooks (Twilio SMS status, Postmark email events) and email
suppression after hard bounces / spam complaints (spec §5.2, §13.1).

Webhook routes only verify + persist a `webhook_events` row (status
'received') and enqueue the processors below; failures are retried by
`platform_jobs.retry_failed_webhooks` (providers 'twilio_status', 'postmark').

Suppression
  • a Postmark hard bounce (HardBounce, BadEmailAddress, ManuallyDeactivated,
    Inactive=true) or a SpamComplaint sets users.email_bounced_at /
    email_bounce_reason — the email channel and receipt emails are then skipped
    for that user (the inbox still gets everything);
  • `clear_email_bounce(user)` lifts it. Call it whenever the user changes or
    verifies their email address (identity/profile code).
"""
import json
import logging
from datetime import datetime

from backend.models import db
from backend.models.notification import Notification, NotificationDelivery
from backend.models.platform import WebhookEvent
from backend.models.user import AdminUser

log = logging.getLogger('negoride.notify.status')

HARD_BOUNCE_TYPES = ('HardBounce', 'BadEmailAddress', 'ManuallyDeactivated', 'SpamNotification', 'Blocked')


# ── suppression helpers (public — other modules call these) ────────────────

def is_email_suppressed(user):
    return bool(user is not None and getattr(user, 'email_bounced_at', None))


def mark_email_bounced(user, reason):
    if user is None or user.email_bounced_at:
        return False
    user.email_bounced_at = datetime.utcnow()
    user.email_bounce_reason = (reason or 'bounced')[:255]
    from backend.services.audit import audit
    audit('user.email_suppressed', None, 'user', user.id, actor_type='system',
          meta={'reason': user.email_bounce_reason, 'email': user.email})
    return True


def clear_email_bounce(user, commit=False):
    """Hook for the identity/profile code: call after the user changes or
    verifies their email so emails flow again. Returns True if a suppression
    was lifted. The caller commits (or pass commit=True)."""
    if user is None or not getattr(user, 'email_bounced_at', None):
        return False
    user.email_bounced_at = None
    user.email_bounce_reason = None
    if commit:
        db.session.commit()
    return True


# ── processors (jobs) ───────────────────────────────────────────────────────

def _start(webhook_event_id):
    row = db.session.get(WebhookEvent, webhook_event_id)
    if not row or row.status == 'processed':
        return None
    row.attempts = (row.attempts or 0) + 1
    return row


def _finish(row, error=None):
    row.status = 'failed' if error else 'processed'
    row.error = str(error)[:2000] if error else None
    row.processed_at = None if error else datetime.utcnow()
    db.session.commit()


def process_twilio_status(webhook_event_id):
    row = _start(webhook_event_id)
    if row is None:
        return
    try:
        form = json.loads(row.payload or '{}')
        sid, status = form.get('MessageSid', ''), form.get('MessageStatus', '')
        d = NotificationDelivery.query.filter_by(provider_message_id=sid).first() if sid else None
        if d:
            if status == 'delivered':
                d.status, d.delivered_at = 'delivered', datetime.utcnow()
            elif status in ('failed', 'undelivered'):
                d.status, d.failed_at = 'failed', datetime.utcnow()
                d.error = f"Twilio {status} {form.get('ErrorCode') or ''}".strip()
        _finish(row)
    except Exception as exc:
        db.session.rollback()
        _finish(db.session.get(WebhookEvent, webhook_event_id), exc)
        raise


def process_postmark_event(webhook_event_id):
    row = _start(webhook_event_id)
    if row is None:
        return
    try:
        ev = json.loads(row.payload or '{}')
        kind = ev.get('RecordType', '')
        mid = ev.get('MessageID', '')
        now = datetime.utcnow()
        d = NotificationDelivery.query.filter_by(provider_message_id=mid, channel='email').first() if mid else None
        if d:
            if kind == 'Delivery':
                d.status, d.delivered_at = ('opened' if d.status == 'opened' else 'delivered'), now
            elif kind == 'Open':
                d.status, d.opened_at = 'opened', now
            elif kind in ('Bounce', 'SpamComplaint'):
                d.status, d.failed_at = 'failed', now
                d.error = f"{kind}: {ev.get('Type') or ''} {ev.get('Description') or ''}"[:1000]
        hard = kind == 'SpamComplaint' or (kind == 'Bounce' and (ev.get('Type') in HARD_BOUNCE_TYPES
                                                                  or ev.get('Inactive') is True))
        if hard:
            for user in _users_for(ev.get('Email'), d):
                mark_email_bounced(user, f"{kind}: {ev.get('Type') or kind}")
        _finish(row)
    except Exception as exc:
        db.session.rollback()
        _finish(db.session.get(WebhookEvent, webhook_event_id), exc)
        raise


def _users_for(email, delivery):
    users = []
    if email:
        users = AdminUser.query.filter(AdminUser.email == email.strip()).all()
    if not users and delivery is not None:
        n = db.session.get(Notification, delivery.notification_id)
        u = db.session.get(AdminUser, n.user_id) if n else None
        if u:
            users = [u]
    return users
