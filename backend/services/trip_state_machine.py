"""Trip state machine (spec §4.3) — the ONLY code allowed to change a ride's stage.

    from backend.services.trip_state_machine import transition, TransitionError
    result = transition('carhire', 42, 'DRIVER_ARRIVED', actor=user, lat=.., lng=..)

`transition()`:
  1. locks the ride row (SELECT … FOR UPDATE) so two taps can't double-transition
  2. validates the graph, the actor's role and the guards (payment secured,
     arrival geofence, ride PIN, wait window, no-show timing)
  3. writes trip_stage + the legacy `status` through ONE mapping (v3 apps keep working)
  4. inserts exactly one trip_events row
  5. after COMMIT: emits one realtime event and enqueues notifications / side
     effect jobs (payment capture, refunds, receipts) — nothing slow runs inline

Any failure raises TransitionError and changes nothing.
"""
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend import jobs
from backend.models import db
from backend.models.platform import TripEvent
from backend.services import rides as R
from backend.services import settings_service as S

log = logging.getLogger('negoride.tsm')


class TransitionError(Exception):
    def __init__(self, message, code='invalid_transition', status=400, data=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.data = data or {}


# ── Stage graphs ────────────────────────────────────────────────────────────
CANCEL_BRANCHES = ('CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_DRIVER')

CARHIRE_GRAPH = {
    'REQUESTED': ('NEGOTIATING', 'PRICE_AGREED', 'EXPIRED') + CANCEL_BRANCHES,
    'NEGOTIATING': ('PRICE_AGREED', 'EXPIRED') + CANCEL_BRANCHES,
    'PRICE_AGREED': ('AWAITING_PAYMENT', 'CONFIRMED', 'EXPIRED') + CANCEL_BRANCHES,
    'AWAITING_PAYMENT': ('CONFIRMED', 'EXPIRED') + CANCEL_BRANCHES,
    'CONFIRMED': ('DRIVER_EN_ROUTE', 'DRIVER_NO_SHOW') + CANCEL_BRANCHES,
    'DRIVER_EN_ROUTE': ('DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'DRIVER_NO_SHOW') + CANCEL_BRANCHES,
    'DRIVER_ARRIVING': ('DRIVER_ARRIVED', 'DRIVER_NO_SHOW') + CANCEL_BRANCHES,
    'DRIVER_ARRIVED': ('IN_PROGRESS', 'CUSTOMER_NO_SHOW') + CANCEL_BRANCHES,
    # Cancelling a trip in progress is limited by the refund policy: only a
    # safety ending (customer/admin) or a driver ending it (full refund, strike).
    'IN_PROGRESS': ('COMPLETED',) + CANCEL_BRANCHES,
    'COMPLETED': ('CLOSED',),
}

RIDESHARE_TRIP_GRAPH = {
    'DRAFT': ('PUBLISHED', 'CANCELLED_BY_DRIVER'),
    'PUBLISHED': ('BOARDING', 'IN_PROGRESS', 'CANCELLED_BY_DRIVER'),
    'BOARDING': ('IN_PROGRESS', 'CANCELLED_BY_DRIVER'),
    'IN_PROGRESS': ('COMPLETED',),
    'COMPLETED': ('CLOSED',),
}

RIDESHARE_BOOKING_GRAPH = {
    'REQUESTED': ('PENDING_PAYMENT', 'DECLINED', 'EXPIRED') + CANCEL_BRANCHES,
    'PENDING_PAYMENT': ('CONFIRMED', 'EXPIRED') + CANCEL_BRANCHES,
    'CONFIRMED': ('DRIVER_ARRIVED', 'CHECKED_IN', 'NO_SHOW') + CANCEL_BRANCHES,
    'DRIVER_ARRIVED': ('CHECKED_IN', 'NO_SHOW') + CANCEL_BRANCHES,
    'CHECKED_IN': ('RIDING', 'DROPPED_OFF'),
    'RIDING': ('DROPPED_OFF',),
    'DROPPED_OFF': ('CLOSED',),
}

GRAPHS = {
    'carhire': CARHIRE_GRAPH,
    'scheduled': CARHIRE_GRAPH,
    'rideshare_trip': RIDESHARE_TRIP_GRAPH,
    'rideshare_booking': RIDESHARE_BOOKING_GRAPH,
}

TERMINAL = {
    'carhire': ('CLOSED', 'EXPIRED', 'CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_DRIVER',
                'CUSTOMER_NO_SHOW', 'DRIVER_NO_SHOW'),
    'rideshare_trip': ('CLOSED', 'CANCELLED_BY_DRIVER'),
    'rideshare_booking': ('CLOSED', 'CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_DRIVER',
                          'NO_SHOW', 'EXPIRED', 'DECLINED'),
}
TERMINAL['scheduled'] = TERMINAL['carhire']

# "Active" = a ride the app should show on the Active Ride screen.
ACTIVE_STAGES = {
    'carhire': ('REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT', 'CONFIRMED',
                'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS'),
    'rideshare_trip': ('BOARDING', 'IN_PROGRESS'),
    'rideshare_booking': ('CONFIRMED', 'DRIVER_ARRIVED', 'CHECKED_IN', 'RIDING'),
}
ACTIVE_STAGES['scheduled'] = ACTIVE_STAGES['carhire'][4:]  # from CONFIRMED on

# Stages that require the customer's money to be secured (spec §6.2).
PAYMENT_GATED = {
    'carhire': ('CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS', 'COMPLETED'),
    'rideshare_booking': ('CONFIRMED', 'DRIVER_ARRIVED', 'CHECKED_IN', 'RIDING', 'DROPPED_OFF'),
}
PAYMENT_GATED['scheduled'] = PAYMENT_GATED['carhire']

# Who may request each target stage. 'admin' may request any graph-legal stage.
ACTORS = {
    'carhire': {
        'NEGOTIATING': ('customer', 'driver', 'system'),
        'PRICE_AGREED': ('customer', 'driver', 'system'),
        'AWAITING_PAYMENT': ('customer', 'driver', 'system'),
        'CONFIRMED': ('system',),
        'DRIVER_EN_ROUTE': ('driver',),
        'DRIVER_ARRIVING': ('driver', 'system'),
        'DRIVER_ARRIVED': ('driver',),
        'IN_PROGRESS': ('driver',),
        'COMPLETED': ('driver',),
        'CLOSED': ('system',),
        'EXPIRED': ('system',),
        'CANCELLED_BY_CUSTOMER': ('customer', 'system'),
        'CANCELLED_BY_DRIVER': ('driver', 'system'),
        'CUSTOMER_NO_SHOW': ('driver', 'system'),
        'DRIVER_NO_SHOW': ('customer', 'system'),
    },
    'rideshare_trip': {
        'PUBLISHED': ('driver',), 'BOARDING': ('driver', 'system'), 'IN_PROGRESS': ('driver',),
        'COMPLETED': ('driver',), 'CLOSED': ('system',), 'CANCELLED_BY_DRIVER': ('driver',),
    },
    'rideshare_booking': {
        'PENDING_PAYMENT': ('driver', 'system'), 'DECLINED': ('driver', 'system'),
        'CONFIRMED': ('system',), 'DRIVER_ARRIVED': ('driver',), 'CHECKED_IN': ('driver',),
        'RIDING': ('driver', 'system'), 'DROPPED_OFF': ('driver', 'system'), 'CLOSED': ('system',),
        'NO_SHOW': ('driver', 'system'), 'EXPIRED': ('system',),
        'CANCELLED_BY_CUSTOMER': ('customer',), 'CANCELLED_BY_DRIVER': ('driver', 'system'),
    },
}
ACTORS['scheduled'] = ACTORS['carhire']


# ── Legacy status mapping (spec §4.3 table) ─────────────────────────────────
# NOTE: for car hire the v3 app represents an open negotiation with 'Active'
# (not 'Pending') and spells cancellation 'Cancelled'; the SSE feed and
# HomeScreen filter on exactly those strings, so we keep them.
def legacy_status(ride_type, stage, current=None):
    if ride_type == 'carhire':
        if stage in ('REQUESTED', 'NEGOTIATING'):
            return 'Active'
        if stage in ('PRICE_AGREED', 'AWAITING_PAYMENT', 'CONFIRMED'):
            return 'Accepted'
        if stage in ('DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS'):
            return 'Started'
        if stage in ('COMPLETED', 'CLOSED'):
            return 'Completed'
        return 'Cancelled'
    if ride_type == 'scheduled':
        if stage == 'REQUESTED':
            return 'pending'
        if stage == 'NEGOTIATING':
            return 'price_negotiating'
        if stage in ('PRICE_AGREED', 'AWAITING_PAYMENT'):
            return current if current in ('price_accepted', 'driver_assigned') else 'price_accepted'
        if stage in ('CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED'):
            return 'confirmed'
        if stage == 'IN_PROGRESS':
            return 'in_progress'
        if stage in ('COMPLETED', 'CLOSED'):
            return 'completed'
        return 'cancelled'
    if ride_type == 'rideshare_trip':
        return {'DRAFT': 'Pending', 'PUBLISHED': 'Active', 'BOARDING': 'Active',
                'IN_PROGRESS': 'Ongoing', 'COMPLETED': 'Completed', 'CLOSED': 'Completed'}.get(stage, 'Canceled')
    # rideshare_booking
    if stage in ('REQUESTED', 'PENDING_PAYMENT'):
        return 'Pending'
    if stage in ('CONFIRMED', 'DRIVER_ARRIVED', 'CHECKED_IN', 'RIDING'):
        return 'Reserved'
    if stage in ('DROPPED_OFF', 'CLOSED'):
        return 'Completed'
    return 'Canceled'


# ── Timestamp columns per stage ─────────────────────────────────────────────
STAMP = {
    'carhire': {
        'AWAITING_PAYMENT': 'awaiting_payment_since', 'CONFIRMED': 'confirmed_at',
        'DRIVER_EN_ROUTE': 'en_route_at', 'DRIVER_ARRIVING': 'arriving_at',
        'DRIVER_ARRIVED': 'driver_arrived_at', 'IN_PROGRESS': 'started_at',
        'COMPLETED': 'completed_at', 'CLOSED': 'closed_at',
    },
    'scheduled': {'AWAITING_PAYMENT': 'awaiting_payment_since', 'CONFIRMED': 'confirmed_at',
                  'DRIVER_EN_ROUTE': 'en_route_at', 'DRIVER_ARRIVING': 'arriving_at',
                  'DRIVER_ARRIVED': 'driver_arrived_at', 'IN_PROGRESS': 'started_at',
                  'COMPLETED': 'completed_at', 'CLOSED': 'closed_at'},
    'rideshare_trip': {'PUBLISHED': 'published_at', 'BOARDING': 'boarding_at', 'IN_PROGRESS': 'started_at',
                       'COMPLETED': 'completed_at', 'CLOSED': 'closed_at'},
    'rideshare_booking': {'PENDING_PAYMENT': 'awaiting_payment_since', 'CONFIRMED': 'confirmed_at',
                          'DRIVER_ARRIVED': 'driver_arrived_at', 'CHECKED_IN': 'checked_in_at',
                          'DROPPED_OFF': 'dropped_off_at', 'CLOSED': 'closed_at'},
}


def is_terminal(ride_type, stage):
    return stage in TERMINAL[ride_type]


def is_cancel_stage(stage):
    return stage.startswith('CANCELLED') or stage in ('EXPIRED', 'CUSTOMER_NO_SHOW', 'DRIVER_NO_SHOW',
                                                      'NO_SHOW', 'DECLINED')


def allowed_next(ride_type, stage):
    return GRAPHS[ride_type].get(stage, ())


# ── Guards ──────────────────────────────────────────────────────────────────

def payment_secured(ride_type, ride):
    """True when the customer's money is authorized or captured."""
    from backend.models.money import RidePayment
    rp = (RidePayment.query
          .filter_by(ride_type=ride_type, ride_id=ride.id, purpose='ride')
          .order_by(RidePayment.id.desc()).first())
    if rp and rp.is_secured:
        return True
    # Legacy (pre-v4) payments: fully captured Checkout sessions.
    if ride_type == 'carhire':
        return ride.stripe_paid == 'Yes' or (ride.payment_status or '') == 'paid'
    if ride_type == 'scheduled':
        return bool(ride.stripe_paid) or (ride.payment_status or '').lower() == 'paid'
    if ride_type == 'rideshare_booking':
        return ride.stripe_paid == 'Yes' or (ride.payment_status or '').lower() == 'paid'
    return True


def customer_app_version(customer_id):
    """Highest app version we have seen for this user (device registration)."""
    from backend.models.notification import DeviceToken
    rows = DeviceToken.query.filter_by(user_id=customer_id).all()
    versions = [r.app_version for r in rows if r.app_version]
    return max(versions, key=_vkey) if versions else None


def _vkey(v):
    parts = []
    for p in str(v).split('+')[0].split('.'):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts + [0] * (3 - len(parts)))


def pin_required(ride_type, ride):
    """PIN is required when the flag is on AND the customer's app can show it
    (v4+). v3 customers never see a PIN, so their drivers aren't blocked."""
    if not S.flag('ride_pin'):
        return False
    cids = R.customer_ids(ride_type, ride)
    if not cids:
        return False
    v = customer_app_version(cids[0])
    return bool(v) and _vkey(v) >= (4, 0, 0)


def _now():
    return datetime.utcnow()


def _check_guards(ride_type, ride, from_stage, to_stage, actor_type, ctx):
    if actor_type == 'admin':
        return
    now = _now()

    if (to_stage in PAYMENT_GATED.get(ride_type, ()) and S.flag('pay_before_trip')
            and not payment_secured(ride_type, ride)):
        raise TransitionError('Payment must be authorized before the ride can continue.',
                              code='payment_required', status=402)

    if to_stage == 'DRIVER_ARRIVED' and ride_type in ('carhire', 'scheduled') and S.flag('arrival_geofence') \
            and not ctx.get('legacy'):
        pickup = R.pickup_point(ride_type, ride)
        here = ctx.get('point')
        if pickup:
            if not here:
                raise TransitionError('Your current location is required to mark arrival.',
                                      code='location_required')
            dist = R.haversine_m(pickup, here)
            limit = S.get_int('ride.arrival_geofence_m')
            ctx['distance_to_pickup_m'] = round(dist)
            if dist > limit:
                raise TransitionError(
                    f"You're {round(dist)} m from the pickup point. Move within {limit} m to mark arrival.",
                    code='outside_geofence', data={'distance_m': round(dist), 'limit_m': limit})

    if to_stage in ('IN_PROGRESS', 'CHECKED_IN') and ride_type in ('carhire', 'scheduled', 'rideshare_booking') \
            and not ctx.get('legacy_pin_exempt'):
        if pin_required(ride_type, ride):
            expected = ride.ride_pin
            given = str(ctx.get('pin') or '').strip()
            if not expected:
                raise TransitionError('No ride PIN exists for this ride.', code='pin_missing')
            if not given:
                raise TransitionError("Enter the rider's 4-digit PIN to start.", code='pin_required')
            if not secrets.compare_digest(given, expected):
                raise TransitionError('That PIN is not correct. Ask the rider for the PIN shown in their app.',
                                      code='pin_invalid')

    if to_stage == 'CUSTOMER_NO_SHOW' and actor_type != 'system':
        arrived = getattr(ride, 'driver_arrived_at', None)
        window = S.get_int('ride.wait_window_s')
        if not arrived or (now - arrived).total_seconds() < window:
            remaining = window - int((now - arrived).total_seconds()) if arrived else window
            raise TransitionError(f'You can mark a no-show after the {window // 60}-minute wait window '
                                  f'({max(0, remaining)} s left).', code='wait_window',
                                  data={'seconds_left': max(0, remaining)})

    if to_stage == 'NO_SHOW' and ride_type == 'rideshare_booking' and actor_type != 'system':
        trip = R.load('rideshare_trip', ride.trip_id)
        dep = trip.departure_at
        if dep and now < dep:
            raise TransitionError('A passenger can be marked no-show only after departure time.',
                                  code='too_early')

    if to_stage == 'DRIVER_NO_SHOW' and actor_type == 'customer':
        due = driver_no_show_due_at(ride)
        if not due or now < due:
            raise TransitionError('You can report a driver no-show 15 minutes after the expected arrival time.',
                                  code='too_early')


def driver_no_show_due_at(ride):
    base = getattr(ride, 'initial_eta_at', None) or getattr(ride, 'confirmed_at', None)
    if not base:
        return None
    return base + timedelta(seconds=S.get_int('ride.driver_no_show_grace_s'))


# ── Hooks (other modules register side effects) ─────────────────────────────
_HOOKS = []


def on_transition(fn):
    """Register fn(result: TransitionResult). Runs INSIDE the transaction, just
    before commit; must be fast (enqueue jobs with jobs.enqueue_after_commit)."""
    _HOOKS.append(fn)
    return fn


@dataclass
class TransitionResult:
    ride_type: str
    ride: object
    from_stage: str
    to_stage: str
    actor_type: str
    actor_id: int
    event: TripEvent
    meta: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            'ride_type': self.ride_type, 'ride_id': self.ride.id,
            'from_stage': self.from_stage, 'to_stage': self.to_stage,
            'stage': self.to_stage, 'legacy_status': self.ride.status,
            'event_id': self.event.id, 'actor_type': self.actor_type,
            'at': self.event.created_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'meta': self.meta,
        }


