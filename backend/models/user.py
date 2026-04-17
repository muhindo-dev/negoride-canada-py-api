import bcrypt
from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time, my_date


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
            'avatar': self.avatar,
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
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
