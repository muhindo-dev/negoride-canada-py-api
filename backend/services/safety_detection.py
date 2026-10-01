"""Safety hooks into the ride pipeline (spec §8.4, §9.1, §10).

Location hook (`tracking.location_hook`, driver positions during IN_PROGRESS /
RIDING):
  • route deviation — two consecutive driver points farther than
    safety.route_deviation_m (500 m) from the nearest segment of the PLANNED
    route polyline (`ride_routes`, target dropoff; stored at CONFIRMED /
    IN_PROGRESS from Google Routes, or a straight line without a server key).
    Rides without a stored route fall back to the straight pickup→dropoff
    corridor with tolerance max(route_deviation_m, 20 % of the trip length).
  • long stop — driver stayed within safety.long_stop_radius_m for
    safety.long_stop_s, away from pickup/dropoff
  → one SafetyCheck per customer (max once per safety.check_throttle_s per ride),
    notification `safety.route_deviation` / `safety.long_stop` with check_id,
    unanswered checks escalate in safety_jobs.

After-hooks (`trip_effects.after_hook`):
  • CONFIRMED / IN_PROGRESS (car hire, scheduled) → store the planned route
  • IN_PROGRESS / RIDING → auto-share to trusted contacts (auto_share_all, or
    auto_share_night during the rider's local night). Contacts flagged
    auto_share get it; when none is flagged, all trusted contacts do.
  • COMPLETED / DROPPED_OFF / terminal → share links expire N min later,
    running recordings for the ride stop.

Imported by backend.routes.safety (so web + worker processes register it).
"""
import logging
import math
from datetime import datetime, timedelta

from backend import jobs
from backend.models import db
from backend.models.safety import Recording, RideRoute, SafetyCheck, TrustedContact
from backend.models.user import AdminUser
from backend.services import live_share
from backend.services import realtime
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services import tracking
from backend.services import trip_effects
from backend.services import trip_state_machine as TSM

log = logging.getLogger('negoride.safety.detect')

MOVING_STAGES = ('IN_PROGRESS', 'RIDING')
ENDPOINT_EXCLUSION_M = 200


def _xy(origin, p):
    """Equirectangular metres relative to origin (fine for city-scale)."""
    lat0 = math.radians(origin[0])
    return ((p[1] - origin[1]) * 111320.0 * math.cos(lat0), (p[0] - origin[0]) * 110540.0)


def distance_to_segment_m(p, a, b):
    ax, ay = 0.0, 0.0
    bx, by = _xy(a, b)
    px, py = _xy(a, p)
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def distance_to_polyline_m(p, pts):
    if not pts:
        return None
    if len(pts) == 1:
        return R.haversine_m(p, pts[0]) or 0.0
    return min(distance_to_segment_m(p, a, b) for a, b in zip(pts, pts[1:]))


ROUTE_STAGES = ('CONFIRMED', 'IN_PROGRESS')


def planned_route(ride_type, ride_id, target='dropoff'):
    """Latest stored RideRoute for the ride/target, or None."""
    return (RideRoute.query.filter_by(ride_type=ride_type, ride_id=int(ride_id), target=target)
            .order_by(RideRoute.id.desc()).first())


def store_planned_route(ride_type, ride, target, origin=None):
    """Compute (Google Routes, else straight line) and store the planned route.
    target 'dropoff': origin (default pickup) → dropoff; 'pickup': driver → pickup."""
    from backend.services import geo_routes as G
    dest = R.dropoff_point(ride_type, ride) if target == 'dropoff' else R.pickup_point(ride_type, ride)
    origin = origin or (R.pickup_point(ride_type, ride) if target == 'dropoff' else None)
    if not origin or not dest:
        return None
    res = G.planned_route(origin, dest)
    row = RideRoute(ride_type=ride_type, ride_id=ride.id, target=target, polyline=res['polyline'],
                    distance_m=res.get('distance_m'), duration_s=res.get('seconds'),
                    source=res.get('source') or 'straight_line', created_at=datetime.utcnow())
    db.session.add(row)
    db.session.commit()
    return row


def _driver_position(ride_type, ride):
    drv = R.driver_id(ride_type, ride)
    if not drv:
        return None
    lt = tracking.latest(drv)
    if lt and lt.get('lat') is not None:
        return float(lt['lat']), float(lt['lng'])
    d = db.session.get(AdminUser, drv)
    if d and d.current_latitude is not None and d.current_longitude is not None:
        try:
            return float(d.current_latitude), float(d.current_longitude)
        except (TypeError, ValueError):
            return None
    return None


