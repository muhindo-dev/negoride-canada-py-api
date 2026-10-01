"""Live location pipeline (spec §9.1, §16).

Every driver/customer position (socket `location:update` or HTTP
/api/update-location) goes through `ingest()`. A request carries ONE point
(`lat`/`lng`…) or a BATCH (`points: [{lat, lng, speed, heading, accuracy,
recorded_at}]`, offline catch-up) or both.

  • breadcrumbs → `ride_locations` during an active ride. Rows are BUFFERED in
    process and bulk-inserted every `tracking.batch_flush_s` (3 s) by a daemon
    flusher (and on shutdown via atexit). Identical (user, recorded_at) points
    are dropped (in the buffer and against the table). Tests / JOB_MODE=eager
    write through synchronously (set `tracking.BATCH = True` to force buffering).
  • LIVE point = the newest point that is not older than
    `tracking.max_point_age_s` (600) and newer than the last live point. Older /
    out-of-order points are stored but never move the car, emit, or run hooks.
  • live point → users.current_* + latest position (Redis `negoride:loc:{id}`,
    in-process fallback), `ride.driver_location` to the ride room, admin
    `driver.location`, auto DRIVER_ARRIVING, throttled ETA refresh, and
    LOCATION_HOOKS (safety route-deviation / long-stop detection).
  • recent trail per (ride, user) for the detectors: Redis list
    `negoride:trail:{type}:{id}:{uid}` (in-process fallback, DB when empty).
"""
import atexit
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from backend import jobs
from backend.models import db
from backend.models.safety import RideLocation
from backend.services import realtime
from backend.services import rides as R

log = logging.getLogger('negoride.tracking')
LOCATION_HOOKS = []   # fn(user, ride_type, ride, point_dict)
MAX_BATCH = 500       # points accepted per request
TRAIL_LEN = 240       # recent points kept per (ride, user) for detectors
BATCH = None          # None = auto (buffer unless JOB_MODE=eager); True/False forces

MOVING_STAGES = ('DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS', 'BOARDING',
                 'RIDING', 'CHECKED_IN', 'CONFIRMED')


def location_hook(fn):
    LOCATION_HOOKS.append(fn)
    return fn


class LocationError(ValueError):
    pass


def _num(v, name, lo, hi):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise LocationError(f'Invalid {name}')
    if not lo <= f <= hi:
        raise LocationError(f'Invalid {name}')
    return f


def _parse_ts(v):
    if v in (None, ''):
        return None
    if isinstance(v, (int, float)):
        ts = float(v) / (1000.0 if v > 1e11 else 1.0)          # epoch ms or s
        return datetime.utcfromtimestamp(ts)
    s = str(v).strip()
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        raise LocationError('Invalid recorded_at')
    if dt.tzinfo is not None:
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse(data):
    lat = data.get('lat', data.get('latitude', data.get('lati')))
    lng = data.get('lng', data.get('longitude', data.get('long')))
    if lat is None or lng is None:
        raise LocationError('latitude and longitude are required')
    p = {'lat': _num(lat, 'latitude', -90, 90), 'lng': _num(lng, 'longitude', -180, 180)}
    for key, alt, lo, hi in (('speed', 'speed_mps', 0, 120), ('heading', 'bearing', 0, 360),
                             ('accuracy', 'accuracy_m', 0, 100000)):
        v = data.get(key, data.get(alt))
        if v not in (None, ''):
            try:
                p[key] = max(lo, min(hi, float(v)))
            except (TypeError, ValueError):
                pass
    return p


def parse_points(data, now=None):
    """All points of a request, oldest first, each with a naive-UTC `recorded_at`
    (seconds precision; future timestamps are clamped to now)."""
    now = (now or datetime.utcnow()).replace(microsecond=0)
    raw = []
    if isinstance(data.get('points'), list):
        raw.extend(x for x in data['points'][:MAX_BATCH] if isinstance(x, dict))
    if data.get('lat', data.get('latitude', data.get('lati'))) is not None:
        raw.append(data)
    if not raw:
        raise LocationError('latitude and longitude are required')
    out, bad = [], 0
    for item in raw:
        try:
            p = parse(item)
            ts = _parse_ts(item.get('recorded_at', item.get('timestamp')))
        except LocationError:
            if len(raw) == 1:
                raise
            bad += 1
            continue
        p['client_ts'] = ts is not None
        ts = (ts or now).replace(microsecond=0)
        p['recorded_at'] = min(ts, now)
        out.append(p)
    if not out:
        raise LocationError('No valid points')
    out.sort(key=lambda x: x['recorded_at'])
    return out, bad


