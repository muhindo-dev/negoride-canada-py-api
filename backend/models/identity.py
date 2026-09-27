"""Identity, legal consent, driver onboarding and support models
(spec §11, §12, §14, §15, §19.8)."""
from backend.models import db
from backend.models.base import SerializeMixin, utcnow


class PhoneVerification(SerializeMixin, db.Model):
    __tablename__ = 'phone_verifications'
    _hidden = ('token_hash', 'code_hash')

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer)
    phone = db.Column(db.String(20), nullable=False)
    purpose = db.Column(db.String(30), nullable=False)
    channel = db.Column(db.String(20), nullable=False, default='sms')
    twilio_sid = db.Column(db.String(64))
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending|approved|failed|expired|canceled
    attempts = db.Column(db.Integer, nullable=False, default=0)
    ip = db.Column(db.String(64))
    device_id = db.Column(db.String(191))
    token_hash = db.Column(db.String(64))
    token_expires_at = db.Column(db.DateTime)
    consumed_at = db.Column(db.DateTime)
    test_mode = db.Column(db.Boolean, nullable=False, default=False)
    error = db.Column(db.String(500))
    code_hash = db.Column(db.String(64))      # dev fallback only (Twilio not configured, non-production)
    line_type = db.Column(db.String(30))      # Twilio Lookup line type (mobile|landline|nonFixedVoip|…)
    locale = db.Column(db.String(5))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    verified_at = db.Column(db.DateTime)


class UserDevice(SerializeMixin, db.Model):
    __tablename__ = 'user_devices'
    __table_args__ = (db.UniqueConstraint('user_id', 'device_id', name='uq_user_device'),)

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    device_id = db.Column(db.String(191), nullable=False)
    platform = db.Column(db.String(20))
    label = db.Column(db.String(191))
    trusted_at = db.Column(db.DateTime)
    first_seen_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_seen_at = db.Column(db.DateTime)
    last_ip = db.Column(db.String(64))


class LegalDocument(SerializeMixin, db.Model):
    __tablename__ = 'legal_documents'
    __table_args__ = (db.UniqueConstraint('type', 'version', 'language', name='uq_legal_version'),)

    id = db.Column(db.Integer, primary_key=True)
    # terms|privacy|community_guidelines|driver_agreement|cancellation_policy|
    # safety_policy|recording_notice|background_check_consent
    type = db.Column(db.String(40), nullable=False)
    version = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    summary_markdown = db.Column(db.Text)
    what_changed = db.Column(db.Text)
    body_markdown = db.Column(db.Text(length=4294967295), nullable=False)
    language = db.Column(db.String(5), nullable=False, default='en')
    audience = db.Column(db.String(20), nullable=False, default='all')  # all|customer|driver
    status = db.Column(db.String(20), nullable=False, default='draft')  # draft|published|archived
    requires_reacceptance = db.Column(db.Boolean, nullable=False, default=False)
    effective_at = db.Column(db.DateTime)
    published_at = db.Column(db.DateTime)
    published_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class LegalAcceptance(SerializeMixin, db.Model):
    __tablename__ = 'legal_acceptances'
    __table_args__ = (db.UniqueConstraint('user_id', 'document_id', name='uq_accept'),)

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    document_id = db.Column(db.Integer, nullable=False)
    document_type = db.Column(db.String(40), nullable=False)
    version = db.Column(db.String(20), nullable=False)
    accepted_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(500))
    app_version = db.Column(db.String(30))
    method = db.Column(db.String(20), nullable=False, default='checkbox')  # checkbox|modal|esignature
    signature_name = db.Column(db.String(200))


