"""Notification inbox, preferences, device registration and app config (spec §5).

    GET  /api/notifications?page=&per_page=&unread=1
    GET  /api/notifications/unread-count
    POST /api/notifications/{id}/read
    POST /api/notifications/{id}/opened          (push tap / foreground display)
    POST /api/notifications/read-all
    GET  /api/notification-preferences
    PUT  /api/notification-preferences           {groups: {negotiation: {push, sms, email}}, quiet_start, quiet_end}
    POST /api/devices/register                   {device_id, platform, app_version, onesignal_subscription_id, locale, timezone}
    GET  /api/app/config                         public settings / feature flags (no auth)
    POST /api/devices/live-activity              {ride_type, ride_id, activity_id, push_token} (iOS Live Activity)
    DELETE /api/devices/live-activity/{activity_id}
    POST /api/webhooks/twilio/status             Twilio message status callback (signed) → job
    POST /api/webhooks/postmark                  Postmark delivery/open/bounce/spam (basic auth) → job
"""
import base64
import hashlib
import hmac
import os
from datetime import datetime

from flask import Blueprint, request

from backend.models import db
from backend.models.notification import DeviceToken, Notification, NotificationDelivery, NotificationPreference
from backend.services import settings_service as S
from backend.services.notify import catalogue as C
from backend.services.notify import mark_opened
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import error_response, paginated_response, success_response

notifications_bp = Blueprint('notifications', __name__)


def _body():
    return request.get_json(silent=True) or request.form or {}


@notifications_bp.route('/api/notifications', methods=['GET'])
@jwt_required_with_user
def inbox(user):
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, max(1, request.args.get('per_page', 30, type=int)))
    q = Notification.query.filter_by(user_id=user.id)
    if request.args.get('unread') in ('1', 'true'):
        q = q.filter(Notification.read_at.is_(None))
    total = q.count()
    rows = q.order_by(Notification.created_at.desc(), Notification.id.desc()) \
        .offset((page - 1) * per_page).limit(per_page).all()
    return paginated_response([r.to_dict() for r in rows], total, page, per_page)


@notifications_bp.route('/api/notifications/unread-count', methods=['GET'])
@jwt_required_with_user
def unread_count(user):
    n = Notification.query.filter_by(user_id=user.id).filter(Notification.read_at.is_(None)).count()
    return success_response('Unread', {'unread': n})


@notifications_bp.route('/api/notifications/<int:nid>/read', methods=['POST'])
@jwt_required_with_user
def read_one(user, nid):
    n = Notification.query.filter_by(id=nid, user_id=user.id).first()
    if not n:
        return error_response('Notification not found', status_code=404)
    n.read_at = n.read_at or datetime.utcnow()
    db.session.commit()
    return success_response('Marked as read', n.to_dict())


@notifications_bp.route('/api/notifications/<int:nid>/opened', methods=['POST'])
@jwt_required_with_user
def opened(user, nid):
    n = mark_opened(user.id, nid)
    if not n:
        return error_response('Notification not found', status_code=404)
    return success_response('Opened', n.to_dict())


