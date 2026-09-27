"""Two-way ratings, reviews and tips (spec §17).

Rules
  • customer ↔ driver, 1–5 stars, after COMPLETED / DROPPED_OFF (or CLOSED), within
    `rating.rate_within_h` (72 h) of the ride ending; one rating per (ride, rater) → 409
  • tags from fixed positive / negative lists (per rater role); optional comment
  • 1–2 stars → response asks "What went wrong?" + offers "Report a safety issue"
  • optional tip (customer → driver, 100 % to the driver) via a Checkout
    (payment_service.start_extra_payment('tip', …)); the wallet is credited when paid
  • hidden from the other party until both submitted, or 72 h after the ride ended
    (`visible_at`); customers never see an individual rating attributed to them
  • score = Bayesian average over the ratee's last `rating.window` non-hidden
    ratings: (prior_mean × prior_weight + Σ stars) / (prior_weight + n)
    → users.rating (2 dp), users.rating_count (all non-hidden), users.rating_avg_raw
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.exc import IntegrityError

from backend.models import db
from backend.models.experience import RideRating
from backend.models.user import AdminUser
from backend.services import rides as R
from backend.services import settings_service as S

log = logging.getLogger('negoride.ratings')

RATEABLE_TYPES = ('carhire', 'scheduled', 'rideshare_booking')
RATEABLE_STAGES = ('COMPLETED', 'DROPPED_OFF', 'CLOSED')

# key → (EN, FR). Customer rates the driver (spec §17); driver rates the customer.
TAGS = {
    'customer': {
        'positive': {
            'safe_driving': ('Safe driving', 'Conduite sécuritaire'),
            'clean_car': ('Clean car', 'Voiture propre'),
            'great_conversation': ('Great conversation', 'Bonne conversation'),
            'fair_negotiator': ('Fair negotiator', 'Négociateur équitable'),
            'on_time': ('On time', 'À l’heure'),
        },
        'negative': {
            'late': ('Late', 'En retard'),
            'unsafe_driving': ('Unsafe driving', 'Conduite dangereuse'),
            'rude': ('Rude', 'Impoli'),
            'dirty_car': ('Dirty car', 'Voiture sale'),
            'wrong_route': ('Wrong route', 'Mauvais itinéraire'),
            'price_changed': ('Price changed after agreement', 'Prix modifié après accord'),
        },
    },
    'driver': {
        'positive': {
            'respectful': ('Respectful', 'Respectueux'),
            'on_time': ('On time', 'À l’heure'),
            'great_conversation': ('Great conversation', 'Bonne conversation'),
            'fair_negotiator': ('Fair negotiator', 'Négociateur équitable'),
            'tidy': ('Left the car tidy', 'A laissé la voiture propre'),
        },
        'negative': {
            'late': ('Late', 'En retard'),
            'rude': ('Rude', 'Impoli'),
            'messy': ('Messy', 'Désordonné'),
            'price_changed': ('Tried to change the price after agreement', 'A voulu changer le prix après accord'),
            'unsafe_behaviour': ('Unsafe behaviour', 'Comportement dangereux'),
        },
    },
}


class RatingError(Exception):
    def __init__(self, message, code='rating_error', status=400, data=None):
        super().__init__(message)
        self.message, self.code, self.status, self.data = message, code, status, data or {}


def tag_catalogue():
    out = {}
    for role, groups in TAGS.items():
        out[role] = {kind: [{'key': k, 'en': v[0], 'fr': v[1]} for k, v in tags.items()]
                     for kind, tags in groups.items()}
    return out


def _normalize_tags(role, tags):
    if not tags:
        return []
    if not isinstance(tags, (list, tuple)):
        raise RatingError('tags must be a list.', code='bad_tags')
    lookup = {}
    for kind, group in TAGS[role].items():
        for k, (en, fr) in group.items():
            lookup[k] = k
            lookup[en.lower()] = k
            lookup[fr.lower()] = k
    out = []
    for t in tags:
        k = lookup.get(str(t).strip().lower())
        if not k:
            raise RatingError(f"Unknown tag '{t}'.", code='bad_tags')
        if k not in out:
            out.append(k)
    return out


def ended_at(ride_type, ride):
    return (getattr(ride, 'completed_at', None) or getattr(ride, 'dropped_off_at', None)
            or getattr(ride, 'closed_at', None) or ride.stage_changed_at)


def other_party(ride_type, ride, user_id):
    drv = R.driver_id(ride_type, ride)
    if user_id == drv:
        cids = R.customer_ids(ride_type, ride)
        return cids[0] if cids else None
    return drv


# ── score ───────────────────────────────────────────────────────────────────

def bayesian(stars_list, prior_mean, prior_weight):
    n = len(stars_list)
    return (prior_mean * prior_weight + sum(stars_list)) / float(prior_weight + n) if (prior_weight + n) else prior_mean


def recompute_score(user_id, commit=False):
    """Recompute users.rating / rating_count / rating_avg_raw from ride_ratings."""
    window = max(1, S.get_int('rating.window', 100))
    prior_mean = S.get_float('rating.prior_mean', 4.8)
    prior_weight = max(0, S.get_int('rating.prior_weight', 5))
    base = RideRating.query.filter(RideRating.ratee_id == user_id, RideRating.hidden_by_admin.is_(False))
    recent = [r.stars for r in base.order_by(RideRating.created_at.desc(), RideRating.id.desc()).limit(window)]
    total = base.count()
    user = db.session.get(AdminUser, int(user_id))
    if not user:
        return None
    if recent:
        score = bayesian(recent, prior_mean, prior_weight)
        user.rating = Decimal(str(score)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        user.rating_avg_raw = (Decimal(sum(recent)) / Decimal(len(recent))).quantize(Decimal('0.001'),
                                                                                     rounding=ROUND_HALF_UP)
    else:
        user.rating = 0
        user.rating_avg_raw = None
    user.rating_count = total
    if commit:
        db.session.commit()
    return {'rating': float(user.rating or 0), 'rating_count': total,
            'rating_avg_raw': float(user.rating_avg_raw) if user.rating_avg_raw is not None else None}


# ── submit ──────────────────────────────────────────────────────────────────

def _int(v, name, lo=None, hi=None, default=None):
    if v in (None, ''):
        return default
    try:
        i = int(v)
    except (TypeError, ValueError):
        raise RatingError(f'Invalid {name}.', code=f'bad_{name}')
    if (lo is not None and i < lo) or (hi is not None and i > hi):
        raise RatingError(f'{name} must be between {lo} and {hi}.', code=f'bad_{name}')
    return i


def submit(user, ride_type, ride_id, data):
    """Save a rating. Returns (rating, extra) where extra carries tip checkout / prompts."""
    if not S.flag('ratings_v2'):
        raise RatingError('Ratings are not available right now.', code='feature_off', status=403)
    rt = R.normalize_type(ride_type)
    if rt not in RATEABLE_TYPES:
        raise RatingError('Rate each passenger booking, not the whole trip.', code='not_rateable')
    ride = R.load(rt, ride_id)
    role = R.role_of(user, rt, ride)
    if role not in ('customer', 'driver'):
        raise RatingError('Only the rider and the driver can rate this ride.', code='forbidden', status=403)
    stage = R.current_stage(rt, ride)
    if stage not in RATEABLE_STAGES:
        raise RatingError('You can rate the ride once it is completed.', code='not_completed', status=409)
    end = ended_at(rt, ride) or datetime.utcnow()
    now = datetime.utcnow()
    within = timedelta(hours=S.get_int('rating.rate_within_h', 72))
    if now > end + within:
        raise RatingError('The rating window for this ride has closed.', code='rating_window_closed', status=410)

    stars = _int(data.get('stars'), 'stars', 1, 5)
    if stars is None:
        raise RatingError('stars is required (1–5).', code='bad_stars')
    tags = _normalize_tags(role, data.get('tags'))
    comment = (data.get('comment') or '').strip()[:1000] or None
    tip_cents = _int(data.get('tip_cents'), 'tip_cents', 0, 50000, 0)
    if tip_cents and role != 'customer':
        raise RatingError('Only the rider can add a tip.', code='tip_not_allowed')
    if tip_cents and tip_cents < 50:
        raise RatingError('The minimum tip is $0.50.', code='tip_too_low')

    ratee = other_party(rt, ride, user.id)
    if not ratee:
        raise RatingError('There is no one to rate on this ride.', code='no_ratee', status=409)
    if RideRating.query.filter_by(ride_type=rt, ride_id=ride.id, rater_id=user.id).first():
        raise RatingError('You have already rated this ride.', code='duplicate', status=409)

    rating = RideRating(ride_type=rt, ride_id=ride.id, rater_id=user.id, ratee_id=ratee, role=role,
                        stars=stars, tags=tags, comment=comment, tip_cents=tip_cents or 0,
                        visible_at=end + within, created_at=now)
    db.session.add(rating)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise RatingError('You have already rated this ride.', code='duplicate', status=409)
    # Both sides in → visible now.
    counterpart = RideRating.query.filter(RideRating.ride_type == rt, RideRating.ride_id == ride.id,
                                          RideRating.rater_id == ratee).first()
    if counterpart:
        now = now.replace(microsecond=0)   # DATETIME rounds; never land in the future
        rating.visible_at = now
        if counterpart.visible_at is None or counterpart.visible_at > now:
            counterpart.visible_at = now
    recompute_score(ratee)
    db.session.commit()

    extra = {}
    if stars <= 2:
        extra['ask_what_went_wrong'] = True
        extra['safety_report'] = {
            'label': 'Report a safety issue',
            'endpoint': '/api/safety/reports',
            'ride_type': rt, 'ride_id': ride.id,
        }
    if tip_cents:
        from backend.services.payments import payment_service as PS
        try:
            rp = PS.start_extra_payment('tip', rt, ride.id, user, tip_cents, driver_id=ratee,
                                        description=f'Tip for your NegoRide trip #{ride.id}')
            rating = db.session.get(RideRating, rating.id)
            rating.tip_payment_id = rp.id
            db.session.commit()
            extra['tip'] = {'ride_payment_id': rp.id, 'amount_cents': tip_cents, 'checkout_url': rp.checkout_url,
                            'status': rp.capture_status}
        except PS.PaymentError as e:
            extra['tip'] = {'error': e.message, 'error_code': e.code}

    _after_save(rt, ride.id, ratee, role)
    return db.session.get(RideRating, rating.id), extra


def _after_save(ride_type, ride_id, ratee_id, rater_role):
    try:
        from backend.services import ride_jobs
        ride_jobs.close_if_both_rated(ride_type, ride_id)
    except Exception:
        db.session.rollback()
        log.exception('close_if_both_rated failed')
    if rater_role == 'customer':
        try:
            from backend.services import account_service
            account_service.evaluate_rating_rules(ratee_id)
        except (ImportError, AttributeError):
            pass
        except Exception:
            db.session.rollback()
            log.exception('evaluate_rating_rules failed')


# ── views ───────────────────────────────────────────────────────────────────

def _public(r, include_comment=True):
    return {'id': r.id, 'stars': r.stars, 'tags': r.tags or [], 'comment': r.comment if include_comment else None,
            'role': r.role, 'created_at': r.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')}


def status_for(user, ride_type, ride_id):
    rt = R.normalize_type(ride_type)
    ride = R.load(rt, ride_id)
    role = R.role_of(user, rt, ride)
    if role not in ('customer', 'driver', 'admin'):
        raise RatingError('You are not part of this ride.', code='forbidden', status=403)
    now = datetime.utcnow()
    mine = RideRating.query.filter_by(ride_type=rt, ride_id=ride.id, rater_id=user.id).first()
    other_id = other_party(rt, ride, user.id) if role != 'admin' else None
    other = RideRating.query.filter_by(ride_type=rt, ride_id=ride.id, rater_id=other_id).first() if other_id else None
    stage = R.current_stage(rt, ride)
    end = ended_at(rt, ride)
    deadline = end + timedelta(hours=S.get_int('rating.rate_within_h', 72)) if end else None
    can_rate = (rt in RATEABLE_TYPES and role in ('customer', 'driver') and mine is None
                and stage in RATEABLE_STAGES and (deadline is None or now <= deadline))
    visible_other = None
    # Customers never see an individual rating attributed to them (spec §17 fairness).
    if other and role == 'driver' and not other.hidden_by_admin and other.visible_at and other.visible_at <= now:
        visible_other = _public(other)
    return {
        'ride_type': rt, 'ride_id': ride.id, 'viewer_role': role,
        'can_rate': can_rate, 'rate_until': deadline.strftime('%Y-%m-%dT%H:%M:%SZ') if deadline else None,
        'my_rating': {**_public(mine), 'tip_cents': mine.tip_cents, 'tip_payment_id': mine.tip_payment_id}
        if mine else None,
        'other_party_rated': other is not None,
        'other_rating': visible_other,
        'tags': tag_catalogue().get(role if role in TAGS else 'customer'),
    }


def profile_card(driver_id):
    from backend.models.identity import BackgroundCheck
    from backend.models.negotiation import Negotiation
    from backend.models.scheduled_booking import ScheduledBooking
    from backend.models.trip_booking import TripBooking
    from backend.models.user import resolve_media_url
    d = db.session.get(AdminUser, int(driver_id))
    if not d or not d.is_approved_driver():
        return None
    done = ('COMPLETED', 'CLOSED')
    trips = (Negotiation.query.filter(Negotiation.driver_id == d.id,
                                      (Negotiation.trip_stage.in_(done)) | (Negotiation.status == 'Completed')).count()
             + ScheduledBooking.query.filter(ScheduledBooking.driver_id == d.id,
                                             (ScheduledBooking.trip_stage.in_(done))
                                             | (ScheduledBooking.status == 'completed')).count()
             + TripBooking.query.filter(TripBooking.driver_id == d.id,
                                        TripBooking.trip_stage.in_(('DROPPED_OFF', 'CLOSED'))).count())
    now = datetime.utcnow()
    since = d.created_at or now
    years = round(max(0.0, (now - since).days / 365.25), 1)
    counts = {}
    positive = TAGS['customer']['positive']
    rows = (RideRating.query.filter(RideRating.ratee_id == d.id, RideRating.role == 'customer',
                                    RideRating.hidden_by_admin.is_(False))
            .order_by(RideRating.id.desc()).limit(500).all())
    for r in rows:
        for t in (r.tags or []):
            if t in positive:
                counts[t] = counts.get(t, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    bgc = BackgroundCheck.query.filter_by(user_id=d.id, status='clear').first() is not None
    veh = R.vehicle_card(d) or {}
    first = (d.first_name or (d.name or '').split(' ')[0] or 'Driver').strip()
    return {
        'id': d.id, 'first_name': first, 'avatar': resolve_media_url(d.avatar),
        'rating': float(d.rating) if d.rating else None, 'rating_count': d.rating_count or 0,
        'total_trips': trips, 'years_on_negoride': years,
        'member_since': since.strftime('%Y-%m'),
        'top_compliments': [{'key': k, 'label': positive[k][0], 'label_fr': positive[k][1], 'count': c}
                            for k, c in top],
        'vehicle': {k: veh.get(k) for k in ('make', 'model', 'year', 'color', 'seats')},
        'badges': {'verified': bool(d.is_approved_driver()), 'background_checked': bgc,
                   'phone_verified': bool(d.phone_verified_at)},
    }
