"""Experience periodic job — `backend.jobs.scheduler.PERIODIC` runs `tick` every 30 s.

  • favourite-first requests past their 45 s window → broadcast
  • unanswered broadcast requests → expired (customer told, offers withdrawn)
  • rideshare departure reminders `rideshare.departure_reminder_min` before
    departure → 'rideshare.departure_reminder' to passengers + driver, once per trip
  • online-driver supply snapshot (every 10 min bucket) for the supply/demand report
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from backend.models import db
from backend.models.experience import ExperienceMark
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking

log = logging.getLogger('negoride.experience_jobs')

REMINDER_KIND = 'rideshare.departure_reminder'


def tick(now=None):
    now = now or datetime.utcnow()
    out = {}
    from backend.services import matching_service
    try:
        out.update(matching_service.tick(now))
    except Exception:
        db.session.rollback()
        log.exception('matching tick failed')
    try:
        out['departure_reminders'] = departure_reminders(now)
    except Exception:
        db.session.rollback()
        log.exception('departure reminders failed')
    try:
        from backend.services import insights_service
        out['online_drivers'] = insights_service.snapshot_supply(now)
    except Exception:
        db.session.rollback()
        log.exception('supply snapshot failed')
    return out


def mark_once(kind, ref_type, ref_id):
    """True the first time (kind, ref) is marked; False afterwards (unique key)."""
    try:
        db.session.add(ExperienceMark(kind=kind, ref_type=ref_type, ref_id=int(ref_id), created_at=datetime.utcnow()))
        db.session.flush()
        return True
    except IntegrityError:
        db.session.rollback()
        return False


def departure_reminders(now):
    from backend.services.notify import notify
    from backend.services import settings_service as S
    lead = timedelta(minutes=S.get_int('rideshare.departure_reminder_min', 60))
    trips = Trip.query.filter(Trip.trip_stage.in_(('PUBLISHED', 'BOARDING')), Trip.departure_at.isnot(None),
                              Trip.departure_at > now, Trip.departure_at <= now + lead).limit(200).all()
    sent = 0
    for t in trips:
        if ExperienceMark.query.filter_by(kind=REMINDER_KIND, ref_type='rideshare_trip', ref_id=t.id).first():
            continue
        passengers = sorted({int(b.customer_id) for b in TripBooking.query.filter(
            TripBooking.trip_id == t.id,
            TripBooking.trip_stage.in_(('CONFIRMED', 'DRIVER_ARRIVED', 'CHECKED_IN')))})
        if not mark_once(REMINDER_KIND, 'rideshare_trip', t.id):
            continue
        minutes = max(1, int(round((t.departure_at - now).total_seconds() / 60)))
        pickup = t.start_address or t.start_name or 'the pickup point'
        route = f"{t.start_name or 'Start'} → {t.end_name or 'Destination'}"
        ctx = {'ride_type': 'rideshare_trip', 'ride_id': t.id, 'minutes': minutes, 'pickup': pickup, 'route': route}
        ids = passengers + ([int(t.driver_id)] if t.driver_id else [])
        if ids:
            notify('rideshare.departure_reminder', ids, ctx, dedupe_key=f'dep-{t.id}')
        db.session.commit()
        sent += 1
    return sent
