"""Notification dispatcher (spec §5.2).

    from backend.services.notify import notify
    notify('ride.driver_arrived', [customer_id], {'pin': '4821', ...})

`notify()` never blocks the request: it queues `notify_now` to run after the
current DB transaction commits. `notify_now` (a job) then, per recipient:
  1. renders EN/FR copy from the catalogue,
  2. stores the inbox row (`notifications`) — every notification lands in the inbox,
  3. applies preferences + quiet hours (mandatory groups always go out),
  4. creates one `notification_deliveries` row per channel and delivers it,
     retrying failures with exponential backoff (3 attempts),
  5. for critical events, schedules an SMS escalation if the push is not
     opened within 60 s.
"""
import logging
from datetime import datetime, timedelta

from jinja2 import Environment, Undefined

from backend import jobs
from backend.models import db
from backend.models.notification import Notification, NotificationDelivery, NotificationPreference
from backend.models.user import AdminUser
from backend.services import settings_service as S
from backend.services.notify import catalogue as C

log = logging.getLogger('negoride.notify')

MAX_ATTEMPTS = 3
BACKOFF_S = (0, 20, 90)          # delay before attempt 1, 2, 3
ESCALATE_AFTER_S = 60

_env = Environment(undefined=Undefined, autoescape=False)


def template_for(spec, event_key, lang):
    """(title, body) templates: an admin override (notification_template_overrides)
    wins over the catalogue copy; empty override fields fall back."""
    title, body = spec['title'].get(lang) or spec['title']['en'], spec['body'].get(lang) or spec['body']['en']
    try:
        from backend.models.notification import NotificationTemplateOverride as O
        row = O.query.filter_by(event_key=event_key, lang=lang).first()
        if row is not None:
            title = row.title if row.title not in (None, '') else title
            body = row.body if row.body not in (None, '') else body
    except Exception:
        db.session.rollback()
    return title, body


def render(template, context):
    if not template:
        return ''
    try:
        return _env.from_string(template).render(**context).strip()
    except Exception as exc:  # never fail a notification on a template bug
        log.warning('Template render failed: %s', exc)
        return template


def lang_of(user):
    lang = (getattr(user, 'preferred_language', None) or 'en').lower()[:2]
    return 'fr' if lang == 'fr' else 'en'


def notify(event_key, user_ids, context=None, *, delay_s=0, dedupe_key=None):
    """Queue a notification (after the current transaction commits)."""
    C.get(event_key)  # validate early
    ids = sorted({int(u) for u in (user_ids or []) if u})
    if not ids:
        return
    if not S.flag('notifications_v4'):
        # Legacy behaviour: plain OneSignal push only.
        jobs.enqueue_after_commit(_legacy_push, event_key, ids, context or {}, delay_s=delay_s)
        return
    jobs.enqueue_after_commit(notify_now, event_key, ids, context or {}, dedupe_key, delay_s=delay_s)


def _legacy_push(event_key, user_ids, context):
    from backend.services.notification_service import send_push
    spec = C.get(event_key)
    send_push(user_ids=user_ids, title=render(spec['title']['en'], context),
              message=render(spec['body']['en'], context), data={'event': event_key})


def _prefs(user_id):
    return {p.event_group: p for p in NotificationPreference.query.filter_by(user_id=user_id).all()}


def _in_quiet_hours(pref, now_local):
    if not pref or not pref.quiet_start or not pref.quiet_end:
        return False
    cur = now_local.strftime('%H:%M')
    s, e = pref.quiet_start, pref.quiet_end
    return (s <= cur < e) if s < e else (cur >= s or cur < e)


def _local_now(user):
    now = datetime.utcnow()
    tz = getattr(user, 'timezone', None)
    if tz:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
        except Exception:
            pass
    return now


def channels_for(spec, user, prefs):
    """Apply preferences. Mandatory groups ignore mutes and quiet hours."""
    group = spec['group']
    chans = [c for c in spec['channels'] if c != 'inbox']
    if group in C.MANDATORY_GROUPS or spec['critical']:
        return chans
    pref = prefs.get(group)
    quiet = _in_quiet_hours(pref, _local_now(user))
    out = []
    for c in chans:
        if c == 'socket':
            out.append(c)
            continue
        if pref is not None and not getattr(pref, c, True):
            continue
        if quiet and c in ('push', 'sms'):
            continue
        out.append(c)
    return out


