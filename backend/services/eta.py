"""Live ETA (spec §16).

`tracking._after_driver_point` calls `maybe_refresh(ride_type, ride_id, (lat, lng))`
for every driver position while the ride is DRIVER_EN_ROUTE / DRIVER_ARRIVING
(ETA to pickup) or IN_PROGRESS (ETA to drop-off). This module:

  • throttles to one computation per ride per `eta.min_refresh_s` (Redis key
    when available, otherwise an in-process table) — unless the driver deviates
    (straight-line distance to the target grew by ≥ `eta.deviation_m` since the
    last computation), which refreshes at once;
  • never blocks the location request: the Google Routes call runs in a job
    (`refresh_job`); without GOOGLE_MAPS_SERVER_KEY a haversine/average-speed
    estimate is used;
  • writes ride.eta_seconds / eta_distance_m / eta_target / eta_updated_at and,
    on the first pickup ETA, initial_eta_at (= expected arrival time, used by the
    DRIVER_NO_SHOW detector: arrival due at initial_eta_at + grace);
  • emits `ride.eta_updated` to the ride room and each customer's user room;
  • moves DRIVER_EN_ROUTE → DRIVER_ARRIVING (state machine, actor=system) once
    the pickup ETA is ≤ `ride.arriving_eta_s`.
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta

from backend import jobs
from backend.models import db
from backend.services import geo_routes as G
from backend.services import realtime
from backend.services import rides as R
from backend.services import settings_service as S

log = logging.getLogger('negoride.eta')

PICKUP_STAGES = ('DRIVER_EN_ROUTE', 'DRIVER_ARRIVING')
DROPOFF_STAGES = ('IN_PROGRESS',)
ETA_STAGES = PICKUP_STAGES + DROPOFF_STAGES

_state = {}           # in-process fallback: key → {'at': epoch, 'straight_m': float, 'last': payload}
_state_lock = threading.Lock()


def _key(ride_type, ride_id):
    return f'{ride_type}:{int(ride_id)}'


def _get_state(key):
    r = jobs.get_redis()
    if r is not None:
        try:
            raw = r.get('negoride:eta:' + key)
            return json.loads(raw) if raw else None
        except Exception:
            pass
    with _state_lock:
        return dict(_state[key]) if key in _state else None


def _set_state(key, value, ttl=3600):
    r = jobs.get_redis()
    if r is not None:
        try:
            r.set('negoride:eta:' + key, json.dumps(value), ex=ttl)
            return
        except Exception:
            pass
    with _state_lock:
        _state[key] = dict(value)


def reset_state():
    """Tests."""
    with _state_lock:
        _state.clear()


def target_for(ride_type, ride, stage=None):
    """('pickup'|'dropoff', (lat, lng)) or (None, None)."""
    stage = stage or R.current_stage(ride_type, ride)
    if stage in PICKUP_STAGES:
        return 'pickup', R.pickup_point(ride_type, ride)
    if stage in DROPOFF_STAGES:
        return 'dropoff', R.dropoff_point(ride_type, ride)
    return None, None


def maybe_refresh(ride_type, ride_id, point, force=False):
    """Queue an ETA computation if the throttle allows. Returns True when queued."""
    if not S.flag('live_eta'):
        return False
    try:
        ride = R.load(ride_type, ride_id)
    except R.RideNotFound:
        return False
    target, tp = target_for(ride_type, ride)
    if not target or not tp or not point:
        return False
    lat, lng = float(point[0]), float(point[1])
    straight = G.haversine_m((lat, lng), tp)
    key = _key(ride_type, ride_id)
    st = _get_state(key) or {}
    now = time.time()
    min_s = S.get_int('eta.min_refresh_s', 30)
    same_target = st.get('target') == target
    deviated = same_target and st.get('straight_m') is not None and \
        straight >= float(st['straight_m']) + S.get_int('eta.deviation_m', 300)
    if not force and same_target and st.get('at') and now - float(st['at']) < min_s and not deviated:
        return False
    st.update({'at': now, 'straight_m': straight, 'target': target})
    _set_state(key, st)
    jobs.enqueue('backend.services.eta.refresh_job', ride_type, int(ride_id), lat, lng,
                 'deviation' if deviated else 'interval')
    return True


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def payload(ride_type, ride_id, seconds, distance_m, target, updated_at, source=None):
    return {
        'ride_type': ride_type, 'ride_id': int(ride_id), 'seconds': int(seconds),
        'minutes': max(1, int(round(seconds / 60.0))) if seconds > 0 else 0,
        'distance_m': int(distance_m) if distance_m is not None else None, 'target': target,
        'arrives_at': _iso(updated_at + timedelta(seconds=int(seconds))), 'updated_at': _iso(updated_at),
        'source': source,
    }


def refresh_job(ride_type, ride_id, lat, lng, reason='interval'):
    """Job: compute the ETA (Google Routes or estimate), persist, emit, auto-ARRIVING."""
    from backend.services import trip_state_machine as TSM
    try:
        ride = R.load(ride_type, ride_id)
    except R.RideNotFound:
        return None
    stage = R.current_stage(ride_type, ride)
    target, tp = target_for(ride_type, ride, stage)
    if not target or not tp:
        return None
    res = G.compute_route((float(lat), float(lng)), tp)
    now = datetime.utcnow()

    ride = R.load(ride_type, ride_id, lock=True)
    if R.current_stage(ride_type, ride) != stage:   # moved on while we were computing
        db.session.rollback()
        return None
    if hasattr(ride, 'eta_seconds'):
        ride.eta_seconds = int(res['seconds'])
        ride.eta_distance_m = int(res['distance_m'])
        ride.eta_target = target
        ride.eta_updated_at = now
        if target == 'pickup' and getattr(ride, 'initial_eta_at', 'x') is None:
            ride.initial_eta_at = now + timedelta(seconds=int(res['seconds']))
    db.session.commit()

    data = payload(ride_type, ride_id, res['seconds'], res['distance_m'], target, now, res.get('source'))
    data['stage'] = stage
    data['reason'] = reason
    st = _get_state(_key(ride_type, ride_id)) or {}
    st['last'] = data
    _set_state(_key(ride_type, ride_id), st)
    realtime.to_ride(ride_type, ride_id, 'ride.eta_updated', data)
    for cid in R.customer_ids(ride_type, ride):
        realtime.to_user(cid, 'ride.eta_updated', data)
    push_live_activity(ride_type, ride_id, data)

    if target == 'pickup' and stage == 'DRIVER_EN_ROUTE' and ride_type in ('carhire', 'scheduled') \
            and res['seconds'] <= S.get_int('ride.arriving_eta_s'):
        try:
            TSM.transition(ride_type, ride_id, 'DRIVER_ARRIVING', actor=None,
                           meta={'auto': True, 'by': 'eta', 'eta_seconds': int(res['seconds'])})
        except TSM.TransitionError:
            db.session.rollback()
    return data


def current(ride_type, ride):
    """Latest ETA for GET /api/rides/{type}/{id}/eta (polling fallback)."""
    if getattr(ride, 'eta_seconds', None) is not None and ride.eta_updated_at:
        return payload(ride_type, ride.id, ride.eta_seconds, ride.eta_distance_m, ride.eta_target,
                       ride.eta_updated_at, None)
    st = _get_state(_key(ride_type, ride.id)) or {}
    return st.get('last')


def push_live_activity(ride_type, ride_id, data):
    """iOS Live Activity / Android ongoing notification update (spec §16). The
    hook lives in the rides/notifications area:
    `backend.services.notify.live_activity.push_update(ride_type, ride_id, payload)`.
    Optional — skipped when that module/function doesn't exist; never raises."""
    try:
        from backend.services.notify import live_activity
        fn = live_activity.push_update
    except (ImportError, AttributeError):
        return False
    try:
        fn(ride_type, int(ride_id), data)
        return True
    except Exception:
        log.exception('live activity push for %s #%s failed', ride_type, ride_id)
        return False