def _resolve_actor(actor, actor_type, ride_type, ride):
    if actor is None:
        return 'system', None
    if actor_type:
        return actor_type, getattr(actor, 'id', None)
    role = R.role_of(actor, ride_type, ride)
    if role is None:
        raise TransitionError('You are not part of this ride.', code='forbidden', status=403)
    return role, actor.id


def transition(ride_type, ride_id, to_stage, actor=None, actor_type=None, *, lat=None, lng=None,
               pin=None, meta=None, legacy=False, commit=True, ride=None):
    """Move a ride to `to_stage`. See module docstring."""
    ride_type = R.normalize_type(ride_type)
    to_stage = (to_stage or '').upper()
    if ride is None:
        try:
            ride = R.load(ride_type, ride_id, lock=True)
        except R.RideNotFound as e:
            raise TransitionError(str(e), code='not_found', status=404)
    else:
        # Always hold the row lock: flush the caller's pending edits, then
        # re-read the row FOR UPDATE (populate_existing refreshes the object with
        # the latest committed + our flushed state). Prevents double transitions
        # when two requests/jobs race on the same ride.
        db.session.flush()
        model = type(ride)
        ride = (model.query.filter(model.id == ride.id).with_for_update()
                .populate_existing().one())

    a_type, a_id = _resolve_actor(actor, actor_type, ride_type, ride)
    from_stage = R.current_stage(ride_type, ride)

    if from_stage == to_stage:
        raise TransitionError(f'The ride is already {to_stage.replace("_", " ").lower()}.',
                              code='already_in_stage', status=409, data={'stage': from_stage})
    if to_stage not in allowed_next(ride_type, from_stage):
        raise TransitionError(
            f'Cannot move this ride from {from_stage} to {to_stage}.', code='invalid_transition', status=409,
            data={'stage': from_stage, 'allowed': list(allowed_next(ride_type, from_stage))})
    if a_type != 'admin' and a_type not in ACTORS[ride_type].get(to_stage, ()):
        raise TransitionError(f'A {a_type} cannot move the ride to {to_stage}.', code='forbidden_actor',
                              status=403)

    ctx = {'pin': pin, 'legacy': legacy, 'legacy_pin_exempt': False}
    if lat is not None and lng is not None:
        try:
            ctx['point'] = (float(lat), float(lng))
        except (TypeError, ValueError):
            raise TransitionError('Invalid coordinates.', code='bad_location')
    elif a_type == 'driver' and to_stage == 'DRIVER_ARRIVED':
        ctx['point'] = _last_known_point(a_id)
    if legacy and to_stage in ('IN_PROGRESS', 'CHECKED_IN'):
        # v3 driver apps have no PIN UI. PIN is still enforced if the rider is on v4.
        ctx['legacy_pin_exempt'] = not pin_required(ride_type, ride)
    _check_guards(ride_type, ride, from_stage, to_stage, a_type, ctx)

    now = _now()
    event_meta = dict(meta or {})
    if 'distance_to_pickup_m' in ctx:
        event_meta['distance_to_pickup_m'] = ctx['distance_to_pickup_m']
    if to_stage == 'COMPLETED' and ctx.get('point'):
        drop = R.dropoff_point(ride_type, ride)
        if drop:
            d = R.haversine_m(drop, ctx['point'])
            event_meta['distance_to_dropoff_m'] = round(d)
            limit = S.get_int('ride.complete_geofence_m')
            if limit and d > limit:
                event_meta['ended_away_from_dropoff'] = True
    if legacy:
        event_meta['legacy'] = True

    # ── apply ───────────────────────────────────────────────────────────────
    ride.trip_stage = to_stage
    ride.stage_changed_at = now
    old_status = ride.status
    ride.status = legacy_status(ride_type, to_stage, old_status)
    col = STAMP.get(ride_type, {}).get(to_stage)
    if col and hasattr(ride, col):
        setattr(ride, col, now)
    _apply_type_specifics(ride_type, ride, to_stage, a_type, now, event_meta)

    point = ctx.get('point')
    event = TripEvent(ride_type=ride_type, ride_id=ride.id, from_stage=from_stage, to_stage=to_stage,
                      actor_type=a_type, actor_id=a_id,
                      lat=point[0] if point else None, lng=point[1] if point else None,
                      meta=event_meta or None, created_at=now)
    db.session.add(event)
    db.session.flush()

    result = TransitionResult(ride_type, ride, from_stage, to_stage, a_type, a_id, event, event_meta)
    for hook in list(_HOOKS):
        hook(result)

    jobs.enqueue_after_commit('backend.services.trip_effects.after_transition', event.id)
    if commit:
        db.session.commit()
    return result


