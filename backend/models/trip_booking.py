from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class TripBooking(db.Model):
    __tablename__ = 'trip_bookings'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    trip_id = db.Column(db.BigInteger, db.ForeignKey('trips.id'), nullable=False)
    customer_id = db.Column(db.BigInteger, nullable=False)
    driver_id = db.Column(db.BigInteger, nullable=False)
    start_stage_id = db.Column(db.BigInteger, nullable=False)
    end_stage_id = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String(255), nullable=False, default='Pending')
    payment_status = db.Column(db.String(255), nullable=False, default='unpaid')
    start_time = db.Column(db.String(255), nullable=True)
    end_time = db.Column(db.String(255), nullable=True)
    slot_count = db.Column(db.Integer, nullable=True)
    price = db.Column(db.Integer, nullable=True)
    customer_note = db.Column(db.Text, nullable=True)
    driver_notes = db.Column(db.Text, nullable=True)

    # Stripe payment
    stripe_id = db.Column(db.String(255), nullable=True)
    stripe_url = db.Column(db.String(500), nullable=True)
    stripe_product_id = db.Column(db.String(255), nullable=True)
    stripe_price_id = db.Column(db.String(255), nullable=True)
    stripe_paid = db.Column(db.String(255), nullable=False, default='No')
    payment_completed_at = db.Column(db.DateTime, nullable=True)
    payment_failure_reason = db.Column(db.String(255), nullable=True)

    # Text fields
    start_stage_text = db.Column(db.Text, nullable=True)
    end_stage_text = db.Column(db.Text, nullable=True)
    trip_text = db.Column(db.Text, nullable=True)
    customer_text = db.Column(db.Text, nullable=True)
    driver_text = db.Column(db.Text, nullable=True)

    # Relationships
    customer = db.relationship('AdminUser', backref='trip_bookings',
                               foreign_keys=[customer_id],
                               primaryjoin='TripBooking.customer_id == AdminUser.id',
                               lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'trip_id': self.trip_id,
            'customer_id': self.customer_id,
            'driver_id': self.driver_id,
            'start_stage_id': self.start_stage_id,
            'end_stage_id': self.end_stage_id,
            'status': self.status,
            'payment_status': self.payment_status,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'slot_count': self.slot_count,
            'price': self.price,
            'customer_note': self.customer_note,
            'driver_notes': self.driver_notes,
            'stripe_id': self.stripe_id,
            'stripe_url': self.stripe_url,
            'stripe_paid': self.stripe_paid,
            'payment_completed_at': my_date_time(self.payment_completed_at),
            'payment_failure_reason': self.payment_failure_reason,
            'start_stage_text': self.start_stage_text,
            'end_stage_text': self.end_stage_text,
            'trip_text': self.trip_text,
            'customer_text': self.customer_text,
            'driver_text': self.driver_text,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
