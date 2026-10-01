"""Ride-level actions shared by the v4 /api/rides endpoints, the legacy
endpoints and the scheduled jobs: cancellation (with policy), no-shows,
serialization of the full ride object."""
from datetime import datetime, timedelta

from backend.models import db
from backend.models.platform import TripEvent
from backend.services import refund_policy as RP
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services import trip_state_machine as TSM


def _paid_cents(ride_type, ride):
    from backend.services.payments.payment_service import latest_payment
    rp = latest_payment(ride_type, ride.id)
    if not rp:
        # Legacy captured payment (v3 Checkout without a RidePayment row)
        if TSM.payment_secured(ride_type, ride):
            return R.fare_cents(ride_type, ride)
        return 0
    if rp.capture_status == 'authorized':
        return rp.amount_authorized_cents
    if rp.took_money:
        return rp.amount_captured_cents - rp.amount_refunded_cents
    return 0


def cancel_context(ride_type, ride, reason):
    stage = R.current_stage(ride_type, ride)
    departure = None
    if ride_type == 'rideshare_booking':
        trip = R.load('rideshare_trip', ride.trip_id)
        departure = trip.departure_at
    return RP.CancelContext(
        ride_type=ride_type, stage=stage, reason=reason,
        fare_cents=R.fare_cents(ride_type, ride), paid_cents=_paid_cents(ride_type, ride),
        confirmed_at=getattr(ride, 'confirmed_at', None), en_route_at=getattr(ride, 'en_route_at', None),
        arrived_at=getattr(ride, 'driver_arrived_at', None), departure_at=departure)


def cancel_reason_for(role, explicit=None):
    if explicit:
        return explicit
    return {'customer': 'customer_cancel', 'driver': 'driver_cancel'}.get(role, 'admin')


def preview(ride_type, ride, role, now=None):
    reason = cancel_reason_for(role)
    if reason == 'admin':
        reason = 'customer_cancel'
    return RP.evaluate(cancel_context(ride_type, ride, reason), now or datetime.utcnow(), RP.config())


TARGET_FOR_REASON = {
    'customer_cancel': 'CANCELLED_BY_CUSTOMER',
    'driver_cancel': 'CANCELLED_BY_DRIVER',
    'customer_no_show': 'CUSTOMER_NO_SHOW',
    'driver_no_show': 'DRIVER_NO_SHOW',
    'expired': 'EXPIRED',
    'declined': 'DECLINED',
    'safety': 'CANCELLED_BY_CUSTOMER',
}


def cancel(ride_type, ride_id, actor=None, actor_type=None, reason=None, reason_code=None, note=None,
           legacy=False, commit=True):
    """Cancel / expire / no-show a ride applying the refund policy.
    The policy decision is stored on the trip_event; money moves in a job."""
    ride_type = R.normalize_type(ride_type)
    ride = R.load(ride_type, ride_id, lock=True)
    TSM.ensure_stage(ride_type, ride)
    role = actor_type or (R.role_of(actor, ride_type, ride) if actor is not None else 'system')
    if role is None:
        raise TSM.TransitionError('You are not part of this ride.', code='forbidden', status=403)
    reason = cancel_reason_for(role, reason)
    if reason == 'admin':
        reason = 'customer_cancel'
    target = TARGET_FOR_REASON[reason]
    if ride_type == 'rideshare_booking' and target in ('CUSTOMER_NO_SHOW',):
        target = 'NO_SHOW'
    if ride_type == 'rideshare_trip':
        target = 'CANCELLED_BY_DRIVER'

    decision = None
    if ride_type != 'rideshare_trip':
        decision = RP.evaluate(cancel_context(ride_type, ride, reason), datetime.utcnow(), RP.config())
        if not decision.allowed:
            raise TSM.TransitionError(decision.explanation, code=decision.rule_id, status=409)
    meta = {'reason': reason, 'reason_code': reason_code, 'note': note}
    if decision:
        meta['policy'] = decision.to_dict()
    result = TSM.transition(ride_type, ride.id, target, actor=actor if role != 'system' else None,
                            actor_type=role if role in ('admin',) else None, meta=meta, legacy=legacy,
                            commit=commit, ride=ride)
    return result, decision


