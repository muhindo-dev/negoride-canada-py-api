from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class ChatHead(db.Model):
    __tablename__ = 'chat_heads'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    product_id = db.Column(db.BigInteger, nullable=True)
    product_name = db.Column(db.Text, nullable=True)
    product_photo = db.Column(db.Text, nullable=True)
    product_owner_id = db.Column(db.Integer, nullable=True)
    product_owner_name = db.Column(db.Text, nullable=True)
    product_owner_photo = db.Column(db.Text, nullable=True)
    product_owner_last_seen = db.Column(db.String(255), nullable=True)
    customer_id = db.Column(db.Integer, nullable=True)
    customer_name = db.Column(db.Text, nullable=True)
    customer_photo = db.Column(db.Text, nullable=True)
    customer_last_seen = db.Column(db.String(255), nullable=True)
    last_message_body = db.Column(db.Text, nullable=True)
    last_message_time = db.Column(db.String(255), nullable=True)
    last_message_status = db.Column(db.String(255), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product_name,
            'product_photo': self.product_photo,
            'product_owner_id': self.product_owner_id,
            'product_owner_name': self.product_owner_name,
            'product_owner_photo': self.product_owner_photo,
            'product_owner_last_seen': self.product_owner_last_seen,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'customer_photo': self.customer_photo,
            'customer_last_seen': self.customer_last_seen,
            'last_message_body': self.last_message_body,
            'last_message_time': self.last_message_time,
            'last_message_status': self.last_message_status,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
