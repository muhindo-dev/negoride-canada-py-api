"""Post-commit side effects of a stage transition (job).

`after_transition(event_id)` runs once per trip_events row, after the
transaction that created it committed:
  • one realtime `ride.stage_changed` event (ride room, each party, admin:ops)
  • the catalogue notifications for the stage
  • money: capture at completion, policy settlement on cancellation
  • rideshare cascades (trip → its seat bookings)
  • delayed follow-ups (wait warning, rating reminder)
  • registered AFTER_HOOKS (safety: stop recording / expire share links; receipts …)
"""
import logging
from datetime import datetime, timedelta

from backend import jobs
from backend.models import db
from backend.models.money import DriverStrike
from backend.models.platform import TripEvent
from backend.models.user import AdminUser
from backend.services import realtime
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services import trip_state_machine as TSM
from backend.services.notify import notify
from backend.utils.money import fmt

log = logging.getLogger('negoride.effects')

AFTER_HOOKS = []   # fn(event: TripEvent, ride) — registered by feature modules


def after_hook(fn):
    AFTER_HOOKS.append(fn)
    return fn


def _first(uid):
    u = db.session.get(AdminUser, uid) if uid else None
    if not u:
        return ''
    return (u.first_name or (u.name or '').split(' ')[0] or '').strip()


def ride_context(ride_type, ride):
    """Template context shared by ride notifications."""
    drv = R.driver_id(ride_type, ride)
    cids = R.customer_ids(ride_type, ride)
    driver = db.session.get(AdminUser, drv) if drv else None
    veh = R.vehicle_card(driver) if driver else None
    vehicle = None
    if veh:
        vehicle = ' '.join(str(x) for x in (veh.get('color'), veh.get('make'), veh.get('model')) if x)
        if veh.get('plate'):
            vehicle = f"{vehicle} {veh['plate']}".strip()
    pickup, dropoff = R.addresses(ride_type, ride)
    ctx = {
        'ride_type': ride_type, 'ride_id': ride.id,
        'driver_first': _first(drv) or 'Your driver', 'customer_first': _first(cids[0]) if cids else '',
        'vehicle': vehicle or '', 'price': fmt(R.fare_cents(ride_type, ride)),
        'pickup': pickup or '', 'dropoff': dropoff or '',
    }
    if ride_type in ('rideshare_booking', 'rideshare_trip'):
        trip = ride if ride_type == 'rideshare_trip' else R.load('rideshare_trip', ride.trip_id)
        ctx['trip_id'] = trip.id
        if ride_type == 'rideshare_booking':
            ctx['booking_id'] = ride.id
        ctx['route'] = f"{trip.start_name or trip.start_address or ''} → {trip.end_name or trip.end_address or ''}"
        ctx['departure'] = trip.departure_at.strftime('%a %b %d, %H:%M UTC') if trip.departure_at else (trip.scheduled_start_time or '')
    eta = getattr(ride, 'eta_seconds', None)
    if eta:
        ctx['eta_min'] = max(1, round(eta / 60))
    return ctx