def _last_known_point(user_id):
    from backend.models.user import AdminUser
    u = db.session.get(AdminUser, user_id) if user_id else None
    if u and u.current_latitude is not None and u.current_longitude is not None:
        if u.last_location_update and (_now() - u.last_location_update).total_seconds() <= 120:
            return float(u.current_latitude), float(u.current_longitude)
    return None


def _apply_type_specifics(ride_type, ride, to_stage, actor_type, now, meta):
    terminal = is_terminal(ride_type, to_stage) or to_stage == 'COMPLETED'
    if ride_type == 'carhire':
        ride.is_active = 'No' if terminal else 'Yes'
        if to_stage in ('CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_DRIVER', 'EXPIRED', 'CUSTOMER_NO_SHOW',
                        'DRIVER_NO_SHOW'):
            ride.cancelled_at = now
            ride.cancelled_by = {'CANCELLED_BY_CUSTOMER': 'customer', 'CANCELLED_BY_DRIVER': 'driver',
                                 'CUSTOMER_NO_SHOW': 'driver', 'DRIVER_NO_SHOW': 'customer'}.get(to_stage, 'system')
            if meta.get('reason_code'):
                ride.cancel_reason_code = meta['reason_code'][:40]
            if meta.get('note'):
                ride.cancel_reason = meta['note']
        if to_stage == 'PRICE_AGREED':
            ride.customer_accepted = 'Accepted'
            ride.customer_driver = 'Accepted'
    elif ride_type == 'scheduled':
        if is_cancel_stage(to_stage):
            ride.cancelled_at = now
            if meta.get('reason_code'):
                ride.cancel_reason_code = meta['reason_code'][:40]
            if meta.get('note') or meta.get('reason_code'):
                ride.cancellation_reason = meta.get('note') or meta.get('reason_code')
    elif ride_type == 'rideshare_trip':
        if to_stage == 'IN_PROGRESS':
            ride.start_time = now.strftime('%Y-%m-%d %H:%M:%S')
        if to_stage == 'COMPLETED':
            ride.end_time = now.strftime('%Y-%m-%d %H:%M:%S')
        if to_stage == 'CANCELLED_BY_DRIVER':
            ride.cancelled_at = now
    elif ride_type == 'rideshare_booking':
        if is_cancel_stage(to_stage):
            ride.cancelled_at = now
            if meta.get('reason_code'):
                ride.cancel_reason_code = meta['reason_code'][:40]
        if to_stage == 'CHECKED_IN':
            ride.start_time = now.strftime('%Y-%m-%d %H:%M:%S')
        if to_stage == 'DROPPED_OFF':
            ride.end_time = now.strftime('%Y-%m-%d %H:%M:%S')

    # Ride PIN is created when the booking is confirmed (shown to the customer only).
    if to_stage == 'CONFIRMED' and hasattr(ride, 'ride_pin') and not ride.ride_pin:
        ride.ride_pin = f'{secrets.randbelow(10000):04d}'


