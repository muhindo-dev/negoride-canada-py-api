"""Server-driven iOS Live Activities / Dynamic Island (spec §5.1).

Flow
  1. The iOS app starts a Live Activity for the active ride and calls the
     OneSignal SDK `LiveActivities.enter(activity_id, push_token)` — OneSignal
     keys the device under `activity_id` (there is no REST registration call).
  2. The app also registers it with us: POST /api/devices/live-activity
     {ride_type, ride_id, activity_id, push_token} → `live_activity_tokens`.
  3. We push updates by activity id through OneSignal's Live Activities API
        POST https://api.onesignal.com/apps/{app_id}/live_activities/{activity_id}/notifications
        Authorization: Key <ONESIGNAL_REST_API_KEY>
        {event: 'update'|'end', event_updates: <ContentState>, name, contents?, headings?,
         stale_date?, dismissal_date?, priority: 5|10, ios_relevance_score?}
     (verified against documentation.onesignal.com/reference/update-live-activity-api, Sept 2026).
     • catalogue events with the `live_activity` channel (ride.driver_en_route /
       driver_arriving / driver_arrived / started) — see dispatcher/channels;
     • ETA refreshes: services/eta.py calls `push_update(ride_type, ride_id, payload)`;
     • terminal stages (and COMPLETED / DROPPED_OFF): `end_for_ride()` sends
       event 'end' and marks the rows ended.
  Without ONESIGNAL_REST_API_KEY, or with NOTIFY_PUSH_DRY_RUN=1, requests are
  recorded in LA_LOG instead (tests / local).

ContentState (`event_updates`) — the Swift `ActivityAttributes.ContentState`
must decode exactly these keys:
  {stage, title, subtitle, eta_min, eta_arrives_at (unix s|null), driver_first,
   vehicle, plate, pin, progress (0..1), updated_at (unix s)}
"""
import logging
import os
from datetime import datetime

import requests

from backend.models import db
from backend.models.notification import LiveActivityToken

log = logging.getLogger('negoride.live_activity')
LA_LOG = []          # dry-run / test introspection: (activity_id, body)
API = 'https://api.onesignal.com/apps/{app_id}/live_activities/{activity_id}/notifications'

# Progress bar position per stage (the lock-screen stepper).
PROGRESS = {
    'CONFIRMED': 0.1, 'DRIVER_EN_ROUTE': 0.25, 'DRIVER_ARRIVING': 0.4, 'DRIVER_ARRIVED': 0.5,
    'IN_PROGRESS': 0.7, 'CHECKED_IN': 0.6, 'RIDING': 0.75, 'COMPLETED': 1.0, 'DROPPED_OFF': 1.0,
}
TITLES = {
    'CONFIRMED': 'Ride confirmed', 'DRIVER_EN_ROUTE': '{driver} is on the way',
    'DRIVER_ARRIVING': '{driver} is almost there', 'DRIVER_ARRIVED': '{driver} has arrived',
    'IN_PROGRESS': 'On your trip', 'CHECKED_IN': 'Checked in', 'RIDING': 'On your trip',
    'COMPLETED': "You've arrived", 'DROPPED_OFF': "You've arrived",
}
RIDE_TYPES = ('carhire', 'scheduled', 'rideshare_booking')


