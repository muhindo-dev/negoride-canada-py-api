"""OneSignal push notification service."""
import os
import requests

ONESIGNAL_APP_ID = os.environ.get('ONESIGNAL_APP_ID', '56ef70cd-45a3-4a66-9838-3146fbbffe77')
ONESIGNAL_REST_API_KEY = os.environ.get('ONESIGNAL_REST_API_KEY', '')
ONESIGNAL_API_URL = 'https://onesignal.com/api/v1/notifications'


def send_push(
    user_ids: list = None,
    segments: list = None,
    title: str = 'NegoRide Canada',
    message: str = '',
    data: dict = None,
):
    """Send a push notification via OneSignal.

    Args:
        user_ids: List of OneSignal external_user_ids (our admin_users.id)
        segments: OneSignal segments (e.g., ['All'])
        title: Notification title
        message: Notification body
        data: Additional data payload
    """
    if not ONESIGNAL_REST_API_KEY:
        return {'error': 'ONESIGNAL_REST_API_KEY not configured'}

    headers = {
        'Authorization': f'Basic {ONESIGNAL_REST_API_KEY}',
        'Content-Type': 'application/json',
    }

    payload = {
        'app_id': ONESIGNAL_APP_ID,
        'headings': {'en': title},
        'contents': {'en': message},
    }

    if user_ids:
        payload['include_external_user_ids'] = [str(uid) for uid in user_ids]
    elif segments:
        payload['included_segments'] = segments
    else:
        return {'error': 'Must provide user_ids or segments'}

    if data:
        payload['data'] = data

    try:
        resp = requests.post(ONESIGNAL_API_URL, json=payload, headers=headers, timeout=10)
        return resp.json()
    except requests.RequestException as e:
        return {'error': str(e)}


def send_sms(phone_number: str, message: str):
    """Send an SMS via OneSignal (SMS channel).

    Falls back to a stub if OneSignal SMS is not configured.
    """
    # OneSignal SMS support requires SMS channel setup
    # For now, log the message
    print(f"[SMS] To: {phone_number} | Message: {message}")
    return {'status': 'logged', 'phone': phone_number}


def notify_admin(message: str, data: dict = None):
    """Send a notification to the admin user (id=1)."""
    return send_push(
        user_ids=[1],
        title='Admin Notification',
        message=message,
        data=data,
    )


def notify_user(user_id: int, title: str, message: str, data: dict = None):
    """Send a notification to a specific user."""
    return send_push(
        user_ids=[user_id],
        title=title,
        message=message,
        data=data,
    )