def notify_now(event_key, user_ids, context, dedupe_key=None):
    """Job: create inbox rows + deliveries and send them."""
    spec = C.get(event_key)
    created = []
    for uid in user_ids:
        user = db.session.get(AdminUser, uid)
        if not user:
            continue
        ctx = dict(context or {})
        per_user = ctx.pop('per_user', {}) or {}
        ctx.update(per_user.get(str(uid), per_user.get(uid, {})))
        lang = lang_of(user)
        t_tpl, b_tpl = template_for(spec, event_key, lang)
        title = render(t_tpl, ctx) or render(spec['title']['en'], ctx)
        body = render(b_tpl, ctx) or render(spec['body']['en'], ctx)
        route = render(spec['route'] or '', ctx) or None
        data = {k: v for k, v in ctx.items() if isinstance(v, (str, int, float, bool)) or v is None}
        data.update({'event': event_key, 'route': route})
        if dedupe_key:
            exists = Notification.query.filter_by(user_id=uid, event_key=event_key).filter(
                Notification.data['dedupe_key'].as_string() == str(dedupe_key)).first()
            if exists:
                continue
            data['dedupe_key'] = str(dedupe_key)
        n = Notification(user_id=uid, event_key=event_key, event_group=spec['group'], title=title or event_key,
                         body=body, data=data, deep_link=_deep_link(route, ctx), is_critical=spec['critical'])
        db.session.add(n)
        db.session.flush()
        n.data = {**data, 'notification_id': n.id}
        deliveries = [NotificationDelivery(notification_id=n.id, channel='inbox', status='delivered',
                                           attempts=1, sent_at=datetime.utcnow(), delivered_at=datetime.utcnow())]
        for ch in channels_for(spec, user, _prefs(uid)):
            if ch == 'live_activity' and not _has_live_activity(uid, ctx):
                continue       # only iOS riders with a registered activity for this ride
            if ch == 'email' and getattr(user, 'email_bounced_at', None):
                continue       # hard bounce / spam complaint → email suppressed (inbox still has it)
            deliveries.append(NotificationDelivery(notification_id=n.id, channel=ch, status='queued'))
        db.session.add_all(deliveries)
        db.session.commit()
        created.append(n.id)
        for d in deliveries:
            if d.channel != 'inbox':
                deliver(d.id)
        # Every critical event that goes out by push escalates to SMS when the
        # push isn't opened in time (spec §5.2) — not only the sms_fallback ones.
        if spec['critical'] and S.flag('sms_fallback') \
                and any(d.channel == 'push' for d in deliveries) \
                and not any(d.channel == 'sms' for d in deliveries):
            jobs.enqueue_in(ESCALATE_AFTER_S, escalate_if_unopened, n.id)
    return created


def _has_live_activity(user_id, ctx):
    from backend.services.notify import live_activity
    return live_activity.enabled() and live_activity.has_active(user_id, ctx.get('ride_type'), ctx.get('ride_id'))


def admin_ids(roles=('ops',)):
    """Active admin users holding any of `roles` (super_admin always included;
    legacy Admin / Super Admin users count as super_admin)."""
    from sqlalchemy import or_
    conds = [AdminUser.user_type.in_(('Admin', 'Super Admin')), AdminUser.admin_roles.like('%super_admin%')]
    for r in roles or ():
        conds.append(AdminUser.admin_roles.like(f'%{r}%'))
    q = AdminUser.query.filter(or_(*conds), AdminUser.deleted_at.is_(None), AdminUser.status == 1)
    out = []
    for u in q.limit(500):
        mine = u.get_admin_roles()
        if 'super_admin' in mine or any(r in mine for r in (roles or ())):
            out.append(u.id)
    return out


