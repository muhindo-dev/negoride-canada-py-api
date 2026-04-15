from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class PayoutRequest(db.Model):
    __tablename__ = 'payout_requests'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('admin_users.id'), nullable=False)
    payout_account_id = db.Column(db.BigInteger, db.ForeignKey('payout_accounts.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), default='USD')
    fee_amount = db.Column(db.Numeric(10, 2), default=0)
    net_amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.Enum('pending', 'processing', 'completed', 'failed', 'cancelled'), default='pending')
    payout_method = db.Column(db.Enum('standard', 'instant'), default='standard')
    stripe_transfer_id = db.Column(db.String(255), nullable=True)
    stripe_payout_id = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    failure_reason = db.Column(db.Text, nullable=True)
    requested_at = db.Column(db.DateTime, nullable=False)
    processing_at = db.Column(db.DateTime, nullable=True)
    processed_at = db.Column(db.DateTime, nullable=True)
    failed_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    metadata_json = db.Column('metadata', db.JSON, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    payout_account = db.relationship('PayoutAccount', backref='payout_requests', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'payout_account_id': self.payout_account_id,
            'amount': float(self.amount) if self.amount else 0,
            'currency': self.currency,
            'fee_amount': float(self.fee_amount) if self.fee_amount else 0,
            'net_amount': float(self.net_amount) if self.net_amount else 0,
            'status': self.status,
            'payout_method': self.payout_method,
            'stripe_transfer_id': self.stripe_transfer_id,
            'stripe_payout_id': self.stripe_payout_id,
            'description': self.description,
            'admin_notes': self.admin_notes,
            'failure_reason': self.failure_reason,
            'requested_at': my_date_time(self.requested_at),
            'processing_at': my_date_time(self.processing_at),
            'processed_at': my_date_time(self.processed_at),
            'failed_at': my_date_time(self.failed_at),
            'cancelled_at': my_date_time(self.cancelled_at),
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
