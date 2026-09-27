"""Ratings, favourites and referrals (spec §14.3, §17, §18)."""
from backend.models import db
from backend.models.base import SerializeMixin, utcnow


class RideRating(SerializeMixin, db.Model):
    __tablename__ = 'ride_ratings'
    __table_args__ = (db.UniqueConstraint('ride_type', 'ride_id', 'rater_id', name='uq_rating'),)

    id = db.Column(db.BigInteger, primary_key=True)
    ride_type = db.Column(db.String(30), nullable=False)
    ride_id = db.Column(db.BigInteger, nullable=False)
    rater_id = db.Column(db.Integer, nullable=False)
    ratee_id = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(20), nullable=False)  # role of the RATER: customer|driver
    stars = db.Column(db.SmallInteger, nullable=False)
    tags = db.Column(db.JSON)
    comment = db.Column(db.Text)
    tip_cents = db.Column(db.BigInteger, nullable=False, default=0)
    tip_payment_id = db.Column(db.BigInteger)
    visible_at = db.Column(db.DateTime)
    hidden_by_admin = db.Column(db.Boolean, nullable=False, default=False)
    hidden_by = db.Column(db.Integer)
    hidden_reason = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class FavouriteDriver(SerializeMixin, db.Model):
    __tablename__ = 'favourite_drivers'
    __table_args__ = (db.UniqueConstraint('customer_id', 'driver_id', name='uq_fav'),)

    id = db.Column(db.BigInteger, primary_key=True)
    customer_id = db.Column(db.Integer, nullable=False)
    driver_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class Referral(SerializeMixin, db.Model):
    __tablename__ = 'referrals'

    id = db.Column(db.BigInteger, primary_key=True)
    referrer_id = db.Column(db.Integer, nullable=False)
    referred_id = db.Column(db.Integer, nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending|qualified|paid
    bonus_cents = db.Column(db.BigInteger, nullable=False, default=0)
    paid_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


# ── Car hire matching (spec §18.2) — migration v4_0301 ─────────────────────

class RideRequest(SerializeMixin, db.Model):
    """One customer car-hire request. mode: direct | favourite_first | broadcast.
    status: favourite → broadcasting → matched | expired | cancelled | no_drivers."""
    __tablename__ = 'ride_requests'

    id = db.Column(db.BigInteger, primary_key=True)
    customer_id = db.Column(db.Integer, nullable=False)
    mode = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    service_type = db.Column(db.String(40), nullable=False, default='car')
    pickup_lat = db.Column(db.Numeric(10, 7), nullable=False)
    pickup_lng = db.Column(db.Numeric(10, 7), nullable=False)
    pickup_address = db.Column(db.String(500))
    dropoff_lat = db.Column(db.Numeric(10, 7))
    dropoff_lng = db.Column(db.Numeric(10, 7))
    dropoff_address = db.Column(db.String(500))
    offer_cents = db.Column(db.BigInteger, nullable=False)
    note = db.Column(db.String(500))
    favourite_driver_id = db.Column(db.Integer)
    favourite_until = db.Column(db.DateTime)
    broadcast_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)
    negotiation_id = db.Column(db.BigInteger)
    matched_driver_id = db.Column(db.Integer)
    matched_at = db.Column(db.DateTime)
    distance_m = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class RideRequestOffer(SerializeMixin, db.Model):
    """A request offered to one driver. status: offered | accepted | countered |
    declined | withdrawn | expired."""
    __tablename__ = 'ride_request_offers'
    __table_args__ = (db.UniqueConstraint('request_id', 'driver_id', name='uq_rro'),)

    id = db.Column(db.BigInteger, primary_key=True)
    request_id = db.Column(db.BigInteger, nullable=False)
    driver_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='offered')
    is_favourite = db.Column(db.Boolean, nullable=False, default=False)
    distance_m = db.Column(db.Integer)
    eta_s = db.Column(db.Integer)
    counter_cents = db.Column(db.BigInteger)
    offered_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    responded_at = db.Column(db.DateTime)


class ExperienceMark(db.Model):
    """'Sent once' markers, e.g. ('rideshare.departure_reminder', 'rideshare_trip', 42)."""
    __tablename__ = 'experience_marks'
    __table_args__ = (db.UniqueConstraint('kind', 'ref_type', 'ref_id', name='uq_exp_mark'),)

    id = db.Column(db.BigInteger, primary_key=True)
    kind = db.Column(db.String(40), nullable=False)
    ref_type = db.Column(db.String(30), nullable=False)
    ref_id = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class DriverSupplySnapshot(db.Model):
    __tablename__ = 'driver_supply_snapshots'

    id = db.Column(db.BigInteger, primary_key=True)
    bucket_at = db.Column(db.DateTime, nullable=False, unique=True)
    online_drivers = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