def on_route_stage(ride_type, ride, stage):
    """CONFIRMED → planned trip (pickup→dropoff) + driver→pickup route;
    IN_PROGRESS → the trip route if none was stored yet."""
    if ride_type not in ('carhire', 'scheduled') or stage not in ROUTE_STAGES:
        return []
    out = []
    try:
        if planned_route(ride_type, ride.id, 'dropoff') is None:
            out.append(store_planned_route(ride_type, ride, 'dropoff'))
        if stage == 'CONFIRMED':
            pos = _driver_position(ride_type, ride)
            if pos:
                out.append(store_planned_route(ride_type, ride, 'pickup', origin=pos))
    except Exception:
        db.session.rollback()
        log.exception('planned route for %s #%s failed', ride_type, ride.id)
    return [r for r in out if r is not None]


def corridor_tolerance_m(a, b):
    trip = R.haversine_m(a, b) or 0
    return max(S.get_int('safety.route_deviation_m'), 0.2 * trip)


def _recent_check(ride_type, ride_id, now):
    throttle = S.get_int('safety.check_throttle_s', 600) or 600
    return (SafetyCheck.query.filter_by(ride_type=ride_type, ride_id=ride_id)
            .filter(SafetyCheck.created_at >= now - timedelta(seconds=throttle)).first())


