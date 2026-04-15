from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    negotiation_id = db.Column(db.BigInteger, nullable=False)
    customer_id = db.Column(db.BigInteger, nullable=False)
    driver_id = db.Column(db.BigInteger, nullable=False)
    stripe_payment_intent_id = db.Column(db.String(255), unique=True, nullable=True)
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    stripe_payment_method = db.Column(db.String(255), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    service_fee = db.Column(db.Numeric(10, 2), default=0)
    driver_amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.Enum('pending', 'processing', 'requires_action', 'succeeded', 'failed', 'canceled', 'refunded'), default='pending')
    payment_type = db.Column(db.Enum('ride_payment', 'wallet_topup', 'refund'), default='ride_payment')
    currency = db.Column(db.String(3), default='cad')
    description = db.Column(db.Text, nullable=True)
    failure_reason = db.Column(db.Text, nullable=True)
    metadata_json = db.Column('metadata', db.JSON, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    failed_at = db.Column(db.DateTime, nullable=True)
    refunded_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'negotiation_id': self.negotiation_id,
            'customer_id': self.customer_id,
            'driver_id': self.driver_id,
            'stripe_payment_intent_id': self.stripe_payment_intent_id,
            'amount': float(self.amount) if self.amount else 0,
            'service_fee': float(self.service_fee) if self.service_fee else 0,
            'driver_amount': float(self.driver_amount) if self.driver_amount else 0,
            'status': self.status,
            'payment_type': self.payment_type,
            'currency': self.currency,
            'description': self.description,
            'failure_reason': self.failure_reason,
            'paid_at': my_date_time(self.paid_at),
            'failed_at': my_date_time(self.failed_at),
            'refunded_at': my_date_time(self.refunded_at),
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
