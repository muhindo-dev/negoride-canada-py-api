"""Live location pipeline (spec §9.1, §16).

Every driver/customer position (socket `location:update` or HTTP
/api/update-location) goes through `ingest()`:
  • latest position → users.current_* (+ Redis `negoride:loc:{id}` when available)
  • during an active ride → one ride_locations breadcrumb, a `ride.driver_location`
    event to the ride room (and admin:ops), auto DRIVER_ARRIVING, throttled ETA
    refresh, and LOCATION_HOOKS (safety route-deviation / long-stop detection)
"""
import json
import logging
from datetime import datetime

from backend import jobs
from backend.models import db
from backend.models.safety import RideLocation
from backend.services import realtime
from backend.services import rides as R

log = logging.getLogger('negoride.tracking')
LOCATION_HOOKS = []   # fn(user, ride_type, ride, point_dict)


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


def latest(user_id):
    r = jobs.get_redis()
    if r is not None:
        try:
            raw = r.get(f'negoride:loc:{int(user_id)}')
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return None


def ingest(user, data, commit=True):
    p = parse(data)
    now = datetime.utcnow()
    user.current_latitude = p['lat']
    user.current_longitude = p['lng']
    user.last_location_update = now
    r = jobs.get_redis()
    if r is not None:
        try:
            r.set(f'negoride:loc:{user.id}', json.dumps({**p, 'at': now.isoformat() + 'Z'}), ex=600)
        except Exception:
            pass

    from backend.services.ride_actions import find_active_for
    ride_type, ride = find_active_for(user)
    ctx = None
    if ride is not None:
        role = R.role_of(user, ride_type, ride)
        stage = ride.trip_stage
        moving = stage in ('DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS', 'BOARDING',
                           'RIDING', 'CHECKED_IN', 'CONFIRMED')
        if moving:
            db.session.add(RideLocation(ride_type=ride_type, ride_id=ride.id, user_id=user.id, lat=p['lat'],
                                        lng=p['lng'], speed_mps=p.get('speed'),
                                        heading=int(p['heading']) if p.get('heading') is not None else None,
                                        accuracy_m=int(p['accuracy']) if p.get('accuracy') is not None else None,
                                        recorded_at=now))
        ctx = {'ride_type': ride_type, 'ride_id': ride.id, 'stage': stage, 'role': role}
    if commit:
        db.session.commit()

    event = {'user_id': user.id, **p, 'at': now.strftime('%Y-%m-%dT%H:%M:%SZ')}
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
            log.exception('location hook failed')
    return p, ctx


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
