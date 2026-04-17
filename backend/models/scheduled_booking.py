from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class ScheduledBooking(db.Model):
    __tablename__ = 'scheduled_bookings'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.BigInteger, nullable=False)
    driver_id = db.Column(db.BigInteger, nullable=True)
    assigned_by = db.Column(db.BigInteger, nullable=True)
    service_type = db.Column(db.String(100), nullable=False)
    automobile_type = db.Column(db.String(100), nullable=True)

    # Pickup location
    pickup_lat = db.Column(db.Numeric(10, 7), nullable=False)
    pickup_lng = db.Column(db.Numeric(10, 7), nullable=False)
    pickup_place_name = db.Column(db.String(300), nullable=True)
    pickup_address = db.Column(db.String(500), nullable=False)
    pickup_description = db.Column(db.Text, nullable=True)

    # Destination
    destination_lat = db.Column(db.Numeric(10, 7), nullable=False)
    destination_lng = db.Column(db.Numeric(10, 7), nullable=False)
    destination_place_name = db.Column(db.String(300), nullable=True)
    destination_address = db.Column(db.String(500), nullable=False)
    destination_description = db.Column(db.Text, nullable=True)

    # Trip details
    passengers = db.Column(db.SmallInteger, default=1)
    luggage = db.Column(db.SmallInteger, default=0)
    luggage_weight_lbs = db.Column(db.Integer, default=0)
    luggage_description = db.Column(db.Text, nullable=True)
    message = db.Column(db.Text, nullable=True)
    scheduled_at = db.Column(db.DateTime, nullable=False)

    # Pricing (in CENTS)
    customer_proposed_price = db.Column(db.BigInteger, default=0)
    driver_proposed_price = db.Column(db.BigInteger, nullable=True)
    agreed_price = db.Column(db.BigInteger, nullable=True)

    # Status
    status = db.Column(db.String(50), default='pending')
    payment_status = db.Column(db.String(50), default='unpaid')

    # Compliance
    community_guidelines_accepted = db.Column(db.Boolean, default=False)
    community_guidelines_accepted_at = db.Column(db.DateTime, nullable=True)

    # Courier chaining (multi-parcel sequencing)
    courier_batch_id = db.Column(db.String(64), nullable=True, index=True)
    courier_sequence = db.Column(db.Integer, default=1)
    courier_total = db.Column(db.Integer, default=1)
    courier_next_booking_id = db.Column(db.BigInteger, nullable=True)

    # Courier proof of pickup and delivery
    pickup_proof_image = db.Column(db.Text, nullable=True)
    pickup_proof_uploaded_at = db.Column(db.DateTime, nullable=True)
    dropoff_proof_image = db.Column(db.Text, nullable=True)
    dropoff_proof_uploaded_at = db.Column(db.DateTime, nullable=True)

    # Stripe
    stripe_id = db.Column(db.String(255), nullable=True)
    stripe_url = db.Column(db.Text, nullable=True)
    stripe_product_id = db.Column(db.String(255), nullable=True)
    stripe_price_id = db.Column(db.String(255), nullable=True)
    stripe_paid = db.Column(db.Boolean, default=False)
    payment_completed_at = db.Column(db.DateTime, nullable=True)

    # Status timestamps
    assigned_at = db.Column(db.DateTime, nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancellation_reason = db.Column(db.Text, nullable=True)

    # Notes
    driver_notes = db.Column(db.Text, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    customer = db.relationship('AdminUser', backref='customer_bookings',
                               foreign_keys=[customer_id],
                               primaryjoin='ScheduledBooking.customer_id == AdminUser.id',
                               lazy=True)
    driver = db.relationship('AdminUser', backref='driver_bookings',
                             foreign_keys=[driver_id],
                             primaryjoin='ScheduledBooking.driver_id == AdminUser.id',
                             lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'driver_id': self.driver_id,
            'customer_name': self.customer.name if self.customer else None,
            'driver_name': self.driver.name if self.driver else None,
            'assigned_by': self.assigned_by,
            'service_type': self.service_type,
            'automobile_type': self.automobile_type,
            'pickup_lat': float(self.pickup_lat) if self.pickup_lat else None,
            'pickup_lng': float(self.pickup_lng) if self.pickup_lng else None,
            'pickup_place_name': self.pickup_place_name,
            'pickup_address': self.pickup_address,
            'pickup_description': self.pickup_description,
            'destination_lat': float(self.destination_lat) if self.destination_lat else None,
            'destination_lng': float(self.destination_lng) if self.destination_lng else None,
            'destination_place_name': self.destination_place_name,
            'destination_address': self.destination_address,
            'destination_description': self.destination_description,
            'passengers': self.passengers,
            'luggage': self.luggage,
            'luggage_weight_lbs': self.luggage_weight_lbs,
            'luggage_description': self.luggage_description,
            'message': self.message,
            'scheduled_at': my_date_time(self.scheduled_at),
            'customer_proposed_price': self.customer_proposed_price,
            'driver_proposed_price': self.driver_proposed_price,
            'agreed_price': self.agreed_price,
            'status': self.status,
            'payment_status': self.payment_status,
            'community_guidelines_accepted': self.community_guidelines_accepted,
            'community_guidelines_accepted_at': my_date_time(self.community_guidelines_accepted_at),
            'courier_batch_id': self.courier_batch_id,
            'courier_sequence': self.courier_sequence,
            'courier_total': self.courier_total,
            'courier_next_booking_id': self.courier_next_booking_id,
            'pickup_proof_image': self.pickup_proof_image,
            'pickup_proof_uploaded_at': my_date_time(self.pickup_proof_uploaded_at),
            'dropoff_proof_image': self.dropoff_proof_image,
            'dropoff_proof_uploaded_at': my_date_time(self.dropoff_proof_uploaded_at),
            'stripe_id': self.stripe_id,
            'stripe_url': self.stripe_url,
            'stripe_paid': self.stripe_paid,
            'payment_completed_at': my_date_time(self.payment_completed_at),
            'assigned_at': my_date_time(self.assigned_at),
            'confirmed_at': my_date_time(self.confirmed_at),
            'started_at': my_date_time(self.started_at),
            'completed_at': my_date_time(self.completed_at),
            'cancelled_at': my_date_time(self.cancelled_at),
            'cancellation_reason': self.cancellation_reason,
            'driver_notes': self.driver_notes,
            'admin_notes': self.admin_notes,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
