from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    chat_head_id = db.Column(db.BigInteger, db.ForeignKey('chat_heads.id'), nullable=False)
    sender_id = db.Column(db.BigInteger, nullable=False)
    receiver_id = db.Column(db.BigInteger, nullable=False)
    sender_name = db.Column(db.Text, nullable=True)
    sender_photo = db.Column(db.Text, nullable=True)
    receiver_name = db.Column(db.Text, nullable=True)
    receiver_photo = db.Column(db.Text, nullable=True)
    body = db.Column(db.Text, nullable=True)
    type = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(255), nullable=True)
    audio = db.Column(db.Text, nullable=True)
    video = db.Column(db.Text, nullable=True)
    document = db.Column(db.Text, nullable=True)
    photo = db.Column(db.Text, nullable=True)
    longitude = db.Column(db.String(255), nullable=True)
    latitude = db.Column(db.String(255), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'chat_head_id': self.chat_head_id,
            'sender_id': self.sender_id,
            'receiver_id': self.receiver_id,
            'sender_name': self.sender_name,
            'sender_photo': self.sender_photo,
            'receiver_name': self.receiver_name,
            'receiver_photo': self.receiver_photo,
            'body': self.body,
            'type': self.type,
            'status': self.status,
            'audio': self.audio,
            'video': self.video,
            'document': self.document,
            'photo': self.photo,
            'longitude': self.longitude,
            'latitude': self.latitude,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
