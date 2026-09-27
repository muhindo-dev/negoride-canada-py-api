"""Delivery channels (spec §5.2): push (OneSignal), sms (Twilio), email, socket.

`send(channel, notification, user, spec)` returns a provider message id or
raises. PermanentFailure = don't retry (no address, not configured, opted out).
"""
import logging
import os

import requests

from backend.services import realtime

log = logging.getLogger('negoride.notify.channels')
PUSH_LOG = []  # test introspection


class PermanentFailure(Exception):
    pass


def send(channel, n, user, spec):
    if channel == 'push':
        return push_onesignal(n, user, spec)
    if channel == 'sms':
        return sms_twilio(n, user, spec)
    if channel == 'email':
        return email(n, user, spec)
    if channel == 'socket':
        return socket(n, user, spec)
    raise PermanentFailure(f'Unknown channel {channel}')


def _payload_data(n):
    data = dict(n.data or {})
    data.update({'notification_id': n.id, 'event': n.event_key, 'deep_link': n.deep_link})
    return data


# ── push ────────────────────────────────────────────────────────────────────

def push_onesignal(n, user, spec):
    app_id = os.getenv('ONESIGNAL_APP_ID', '56ef70cd-45a3-4a66-9838-3146fbbffe77')
    key = os.getenv('ONESIGNAL_REST_API_KEY', '')
    body = {
        'app_id': app_id,
        'include_aliases': {'external_id': [str(user.id)]},
        'target_channel': 'push',
        'headings': {'en': n.title},
        'contents': {'en': n.body or n.title},
        'data': _payload_data(n),
        'priority': 10,
        'ttl': 600 if spec['critical'] else 86400,
        'existing_android_channel_id': spec.get('android_channel') or 'ride_updates',
        'ios_interruption_level': 'time_sensitive' if spec['critical'] else 'active',
        'collapse_id': f"{n.event_key}:{(n.data or {}).get('ride_id', n.id)}"[:64],
    }
    if spec.get('sound'):
        body["ios_sound"] = f"{spec['sound']}.wav"
        body['android_sound'] = spec['sound']
    if os.getenv('NOTIFY_PUSH_DRY_RUN') == '1' or not key:
        PUSH_LOG.append(body)
        if not key:
            raise PermanentFailure('ONESIGNAL_REST_API_KEY not configured')
        return 'dry-run'
    r = requests.post('https://api.onesignal.com/notifications?c=push', json=body, timeout=10,
                      headers={'Authorization': f'Key {key}', 'Content-Type': 'application/json'})
    data = r.json() if r.content else {}
    if r.status_code >= 500:
        raise RuntimeError(f'OneSignal {r.status_code}')
    if r.status_code >= 400:
        raise PermanentFailure(f"OneSignal {r.status_code}: {data.get('errors')}")
    if not data.get('id'):
        # "id empty" = the user has no subscribed device. Not retryable.
        raise PermanentFailure(f"No push subscription for user {user.id}: {data.get('errors')}")
    return data['id']


# ── sms ─────────────────────────────────────────────────────────────────────

def sms_twilio(n, user, spec):
    from backend.services import twilio_client
    from backend.utils.phone import safe_normalize
    to = user.phone_e164 or safe_normalize(user.phone_number)
    if not to:
        raise PermanentFailure('User has no valid phone number')
    if getattr(user, 'sms_opt_out_at', None):
        raise PermanentFailure('User replied STOP (SMS opt-out)')
    text = n.body or n.title
    if not text.lower().startswith('negoride'):
        text = f'NegoRide: {text}'
    try:
        return twilio_client.send_sms(to, text)
    except twilio_client.TwilioError as exc:
        if exc.code == 'not_configured' or (exc.status and 400 <= exc.status < 500):
            raise PermanentFailure(str(exc))
        raise


# ── email ───────────────────────────────────────────────────────────────────

def email(n, user, spec):
    from backend.services.notify import email_provider
    from backend.services.notify.templates import render_email
    if not user.email:
        raise PermanentFailure('User has no email address')
    subject, html, text = render_email(spec.get('email_template') or 'generic', n, user)
    try:
        return email_provider.send(user.email, subject, html, text, tag=n.event_key)
    except email_provider.EmailError as exc:
        if 'not configured' in str(exc):
            raise PermanentFailure(str(exc))
        raise


# ── socket ──────────────────────────────────────────────────────────────────

def socket(n, user, spec):
    payload = {
        'id': n.id, 'event': n.event_key, 'title': n.title, 'body': n.body,
        'data': _payload_data(n), 'critical': bool(n.is_critical),
        'created_at': n.created_at.strftime('%Y-%m-%dT%H:%M:%SZ') if n.created_at else None,
    }
    realtime.to_user(user.id, 'notification', payload)
    return f'socket:{user.id}'
