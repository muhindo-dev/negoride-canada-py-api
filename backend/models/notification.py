"""Notification engine models (spec §5.2)."""
from backend.models import db
from backend.models.base import SerializeMixin, utcnow


class Notification(SerializeMixin, db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    event_key = db.Column(db.String(80), nullable=False)
    event_group = db.Column(db.String(30), nullable=False, default='general')
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text)
    data = db.Column(db.JSON)
    deep_link = db.Column(db.String(255))
    is_critical = db.Column(db.Boolean, nullable=False, default=False)
    read_at = db.Column(db.DateTime)
    opened_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    deliveries = db.relationship('NotificationDelivery', backref='notification', lazy=True,
                                 primaryjoin='Notification.id == NotificationDelivery.notification_id',
                                 foreign_keys='NotificationDelivery.notification_id')


class NotificationDelivery(SerializeMixin, db.Model):
    __tablename__ = 'notification_deliveries'

    id = db.Column(db.BigInteger, primary_key=True)
    notification_id = db.Column(db.BigInteger, nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False)
    provider_message_id = db.Column(db.String(191))
    status = db.Column(db.String(20), nullable=False, default='queued')
    error = db.Column(db.Text)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    queued_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    sent_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    opened_at = db.Column(db.DateTime)
    failed_at = db.Column(db.DateTime)
    next_attempt_at = db.Column(db.DateTime)


class NotificationPreference(SerializeMixin, db.Model):
    __tablename__ = 'notification_preferences'
    __table_args__ = (db.UniqueConstraint('user_id', 'event_group', name='uq_np_user_group'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    event_group = db.Column(db.String(30), nullable=False)
    push = db.Column(db.Boolean, nullable=False, default=True)
    sms = db.Column(db.Boolean, nullable=False, default=True)
    email = db.Column(db.Boolean, nullable=False, default=True)
    quiet_start = db.Column(db.String(5))
    quiet_end = db.Column(db.String(5))
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class DeviceToken(SerializeMixin, db.Model):
    __tablename__ = 'device_tokens'
    __table_args__ = (db.UniqueConstraint('user_id', 'device_id', name='uq_device_user'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    onesignal_subscription_id = db.Column(db.String(191))
    device_id = db.Column(db.String(191))
    platform = db.Column(db.String(20))
    app_version = db.Column(db.String(30))
    os_version = db.Column(db.String(60))
    locale = db.Column(db.String(10))
    timezone = db.Column(db.String(60))
    last_seen_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)