# ── admin: reassign the driver (v4 admin + legacy admin assign-driver) ──────

REASSIGNABLE = ('REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT', 'CONFIRMED',
                'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING')


def reassign_driver(ride_type, ride_id, driver_id, admin, reason):
    """Assign / reassign the driver before pickup (car hire, scheduled). Writes a
    trip_events row (same stage, meta reassigned_from/to), moves the ride
    payments to the new driver, audits and notifies all parties in realtime.
    Raises TransitionError. Caller gets the payload; this commits."""
    from backend.models.money import RidePayment
    from backend.models.user import AdminUser
    from backend.services import realtime
    from backend.services.audit import audit
    ride_type = R.normalize_type(ride_type)
    if ride_type not in ('carhire', 'scheduled'):
        raise TSM.TransitionError('Only car hire and scheduled rides can be reassigned.', code='unsupported')
    ride = R.load(ride_type, ride_id, lock=True)
    stage = TSM.ensure_stage(ride_type, ride)
    if stage not in REASSIGNABLE:
        raise TSM.TransitionError(f'A ride in stage {stage} cannot be reassigned.', code='bad_stage', status=409)
    try:
        new_driver = db.session.get(AdminUser, int(driver_id or 0))
    except (TypeError, ValueError):
        new_driver = None
    if not new_driver or not new_driver.is_approved_driver() or not new_driver.is_account_active():
        raise TSM.TransitionError('Choose an approved, active driver.', code='driver_unavailable')
    old = ride.driver_id or None
    if old == new_driver.id:
        raise TSM.TransitionError('That driver is already assigned.', code='already_assigned', status=409)
    ride.driver_id = new_driver.id
    if ride_type == 'carhire':
        ride.driver_name = new_driver.name
    else:
        ride.assigned_by, ride.assigned_at = admin.id, datetime.utcnow()
    for rp in RidePayment.query.filter_by(ride_type=ride_type, ride_id=ride.id).all():
        rp.driver_id = new_driver.id
    db.session.add(TripEvent(ride_type=ride_type, ride_id=ride.id, from_stage=stage, to_stage=stage,
                             actor_type='admin', actor_id=admin.id,
                             meta={'reassigned_from': old, 'reassigned_to': new_driver.id, 'reason': reason}))
    audit('ride.reassign_driver', admin, ride_type, ride.id, before={'driver_id': old},
          after={'driver_id': new_driver.id}, meta={'reason': reason})
    db.session.commit()
    payload = {'ride_type': ride_type, 'ride_id': ride.id, 'stage': stage, 'driver_id': new_driver.id}
    for uid in {old, new_driver.id, *R.customer_ids(ride_type, ride)} - {None}:
        realtime.to_user(uid, 'ride.driver_reassigned', payload)
    realtime.to_ride(ride_type, ride.id, 'ride.driver_reassigned', payload)
    realtime.to_admins('ride.driver_reassigned', {**payload, 'previous_driver_id': old, 'by': admin.id})
    return payload


# ── serialization ───────────────────────────────────────────────────────────

