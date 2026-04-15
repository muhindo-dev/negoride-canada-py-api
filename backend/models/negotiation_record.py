from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class NegotiationRecord(db.Model):
    __tablename__ = 'negotiation_records'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    negotiation_id = db.Column(db.Integer, db.ForeignKey('negotiations.id'), nullable=False)
    customer_id = db.Column(db.Integer, nullable=False)
    driver_id = db.Column(db.Integer, nullable=False)
    last_negotiator_id = db.Column(db.Integer, nullable=False)
    first_negotiator_id = db.Column(db.Integer, nullable=False)
    price_accepted = db.Column(db.String(10), default='No')
    price = db.Column(db.Integer, nullable=False)  # In CENTS
    message_type = db.Column(db.String(255), default='Negotiation')
    message_body = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.Text, nullable=True)
    audio_url = db.Column(db.Text, nullable=True)
    is_received = db.Column(db.String(10), default='No')
    is_seen = db.Column(db.String(10), default='No')
    latitude = db.Column(db.String(255), nullable=True)
    longitude = db.Column(db.String(255), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'negotiation_id': self.negotiation_id,
            'customer_id': self.customer_id,
            'driver_id': self.driver_id,
            'last_negotiator_id': self.last_negotiator_id,
            'first_negotiator_id': self.first_negotiator_id,
            'price_accepted': self.price_accepted,
            'price': self.price,
            'message_type': self.message_type,
            'message_body': self.message_body,
            'image_url': self.image_url,
            'audio_url': self.audio_url,
            'is_received': self.is_received,
            'is_seen': self.is_seen,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