# ── latest position ─────────────────────────────────────────────────────────

_latest_mem = {}
_mem_lock = threading.Lock()


def latest(user_id):
    """{'lat','lng','speed'?,'heading'?,'accuracy'?,'at'} or None. Redis first,
    per-process memory as fallback (production must run Redis)."""
    r = jobs.get_redis()
    if r is not None:
        try:
            raw = r.get(f'negoride:loc:{int(user_id)}')
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    with _mem_lock:
        v = _latest_mem.get(int(user_id))
    if v and time.time() - v[0] < 600:
        return dict(v[1])
    return None


def _set_latest(user_id, value):
    r = jobs.get_redis()
    if r is not None:
        try:
            r.set(f'negoride:loc:{int(user_id)}', json.dumps(value), ex=600)
        except Exception:
            pass
    with _mem_lock:
        _latest_mem[int(user_id)] = (time.time(), dict(value))


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def _last_live_at(user):
    lt = latest(user.id)
    if lt and lt.get('at'):
        try:
            return _parse_ts(lt['at'])
        except LocationError:
            pass
    return None


# ── recent trail (detectors) ────────────────────────────────────────────────

_trail_mem = {}


def _trail_key(ride_type, ride_id, user_id):
    return f'{ride_type}:{int(ride_id)}:{int(user_id)}'


def _push_trail(ride_type, ride_id, user_id, points):
    key = _trail_key(ride_type, ride_id, user_id)
    items = [[_iso(p['recorded_at']), p['lat'], p['lng']] for p in points]
    r = jobs.get_redis()
    if r is not None:
        try:
            pipe = r.pipeline()
            for it in items:
                pipe.lpush('negoride:trail:' + key, json.dumps(it))
            pipe.ltrim('negoride:trail:' + key, 0, TRAIL_LEN - 1)
            pipe.expire('negoride:trail:' + key, 7200)
            pipe.execute()
            return
        except Exception:
            pass
    with _mem_lock:
        dq = _trail_mem.setdefault(key, deque(maxlen=TRAIL_LEN))
        dq.extend(items)


def recent_points(ride_type, ride_id, user_id, since=None, limit=TRAIL_LEN):
    """Recent LIVE points for (ride, user), oldest first: [{'lat','lng','recorded_at'}].
    Trail cache first; falls back to ride_locations (+ unflushed buffer)."""
    key = _trail_key(ride_type, ride_id, user_id)
    items = None
    r = jobs.get_redis()
    if r is not None:
        try:
            raw = r.lrange('negoride:trail:' + key, 0, limit - 1)
            items = [json.loads(x) for x in raw][::-1] if raw else None
        except Exception:
            items = None
    if items is None:
        with _mem_lock:
            dq = _trail_mem.get(key)
            items = list(dq)[-limit:] if dq else None
    if items:
        pts = [{'recorded_at': _parse_ts(a), 'lat': float(b), 'lng': float(c)} for a, b, c in items]
    else:
        q = RideLocation.query.filter_by(ride_type=ride_type, ride_id=int(ride_id), user_id=int(user_id))
        if since:
            q = q.filter(RideLocation.recorded_at >= since)
        rows = q.order_by(RideLocation.recorded_at.desc(), RideLocation.id.desc()).limit(limit).all()
        pts = [{'recorded_at': x.recorded_at, 'lat': float(x.lat), 'lng': float(x.lng)} for x in rows][::-1]
        with _buf_lock:
            pts += [{'recorded_at': b['recorded_at'], 'lat': b['lat'], 'lng': b['lng']} for b in _buffer
                    if b['ride_type'] == ride_type and b['ride_id'] == int(ride_id) and b['user_id'] == int(user_id)]
        pts.sort(key=lambda x: x['recorded_at'])
    if since:
        pts = [p for p in pts if p['recorded_at'] >= since]
    return pts[-limit:]


def reset_memory():
    """Tests."""
    with _mem_lock:
        _latest_mem.clear()
        _trail_mem.clear()