def timeline(ride_type, ride_id):
    rows = (TripEvent.query.filter_by(ride_type=ride_type, ride_id=ride_id)
            .order_by(TripEvent.created_at.asc(), TripEvent.id.asc()).all())
    out = []
    for e in rows:
        out.append(e.to_dict())
    return out


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def serialize(ride_type, ride, viewer, include_timeline=True):
    """Full ride object for GET /api/rides/{type}/{id} (spec §4.4)."""
    from backend.models.user import AdminUser
    from backend.services.payments.payment_service import latest_payment
    stage = R.current_stage(ride_type, ride)
    role = R.role_of(viewer, ride_type, ride) if viewer else None
    driver_id = R.driver_id(ride_type, ride)
    cids = R.customer_ids(ride_type, ride)
    confirmed = stage not in ('REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT',
                              'PENDING_PAYMENT', 'DRAFT')
    pickup, dropoff = R.addresses(ride_type, ride)
    pp, dp = R.pickup_point(ride_type, ride), R.dropoff_point(ride_type, ride)
    driver = db.session.get(AdminUser, driver_id) if driver_id else None

    rp = latest_payment(ride_type, ride.id) if ride_type != 'rideshare_trip' else None
    fare = R.fare_cents(ride_type, ride)
    out = {
        'ride_type': ride_type,
        'id': ride.id,
        'stage': stage,
        'legacy_status': ride.status,
        'stage_changed_at': _iso(ride.stage_changed_at),
        'is_terminal': TSM.is_terminal(ride_type, stage),
        'is_active': stage in TSM.ACTIVE_STAGES.get(ride_type, ()),
        'viewer_role': role,
        'allowed_next': list(TSM.allowed_next(ride_type, stage)),
        'pickup': {'address': pickup, 'lat': pp[0] if pp else None, 'lng': pp[1] if pp else None},
        'dropoff': {'address': dropoff, 'lat': dp[0] if dp else None, 'lng': dp[1] if dp else None},
        'price': {'fare_cents': fare, 'currency': 'cad',
                  'initial_cents': getattr(ride, 'initial_price', None) if ride_type == 'carhire' else None},
        'payment': None,
        'driver': R.user_card(driver_id, full=confirmed) if driver_id else None,
        'vehicle': R.vehicle_card(driver, ride_type=ride_type, ride=ride, viewer=viewer) if (driver and confirmed) else None,
        'customer': R.user_card(cids[0], full=confirmed) if len(cids) == 1 else None,
        'passenger_count': len(cids) if ride_type == 'rideshare_trip' else None,
        'eta': None,
        'pin': None,
        'pin_required': TSM.pin_required(ride_type, ride) if ride_type != 'rideshare_trip' else False,
        'wait': None,
        'timestamps': {},
        'disputed': bool(getattr(ride, 'disputed_at', None)),
    }
    if rp:
        out['payment'] = {
            'id': rp.id, 'status': rp.capture_status, 'secured': rp.is_secured, 'checkout_url':
                rp.checkout_url if (role == 'customer' and rp.capture_status == 'pending') else None,
            'amount_authorized_cents': rp.amount_authorized_cents, 'amount_captured_cents': rp.amount_captured_cents,
            'amount_refunded_cents': rp.amount_refunded_cents, 'fees_cents': rp.fees_cents,
            # §4.1 payment overlay: none | partially_refunded | refunded
            'refund_status': rp.capture_status if rp.capture_status in ('refunded', 'partially_refunded')
            else ('none' if not rp.amount_refunded_cents else 'partially_refunded'),
            'provider': rp.provider, 'settlement_status': rp.settlement_status,
            'card': f"{(rp.payment_method_brand or '').title()} •••• {rp.payment_method_last4}" if rp.payment_method_last4 else None,
        }
    else:
        out['payment'] = {'status': 'legacy_paid' if TSM.payment_secured(ride_type, ride) else 'unpaid',
                          'secured': TSM.payment_secured(ride_type, ride)}
    # PIN: shown ONLY to the customer (spec §4.4)
    if role == 'customer' and getattr(ride, 'ride_pin', None):
        out['pin'] = ride.ride_pin
    if ride_type == 'carhire':
        if ride.eta_seconds is not None:
            out['eta'] = {'seconds': ride.eta_seconds, 'minutes': max(1, round(ride.eta_seconds / 60)),
                          'distance_m': ride.eta_distance_m, 'target': ride.eta_target,
                          'arrives_at': _iso((ride.eta_updated_at or datetime.utcnow()) + timedelta(seconds=ride.eta_seconds)),
                          'updated_at': _iso(ride.eta_updated_at)}
        for col in ('confirmed_at', 'en_route_at', 'driver_arrived_at', 'started_at', 'completed_at',
                    'cancelled_at', 'closed_at', 'awaiting_payment_since'):
            out['timestamps'][col] = _iso(getattr(ride, col, None))
        if ride.awaiting_payment_since and stage == 'AWAITING_PAYMENT':
            out['payment_deadline'] = _iso(ride.awaiting_payment_since + timedelta(seconds=S.get_int('ride.payment_timeout_s')))
    else:
        for col in ('confirmed_at', 'driver_arrived_at', 'checked_in_at', 'dropped_off_at', 'started_at',
                    'completed_at', 'cancelled_at', 'boarding_at', 'departure_at'):
            if hasattr(ride, col):
                out['timestamps'][col] = _iso(getattr(ride, col))
    arrived = getattr(ride, 'driver_arrived_at', None)
    if stage == 'DRIVER_ARRIVED' and arrived:
        window = S.get_int('ride.wait_window_s')
        ends = arrived + timedelta(seconds=window)
        out['wait'] = {'started_at': _iso(arrived), 'ends_at': _iso(ends), 'window_s': window,
                       'free_s': S.get_int('wait.free_s'), 'rate_cents_per_min': S.get_int('wait.rate_cents_per_min'),
                       'seconds_left': max(0, int((ends - datetime.utcnow()).total_seconds()))}
    if ride_type == 'rideshare_trip':
        from backend.models.trip_booking import TripBooking
        bookings = (TripBooking.query.filter(TripBooking.trip_id == ride.id)
                    .order_by(TripBooking.pickup_order.asc(), TripBooking.id.asc()).all())
        if role in ('driver', 'admin'):
            out['passengers'] = [{
                'booking_id': b.id, 'stage': R.current_stage('rideshare_booking', b), 'seats': b.slot_count,
                'customer': R.user_card(b.customer_id, full=True), 'pickup_address': b.pickup_address,
                'pickup_order': b.pickup_order,
            } for b in bookings if not TSM.is_cancel_stage(R.current_stage('rideshare_booking', b))]
        out['departure_at'] = _iso(ride.departure_at)
    if include_timeline:
        out['timeline'] = timeline(ride_type, ride.id)
    return out


