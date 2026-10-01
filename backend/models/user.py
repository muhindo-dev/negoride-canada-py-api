import bcrypt
from datetime import datetime
from flask import request, has_request_context
from backend.models import db
from backend.utils.helpers import my_date_time, my_date


def resolve_media_url(path):
    """Turn a stored image reference into a URL the current client can load.

    Images in our own storage (bare filenames, `images/…` relative paths, or
    stale absolute URLs pointing at an old backend host) are rebuilt against the
    host the client actually used to reach this API — so the same record works
    from the emulator (10.0.2.2), a LAN device, or production without change.
    Genuinely external images (e.g. seed avatars on other domains) are returned
    untouched.
    """
    if not path:
        return path
    s = str(path)
    if s.startswith('http') and '/storage/' not in s and '/uploads/' not in s:
        return s  # external image on another domain — leave as-is
    filename = s.split('/')[-1]
    if has_request_context():
        base = request.host_url.rstrip('/')
    else:
        from backend.config import Config
        base = (Config.APP_URL or '').rstrip('/')
    return f"{base}/storage/images/{filename}" if base else f"/storage/images/{filename}"


class AdminUser(db.Model):
    __tablename__ = 'admin_users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(500), unique=True, nullable=False)
    password = db.Column(db.String(500), nullable=False)
    name = db.Column(db.String(500), nullable=True)
    avatar = db.Column(db.Text, nullable=True)  # stored as TEXT (was varchar(10000))
    remember_token = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.Text, nullable=True)
    date_of_birth = db.Column(db.Text, nullable=True)
    sex = db.Column(db.Text, nullable=True)
    current_address = db.Column(db.Text, nullable=True)
    phone_number = db.Column(db.Text, nullable=True)
    country_code = db.Column(db.String(5), default='+1')
    country_name = db.Column(db.String(20), default='Canada')
    country_short_name = db.Column(db.String(3), default='CA')
    email = db.Column(db.Text, nullable=True)
    user_type = db.Column(db.String(25), default='Customer')
    deleted_at = db.Column(db.Date, nullable=True)
    status = db.Column(db.Integer, default=1)
    otp = db.Column(db.BigInteger, nullable=True)
    driving_license_number = db.Column(db.Text, nullable=True)
    nin = db.Column(db.Text, nullable=True)
    driving_license_issue_date = db.Column(db.Text, nullable=True)
    driving_license_validity = db.Column(db.Text, nullable=True)
    driving_license_issue_authority = db.Column(db.Text, nullable=True)
    driving_license_photo = db.Column(db.Text, nullable=True)
    ready_for_trip = db.Column(db.String(55), default='No')
    automobile = db.Column(db.String(55), nullable=True)

    # Service capabilities
    is_car = db.Column(db.String(255), default='No')
    is_boda = db.Column(db.String(255), default='No')
    is_ambulance = db.Column(db.String(255), default='No')
    is_police = db.Column(db.String(255), default='No')
    is_delivery = db.Column(db.String(255), default='No')
    is_breakdown = db.Column(db.String(255), default='No')
    is_firebrugade = db.Column(db.String(255), default='No')

    # Service approvals
    is_car_approved = db.Column(db.String(255), default='No')
    is_boda_approved = db.Column(db.String(255), default='No')
    is_ambulance_approved = db.Column(db.String(255), default='No')
    is_police_approved = db.Column(db.String(255), default='No')
    is_delivery_approved = db.Column(db.String(255), default='No')
    is_breakdown_approved = db.Column(db.String(255), default='No')
    is_firebrugade_approved = db.Column(db.String(255), default='No')

    # Email verification
    email_verified_at = db.Column(db.DateTime, nullable=True)
    email_verification_token = db.Column(db.String(64), nullable=True)
    verification_token_expires = db.Column(db.DateTime, nullable=True)

    # Password reset
    password_reset_token = db.Column(db.String(64), nullable=True)
    password_reset_expires = db.Column(db.DateTime, nullable=True)

    # Driver extras
    max_passengers = db.Column(db.Integer, nullable=False, default=4)
    rating = db.Column(db.Numeric(3, 2), nullable=False, default=0.00)
    current_latitude = db.Column(db.Numeric(10, 8), nullable=True)
    current_longitude = db.Column(db.Numeric(11, 8), nullable=True)
    last_location_update = db.Column(db.DateTime, nullable=True)

    # ── v4 identity / account status (spec §11, §15, §17) ──
    account_status = db.Column(db.String(20), nullable=True)
    status_reason = db.Column(db.String(500), nullable=True)
    status_reason_code = db.Column(db.String(40), nullable=True)
    status_changed_by = db.Column(db.Integer, nullable=True)
    status_changed_at = db.Column(db.DateTime, nullable=True)
    suspended_until = db.Column(db.DateTime, nullable=True)
    pending_account_status = db.Column(db.String(20), nullable=True)
    token_version = db.Column(db.Integer, nullable=False, default=0)
    phone_e164 = db.Column(db.String(20), nullable=True)
    phone_verified_at = db.Column(db.DateTime, nullable=True)
    phone_line_type = db.Column(db.String(30), nullable=True)
    rating_count = db.Column(db.Integer, nullable=False, default=0)
    rating_avg_raw = db.Column(db.Numeric(4, 3), nullable=True)
    marketing_opt_in = db.Column(db.Boolean, nullable=False, default=False)
    marketing_opt_in_at = db.Column(db.DateTime, nullable=True)
    admin_roles = db.Column(db.String(255), nullable=True)
    preferred_language = db.Column(db.String(5), nullable=True)
    timezone = db.Column(db.String(60), nullable=True)
    province = db.Column(db.String(2), nullable=True)
    legal_name = db.Column(db.String(200), nullable=True)
    pending_status_meta = db.Column(db.JSON, nullable=True)
    sms_opt_out_at = db.Column(db.DateTime, nullable=True)
    email_bounced_at = db.Column(db.DateTime, nullable=True)      # Postmark hard bounce / spam complaint
    email_bounce_reason = db.Column(db.String(255), nullable=True)

    # Relationships
    wallet = db.relationship('UserWallet', backref='user', uselist=False, lazy=True)
    payout_account = db.relationship('PayoutAccount', backref='user', uselist=False, lazy=True)

    @property
    def is_driver(self):
        return 'Yes' if self.user_type in ('Driver', 'Pending Driver') else 'No'

    @property
    def is_driver_approved(self):
        return 'Yes' if self.user_type == 'Driver' else 'No'

    @property
    def is_online(self):
        return self.ready_for_trip

    # Real (per-service) approval columns. A user is an APPROVED driver only if an
    # admin has approved at least one service. "Pending Driver" applicants have the
    # is_<svc> applied flags set but none of these, so they are NOT approved.
    _APPROVED_SERVICE_COLUMNS = (
        'is_car_approved', 'is_boda_approved', 'is_ambulance_approved',
        'is_delivery_approved', 'is_breakdown_approved',
    )

    def is_approved_driver(self):
        """True only after admin approval of the driver application."""
        if self.user_type == 'Driver':
            return True
        return any(
            getattr(self, col, None) == 'Yes'
            for col in self._APPROVED_SERVICE_COLUMNS
        )

    # ── v4 account status helpers (spec §15) ──
    ACCOUNT_STATUSES = ('active', 'suspended', 'deactivated', 'banned', 'pending_review')

    def effective_account_status(self):
        """account_status, falling back to the legacy integer `status`.
        A temporary suspension whose end date has passed reads as active."""
        st = self.account_status
        if not st:
            st = 'active' if self.status in (1, '1', None) else 'deactivated'
        if st == 'suspended' and self.suspended_until and self.suspended_until <= datetime.utcnow():
            return 'active'
        return st

    def is_account_active(self):
        return self.effective_account_status() == 'active'

    def get_admin_roles(self):
        """Admin roles (spec §19.14). Legacy Admin/Super Admin users are super admins."""
        roles = [r.strip() for r in (self.admin_roles or '').split(',') if r.strip()]
        if not roles and self.user_type in ('Admin', 'Super Admin'):
            roles = ['super_admin']
        return roles

    def has_admin_role(self, *roles):
        mine = self.get_admin_roles()
        return 'super_admin' in mine or any(r in mine for r in roles)

    def set_password(self, password):
        self.password = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

    def check_password(self, password):
        stored_hash = self.password
        if stored_hash.startswith('$2y$'):
            stored_hash = '$2b$' + stored_hash[4:]
        return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'name': self.name,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone_number': self.phone_number,
            'avatar': resolve_media_url(self.avatar),
            'country_name': self.country_name,
            'country_code': self.country_code,
            'country_short_name': self.country_short_name,
            'date_of_birth': self.date_of_birth,
            'sex': self.sex,
            'current_address': self.current_address,
            'user_type': self.user_type,
            'status': 'active' if self.status == 1 else 'inactive',
            'ready_for_trip': self.ready_for_trip,
            'automobile': self.automobile,
            'driving_license_number': self.driving_license_number,
            'nin': self.nin,
            'driving_license_issue_date': self.driving_license_issue_date,
            'driving_license_validity': self.driving_license_validity,
            'driving_license_issue_authority': self.driving_license_issue_authority,
            'driving_license_photo': self.driving_license_photo,
            'is_driver': self.is_driver,
            'is_driver_approved': self.is_driver_approved,
            'is_online': self.is_online,
            'is_car': self.is_car,
            'is_boda': self.is_boda,
            'is_ambulance': self.is_ambulance,
            'is_police': self.is_police,
            'is_delivery': self.is_delivery,
            'is_breakdown': self.is_breakdown,
            'is_firebrugade': self.is_firebrugade,
            'is_car_approved': self.is_car_approved,
            'is_boda_approved': self.is_boda_approved,
            'is_ambulance_approved': self.is_ambulance_approved,
            'is_police_approved': self.is_police_approved,
            'is_delivery_approved': self.is_delivery_approved,
            'is_breakdown_approved': self.is_breakdown_approved,
            'is_firebrugade_approved': self.is_firebrugade_approved,
            'max_passengers': self.max_passengers,
            'rating': float(self.rating) if self.rating else None,
            'current_latitude': str(self.current_latitude) if self.current_latitude else None,
            'current_longitude': str(self.current_longitude) if self.current_longitude else None,
            'last_location_update': my_date_time(self.last_location_update),
            'account_status': self.effective_account_status(),
            'suspended_until': my_date_time(self.suspended_until),
            'status_reason_code': self.status_reason_code,
            'phone_e164': self.phone_e164,
            'phone_verified': bool(self.phone_verified_at),
            'phone_verified_at': my_date_time(self.phone_verified_at),
            'email_verified': bool(self.email_verified_at),
            'rating_count': self.rating_count or 0,
            'marketing_opt_in': bool(self.marketing_opt_in),
            'preferred_language': self.preferred_language,
            'province': self.province,
            'admin_roles': self.get_admin_roles(),
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }

    # Personally-identifying fields that must not be harvestable by enumerating
    # the user directory via bulk search/listing endpoints.
    _SENSITIVE_PUBLIC_KEYS = (
        'email', 'phone_number', 'nin', 'date_of_birth',
        'driving_license_number', 'driving_license_issue_date',
        'driving_license_validity', 'driving_license_issue_authority',
        'driving_license_photo',
    )

    def to_public_dict(self):
        """A reduced projection safe to return in bulk search/listing responses.

        Excludes PII (email, phone, national ID, driving-licence details, DOB).
        Use this instead of to_dict() anywhere a caller can enumerate arbitrary
        users; use the full to_dict() only for the user's own record or admins.
        """
        data = self.to_dict()
        for key in self._SENSITIVE_PUBLIC_KEYS:
            data.pop(key, None)
        return data