class DriverApplication(SerializeMixin, db.Model):
    __tablename__ = 'driver_applications'

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, unique=True)
    # in_progress|submitted|under_review|needs_changes|approved|rejected
    status = db.Column(db.String(30), nullable=False, default='in_progress')
    current_step = db.Column(db.String(40), nullable=False, default='account_created')
    steps = db.Column(db.JSON)
    legal_first_name = db.Column(db.String(100))
    legal_last_name = db.Column(db.String(100))
    date_of_birth = db.Column(db.Date)
    address_line = db.Column(db.String(255))
    city = db.Column(db.String(100))
    province = db.Column(db.String(2))
    postal_code = db.Column(db.String(10))
    service_types = db.Column(db.JSON)
    licence_class = db.Column(db.String(10))
    licence_number = db.Column(db.String(60))
    licence_expires_at = db.Column(db.Date)
    vehicle_make = db.Column(db.String(60))
    vehicle_model = db.Column(db.String(60))
    vehicle_year = db.Column(db.Integer)
    vehicle_color = db.Column(db.String(40))
    vehicle_plate = db.Column(db.String(20))
    vehicle_seats = db.Column(db.Integer)
    prequal = db.Column(db.JSON)
    orientation_completed_at = db.Column(db.DateTime)
    orientation_score = db.Column(db.Integer)
    pay_later_from_earnings = db.Column(db.Boolean, nullable=False, default=False)
    referral_code = db.Column(db.String(20), unique=True)
    referred_by = db.Column(db.Integer)
    submitted_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer)
    reviewed_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class DriverDocument(SerializeMixin, db.Model):
    __tablename__ = 'driver_documents'
    _hidden = ('file_path',)

    id = db.Column(db.BigInteger, primary_key=True)
    application_id = db.Column(db.BigInteger, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    # licence_front|licence_back|registration|insurance|vehicle_front|vehicle_back|
    # vehicle_left|vehicle_right|vehicle_interior|selfie
    type = db.Column(db.String(40), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(60))
    sha256 = db.Column(db.String(64))
    expires_at = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending|approved|rejected|expired|superseded
    reviewer_note = db.Column(db.String(500))
    reviewed_by = db.Column(db.Integer)
    reviewed_at = db.Column(db.DateTime)
    reminders_sent = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class BackgroundCheck(SerializeMixin, db.Model):
    __tablename__ = 'background_checks'
    _hidden = ('report_url',)

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    application_id = db.Column(db.BigInteger)
    provider = db.Column(db.String(20), nullable=False, default='certn')
    provider_application_id = db.Column(db.String(191))
    package = db.Column(db.String(80))
    # awaiting_payment|paid|initiated|pending|clear|consider|failed|cancelled|expired
    status = db.Column(db.String(30), nullable=False, default='awaiting_payment')
    result = db.Column(db.String(30))
    report_url = db.Column(db.Text)
    invite_url = db.Column(db.Text)
    fee_cents = db.Column(db.BigInteger, nullable=False, default=0)
    fee_payment_id = db.Column(db.BigInteger)
    fee_paid_at = db.Column(db.DateTime)
    paid_by = db.Column(db.String(20), nullable=False, default='driver')  # driver|platform|earnings
    consent_acceptance_id = db.Column(db.BigInteger)
    adjudicated_by = db.Column(db.Integer)
    adjudicated_at = db.Column(db.DateTime)
    adjudication_note = db.Column(db.Text)
    raw_status = db.Column(db.String(60))
    initiated_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)
    last_polled_at = db.Column(db.DateTime)
    deduction_status = db.Column(db.String(20))   # pay-later: pending|settled|waived
    deduction_settled_at = db.Column(db.DateTime)
    recheck_reminded_at = db.Column(db.DateTime)
    provider_score = db.Column(db.String(30))     # Certn overall_score (CLEAR|REVIEW|REJECT|…)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class SupportTicket(SerializeMixin, db.Model):
    __tablename__ = 'support_tickets'

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(30), nullable=False, default='general')  # general|appeal|dispute|lost_item|safety|billing
    ride_type = db.Column(db.String(30))
    ride_id = db.Column(db.BigInteger)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='open')  # open|pending|resolved|closed
    priority = db.Column(db.String(10), nullable=False, default='normal')
    assigned_to = db.Column(db.Integer)
    sla_due_at = db.Column(db.DateTime)
    resolution = db.Column(db.Text)
    first_response_at = db.Column(db.DateTime)
    closed_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    resolved_at = db.Column(db.DateTime)


class SupportTicketMessage(SerializeMixin, db.Model):
    __tablename__ = 'support_ticket_messages'

    id = db.Column(db.BigInteger, primary_key=True)
    ticket_id = db.Column(db.BigInteger, nullable=False, index=True)
    author_id = db.Column(db.Integer, nullable=False)
    author_type = db.Column(db.String(20), nullable=False, default='user')
    body = db.Column(db.Text, nullable=False)
    attachments = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