def find_active_for(user):
    """The caller's current active ride (spec §4.4 GET /api/rides/active)."""
    from backend.models.negotiation import Negotiation
    from backend.models.scheduled_booking import ScheduledBooking
    from backend.models.trip import Trip
    from backend.models.trip_booking import TripBooking
    uid = user.id
    candidates = []
    active_c = TSM.ACTIVE_STAGES['carhire']
    for n in (Negotiation.query.filter((Negotiation.customer_id == uid) | (Negotiation.driver_id == uid))
              .filter(Negotiation.trip_stage.in_(active_c)).order_by(Negotiation.id.desc()).limit(5)):
        candidates.append(('carhire', n))
    for b in (ScheduledBooking.query.filter((ScheduledBooking.customer_id == uid) | (ScheduledBooking.driver_id == uid))
              .filter(ScheduledBooking.trip_stage.in_(TSM.ACTIVE_STAGES['scheduled']))
              .order_by(ScheduledBooking.id.desc()).limit(5)):
        candidates.append(('scheduled', b))
    for t in (Trip.query.filter(Trip.driver_id == uid, Trip.trip_stage.in_(TSM.ACTIVE_STAGES['rideshare_trip']))
              .order_by(Trip.id.desc()).limit(3)):
        candidates.append(('rideshare_trip', t))
    for b in (TripBooking.query.filter(TripBooking.customer_id == uid,
                                       TripBooking.trip_stage.in_(TSM.ACTIVE_STAGES['rideshare_booking']))
              .order_by(TripBooking.id.desc()).limit(3)):
        candidates.append(('rideshare_booking', b))
    if not candidates:
        return None, None
    # Priority: rides already moving beat rides still being arranged.
    order = ['IN_PROGRESS', 'RIDING', 'CHECKED_IN', 'DRIVER_ARRIVED', 'DRIVER_ARRIVING', 'DRIVER_EN_ROUTE',
             'BOARDING', 'CONFIRMED', 'AWAITING_PAYMENT', 'PRICE_AGREED', 'NEGOTIATING', 'REQUESTED']
    candidates.sort(key=lambda c: (order.index(c[1].trip_stage) if c[1].trip_stage in order else 99,
                                   -(c[1].stage_changed_at or datetime.min).timestamp()))
    return candidates[0]
