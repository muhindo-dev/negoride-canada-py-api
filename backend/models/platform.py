"""Platform models: settings/feature flags, audit log, webhook inbox,
idempotency keys, trip timeline events, analytics."""
from backend.models import db
from backend.models.base import SerializeMixin, utcnow


class AppSetting(SerializeMixin, db.Model):
    __tablename__ = 'app_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column('key', db.String(120), unique=True, nullable=False)
    value = db.Column(db.Text)
    value_type = db.Column(db.String(20), nullable=False, default='string')
    category = db.Column(db.String(40), nullable=False, default='general')
    description = db.Column(db.String(500))
    is_public = db.Column(db.Boolean, nullable=False, default=False)
    updated_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class AuditLog(SerializeMixin, db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.BigInteger, primary_key=True)
    actor_id = db.Column(db.Integer)
    actor_type = db.Column(db.String(20), nullable=False, default='admin')
    action = db.Column(db.String(120), nullable=False)
    entity_type = db.Column(db.String(60))
    entity_id = db.Column(db.String(64))
    before_json = db.Column(db.JSON)
    after_json = db.Column(db.JSON)
    meta = db.Column(db.JSON)
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class WebhookEvent(SerializeMixin, db.Model):
    __tablename__ = 'webhook_events'
    __table_args__ = (db.UniqueConstraint('provider', 'event_id', name='uq_webhook_provider_event'),)

    id = db.Column(db.BigInteger, primary_key=True)
    provider = db.Column(db.String(20), nullable=False)
    event_id = db.Column(db.String(191), nullable=False)
    event_type = db.Column(db.String(120))
    payload = db.Column(db.Text(length=4294967295), nullable=False)
    signature_valid = db.Column(db.Boolean, nullable=False, default=True)
    status = db.Column(db.String(20), nullable=False, default='received')
    attempts = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text)
    received_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    processed_at = db.Column(db.DateTime)


class IdempotencyKey(db.Model):
    __tablename__ = 'idempotency_keys'
    __table_args__ = (db.UniqueConstraint('user_id', 'endpoint', 'idem_key', name='uq_idem'),)

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    idem_key = db.Column(db.String(120), nullable=False)
    endpoint = db.Column(db.String(191), nullable=False)
    status_code = db.Column(db.Integer)
    response_json = db.Column(db.Text(length=4294967295))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class TripEvent(SerializeMixin, db.Model):
    __tablename__ = 'trip_events'

    id = db.Column(db.BigInteger, primary_key=True)
    ride_type = db.Column(db.String(30), nullable=False)
    ride_id = db.Column(db.BigInteger, nullable=False)
    from_stage = db.Column(db.String(40))
    to_stage = db.Column(db.String(40), nullable=False)
    actor_type = db.Column(db.String(20), nullable=False)
    actor_id = db.Column(db.Integer)
    lat = db.Column(db.Numeric(10, 7))
    lng = db.Column(db.Numeric(10, 7))
    meta = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class AnalyticsEvent(SerializeMixin, db.Model):
    __tablename__ = 'analytics_events'

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer)
    name = db.Column(db.String(80), nullable=False)
    value_num = db.Column(db.Numeric(14, 3))
    props = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
