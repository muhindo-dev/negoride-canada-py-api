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

    # ── v4 lifecycle (spec §4.2, §18) ──
    trip_stage = db.Column(db.String(40), nullable=True, index=True)
    stage_changed_at = db.Column(db.DateTime, nullable=True)
    ride_pin = db.Column(db.String(8), nullable=True)
    price_per_seat_cents = db.Column(db.BigInteger, nullable=True)
    offered_price_per_seat_cents = db.Column(db.BigInteger, nullable=True)
    total_cents = db.Column(db.BigInteger, nullable=True)
    request_status = db.Column(db.String(20), nullable=True)
    request_expires_at = db.Column(db.DateTime, nullable=True)
    pickup_order = db.Column(db.Integer, nullable=True)
    pickup_lat = db.Column(db.Numeric(10, 7), nullable=True)
    pickup_lng = db.Column(db.Numeric(10, 7), nullable=True)
    pickup_address = db.Column(db.String(500), nullable=True)
    pickup_province = db.Column(db.String(4), nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    driver_arrived_at = db.Column(db.DateTime, nullable=True)
    checked_in_at = db.Column(db.DateTime, nullable=True)
    dropped_off_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancel_reason_code = db.Column(db.String(40), nullable=True)
    awaiting_payment_since = db.Column(db.DateTime, nullable=True)
    disputed_at = db.Column(db.DateTime, nullable=True)
    dispute_resolved_at = db.Column(db.DateTime, nullable=True)   # safety_service.mark_dispute_resolved (v4_0101)

    # Relationships
    customer = db.relationship('AdminUser', backref='trip_bookings',
                               foreign_keys=[customer_id],
                               primaryjoin='TripBooking.customer_id == AdminUser.id',
                               lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'trip_stage': self.trip_stage,
            'stage_changed_at': my_date_time(self.stage_changed_at),
            'price_per_seat_cents': self.price_per_seat_cents,
            'offered_price_per_seat_cents': self.offered_price_per_seat_cents,
            'total_cents': self.total_cents,
            'request_status': self.request_status,
            'request_expires_at': my_date_time(self.request_expires_at),
            'pickup_order': self.pickup_order,
            'pickup_lat': float(self.pickup_lat) if self.pickup_lat is not None else None,
            'pickup_lng': float(self.pickup_lng) if self.pickup_lng is not None else None,
            'pickup_address': self.pickup_address,
            'checked_in_at': my_date_time(self.checked_in_at),
            'dropped_off_at': my_date_time(self.dropped_off_at),
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
