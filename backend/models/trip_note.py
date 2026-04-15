from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class TripNote(db.Model):
    __tablename__ = 'trip_notes'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    trip_id = db.Column(db.BigInteger, db.ForeignKey('trips.id'), nullable=False)
    user_id = db.Column(db.BigInteger, db.ForeignKey('admin_users.id'), nullable=False)
    note = db.Column(db.Text, nullable=False)
    note_type = db.Column(db.Enum('driver', 'passenger', 'system'), default='driver')

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'trip_id': self.trip_id,
            'user_id': self.user_id,
            'note': self.note,
            'note_type': self.note_type,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
