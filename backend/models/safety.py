"""Safety models (spec §8, §9, §10)."""
from backend.models import db
from backend.models.base import SerializeMixin, utcnow


class SafetyIncident(SerializeMixin, db.Model):
    __tablename__ = 'safety_incidents'
    _hidden = ('idempotency_key',)

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(20), nullable=False, default='customer')
    ride_type = db.Column(db.String(30))
    ride_id = db.Column(db.BigInteger)
    kind = db.Column(db.String(30), nullable=False, default='sos')  # sos|route_deviation|long_stop|check_in_timeout
    status = db.Column(db.String(20), nullable=False, default='open')  # open|acknowledged|resolved|false_alarm
    severity = db.Column(db.String(20), nullable=False, default='critical')
    silent = db.Column(db.Boolean, nullable=False, default=False)
    lat = db.Column(db.Numeric(10, 7))
    lng = db.Column(db.Numeric(10, 7))
    accuracy_m = db.Column(db.Integer)
    battery_pct = db.Column(db.Integer)
    last_lat = db.Column(db.Numeric(10, 7))
    last_lng = db.Column(db.Numeric(10, 7))
    last_location_at = db.Column(db.DateTime)
    idempotency_key = db.Column(db.String(120))
    acknowledged_by = db.Column(db.Integer)
    acknowledged_at = db.Column(db.DateTime)
    escalated_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer)
    resolved_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class SafetyIncidentLocation(SerializeMixin, db.Model):
    __tablename__ = 'safety_incident_locations'

    id = db.Column(db.BigInteger, primary_key=True)
    incident_id = db.Column(db.BigInteger, nullable=False, index=True)
    lat = db.Column(db.Numeric(10, 7), nullable=False)
    lng = db.Column(db.Numeric(10, 7), nullable=False)
    accuracy_m = db.Column(db.Integer)
    speed_mps = db.Column(db.Numeric(6, 2))
    heading = db.Column(db.SmallInteger)
    battery_pct = db.Column(db.Integer)
    recorded_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class TrustedContact(SerializeMixin, db.Model):
    __tablename__ = 'trusted_contacts'

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone_e164 = db.Column(db.String(20), nullable=False)
    relationship = db.Column(db.String(40))
    auto_share = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class SafetyReport(SerializeMixin, db.Model):
    __tablename__ = 'safety_reports'

    id = db.Column(db.BigInteger, primary_key=True)
    reporter_id = db.Column(db.Integer, nullable=False)
    reported_user_id = db.Column(db.Integer)
    ride_type = db.Column(db.String(30))
    ride_id = db.Column(db.BigInteger)
    category = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text)
    attachments = db.Column(db.JSON)
    status = db.Column(db.String(20), nullable=False, default='open')
    reviewed_by = db.Column(db.Integer)
    reviewed_at = db.Column(db.DateTime)
    resolution = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class SafetySettings(SerializeMixin, db.Model):
    __tablename__ = 'safety_settings'

    user_id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    record_audio = db.Column(db.String(10), nullable=False, default='off')  # off|always|ask
    auto_record_on_sos = db.Column(db.Boolean, nullable=False, default=False)
    auto_share_night = db.Column(db.Boolean, nullable=False, default=False)
    auto_share_all = db.Column(db.Boolean, nullable=False, default=False)
    night_start = db.Column(db.String(5), nullable=False, default='21:00')
    night_end = db.Column(db.String(5), nullable=False, default='05:00')
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class SafetyCheck(SerializeMixin, db.Model):
    """"Are you OK?" prompts from route-deviation / long-stop detection."""
    __tablename__ = 'safety_checks'

    id = db.Column(db.BigInteger, primary_key=True)
    ride_type = db.Column(db.String(30), nullable=False)
    ride_id = db.Column(db.BigInteger, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(30), nullable=False)  # route_deviation|long_stop
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending|ok|help|escalated
    lat = db.Column(db.Numeric(10, 7))
    lng = db.Column(db.Numeric(10, 7))
    meta = db.Column(db.JSON)
    incident_id = db.Column(db.BigInteger)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    responded_at = db.Column(db.DateTime)