# ── breadcrumb buffer (bulk insert) ─────────────────────────────────────────

_buffer = []
_buffer_keys = set()
_buf_lock = threading.Lock()
_flusher = None
_flusher_lock = threading.Lock()


def batching():
    if BATCH is not None:
        return bool(BATCH)
    return jobs.mode() != 'eager'


def _row(ride_type, ride_id, user_id, p):
    return {'ride_type': ride_type, 'ride_id': int(ride_id), 'user_id': int(user_id), 'lat': p['lat'],
            'lng': p['lng'], 'speed_mps': p.get('speed'),
            'heading': int(p['heading']) if p.get('heading') is not None else None,
            'accuracy_m': int(p['accuracy']) if p.get('accuracy') is not None else None,
            'recorded_at': p['recorded_at'], '_dedupe': bool(p.get('client_ts'))}


def _existing_keys(rows):
    """(user_id, recorded_at) already in ride_locations for these rows."""
    rows = [r for r in rows if r.get('_dedupe')]
    if not rows:
        return set()
    by_user = {}
    for r in rows:
        by_user.setdefault(r['user_id'], []).append(r['recorded_at'])
    found = set()
    for uid, ts in by_user.items():
        q = (db.session.query(RideLocation.user_id, RideLocation.recorded_at)
             .filter(RideLocation.user_id == uid, RideLocation.recorded_at >= min(ts),
                     RideLocation.recorded_at <= max(ts)))
        found.update((int(a), b) for a, b in q.all())
    return found


def _dedupe_filter(rows, have):
    return [r for r in rows if not (r.get('_dedupe') and (r['user_id'], r['recorded_at']) in have)]


def _insert(rows):
    clean = [{k: v for k, v in r.items() if k != '_dedupe'} for r in rows]
    if clean:
        db.session.execute(RideLocation.__table__.insert(), clean)


def store(rows):
    """Queue (or write through) breadcrumb rows. Points that carry a client
    `recorded_at` are deduped on (user, recorded_at) — re-sent offline batches
    never duplicate; server-stamped points are always kept. Returns rows accepted."""
    fresh = []
    with _buf_lock:
        for r in rows:
            if r.get('_dedupe'):
                k = (r['user_id'], r['recorded_at'])
                if k in _buffer_keys:
                    continue
                _buffer_keys.add(k)
            fresh.append(r)
    if not batching():
        with _buf_lock:
            for r in fresh:
                _buffer_keys.discard((r['user_id'], r['recorded_at']))
        fresh = _dedupe_filter(fresh, _existing_keys(fresh))
        _insert(fresh)
        return len(fresh)
    with _buf_lock:
        _buffer.extend(fresh)
        big = len(_buffer) >= 2000
    _ensure_flusher()
    if big:
        threading.Thread(target=flush_all, daemon=True).start()
    return len(fresh)


def flush():
    """Bulk-insert the buffered breadcrumbs (needs an app context). Returns rows inserted."""
    with _buf_lock:
        rows = list(_buffer)
        _buffer.clear()
        _buffer_keys.clear()
    if not rows:
        return 0
    try:
        rows = _dedupe_filter(rows, _existing_keys(rows))
        _insert(rows)
        db.session.commit()
        return len(rows)
    except Exception:
        db.session.rollback()
        log.exception('breadcrumb flush failed (%d rows) — re-queued', len(rows))
        with _buf_lock:
            _buffer[:0] = rows
            _buffer_keys.update((r['user_id'], r['recorded_at']) for r in rows if r.get('_dedupe'))
        return 0


def flush_all():
    """Flush from any thread (own app context)."""
    try:
        from flask import has_app_context
        if has_app_context():
            return flush()
        from backend.app import app
        with app.app_context():
            try:
                return flush()
            finally:
                db.session.remove()
    except Exception:
        log.exception('breadcrumb flush_all failed')
        return 0


def _flush_loop():
    from backend.services import settings_service as S
    while True:
        try:
            from backend.app import app
            with app.app_context():
                interval = max(1, min(10, S.get_int('tracking.batch_flush_s', 3) or 3))
                try:
                    flush()
                finally:
                    db.session.remove()
        except Exception:
            log.exception('breadcrumb flusher error')
            interval = 3
        time.sleep(interval)


