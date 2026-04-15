from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class Trip(db.Model):
    __tablename__ = 'trips'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    driver_id = db.Column(db.BigInteger, nullable=True)
    customer_id = db.Column(db.BigInteger, nullable=True)
    start_stage_id = db.Column(db.BigInteger, nullable=True)
    end_stage_id = db.Column(db.BigInteger, nullable=True)
    scheduled_start_time = db.Column(db.String(255), nullable=True)
    scheduled_end_time = db.Column(db.String(255), nullable=True)
    start_time = db.Column(db.String(255), nullable=True)
    end_time = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(255), nullable=True)
    vehicel_reg_number = db.Column(db.String(255), nullable=True)
    slots = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    car_model = db.Column(db.Text, nullable=True)
    price = db.Column(db.Integer, nullable=True)
    start_gps = db.Column(db.Text, nullable=True)
    end_pgs = db.Column(db.Text, nullable=True)
    start_name = db.Column(db.Text, nullable=True)
    end_name = db.Column(db.Text, nullable=True)
    start_address = db.Column(db.Text, nullable=True)
    end_address = db.Column(db.Text, nullable=True)

    # Relationships
    bookings = db.relationship('TripBooking', backref='trip', lazy=True)
    notes = db.relationship('TripNote', backref='trip', lazy=True)
    driver = db.relationship('AdminUser', backref='driver_trips', foreign_keys=[driver_id],
                             primaryjoin='Trip.driver_id == AdminUser.id', lazy=True)
    customer = db.relationship('AdminUser', backref='customer_trips', foreign_keys=[customer_id],
                               primaryjoin='Trip.customer_id == AdminUser.id', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'driver_id': self.driver_id,
            'customer_id': self.customer_id,
            'driver_name': self.driver.name if self.driver else None,
            'start_stage_id': self.start_stage_id,
            'end_stage_id': self.end_stage_id,
            'scheduled_start_time': self.scheduled_start_time,
            'scheduled_end_time': self.scheduled_end_time,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'status': self.status,
            'vehicel_reg_number': self.vehicel_reg_number,
            'slots': self.slots,
            'details': self.details,
            'car_model': self.car_model,
            'price': self.price,
            'start_gps': self.start_gps,
            'end_pgs': self.end_pgs,
            'start_name': self.start_name,
            'end_name': self.end_name,
            'start_address': self.start_address,
            'end_address': self.end_address,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