def _create_checks(ride_type, ride, kind, point, meta):
    from backend.services.notify import notify
    now = datetime.utcnow()
    customers = R.customer_ids(ride_type, ride)
    if ride_type == 'rideshare_trip':
        from backend.models.trip_booking import TripBooking
        riding = TripBooking.query.filter(TripBooking.trip_id == ride.id,
                                          TripBooking.trip_stage.in_(['RIDING', 'CHECKED_IN'])).all()
        customers = sorted({int(b.customer_id) for b in riding if b.customer_id}) or customers
    created = []
    for cid in customers:
        chk = SafetyCheck(ride_type=ride_type, ride_id=ride.id, user_id=cid, kind=kind, status='pending',
                          lat=point[0], lng=point[1], meta=meta, created_at=now)
        db.session.add(chk)
        db.session.flush()
        created.append(chk)
        ctx = {'check_id': chk.id, 'ride_type': ride_type, 'ride_id': ride.id, 'kind': kind,
               'respond_url': f'/api/safety/checks/{chk.id}/respond',
               'respond_within_s': S.get_int('safety.check_response_s')}
        notify(f'safety.{kind}', [cid], ctx)
        jobs.enqueue_after_commit('backend.services.safety_jobs.check_timeout', chk.id,
                                  delay_s=max(1, S.get_int('safety.check_response_s')))
    db.session.commit()
    for chk in created:
        payload = {'check_id': chk.id, 'kind': kind, 'ride_type': ride_type, 'ride_id': ride.id,
                   'user_id': chk.user_id, 'lat': point[0], 'lng': point[1], 'meta': meta,
                   'created_at': chk.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')}
        realtime.to_user(chk.user_id, 'safety.check', payload)
        realtime.to_admins('safety.check_created', payload)
    return created


@tracking.location_hook
def detect(user, ride_type, ride, point):
    if not S.flag('route_deviation'):
        return None
    if R.role_of(user, ride_type, ride) != 'driver':
        return None
    stage = R.current_stage(ride_type, ride)
    if stage not in MOVING_STAGES:
        return None
    acc = point.get('accuracy')
    if acc is not None and acc > 200:
        return None
    now = datetime.utcnow()
    if _recent_check(ride_type, ride.id, now):
        return None
    here = (point['lat'], point['lng'])
    a, b = R.pickup_point(ride_type, ride), R.dropoff_point(ride_type, ride)

    # Route deviation: planned polyline when stored, else the straight corridor.
    route = planned_route(ride_type, ride.id, 'dropoff') if ride_type in ('carhire', 'scheduled') else None
    poly = None
    if route is not None:
        from backend.services import geo_routes as G
        poly = G.decode_polyline(route.polyline)
    if poly or (a and b):
        if poly:
            tol = float(S.get_int('safety.route_deviation_m') or 500)
            dist = lambda pt: distance_to_polyline_m(pt, poly)  # noqa: E731
        else:
            tol = corridor_tolerance_m(a, b)
            dist = lambda pt: distance_to_segment_m(pt, a, b)  # noqa: E731
        prev = tracking.recent_points(ride_type, ride.id, user.id, limit=2)
        # prev[-1] is normally the point just ingested; prev[-2] is the one before.
        earlier = prev[-2] if len(prev) > 1 else None
        off_now = dist(here)
        if off_now > tol and earlier is not None:
            off_prev = dist((earlier['lat'], earlier['lng']))
            if off_prev > tol:
                return _create_checks(ride_type, ride, 'route_deviation', here,
                                      {'off_route_m': round(off_now), 'tolerance_m': round(tol),
                                       'reference': 'planned_route' if poly else 'corridor',
                                       'route_source': route.source if route is not None else None})

    # Long stop
    long_s = S.get_int('safety.long_stop_s')
    radius = S.get_int('safety.long_stop_radius_m', 60) or 60
    for end in (a, b):
        if end and (R.haversine_m(end, here) or 0) < ENDPOINT_EXCLUSION_M:
            return None
    started = getattr(ride, 'started_at', None)
    if started and (now - started).total_seconds() < long_s:
        return None
    window = tracking.recent_points(ride_type, ride.id, user.id, since=now - timedelta(seconds=long_s + 120))
    if not window or (now - window[0]['recorded_at']).total_seconds() < long_s:
        return None
    if all((R.haversine_m(here, (p['lat'], p['lng'])) or 0) <= radius for p in window):
        return _create_checks(ride_type, ride, 'long_stop', here,
                              {'stopped_s': int((now - window[0]['recorded_at']).total_seconds())})
    return None


# ── after-hooks ─────────────────────────────────────────────────────────────

def _ended(ride_type, stage):
    return stage in ('COMPLETED', 'DROPPED_OFF', 'CLOSED') or TSM.is_terminal(ride_type, stage)


@trip_effects.after_hook
def on_stage(event, ride):
    rt, stage = event.ride_type, event.to_stage
    if rt in ('carhire', 'scheduled') and stage in ROUTE_STAGES:
        on_route_stage(rt, ride, stage)
    if (rt in ('carhire', 'scheduled') and stage == 'IN_PROGRESS') or (rt == 'rideshare_booking' and stage == 'RIDING'):
        auto_share(rt, ride)
    if _ended(rt, stage):
        ended_at = event.created_at or datetime.utcnow()
        live_share.expire_for_ride(rt, ride.id, ended_at)
        if rt == 'rideshare_trip':
            # passengers' links point at their booking; the cascade handles them.
            pass
        from backend.services import recording_service
        stopped = []
        for rec in Recording.query.filter_by(ride_type=rt, ride_id=ride.id, status='recording').all():
            recording_service.stop(rec, reason='ride_ended')
            stopped.append(rec)
        db.session.commit()
        for rec in stopped:
            recording_service.emit_status(rec)


def auto_share(ride_type, ride):
    from backend.services import safety_service as SS
    if not S.flag('live_share'):
        return []
    done = []
    for cid in R.customer_ids(ride_type, ride):
        user = db.session.get(AdminUser, cid)
        if not user:
            continue
        st = SS.get_settings(cid)
        if not SS.should_auto_share(user, st):
            continue
        contacts = TrustedContact.query.filter_by(user_id=cid, auto_share=True).all()
        if not contacts:
            # The rider turned auto-share on but flagged nobody: share with every
            # trusted contact rather than silently sending nothing.
            contacts = TrustedContact.query.filter_by(user_id=cid).all()
        if not contacts:
            continue
        link = live_share.get_or_create(ride_type, ride.id, cid,
                                        shared_with=[{'contact_id': c.id, 'name': c.name, 'channel': 'sms',
                                                      'reason': 'auto_share'} for c in contacts])
        ctx = {'name': SS.first_name(user), 'link': live_share.url_for_token(link.token), 'ride_type': ride_type,
               'ride_id': ride.id}
        jobs.enqueue_after_commit('backend.services.safety_service.sms_contacts', cid, 'safety.trip_shared',
                                  [c.id for c in contacts], ctx)
        from backend.services.audit import audit
        audit('safety.trip_auto_shared', None, 'ride_share_link', link.id,
              meta={'ride_type': ride_type, 'ride_id': ride.id, 'user_id': cid, 'contacts': len(contacts)})
        db.session.commit()
        done.append(link)
    return done
