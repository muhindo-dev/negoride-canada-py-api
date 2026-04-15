from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('admin_users.id'), nullable=False)
    user_type = db.Column(db.Enum('customer', 'driver'), nullable=False)
    payment_id = db.Column(db.BigInteger, db.ForeignKey('payments.id'), nullable=True)
    type = db.Column(db.Enum('credit', 'debit'), nullable=False)
    category = db.Column(db.Enum('ride_payment', 'ride_earning', 'service_fee', 'refund', 'wallet_topup', 'withdrawal', 'bonus', 'penalty'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    balance_before = db.Column(db.Numeric(10, 2), default=0)
    balance_after = db.Column(db.Numeric(10, 2), default=0)
    reference = db.Column(db.String(255), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.Enum('pending', 'completed', 'failed', 'reversed'), default='completed')
    related_user_id = db.Column(db.BigInteger, nullable=True)
    negotiation_id = db.Column(db.BigInteger, nullable=True)
    booking_id = db.Column(db.BigInteger, nullable=True)
    metadata_text = db.Column('metadata', db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_type': self.user_type,
            'payment_id': self.payment_id,
            'type': self.type,
            'category': self.category,
            'amount': float(self.amount) if self.amount else 0,
            'balance_before': float(self.balance_before) if self.balance_before else 0,
            'balance_after': float(self.balance_after) if self.balance_after else 0,
            'reference': self.reference,
            'description': self.description,
            'status': self.status,
            'related_user_id': self.related_user_id,
            'negotiation_id': self.negotiation_id,
            'booking_id': self.booking_id,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