# ── Convenience wrappers ────────────────────────────────────────────────────

def ensure_stage(ride_type, ride):
    """Backfill trip_stage for a legacy row (no event — it's a derivation)."""
    if not ride.trip_stage:
        ride.trip_stage = R.derive_stage(ride_type, ride)
        ride.stage_changed_at = ride.stage_changed_at or _now()
    return ride.trip_stage


def walk_to(ride_type, ride_id, target, actor=None, actor_type=None, legacy=True, **kwargs):
    """Legacy endpoints (v3 app) skip intermediate v4 steps. Walk the shortest
    graph path to `target`, producing one event per step, all in one commit."""
    ride_type = R.normalize_type(ride_type)
    ride = R.load(ride_type, ride_id, lock=True)
    ensure_stage(ride_type, ride)
    path = shortest_path(ride_type, R.current_stage(ride_type, ride), target)
    if path is None:
        raise TransitionError(f'Cannot move this ride from {ride.trip_stage} to {target}.', status=409,
                              data={'stage': ride.trip_stage})
    results = []
    role = actor_type or (R.role_of(actor, ride_type, ride) if actor is not None else 'system')
    for stage in path:
        allowed = ACTORS[ride_type].get(stage, ())
        if role not in allowed and role != 'admin' and 'system' in allowed:
            # e.g. PRICE_AGREED → CONFIRMED is system-only: run it on the caller's
            # behalf (guards such as "payment secured" still apply).
            results.append(transition(ride_type, ride.id, stage, actor=None, legacy=legacy, commit=False,
                                      ride=ride, meta={'on_behalf_of': role}))
            continue
        results.append(transition(ride_type, ride.id, stage, actor=actor, actor_type=actor_type,
                                  legacy=legacy, commit=False, ride=ride, **kwargs))
    db.session.commit()
    return results