class LiveActivityError(Exception):
    def __init__(self, message, code='bad_request', status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def enabled():
    from backend.services import settings_service as S
    return S.flag('live_activities')


# ── registration ────────────────────────────────────────────────────────────

def register(user, data):
    from backend.services import rides as R
    try:
        rt = R.normalize_type(data.get('ride_type'))
        ride = R.load(rt, int(data.get('ride_id')))
    except (R.RideNotFound, TypeError, ValueError):
        raise LiveActivityError('Ride not found.', code='not_found', status=404)
    if rt not in RIDE_TYPES:
        raise LiveActivityError('Live Activities are for car hire, scheduled and seat bookings.',
                                code='unsupported_ride_type')
    if int(user.id) not in R.all_party_ids(rt, ride):
        raise LiveActivityError('You are not part of this ride.', code='forbidden', status=403)
    activity_id = str(data.get('activity_id') or '').strip()[:191]
    token = str(data.get('push_token') or '').strip()[:512]
    if not activity_id or not token:
        raise LiveActivityError('activity_id and push_token are required.', code='missing_fields')
    row = LiveActivityToken.query.filter_by(activity_id=activity_id).first()
    if row and row.user_id != user.id:
        raise LiveActivityError('This activity belongs to another user.', code='forbidden', status=403)
    if not row:
        row = LiveActivityToken(user_id=user.id, activity_id=activity_id, created_at=datetime.utcnow())
        db.session.add(row)
    row.ride_type, row.ride_id, row.push_token = rt, ride.id, token
    row.platform = (data.get('platform') or 'ios')[:20]
    row.status, row.ended_at = 'active', None
    db.session.commit()
    return row


def unregister(user, activity_id):
    n = 0
    for row in LiveActivityToken.query.filter_by(user_id=user.id, activity_id=str(activity_id)[:191]):
        row.status, row.ended_at = 'ended', datetime.utcnow()
        n += 1
    db.session.commit()
    return n


def active_tokens(ride_type, ride_id, user_id=None):
    q = LiveActivityToken.query.filter_by(ride_type=ride_type, ride_id=int(ride_id), status='active')
    if user_id is not None:
        q = q.filter_by(user_id=int(user_id))
    return q.all()


def has_active(user_id, ride_type, ride_id):
    if not ride_type or not ride_id or ride_type not in RIDE_TYPES:
        return False
    try:
        return bool(active_tokens(ride_type, ride_id, user_id))
    except Exception:
        db.session.rollback()
        return False


# ── content state ───────────────────────────────────────────────────────────

def _unix(dt):
    """Naive UTC datetime → unix seconds."""
    return int((dt - datetime(1970, 1, 1)).total_seconds()) if dt else None


def content_state(ride_type, ride, viewer_id=None, extra=None):
    """The ContentState dict for a ride (see module docstring)."""
    from datetime import timedelta
    from backend.services import rides as R
    from backend.services import trip_state_machine as TSM
    from backend.services.trip_effects import ride_context
    stage = R.current_stage(ride_type, ride)
    ctx = ride_context(ride_type, ride)
    driver = ctx.get('driver_first') or 'Your driver'
    eta_s = getattr(ride, 'eta_seconds', None)
    arrives = None
    if eta_s is not None:
        base = getattr(ride, 'eta_updated_at', None) or datetime.utcnow()
        arrives = _unix(base + timedelta(seconds=int(eta_s)))
    show_pin = viewer_id is not None and viewer_id in R.customer_ids(ride_type, ride) \
        and stage in ('DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'CONFIRMED', 'DRIVER_EN_ROUTE') \
        and TSM.pin_required(ride_type, ride)
    state = {
        'stage': stage,
        'title': TITLES.get(stage, stage.replace('_', ' ').title()).format(driver=driver),
        'subtitle': ctx.get('dropoff') if stage in ('IN_PROGRESS', 'RIDING') else ctx.get('pickup'),
        'eta_min': max(1, round(int(eta_s) / 60)) if eta_s is not None else None,
        'eta_arrives_at': arrives,
        'driver_first': driver,
        'vehicle': ctx.get('vehicle') or '',
        'plate': '',
        'pin': getattr(ride, 'ride_pin', None) if show_pin else None,
        'progress': PROGRESS.get(stage, 0.0),
        'updated_at': _unix(datetime.utcnow()),
    }
    try:
        from backend.models.user import AdminUser
        did = R.driver_id(ride_type, ride)
        veh = R.vehicle_card(db.session.get(AdminUser, did)) if did else None
        state['plate'] = (veh or {}).get('plate') or ''
    except Exception:
        pass
    if extra:
        state.update({k: v for k, v in extra.items() if k in state})
    return state


# ── sending ─────────────────────────────────────────────────────────────────

def _post(activity_id, body):
    app_id = os.getenv('ONESIGNAL_APP_ID', '56ef70cd-45a3-4a66-9838-3146fbbffe77')
    key = os.getenv('ONESIGNAL_REST_API_KEY', '')
    if os.getenv('NOTIFY_PUSH_DRY_RUN') == '1':
        if os.getenv('FLASK_ENV', '').strip().lower() not in ('development', 'dev', 'testing', 'test', 'local'):
            raise RuntimeError('NOTIFY_PUSH_DRY_RUN is not permitted in production')
        LA_LOG.append((activity_id, body))
        return 'dry-run'
    if not key:
        raise RuntimeError('ONESIGNAL_REST_API_KEY not configured')
    r = requests.post(API.format(app_id=app_id, activity_id=activity_id), json=body, timeout=10,
                      headers={'Authorization': f'Key {key}', 'Content-Type': 'application/json'})
    if r.status_code >= 400:
        raise RuntimeError(f'OneSignal Live Activity {r.status_code}: {r.text[:300]}')
    data = r.json() if r.content else {}
    return data.get('id') or 'ok'


def _send(row, event, state, alert=None, priority=10, dismiss_in_s=None):
    body = {'event': event, 'event_updates': state, 'name': f'ride-{row.ride_type}-{row.ride_id}-{state["stage"]}'[:128],
            'priority': priority, 'stale_date': _unix(datetime.utcnow()) + 15 * 60}
    if alert:
        body['headings'] = {'en': alert[0]}
        body['contents'] = {'en': alert[1] or alert[0]}
    if event == 'end':
        body['dismissal_date'] = _unix(datetime.utcnow()) + int(dismiss_in_s or 0)
        body.pop('stale_date', None)
    try:
        pid = _post(row.activity_id, body)
        row.last_pushed_at, row.last_error = datetime.utcnow(), None
        return pid
    except Exception as exc:
        row.last_error = str(exc)[:1000]
        log.warning('Live Activity push failed for %s: %s', row.activity_id, exc)
        return None


def push_update(ride_type, ride_id, payload=None, *, user_id=None, alert=None, priority=5):
    """Update every active Live Activity of a ride (ETA refresh, stage change).
    `payload` overrides ContentState keys (e.g. {'eta_min': 4}). Safe to call
    from any job; never raises. Returns the number of activities updated."""
    if not enabled():
        return 0
    try:
        from backend.services import rides as R
        rows = active_tokens(ride_type, ride_id, user_id)
        if not rows:
            return 0
        ride = R.load(ride_type, ride_id)
        n = 0
        for row in rows:
            state = content_state(ride_type, ride, row.user_id, extra=_eta_extra(payload))
            if _send(row, 'update', state, alert=alert, priority=priority):
                n += 1
        db.session.commit()
        return n
    except Exception:
        db.session.rollback()
        log.exception('push_update failed for %s/%s', ride_type, ride_id)
        return 0


def _eta_extra(payload):
    """Accept either ContentState keys or the `ride.eta_updated` realtime payload."""
    if not payload:
        return None
    extra = dict(payload)
    if 'minutes' in payload and 'eta_min' not in payload:
        extra['eta_min'] = payload.get('minutes')
    if 'seconds' in payload and 'eta_min' not in extra and payload.get('seconds') is not None:
        extra['eta_min'] = max(1, round(int(payload['seconds']) / 60))
    return extra


def send_for_notification(n, user, spec):
    """Channel 'live_activity' of a catalogue event: update this user's activity
    for the ride with a visible alert (title/body of the notification)."""
    data = n.data or {}
    rt, rid = data.get('ride_type'), data.get('ride_id')
    if not enabled() or rt not in RIDE_TYPES or not rid:
        from backend.services.notify.channels import PermanentFailure
        raise PermanentFailure('No Live Activity for this notification')
    from backend.services import rides as R
    rows = active_tokens(rt, rid, user.id)
    if not rows:
        from backend.services.notify.channels import PermanentFailure
        raise PermanentFailure('No active Live Activity registered')
    ride = R.load(rt, rid)
    ids = []
    for row in rows:
        pid = _send(row, 'update', content_state(rt, ride, user.id), alert=(n.title, n.body),
                    priority=10 if spec.get('critical') else 5)
        if pid:
            ids.append(str(pid))
    db.session.commit()
    if not ids:
        raise RuntimeError('Live Activity update failed')
    return ','.join(ids)[:191]


def end_for_ride(ride_type, ride_id, dismiss_in_s=None):
    """Terminal stage (or COMPLETED / DROPPED_OFF): final state + 'end'."""
    if ride_type not in RIDE_TYPES:
        return 0
    try:
        from backend.services import rides as R
        rows = active_tokens(ride_type, ride_id)
        if not rows:
            return 0
        ride = R.load(ride_type, ride_id)
        stage = R.current_stage(ride_type, ride)
        keep = 15 * 60 if stage in ('COMPLETED', 'DROPPED_OFF') else 60
        for row in rows:
            _send(row, 'end', content_state(ride_type, ride, row.user_id), priority=10,
                  dismiss_in_s=keep if dismiss_in_s is None else dismiss_in_s)
            row.status, row.ended_at = 'ended', datetime.utcnow()
        db.session.commit()
        return len(rows)
    except Exception:
        db.session.rollback()
        log.exception('end_for_ride failed for %s/%s', ride_type, ride_id)
        return 0
