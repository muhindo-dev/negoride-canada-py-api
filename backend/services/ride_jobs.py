"""Scheduled lifecycle job — runs every 30 s (spec §4.3):
  • expire unpaid AWAITING_PAYMENT / PENDING_PAYMENT rides
  • expire stale REQUESTED / NEGOTIATING car-hire requests
  • expire unanswered request-to-book seat requests
  • detect DRIVER_NO_SHOW (not arrived by ETA + grace)
  • auto-advance DRIVER_EN_ROUTE → DRIVER_ARRIVING by distance / ETA
  • auto-close COMPLETED / DROPPED_OFF after 72 h
  • move rideshare trips to BOARDING 30 min before departure

Only rows managed by v4 (trip_stage set) are touched, so legacy data is never
swept up. Every action goes through the state machine; failures are logged
per ride and never stop the tick.
"""
import logging
from datetime import datetime, timedelta

from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.models.user import AdminUser
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services import trip_state_machine as TSM
from backend.services.ride_actions import cancel

log = logging.getLogger('negoride.ride_jobs')


def _safe(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        return 1
    except TSM.TransitionError as e:
        db.session.rollback()
        log.info('lifecycle skip: %s', e.message)
    except Exception:
        db.session.rollback()
        log.exception('lifecycle action failed')
    return 0


def tick_lifecycle(now=None):
    now = now or datetime.utcnow()
    done = {}
    done['payment_expired'] = expire_unpaid(now)
    done['requests_expired'] = expire_stale_requests(now)
    done['driver_no_show'] = detect_driver_no_show(now)
    done['arriving'] = auto_arriving()
    done['closed'] = auto_close(now)
    done['boarding'] = rideshare_boarding(now)
    return done


def expire_unpaid(now):
    cutoff = now - timedelta(seconds=S.get_int('ride.payment_timeout_s'))
    n = 0
    for model, rt in ((Negotiation, 'carhire'), (ScheduledBooking, 'scheduled')):
        rows = model.query.filter(model.trip_stage == 'AWAITING_PAYMENT',
                                  model.stage_changed_at <= cutoff).limit(100).all()
        for r in rows:
            if TSM.payment_secured(rt, r):
                continue  # webhook raced the tick — confirmation will follow
            n += _safe(cancel, rt, r.id, actor_type='system', reason='expired', reason_code='payment_timeout')
    rows = TripBooking.query.filter(TripBooking.trip_stage == 'PENDING_PAYMENT',
                                    TripBooking.stage_changed_at <= cutoff).limit(100).all()
    for b in rows:
        if not TSM.payment_secured('rideshare_booking', b):
            n += _safe(cancel, 'rideshare_booking', b.id, actor_type='system', reason='expired',
                       reason_code='payment_timeout')
    return n


def expire_stale_requests(now):
    n = 0
    cutoff = now - timedelta(seconds=S.get_int('ride.negotiation_timeout_s'))
    rows = Negotiation.query.filter(Negotiation.trip_stage.in_(['REQUESTED', 'NEGOTIATING']),
                                    Negotiation.updated_at <= cutoff).limit(100).all()
    for r in rows:
        n += _safe(cancel, 'carhire', r.id, actor_type='system', reason='expired', reason_code='no_agreement')
    rows = TripBooking.query.filter(TripBooking.trip_stage == 'REQUESTED',
                                    TripBooking.request_expires_at <= now).limit(100).all()
    for b in rows:
        n += _safe(cancel, 'rideshare_booking', b.id, actor_type='system', reason='expired',
                   reason_code='request_not_answered')
    return n


def detect_driver_no_show(now):
    n = 0
    stages = ['CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING']
    for model, rt in ((Negotiation, 'carhire'), (ScheduledBooking, 'scheduled')):
        for r in model.query.filter(model.trip_stage.in_(stages)).limit(300).all():
            due = TSM.driver_no_show_due_at(r)
            sched = getattr(r, 'scheduled_at', None)
            if sched and due and sched + timedelta(seconds=S.get_int('ride.driver_no_show_grace_s')) > due:
                due = sched + timedelta(seconds=S.get_int('ride.driver_no_show_grace_s'))
            if due and now >= due:
                n += _safe(cancel, rt, r.id, actor_type='system', reason='driver_no_show',
                           reason_code='not_arrived_in_time')
    return n


def auto_arriving():
    """DRIVER_EN_ROUTE → DRIVER_ARRIVING when ETA ≤ 2 min or distance ≤ 500 m."""
    n = 0
    eta_s, dist_m = S.get_int('ride.arriving_eta_s'), S.get_int('ride.arriving_distance_m')
    for model, rt in ((Negotiation, 'carhire'), (ScheduledBooking, 'scheduled')):
        for r in model.query.filter(model.trip_stage == 'DRIVER_EN_ROUTE').limit(300).all():
            if should_mark_arriving(rt, r, eta_s, dist_m):
                n += _safe(TSM.transition, rt, r.id, 'DRIVER_ARRIVING', actor=None, meta={'auto': True})
    return n


def should_mark_arriving(rt, ride, eta_s=None, dist_m=None):
    eta_s = eta_s if eta_s is not None else S.get_int('ride.arriving_eta_s')
    dist_m = dist_m if dist_m is not None else S.get_int('ride.arriving_distance_m')
    if getattr(ride, 'eta_seconds', None) is not None and getattr(ride, 'eta_target', None) in (None, 'pickup') \
            and ride.eta_seconds <= eta_s:
        return True
    drv = db.session.get(AdminUser, R.driver_id(rt, ride)) if R.driver_id(rt, ride) else None
    pickup = R.pickup_point(rt, ride)
    if drv and pickup and drv.current_latitude is not None and drv.current_longitude is not None:
        d = R.haversine_m(pickup, (float(drv.current_latitude), float(drv.current_longitude)))
        return d is not None and d <= dist_m
    return False


def auto_close(now):
    n = 0
    cutoff = now - timedelta(hours=S.get_int('ride.auto_close_h'))
    for model, rt, st in ((Negotiation, 'carhire', 'COMPLETED'), (ScheduledBooking, 'scheduled', 'COMPLETED'),
                          (TripBooking, 'rideshare_booking', 'DROPPED_OFF'), (Trip, 'rideshare_trip', 'COMPLETED')):
        for r in model.query.filter(model.trip_stage == st, model.stage_changed_at <= cutoff).limit(200).all():
            n += _safe(TSM.transition, rt, r.id, 'CLOSED', actor=None, meta={'auto': True, 'reason': '72h'})
    return n


def rideshare_boarding(now):
    n = 0
    lead = timedelta(minutes=S.get_int('rideshare.boarding_before_min'))
    for t in Trip.query.filter(Trip.trip_stage == 'PUBLISHED', Trip.departure_at.isnot(None),
                               Trip.departure_at <= now + lead).limit(200).all():
        n += _safe(TSM.transition, 'rideshare_trip', t.id, 'BOARDING', actor=None, meta={'auto': True})
    return n


def close_if_both_rated(ride_type, ride_id):
    """Called by the ratings module: COMPLETED → CLOSED once both sides rated."""
    from backend.models.experience import RideRating
    ride = R.load(ride_type, ride_id)
    if R.current_stage(ride_type, ride) not in ('COMPLETED', 'DROPPED_OFF'):
        return False
    raters = {r.rater_id for r in RideRating.query.filter_by(ride_type=ride_type, ride_id=ride_id)}
    needed = set(R.all_party_ids(ride_type, ride))
    if needed and needed <= raters:
        return bool(_safe(TSM.transition, ride_type, ride_id, 'CLOSED', actor=None,
                          meta={'auto': True, 'reason': 'both_rated'}))
    return False
