"""v4 money models — every amount is INTEGER CENTS, CAD (spec §2.3, §6, §7, §13)."""
from backend.models import db
from backend.models.base import SerializeMixin, utcnow


# Statuses in which money was captured (refund overlay included).
CAPTURED_STATES = ('captured', 'partially_captured', 'partially_refunded', 'refunded')
# Statuses in which the customer's money is secured for the ride (§6 guard).
SECURED_STATES = ('authorized', 'captured', 'partially_captured', 'partially_refunded')


def refund_overlay_status(captured_cents, refunded_cents, current):
    """capture_status after a refund: refunded (all money back) / partially_refunded."""
    if not refunded_cents or current not in CAPTURED_STATES:
        return current
    return 'refunded' if int(refunded_cents) >= int(captured_cents or 0) else 'partially_refunded'


class RidePayment(SerializeMixin, db.Model):
    """One Stripe authorization (manual capture) or immediate charge for a ride,
    a seat booking, a tip or a background-check fee."""
    __tablename__ = 'ride_payments'

    id = db.Column(db.BigInteger, primary_key=True)
    ride_type = db.Column(db.String(30), nullable=False)
    ride_id = db.Column(db.BigInteger, nullable=False)
    customer_id = db.Column(db.Integer, nullable=False)
    driver_id = db.Column(db.Integer)
    purpose = db.Column(db.String(30), nullable=False, default='ride')  # ride|tip|background_check
    provider = db.Column(db.String(20), nullable=False, default='stripe')
    checkout_session_id = db.Column(db.String(191), unique=True)
    checkout_url = db.Column(db.Text)
    intent_id = db.Column(db.String(191), unique=True)
    capture_method = db.Column(db.String(20), nullable=False, default='manual')
    currency = db.Column(db.String(3), nullable=False, default='cad')
    fare_cents = db.Column(db.BigInteger, nullable=False, default=0)
    fees_cents = db.Column(db.BigInteger, nullable=False, default=0)
    tax_cents = db.Column(db.BigInteger, nullable=False, default=0)
    amount_authorized_cents = db.Column(db.BigInteger, nullable=False, default=0)
    amount_captured_cents = db.Column(db.BigInteger, nullable=False, default=0)
    amount_refunded_cents = db.Column(db.BigInteger, nullable=False, default=0)
    tip_cents = db.Column(db.BigInteger, nullable=False, default=0)
    # pending → authorized → captured | partially_captured | canceled | failed | expired
    # refund overlay (after money came back): partially_refunded | refunded
    capture_status = db.Column(db.String(30), nullable=False, default='pending')
    payment_method_brand = db.Column(db.String(30))
    payment_method_last4 = db.Column(db.String(4))
    authorized_at = db.Column(db.DateTime)
    auth_expires_at = db.Column(db.DateTime)
    captured_at = db.Column(db.DateTime)
    canceled_at = db.Column(db.DateTime)
    failure_reason = db.Column(db.Text)
    idempotency_key = db.Column(db.String(120))
    # 'safety_review' while a safety-ended ride's hold waits for the admin; then 'settled' / 'auto_released'
    settlement_status = db.Column(db.String(20))
    settle_due_at = db.Column(db.DateTime)
    meta = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    @property
    def is_secured(self):
        """Money is secured (authorized or already captured)."""
        return self.capture_status in SECURED_STATES

    @property
    def took_money(self):
        """Money was captured at some point (including later-refunded payments)."""
        return self.capture_status in CAPTURED_STATES

    @property
    def net_cents(self):
        return (self.amount_captured_cents or 0) - (self.amount_refunded_cents or 0)


class Refund(SerializeMixin, db.Model):
    __tablename__ = 'refunds'

    id = db.Column(db.BigInteger, primary_key=True)
    ride_payment_id = db.Column(db.BigInteger, nullable=False)
    ride_type = db.Column(db.String(30), nullable=False)
    ride_id = db.Column(db.BigInteger, nullable=False)
    customer_id = db.Column(db.Integer, nullable=False)
    amount_cents = db.Column(db.BigInteger, nullable=False)
    # refund (money returned after capture) | release (hold released, never charged)
    kind = db.Column(db.String(20), nullable=False, default='refund')
    rule_id = db.Column(db.String(60))
    reason = db.Column(db.Text)
    provider_refund_id = db.Column(db.String(191))
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending|succeeded|failed
    initiated_by = db.Column(db.Integer)
    initiated_by_type = db.Column(db.String(20), nullable=False, default='system')
    idempotency_key = db.Column(db.String(160), nullable=False, unique=True)
    credit_note_id = db.Column(db.BigInteger)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    processed_at = db.Column(db.DateTime)