@notifications_bp.route('/api/notifications/read-all', methods=['POST'])
@jwt_required_with_user
def read_all(user):
    count = Notification.query.filter_by(user_id=user.id).filter(Notification.read_at.is_(None)) \
        .update({Notification.read_at: datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return success_response('All read', {'updated': count})


def _prefs_payload(user):
    rows = {p.event_group: p for p in NotificationPreference.query.filter_by(user_id=user.id)}
    groups = []
    quiet = next((p for p in rows.values() if p.quiet_start), None)
    for g in C.ALL_GROUPS:
        p = rows.get(g)
        mandatory = g in C.MANDATORY_GROUPS
        groups.append({
            'group': g, 'mandatory': mandatory,
            'push': True if mandatory else (p.push if p else True),
            'sms': True if mandatory else (p.sms if p else True),
            'email': True if mandatory else (p.email if p else (g != 'marketing' or bool(user.marketing_opt_in))),
        })
    return {'groups': groups, 'quiet_start': quiet.quiet_start if quiet else None,
            'quiet_end': quiet.quiet_end if quiet else None, 'marketing_opt_in': bool(user.marketing_opt_in)}


@notifications_bp.route('/api/notification-preferences', methods=['GET'])
@jwt_required_with_user
def get_prefs(user):
    return success_response('Preferences', _prefs_payload(user))


@notifications_bp.route('/api/notification-preferences', methods=['PUT', 'POST'])
@jwt_required_with_user
def put_prefs(user):
    data = _body()
    groups = data.get('groups') or {}
    qs, qe = data.get('quiet_start'), data.get('quiet_end')
    import re
    for v in (qs, qe):
        if v and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', str(v)):
            return error_response('Quiet hours must be HH:MM (24 h).')
    for g in C.MUTABLE_GROUPS:
        conf = groups.get(g)
        p = NotificationPreference.query.filter_by(user_id=user.id, event_group=g).first()
        if conf is None and 'quiet_start' not in data:
            continue
        if not p:
            p = NotificationPreference(user_id=user.id, event_group=g)
            db.session.add(p)
        if isinstance(conf, dict):
            for ch in ('push', 'sms', 'email'):
                if ch in conf:
                    setattr(p, ch, bool(conf[ch]))
        if 'quiet_start' in data:
            p.quiet_start, p.quiet_end = (qs or None), (qe or None)
    if 'marketing_opt_in' in data:
        opt = data.get('marketing_opt_in') in (True, 'true', '1', 1, 'yes', 'on')
        if opt and not user.marketing_opt_in:
            user.marketing_opt_in_at = datetime.utcnow()
        if opt != bool(user.marketing_opt_in):
            # CASL proof: every grant / withdrawal with ip, user agent, wording version + text
            from backend.services import legal_service
            from backend.utils.client_info import app_version, client_ip, user_agent
            legal_service.record_marketing_consent(user, opt, 'preferences', ip=client_ip(), user_agent=user_agent(),
                                                   app_version=app_version(data), lang=user.preferred_language,
                                                   wording_version=data.get('marketing_consent_version'))
        user.marketing_opt_in = opt
    db.session.commit()
    return success_response('Preferences saved', _prefs_payload(user))


@notifications_bp.route('/api/devices/register', methods=['POST'])
@jwt_required_with_user
def register_device(user):
    data = _body()
    device_id = (data.get('device_id') or '').strip()[:191]
    if not device_id:
        return error_response('device_id is required')
    row = DeviceToken.query.filter_by(user_id=user.id, device_id=device_id).first()
    if not row:
        row = DeviceToken(user_id=user.id, device_id=device_id)
        db.session.add(row)
    row.platform = (data.get('platform') or '')[:20] or row.platform
    row.app_version = (data.get('app_version') or request.headers.get('X-App-Version') or '')[:30] or row.app_version
    row.os_version = (data.get('os_version') or '')[:60] or row.os_version
    row.onesignal_subscription_id = (data.get('onesignal_subscription_id') or '')[:191] or row.onesignal_subscription_id
    row.locale = (data.get('locale') or '')[:10] or row.locale
    row.timezone = (data.get('timezone') or '')[:60] or row.timezone
    row.last_seen_at = datetime.utcnow()
    if row.timezone and not user.timezone:
        user.timezone = row.timezone
    if row.locale and not user.preferred_language:
        user.preferred_language = row.locale[:2].lower()
    db.session.commit()
    return success_response('Device registered', row.to_dict())


@notifications_bp.route('/api/app/config', methods=['GET'])
def app_config():
    cfg = S.public_config()
    return success_response('Config', {
        'settings': cfg,
        'flags': {k[3:]: v for k, v in cfg.items() if k.startswith('ff.')},
        'notification_groups': {'mandatory': list(C.MANDATORY_GROUPS), 'mutable': list(C.MUTABLE_GROUPS)},
        'android_channels': list(C.ANDROID_CHANNELS),
        'services': S.enabled_services(),
        'server_time': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'socket': {'namespace': '/rt', 'path': '/socket.io'},
    })


# ── Twilio delivery status callback ─────────────────────────────────────────

def _twilio_signature_ok():
    token = os.getenv('TWILIO_AUTH_TOKEN', '')
    sig = request.headers.get('X-Twilio-Signature', '')
    if not token or not sig:
        return False
    url = os.getenv('TWILIO_STATUS_CALLBACK_URL') or request.url
    payload = url + ''.join(f'{k}{v}' for k, v in sorted(request.form.items()))
    digest = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(digest, sig)


def _persist_and_enqueue(provider, event_id, event_type, payload, processor):
    """Spec §2.5: persist the raw event first (unique id → replays are no-ops),
    then process it in a job. Failures retry via platform_jobs."""
    import json
    from backend import jobs
    from backend.models.platform import WebhookEvent
    event_id = (event_id or '')[:191]
    if WebhookEvent.query.filter_by(provider=provider, event_id=event_id).first():
        return
    row = WebhookEvent(provider=provider, event_id=event_id, event_type=(event_type or '')[:120],
                       payload=json.dumps(payload), signature_valid=True, status='received',
                       received_at=datetime.utcnow())
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()   # concurrent duplicate
        return
    jobs.enqueue(processor, row.id)


@notifications_bp.route('/api/webhooks/twilio/status', methods=['POST'])
def twilio_status():
    if not _twilio_signature_ok():
        return error_response('Invalid signature', status_code=403)
    sid = request.form.get('MessageSid', '')
    status = request.form.get('MessageStatus', '')
    _persist_and_enqueue('twilio_status', f'{sid}:{status}', 'message.status', dict(request.form),
                         'backend.services.notify.email_status.process_twilio_status')
    return '', 204


# ── Email provider webhooks (opens / deliveries / bounces — spec §13.1) ─────

@notifications_bp.route('/api/webhooks/postmark', methods=['POST'])
def postmark_webhook():
    """Postmark Delivery / Open / Bounce / SpamComplaint webhooks. Protected by
    HTTP basic auth credentials configured on the webhook URL
    (POSTMARK_WEBHOOK_USER / POSTMARK_WEBHOOK_PASSWORD). Hard bounces and spam
    complaints suppress email for the user (users.email_bounced_at)."""
    user, pwd = os.getenv('POSTMARK_WEBHOOK_USER', ''), os.getenv('POSTMARK_WEBHOOK_PASSWORD', '')
    auth = request.authorization
    if not user or not auth or not (hmac.compare_digest(auth.username or '', user)
                                    and hmac.compare_digest(auth.password or '', pwd)):
        return error_response('Unauthorized', status_code=401)
    ev = request.get_json(silent=True) or {}
    kind = ev.get('RecordType', '')
    mid = ev.get('MessageID', '')
    ev_id = f"{mid}:{kind}:{ev.get('ID') or ev.get('ReceivedAt') or ev.get('DeliveredAt') or ev.get('BouncedAt') or ''}"
    _persist_and_enqueue('postmark', ev_id, kind, ev, 'backend.services.notify.email_status.process_postmark_event')
    return '', 204


# ── iOS Live Activities (spec §5.1) ─────────────────────────────────────────

@notifications_bp.route('/api/devices/live-activity', methods=['POST'])
@jwt_required_with_user
def register_live_activity(user):
    """The app started a Live Activity for a ride and registers its push token
    so the server can update it (stage, ETA) and end it on a terminal stage.
    Body: {ride_type, ride_id, activity_id, push_token}."""
    from backend.services.notify import live_activity as LA
    try:
        row = LA.register(user, _body())
    except LA.LiveActivityError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    return success_response('Live Activity registered', row.to_dict(), status_code=201)


@notifications_bp.route('/api/devices/live-activity/<activity_id>', methods=['DELETE'])
@jwt_required_with_user
def end_live_activity(user, activity_id):
    """The user dismissed the Live Activity: stop pushing to it."""
    from backend.services.notify import live_activity as LA
    n = LA.unregister(user, activity_id)
    return success_response('Live Activity removed', {'removed': n})
