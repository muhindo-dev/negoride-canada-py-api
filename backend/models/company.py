from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class Company(db.Model):
    __tablename__ = 'companies'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.Text, nullable=True)
    short_name = db.Column(db.Text, nullable=True)
    details = db.Column(db.Text, nullable=True)
    logo = db.Column(db.Text, nullable=True)
    phone_number = db.Column(db.Text, nullable=True)
    phone_number_2 = db.Column(db.Text, nullable=True)
    p_o_box = db.Column(db.Text, nullable=True)
    email = db.Column(db.Text, nullable=True)
    address = db.Column(db.Text, nullable=True)
    website = db.Column(db.String(255), nullable=True)
    subdomain = db.Column(db.String(255), nullable=True)
    color = db.Column(db.String(255), nullable=True)
    welcome_message = db.Column(db.String(255), nullable=True)
    type = db.Column(db.String(255), nullable=True)
    wallet_balance = db.Column(db.String(255), nullable=True)
    can_send_messages = db.Column(db.String(255), nullable=True)
    has_valid_lisence = db.Column(db.String(255), nullable=True)
    administrator_id = db.Column(db.Integer, nullable=False, default=1)
    dp_year = db.Column(db.Integer, nullable=True)
    active_year = db.Column(db.Integer, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'short_name': self.short_name,
            'details': self.details,
            'logo': self.logo,
            'phone_number': self.phone_number,
            'phone_number_2': self.phone_number_2,
            'p_o_box': self.p_o_box,
            'email': self.email,
            'address': self.address,
            'website': self.website,
            'subdomain': self.subdomain,
            'color': self.color,
            'welcome_message': self.welcome_message,
            'type': self.type,
            'wallet_balance': self.wallet_balance,
            'can_send_messages': self.can_send_messages,
            'has_valid_lisence': self.has_valid_lisence,
            'administrator_id': self.administrator_id,
            'dp_year': self.dp_year,
            'active_year': self.active_year,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