class DocumentSequence(db.Model):
    __tablename__ = 'document_sequences'
    __table_args__ = (db.UniqueConstraint('doc_type', 'year', name='uq_docseq'),)

    id = db.Column(db.Integer, primary_key=True)
    doc_type = db.Column(db.String(20), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    last_value = db.Column(db.Integer, nullable=False, default=0)


class Receipt(SerializeMixin, db.Model):
    __tablename__ = 'receipts'
    __table_args__ = (db.UniqueConstraint('ride_type', 'ride_id', name='uq_receipts_ride'),)
    _hidden = ('pdf_path',)

    id = db.Column(db.BigInteger, primary_key=True)
    number = db.Column(db.String(30), nullable=False, unique=True)
    ride_type = db.Column(db.String(30), nullable=False)
    ride_id = db.Column(db.BigInteger, nullable=False)
    ride_payment_id = db.Column(db.BigInteger)
    customer_id = db.Column(db.Integer, nullable=False)
    driver_id = db.Column(db.Integer)
    currency = db.Column(db.String(3), nullable=False, default='cad')
    total_cents = db.Column(db.BigInteger, nullable=False, default=0)
    totals = db.Column(db.JSON, nullable=False)
    pdf_path = db.Column(db.String(500))
    emailed_at = db.Column(db.DateTime)
    email_count = db.Column(db.Integer, nullable=False, default=0)
    issued_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    voided_at = db.Column(db.DateTime)


class CreditNote(SerializeMixin, db.Model):
    __tablename__ = 'credit_notes'
    _hidden = ('pdf_path',)

    id = db.Column(db.BigInteger, primary_key=True)
    number = db.Column(db.String(30), nullable=False, unique=True)
    receipt_id = db.Column(db.BigInteger, nullable=False)
    refund_id = db.Column(db.BigInteger, unique=True)
    customer_id = db.Column(db.Integer, nullable=False)
    amount_cents = db.Column(db.BigInteger, nullable=False)
    tax_cents = db.Column(db.BigInteger, nullable=False, default=0)
    reason = db.Column(db.Text)
    totals = db.Column(db.JSON)
    pdf_path = db.Column(db.String(500))
    emailed_at = db.Column(db.DateTime)
    issued_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class TaxRate(SerializeMixin, db.Model):
    """Rates in basis points (500 = 5.00 %)."""
    __tablename__ = 'tax_rates'

    id = db.Column(db.Integer, primary_key=True)
    province = db.Column(db.String(2), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    gst_bp = db.Column(db.Integer, nullable=False, default=0)
    pst_bp = db.Column(db.Integer, nullable=False, default=0)
    hst_bp = db.Column(db.Integer, nullable=False, default=0)
    qst_bp = db.Column(db.Integer, nullable=False, default=0)
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date)


class DriverStrike(SerializeMixin, db.Model):
    __tablename__ = 'driver_strikes'

    id = db.Column(db.BigInteger, primary_key=True)
    driver_id = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(40), nullable=False)  # driver_cancel|driver_no_show|admin
    ride_type = db.Column(db.String(30))
    ride_id = db.Column(db.BigInteger)
    note = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class TipReceipt(SerializeMixin, db.Model):
    """NR-TIP-YYYY-NNNNNN — receipt for a tip paid after the ride (tips are not taxable)."""
    __tablename__ = 'tip_receipts'
    _hidden = ('pdf_path',)

    id = db.Column(db.BigInteger, primary_key=True)
    number = db.Column(db.String(30), nullable=False, unique=True)
    ride_payment_id = db.Column(db.BigInteger, nullable=False, unique=True)
    ride_type = db.Column(db.String(30), nullable=False)
    ride_id = db.Column(db.BigInteger, nullable=False)
    receipt_id = db.Column(db.BigInteger)
    customer_id = db.Column(db.Integer, nullable=False)
    driver_id = db.Column(db.Integer)
    currency = db.Column(db.String(3), nullable=False, default='cad')
    amount_cents = db.Column(db.BigInteger, nullable=False)
    totals = db.Column(db.JSON, nullable=False)
    pdf_path = db.Column(db.String(500))
    emailed_at = db.Column(db.DateTime)
    issued_at = db.Column(db.DateTime, nullable=False, default=utcnow)