# Driver-initiated walk-throughs never pass through system-only or branch stages.
_WALK_SKIP = ('EXPIRED', 'CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_DRIVER', 'CUSTOMER_NO_SHOW',
              'DRIVER_NO_SHOW', 'NO_SHOW', 'DECLINED', 'DRIVER_ARRIVING', 'AWAITING_PAYMENT')


def shortest_path(ride_type, start, target):
    if start == target:
        return []
    graph = GRAPHS[ride_type]
    from collections import deque
    q = deque([(start, [])])
    seen = {start}
    while q:
        node, path = q.popleft()
        for nxt in graph.get(node, ()):
            if nxt in seen or (nxt in _WALK_SKIP and nxt != target):
                continue
            if nxt == target:
                return path + [nxt]
            seen.add(nxt)
            q.append((nxt, path + [nxt]))
    return None


INITIAL_STAGE = {'carhire': 'REQUESTED', 'scheduled': 'REQUESTED', 'rideshare_trip': 'PUBLISHED',
                 'rideshare_booking': 'PENDING_PAYMENT'}


def record_creation(ride_type, ride, actor=None, actor_type=None, stage=None, meta=None):
    """A ride was just created (flushed, not committed): set its first stage
    and write the opening trip_events row (from_stage = NULL). The caller commits."""
    ride_type = R.normalize_type(ride_type)
    stage = stage or INITIAL_STAGE[ride_type]
    now = _now()
    ride.trip_stage = stage
    ride.stage_changed_at = now
    ride.status = legacy_status(ride_type, stage, ride.status)
    col = STAMP.get(ride_type, {}).get(stage)
    if col and hasattr(ride, col):
        setattr(ride, col, now)
    if actor_type is None:
        actor_type = 'system' if actor is None else (R.role_of(actor, ride_type, ride) or 'customer')
    ev = TripEvent(ride_type=ride_type, ride_id=ride.id, from_stage=None, to_stage=stage, actor_type=actor_type,
                   actor_id=getattr(actor, 'id', None), meta=meta or None, created_at=now)
    db.session.add(ev)
    db.session.flush()
    jobs.enqueue_after_commit('backend.services.trip_effects.after_transition', ev.id)
    return ev