class HelpContact(SerializeMixin, db.Model):
    __tablename__ = 'help_contacts'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(160))
    url = db.Column(db.String(255))
    category = db.Column(db.String(40), nullable=False)
    province = db.Column(db.String(2))
    description = db.Column(db.String(500))
    is_emergency = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=100)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class RideLocation(SerializeMixin, db.Model):
    __tablename__ = 'ride_locations'

    id = db.Column(db.BigInteger, primary_key=True)
    ride_type = db.Column(db.String(30))
    ride_id = db.Column(db.BigInteger)
    user_id = db.Column(db.Integer, nullable=False)
    lat = db.Column(db.Numeric(10, 7), nullable=False)
    lng = db.Column(db.Numeric(10, 7), nullable=False)
    speed_mps = db.Column(db.Numeric(6, 2))
    heading = db.Column(db.SmallInteger)
    accuracy_m = db.Column(db.Integer)
    recorded_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class RideShareLink(SerializeMixin, db.Model):
    __tablename__ = 'ride_share_links'

    id = db.Column(db.BigInteger, primary_key=True)
    token = db.Column(db.String(64), nullable=False, unique=True)
    ride_type = db.Column(db.String(30), nullable=False)
    ride_id = db.Column(db.BigInteger, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    shared_with = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)
    view_count = db.Column(db.Integer, nullable=False, default=0)
    last_viewed_at = db.Column(db.DateTime)


class Recording(SerializeMixin, db.Model):
    __tablename__ = 'recordings'

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(20), nullable=False)
    ride_type = db.Column(db.String(30))
    ride_id = db.Column(db.BigInteger)
    incident_id = db.Column(db.BigInteger)
    status = db.Column(db.String(20), nullable=False, default='recording')  # recording|stopped|deleted
    trigger_source = db.Column(db.String(20), nullable=False, default='manual')  # manual|always|sos
    started_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    stopped_at = db.Column(db.DateTime)
    chunk_count = db.Column(db.Integer, nullable=False, default=0)
    total_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    retain_until = db.Column(db.DateTime)
    legal_hold = db.Column(db.Boolean, nullable=False, default=False)
    deleted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class RecordingChunk(SerializeMixin, db.Model):
    __tablename__ = 'recording_chunks'
    __table_args__ = (db.UniqueConstraint('recording_id', 'seq', name='uq_chunk'),)
    _hidden = ('storage_key',)

    id = db.Column(db.BigInteger, primary_key=True)
    recording_id = db.Column(db.BigInteger, nullable=False)
    seq = db.Column(db.Integer, nullable=False)
    storage_key = db.Column(db.String(500), nullable=False)
    bytes = db.Column(db.BigInteger, nullable=False, default=0)
    sha256 = db.Column(db.String(64))
    duration_ms = db.Column(db.Integer)
    started_at = db.Column(db.DateTime)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class RideRoute(SerializeMixin, db.Model):
    """Planned route for a ride (spec §8.4 route deviation). target: pickup|dropoff.
    `polyline` is a Google encoded polyline (precision 5)."""
    __tablename__ = 'ride_routes'

    id = db.Column(db.BigInteger, primary_key=True)
    ride_type = db.Column(db.String(30), nullable=False)
    ride_id = db.Column(db.BigInteger, nullable=False)
    target = db.Column(db.String(10), nullable=False)
    polyline = db.Column(db.Text, nullable=False)
    distance_m = db.Column(db.Integer)
    duration_s = db.Column(db.Integer)
    source = db.Column(db.String(20), nullable=False, default='straight_line')  # google_routes|straight_line
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class RidePinFailure(SerializeMixin, db.Model):
    """One wrong ride-PIN attempt (brute-force lock, sliding window)."""
    __tablename__ = 'ride_pin_failures'

    id = db.Column(db.BigInteger, primary_key=True)
    ride_type = db.Column(db.String(30), nullable=False)
    ride_id = db.Column(db.BigInteger, nullable=False)
    actor_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