def after_transition(event_id):
    ev = db.session.get(TripEvent, event_id)
    if not ev:
        return
    ride = R.load(ev.ride_type, ev.ride_id)
    rt, stage = ev.ride_type, ev.to_stage
    payload = {
        'ride_type': rt, 'ride_id': ride.id, 'from_stage': ev.from_stage, 'to_stage': stage, 'stage': stage,
        'legacy_status': ride.status, 'event_id': ev.id, 'actor_type': ev.actor_type,
        'at': ev.created_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    realtime.to_ride(rt, ride.id, 'ride.stage_changed', payload)
    for uid in R.all_party_ids(rt, ride):
        realtime.to_user(uid, 'ride.stage_changed', payload)
    realtime.to_admins('ride.stage_changed', payload)

    try:
        _notifications(ev, ride)
        _money_and_cascades(ev, ride)
    finally:
        db.session.commit()

    for hook in list(AFTER_HOOKS):
        try:
            hook(ev, ride)
        except Exception:
            log.exception('after-hook %s failed for event %s', getattr(hook, '__name__', hook), ev.id)
    db.session.commit()


def _policy(ev):
    return (ev.meta or {}).get('policy') or {}


def _notifications(ev, ride):
    rt, stage = ev.ride_type, ev.to_stage
    ctx = ride_context(rt, ride)
    drv = R.driver_id(rt, ride)
    cids = R.customer_ids(rt, ride)
    customer = cids[0] if cids else None
    per_role = {'per_user': {}}
    for c in cids:
        per_role['per_user'][str(c)] = {'is_customer': True}
    if drv:
        per_role['per_user'][str(drv)] = {'is_customer': False}

    if rt in ('carhire', 'scheduled'):
        if stage == 'REQUESTED' and ev.from_stage is None and drv and rt == 'carhire':
            extra = {}
            d = db.session.get(AdminUser, drv)
            pp = R.pickup_point(rt, ride)
            if d and pp and d.current_latitude is not None:
                dist = R.haversine_m(pp, (float(d.current_latitude), float(d.current_longitude)))
                extra['distance_km'] = round(dist / 1000, 1) if dist is not None else None
            notify('negotiation.new_request', [drv], {**ctx, **extra})
        elif stage == 'PRICE_AGREED':
            notify('negotiation.agreed', [customer, drv], {**ctx, **per_role})
        elif stage == 'CONFIRMED':
            notify('payment.authorized', [customer, drv], {**ctx, **per_role})
        elif stage == 'DRIVER_EN_ROUTE':
            notify('ride.driver_en_route', [customer], ctx)
        elif stage == 'DRIVER_ARRIVING':
            notify('ride.driver_arriving', [customer], ctx)
        elif stage == 'DRIVER_ARRIVED':
            window = S.get_int('ride.wait_window_s')
            ends = (getattr(ride, "driver_arrived_at", None) or datetime.utcnow()) + timedelta(seconds=window)
            notify('ride.driver_arrived', [customer],
                   {**ctx, 'pin': ride.ride_pin if TSM.pin_required(rt, ride) else '',
                    'wait_until': ends.strftime('%H:%M UTC')}, dedupe_key=f'arrived-{rt}-{ride.id}')
            warn_in = window - S.get_int('ride.wait_warning_before_s')
            if warn_in > 0:
                jobs.enqueue_in(warn_in, wait_warning, rt, ride.id, ev.id)
        elif stage == 'IN_PROGRESS':
            notify('ride.started', [customer], ctx)
        elif stage == 'COMPLETED':
            earning = ''
            notify('ride.completed', [customer, drv], {**ctx, **per_role, 'earning': earning})
            _rating_reminder(rt, ride, [customer, drv])
        elif stage in ('CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_DRIVER'):
            p = _policy(ev)
            by = 'driver' if stage == 'CANCELLED_BY_DRIVER' else 'customer'
            other = customer if by == 'driver' else drv
            refund_text = ''
            if by == 'driver' and p.get('paid_cents', p.get('breakdown', {}).get('paid_cents', 0)):
                refund_text = 'Full refund issued.'
            if other:
                notify('ride.cancelled', [other], {**ctx, 'cancelled_by': by,
                                                   'cancelled_by_fr': 'chauffeur' if by == 'driver' else 'client',
                                                   'refund_text': refund_text})
        elif stage == 'CUSTOMER_NO_SHOW':
            notify('ride.customer_no_show', [customer], {**ctx, 'fee': fmt(_policy(ev).get('fee_cents', 0))})
        elif stage == 'DRIVER_NO_SHOW':
            credit = _policy(ev).get('credit_cents', 0)
            notify('ride.driver_no_show', [customer], {**ctx, 'credit': fmt(credit) if credit else ''})
        elif stage == 'EXPIRED':
            notify('ride.expired', [customer], ctx)
    elif rt == 'rideshare_booking':
        if stage == 'REQUESTED':
            notify('rideshare.booking_requested', [drv], {**ctx, 'seats': ride.slot_count or 1,
                                                          'minutes': S.get_int('rideshare.request_timeout_min')})
        elif stage == 'PENDING_PAYMENT' and ev.from_stage == 'REQUESTED':
            notify('rideshare.booking_approved', [customer], ctx)
        elif stage == 'DECLINED':
            notify('rideshare.booking_declined', [customer], ctx)
        elif stage == 'CONFIRMED':
            notify('rideshare.booking_confirmed', [customer, drv], ctx)
        elif stage == 'DRIVER_ARRIVED':
            notify('ride.driver_arrived', [customer], {**ctx, 'pin': ride.ride_pin if TSM.pin_required(rt, ride) else ''},
                   dedupe_key=f'arrived-{rt}-{ride.id}')
        elif stage == 'DROPPED_OFF':
            notify('ride.completed', [customer], {**ctx, 'is_customer': True})
            _rating_reminder(rt, ride, [customer])
        elif stage == 'CANCELLED_BY_DRIVER':
            notify('ride.cancelled', [customer], {**ctx, 'cancelled_by': 'driver', 'cancelled_by_fr': 'chauffeur',
                                                  'refund_text': 'Full refund issued.'})
        elif stage == 'CANCELLED_BY_CUSTOMER' and drv:
            notify('ride.cancelled', [drv], {**ctx, 'cancelled_by': 'passenger', 'cancelled_by_fr': 'passager'})
    elif rt == 'rideshare_trip':
        if stage == 'BOARDING':
            notify('rideshare.boarding', cids + ([drv] if drv else []), ctx)


def _rating_reminder(rt, ride, user_ids):
    hours = S.get_int('rating.reminder_after_h')
    jobs.enqueue_in(hours * 3600, rating_reminder, rt, ride.id, [u for u in user_ids if u])


def rating_reminder(ride_type, ride_id, user_ids):
    from backend.models.experience import RideRating
    ride = R.load(ride_type, ride_id)
    rated = {r.rater_id for r in RideRating.query.filter_by(ride_type=ride_type, ride_id=ride_id).all()}
    drv = R.driver_id(ride_type, ride)
    for uid in user_ids:
        if uid in rated:
            continue
        other = (R.customer_ids(ride_type, ride) or [None])[0] if uid == drv else drv
        notify('rating.reminder', [uid], {'ride_type': ride_type, 'ride_id': ride_id, 'other_first': _first(other)},
               dedupe_key=f'rate-{ride_type}-{ride_id}')
    db.session.commit()


def wait_warning(ride_type, ride_id, arrived_event_id):
    ride = R.load(ride_type, ride_id)
    if R.current_stage(ride_type, ride) != 'DRIVER_ARRIVED':
        return
    last = (TripEvent.query.filter_by(ride_type=ride_type, ride_id=ride_id)
            .order_by(TripEvent.id.desc()).first())
    if last and last.id != arrived_event_id:
        return
    cid = (R.customer_ids(ride_type, ride) or [None])[0]
    notify('ride.wait_warning', [cid], {**ride_context(ride_type, ride),
                                        'minutes_left': max(1, S.get_int('ride.wait_warning_before_s') // 60)})
    db.session.commit()


def _money_and_cascades(ev, ride):
    rt, stage = ev.ride_type, ev.to_stage

    # Price agreed → payment step (or straight to CONFIRMED when pay-later is configured)
    if rt in ('carhire', 'scheduled') and stage == 'PRICE_AGREED':
        target = 'AWAITING_PAYMENT' if S.flag('pay_before_trip') else 'CONFIRMED'
        try:
            TSM.transition(rt, ride.id, target, actor=None, meta={'auto': True})
        except TSM.TransitionError as e:
            log.info('auto %s skipped for %s/%s: %s', target, rt, ride.id, e.message)

    if (rt in ('carhire', 'scheduled') and stage == 'COMPLETED') or (rt == 'rideshare_booking' and stage == 'DROPPED_OFF'):
        jobs.enqueue('backend.services.trip_effects.complete_payment_and_receipt', rt, ride.id)

    if TSM.is_cancel_stage(stage) and rt != 'rideshare_trip':
        decision = _policy(ev)
        if decision:
            jobs.enqueue('backend.services.payments.payment_service.settle_cancellation', rt, ride.id, decision)
            cascaded = (ev.meta or {}).get('reason_code') == 'trip_cancelled'  # trip-level strike instead
            if decision.get('strike') and not cascaded:
                add_strike(R.driver_id(rt, ride), 'driver_no_show' if stage == 'DRIVER_NO_SHOW' else 'driver_cancel',
                           rt, ride.id)

    if rt == 'rideshare_trip':
        _trip_cascade(ev, ride)


def _trip_cascade(ev, trip):
    from backend.models.trip_booking import TripBooking
    stage = ev.to_stage
    bookings = TripBooking.query.filter_by(trip_id=trip.id).all()
    for b in bookings:
        TSM.ensure_stage('rideshare_booking', b)
    db.session.commit()
    for b in bookings:
        bs = b.trip_stage
        try:
            if stage == 'IN_PROGRESS' and bs == 'CHECKED_IN':
                TSM.transition('rideshare_booking', b.id, 'RIDING', actor=None, meta={'cascade': ev.id})
            elif stage == 'COMPLETED':
                if bs in ('CHECKED_IN', 'RIDING'):
                    TSM.transition('rideshare_booking', b.id, 'DROPPED_OFF', actor=None, meta={'cascade': ev.id})
                elif bs in ('CONFIRMED', 'DRIVER_ARRIVED'):
                    from backend.services.ride_actions import cancel
                    cancel('rideshare_booking', b.id, actor_type='system', reason='customer_no_show',
                           reason_code='trip_completed_without_boarding')
                elif bs in ('REQUESTED', 'PENDING_PAYMENT'):
                    from backend.services.ride_actions import cancel
                    cancel('rideshare_booking', b.id, actor_type='system', reason='expired')
            elif stage == 'CANCELLED_BY_DRIVER' and not TSM.is_terminal('rideshare_booking', bs):
                from backend.services.ride_actions import cancel
                cancel('rideshare_booking', b.id, actor_type='system', reason='driver_cancel',
                       reason_code='trip_cancelled')
        except TSM.TransitionError as e:
            log.warning('cascade %s → booking %s skipped: %s', stage, b.id, e.message)
    if stage == 'CANCELLED_BY_DRIVER' and any(b.confirmed_at for b in bookings):
        # One strike for cancelling a trip that had confirmed passengers.
        add_strike(trip.driver_id, 'driver_cancel', 'rideshare_trip', trip.id)


def add_strike(driver_id, reason, ride_type, ride_id, note=None):
    """Reliability strike (spec §7.3). Unique per (driver, reason, ride)."""
    if not driver_id:
        return
    exists = DriverStrike.query.filter_by(driver_id=driver_id, reason=reason, ride_type=ride_type,
                                          ride_id=ride_id).first()
    if exists:
        return
    db.session.add(DriverStrike(driver_id=driver_id, reason=reason, ride_type=ride_type, ride_id=ride_id, note=note))
    db.session.commit()
    try:
        from backend.services import account_service
        account_service.evaluate_strikes(driver_id)
    except (ImportError, AttributeError):
        pass


def complete_payment_and_receipt(ride_type, ride_id):
    from backend.services.payments.payment_service import capture_for_completion
    capture_for_completion(ride_type, ride_id)
    issue_receipt_safe(ride_type, ride_id)


def issue_receipt_safe(ride_type, ride_id):
    if not S.flag('receipts_email'):
        return
    try:
        from backend.services import receipts
    except ImportError:
        log.info('receipts module not installed — skipping receipt for %s/%s', ride_type, ride_id)
        return
    receipts.issue_and_send(ride_type, ride_id)


def issue_credit_note_safe(refund_id):
    try:
        from backend.services import receipts
    except ImportError:
        return
    receipts.issue_credit_note_for_refund(refund_id)