def _ensure_flusher():
    global _flusher
    if _flusher is not None and _flusher.is_alive():
        return
    with _flusher_lock:
        if _flusher is not None and _flusher.is_alive():
            return
        _flusher = threading.Thread(target=_flush_loop, name='negoride-breadcrumbs', daemon=True)
        _flusher.start()


atexit.register(flush_all)


# ── ingest ──────────────────────────────────────────────────────────────────

def ingest(user, data, commit=True):
    """Returns (live_point|None, ctx). ctx (None when no active ride) is
    {'ride_type','ride_id','stage','role'}; `ingest.last_stats` style counters
    are in ctx['batch'] / the second return of ingest_batch()."""
    live, ctx, _stats = ingest_batch(user, data, commit=commit)
    return live, ctx


def ingest_batch(user, data, commit=True):
    from backend.services import settings_service as S
    now = datetime.utcnow()
    points, bad = parse_points(data or {}, now)
    max_age = S.get_int('tracking.max_point_age_s', 600) or 600
    last_live = _last_live_at(user)
    # Server-stamped points (no recorded_at) are "now" and always live; client
    # timestamps must be fresh and strictly newer than the last live point.
    live_pts = [p for p in points if not p['client_ts'] or
                ((now - p['recorded_at']).total_seconds() <= max_age
                 and (last_live is None or p['recorded_at'] > last_live))]
    live = live_pts[-1] if live_pts else None

    from backend.services.ride_actions import find_active_for
    ride_type, ride = find_active_for(user)
    ctx = None
    stored = 0
    if ride is not None:
        role = R.role_of(user, ride_type, ride)
        stage = ride.trip_stage
        if stage in MOVING_STAGES:
            stored = store([_row(ride_type, ride.id, user.id, p) for p in points])
        ctx = {'ride_type': ride_type, 'ride_id': ride.id, 'stage': stage, 'role': role}

    if live is not None:
        user.current_latitude = live['lat']
        user.current_longitude = live['lng']
        user.last_location_update = live['recorded_at']
        _set_latest(user.id, {**{k: v for k, v in live.items() if k not in ('recorded_at', 'client_ts')},
                              'at': _iso(live['recorded_at'])})
        if ride is not None:
            _push_trail(ride_type, ride.id, user.id, live_pts)
    if commit:
        db.session.commit()
    stats = {'received': len(points) + bad, 'rejected': bad, 'stored': stored,
             'live': live is not None, 'stale': len(points) - len(live_pts)}
    if ctx is not None:
        ctx['batch'] = stats
    if live is None:
        return None, ctx, stats

    p = {k: v for k, v in live.items() if k not in ('recorded_at', 'client_ts')}
    event = {'user_id': user.id, **p, 'at': _iso(live['recorded_at'])}
    if ride is not None and ctx['role'] == 'driver':
        event.update({'ride_type': ride_type, 'ride_id': ride.id, 'stage': ride.trip_stage})
        realtime.to_ride(ride_type, ride.id, 'ride.driver_location', event)
        _after_driver_point(user, ride_type, ride, p)
    if user.ready_for_trip == 'Yes' or ctx:
        realtime.to_admins('driver.location', {**event, 'role': ctx['role'] if ctx else 'driver',
                                               'online': user.ready_for_trip == 'Yes'})
    for hook in list(LOCATION_HOOKS):
        if ride is None:
            break
        try:
            hook(user, ride_type, ride, p)
        except Exception:
            db.session.rollback()
            log.exception('location hook failed')
    return p, ctx, stats


def _after_driver_point(user, ride_type, ride, p):
    from backend.services import settings_service as S
    from backend.services import trip_state_machine as TSM
    from backend.services.ride_jobs import should_mark_arriving
    if ride.trip_stage == 'DRIVER_EN_ROUTE' and ride_type in ('carhire', 'scheduled'):
        if should_mark_arriving(ride_type, ride):
            try:
                TSM.transition(ride_type, ride.id, 'DRIVER_ARRIVING', actor=None, meta={'auto': True, 'by': 'distance'})
            except TSM.TransitionError:
                db.session.rollback()
    if S.flag('live_eta') and ride.trip_stage in ('DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'IN_PROGRESS'):
        try:
            from backend.services import eta
            eta.maybe_refresh(ride_type, ride.id, (p['lat'], p['lng']))
        except ImportError:
            pass
