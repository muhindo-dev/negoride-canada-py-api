from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class Negotiation(db.Model):
    __tablename__ = 'negotiations'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.Integer, nullable=True)
    customer_name = db.Column(db.Text, nullable=True)
    driver_id = db.Column(db.Integer, nullable=True)
    driver_name = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(255), default='Pending')
    is_active = db.Column(db.String(55), nullable=True)
    customer_accepted = db.Column(db.String(255), default='Pending')
    customer_driver = db.Column(db.String(255), default='Pending')

    # Location
    pickup_lat = db.Column(db.Text, nullable=True)
    pickup_lng = db.Column(db.Text, nullable=True)
    pickup_address = db.Column(db.Text, nullable=True)
    dropoff_lat = db.Column(db.Text, nullable=True)
    dropoff_lng = db.Column(db.Text, nullable=True)
    dropoff_address = db.Column(db.Text, nullable=True)

    # Records & Details
    records = db.Column(db.Text, nullable=True)
    details = db.Column(db.Text, nullable=True)

    # Pricing
    initial_price = db.Column(db.Integer, nullable=True)  # In CENTS
    agreed_price = db.Column(db.Numeric(10, 2), nullable=True)  # In DOLLARS

    # Payment
    payment_status = db.Column(db.Enum('unpaid', 'pending', 'paid', 'failed', 'refunded'), default='unpaid')
    payment_id = db.Column(db.BigInteger, nullable=True)
    payment_completed_at = db.Column(db.DateTime, nullable=True)
    payment_failure_reason = db.Column(db.Text, nullable=True)

    # Stripe
    stripe_id = db.Column(db.String(255), nullable=True)
    stripe_session_id = db.Column(db.String(255), nullable=True)
    stripe_url = db.Column(db.String(500), nullable=True)
    stripe_product_id = db.Column(db.String(255), nullable=True)
    stripe_price_id = db.Column(db.String(255), nullable=True)
    stripe_paid = db.Column(db.String(10), default='No')

    # ── v4 lifecycle (spec §4) ──
    trip_stage = db.Column(db.String(40), nullable=True, index=True)
    stage_changed_at = db.Column(db.DateTime, nullable=True)
    agreed_price_cents = db.Column(db.BigInteger, nullable=True)
    ride_pin = db.Column(db.String(8), nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    en_route_at = db.Column(db.DateTime, nullable=True)
    arriving_at = db.Column(db.DateTime, nullable=True)
    driver_arrived_at = db.Column(db.DateTime, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by = db.Column(db.String(20), nullable=True)
    cancel_reason = db.Column(db.Text, nullable=True)
    cancel_reason_code = db.Column(db.String(40), nullable=True)
    awaiting_payment_since = db.Column(db.DateTime, nullable=True)
    eta_seconds = db.Column(db.Integer, nullable=True)
    eta_distance_m = db.Column(db.Integer, nullable=True)
    eta_target = db.Column(db.String(10), nullable=True)
    eta_updated_at = db.Column(db.DateTime, nullable=True)
    initial_eta_at = db.Column(db.DateTime, nullable=True)
    disputed_at = db.Column(db.DateTime, nullable=True)
    dispute_resolved_at = db.Column(db.DateTime, nullable=True)   # safety_service.mark_dispute_resolved (v4_0101)
    dispute_reason = db.Column(db.Text, nullable=True)
    request_mode = db.Column(db.String(20), nullable=True)
    service_type = db.Column(db.String(40), nullable=True)
    tip_cents = db.Column(db.BigInteger, nullable=True)
    final_fare_cents = db.Column(db.BigInteger, nullable=True)
    waiting_fee_cents = db.Column(db.BigInteger, nullable=True)
    distance_m = db.Column(db.Integer, nullable=True)
    duration_s = db.Column(db.Integer, nullable=True)
    pickup_province = db.Column(db.String(4), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    records_list = db.relationship('NegotiationRecord', backref='negotiation', lazy=True)

    def to_dict(self):
        # Fetch phone numbers from related users
        driver_phone = ''
        customer_phone = ''
        try:
            from backend.models.user import AdminUser
            if self.driver_id:
                driver = AdminUser.query.get(self.driver_id)
                if driver:
                    driver_phone = driver.phone_number or ''
            if self.customer_id:
                customer = AdminUser.query.get(self.customer_id)
                if customer:
                    customer_phone = customer.phone_number or ''
        except Exception:
            pass

        # Include the latest and second-latest offered prices (in cents)
        # so clients can render the last two negotiation points consistently.
        last_offer_price = None
        second_last_offer_price = None
        try:
            from backend.models.negotiation_record import NegotiationRecord
            rows = (
                NegotiationRecord.query
                .filter_by(negotiation_id=self.id)
                .order_by(NegotiationRecord.created_at.desc(), NegotiationRecord.id.desc())
                .limit(2)
                .all()
            )
            if len(rows) >= 1:
                last_offer_price = rows[0].price
            if len(rows) >= 2:
                second_last_offer_price = rows[1].price
        except Exception:
            pass

        return {
            'id': self.id,
            # v4 (ride_pin is deliberately NOT exposed here — customer-only via /api/rides)
            'trip_stage': self.trip_stage,
            'stage_changed_at': my_date_time(self.stage_changed_at),
            'agreed_price_cents': self.agreed_price_cents,
            'confirmed_at': my_date_time(self.confirmed_at),
            'en_route_at': my_date_time(self.en_route_at),
            'driver_arrived_at': my_date_time(self.driver_arrived_at),
            'started_at': my_date_time(self.started_at),
            'completed_at': my_date_time(self.completed_at),
            'cancelled_at': my_date_time(self.cancelled_at),
            'cancelled_by': self.cancelled_by,
            'cancel_reason_code': self.cancel_reason_code,
            'eta_seconds': self.eta_seconds,
            'eta_distance_m': self.eta_distance_m,
            'eta_target': self.eta_target,
            'request_mode': self.request_mode,
            'service_type': self.service_type,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'driver_id': self.driver_id,
            'driver_name': self.driver_name,
            'status': self.status,
            'is_active': self.is_active,
            'customer_accepted': self.customer_accepted,
            'customer_driver': self.customer_driver,
            'pickup_lat': self.pickup_lat,
            'pickup_lng': self.pickup_lng,
            'pickup_address': self.pickup_address,
            'dropoff_lat': self.dropoff_lat,
            'dropoff_lng': self.dropoff_lng,
            'dropoff_address': self.dropoff_address,
            'records': self.records,
            'details': self.details,
            'initial_price': self.initial_price,
            'agreed_price': float(self.agreed_price) if self.agreed_price else None,
            'last_offer_price': last_offer_price,
            'second_last_offer_price': second_last_offer_price,
            'payment_status': self.payment_status,
            'payment_id': self.payment_id,
            'payment_completed_at': my_date_time(self.payment_completed_at),
            'payment_failure_reason': self.payment_failure_reason,
            'stripe_id': self.stripe_id,
            'stripe_session_id': self.stripe_session_id,
            'stripe_url': self.stripe_url,
            'stripe_paid': self.stripe_paid,
            'driver_phone': driver_phone,
            'customer_phone': customer_phone,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