def notify_admins(event_key, context=None, roles=('ops',), *, dedupe_key=None, realtime_event=None):
    """Notify the ops console: every admin with one of `roles` gets the catalogue
    event (inbox + push + email per the catalogue), and the admin socket room
    gets `realtime_event` (default: the event key). Queued after commit.

        notify_admins('admin.background_check_review', {'user_id': 42, 'name': 'Sam',
                      'result': 'consider', 'check_id': 7}, roles=('ops', 'safety_reviewer'))
    """
    ids = admin_ids(roles)
    if ids:
        notify(event_key, ids, context, dedupe_key=dedupe_key)
    from backend.services import realtime
    jobs.enqueue_after_commit(realtime.to_admins, realtime_event or event_key, dict(context or {}))
    return ids


def _deep_link(route, ctx):
    if not route:
        return None
    rid = ctx.get('ride_id')
    rtype = ctx.get('ride_type')
    if rid and rtype:
        return f'negoride://{route}/{rtype}/{rid}'
    if ctx.get('id'):
        return f"negoride://{route}/{ctx['id']}"
    return f'negoride://{route}'


def deliver(delivery_id):
    """Send one delivery through its channel (with retry scheduling)."""
    from backend.services.notify import channels
    d = db.session.get(NotificationDelivery, delivery_id)
    if not d or d.status in ('sent', 'delivered', 'opened'):
        return
    n = db.session.get(Notification, d.notification_id)
    user = db.session.get(AdminUser, n.user_id) if n else None
    if not n or not user:
        d.status, d.error = 'failed', 'recipient missing'
        db.session.commit()
        return
    d.attempts = (d.attempts or 0) + 1
    try:
        spec = C.get(n.event_key)
        provider_id = channels.send(d.channel, n, user, spec)
        d.provider_message_id = provider_id
        d.status = 'delivered' if d.channel == 'socket' else 'sent'
        d.sent_at = datetime.utcnow()
        if d.channel == 'socket':
            d.delivered_at = d.sent_at
        d.error = None
        d.next_attempt_at = None
    except channels.PermanentFailure as exc:
        d.status, d.error, d.failed_at = 'failed', str(exc)[:1000], datetime.utcnow()
    except Exception as exc:
        d.error = str(exc)[:1000]
        if d.attempts >= MAX_ATTEMPTS:
            d.status, d.failed_at = 'failed', datetime.utcnow()
        else:
            d.status = 'retrying'
            d.next_attempt_at = datetime.utcnow() + timedelta(seconds=BACKOFF_S[d.attempts])
    db.session.commit()


def retry_due():
    """Periodic: re-run deliveries whose backoff elapsed (covers thread mode and restarts)."""
    due = (NotificationDelivery.query
           .filter(NotificationDelivery.status == 'retrying',
                   NotificationDelivery.next_attempt_at <= datetime.utcnow())
           .limit(200).all())
    for d in due:
        deliver(d.id)
    # queued deliveries stuck for > 2 min (worker restarted mid-flight)
    stale = (NotificationDelivery.query
             .filter(NotificationDelivery.status == 'queued',
                     NotificationDelivery.queued_at <= datetime.utcnow() - timedelta(minutes=2))
             .limit(200).all())
    for d in stale:
        deliver(d.id)
    return len(due) + len(stale)


def escalate_if_unopened(notification_id):
    """Critical event: push not opened in time → SMS fallback (spec §5.2)."""
    n = db.session.get(Notification, notification_id)
    if not n or n.opened_at or n.read_at:
        return False
    push = [d for d in n.deliveries if d.channel == 'push']
    if any(d.opened_at for d in push):
        return False
    if any(d.channel == 'sms' for d in n.deliveries):
        return False
    d = NotificationDelivery(notification_id=n.id, channel='sms', status='queued')
    db.session.add(d)
    db.session.commit()
    deliver(d.id)
    return True


def mark_opened(user_id, notification_id):
    """App reports a tap / foreground display (socket ack or HTTP)."""
    n = Notification.query.filter_by(id=int(notification_id), user_id=int(user_id)).first()
    if not n:
        return None
    now = datetime.utcnow()
    n.opened_at = n.opened_at or now
    n.read_at = n.read_at or now
    for d in n.deliveries:
        if d.channel in ('push', 'socket') and d.status in ('sent', 'delivered'):
            d.status = 'opened'
            d.opened_at = now
    db.session.commit()
    return n
