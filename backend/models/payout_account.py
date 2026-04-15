from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class PayoutAccount(db.Model):
    __tablename__ = 'payout_accounts'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('admin_users.id'), unique=True, nullable=False)
    account_type = db.Column(db.Enum('express', 'standard', 'custom'), default='express')
    status = db.Column(db.Enum('pending', 'active', 'restricted', 'disabled', 'rejected'), default='pending')
    stripe_account_id = db.Column(db.String(255), unique=True, nullable=True)
    stripe_person_id = db.Column(db.String(255), nullable=True)
    onboarding_completed = db.Column(db.Boolean, default=False)
    charges_enabled = db.Column(db.Boolean, default=False)
    payouts_enabled = db.Column(db.Boolean, default=False)
    details_submitted = db.Column(db.Boolean, default=False)

    # Bank info
    bank_account_last4 = db.Column(db.String(255), nullable=True)
    bank_account_type = db.Column(db.String(255), nullable=True)
    bank_account_country = db.Column(db.String(2), default='CA')
    bank_name = db.Column(db.String(255), nullable=True)
    card_last4 = db.Column(db.String(255), nullable=True)
    card_brand = db.Column(db.String(255), nullable=True)
    card_country = db.Column(db.String(2), nullable=True)

    # Verification
    verification_status = db.Column(db.Enum('unverified', 'pending', 'verified', 'failed'), default='unverified')
    verification_fields_needed = db.Column(db.Text, nullable=True)
    requirements_currently_due = db.Column(db.Text, nullable=True)
    requirements_eventually_due = db.Column(db.Text, nullable=True)
    requirements_past_due = db.Column(db.Text, nullable=True)
    requirements_due_by = db.Column(db.DateTime, nullable=True)

    # Payout preferences
    default_payout_method = db.Column(db.Enum('standard', 'instant'), default='standard')
    default_currency = db.Column(db.String(3), default='CAD')
    minimum_payout_amount = db.Column(db.Numeric(10, 2), default=10.00)

    # Business info
    business_name = db.Column(db.String(255), nullable=True)
    business_type = db.Column(db.String(255), nullable=True)
    business_profile = db.Column(db.Text, nullable=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(255), nullable=True)
    country = db.Column(db.String(2), default='CA')
    stripe_dashboard_url = db.Column(db.String(255), nullable=True)
    last_stripe_sync = db.Column(db.DateTime, nullable=True)
    metadata_text = db.Column('metadata', db.Text, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    activated_at = db.Column(db.DateTime, nullable=True)
    disabled_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'account_type': self.account_type,
            'status': self.status,
            'stripe_account_id': self.stripe_account_id,
            'onboarding_completed': self.onboarding_completed,
            'charges_enabled': self.charges_enabled,
            'payouts_enabled': self.payouts_enabled,
            'details_submitted': self.details_submitted,
            'bank_account_last4': self.bank_account_last4,
            'bank_account_type': self.bank_account_type,
            'bank_account_country': self.bank_account_country,
            'bank_name': self.bank_name,
            'card_last4': self.card_last4,
            'card_brand': self.card_brand,
            'card_country': self.card_country,
            'verification_status': self.verification_status,
            'default_payout_method': self.default_payout_method,
            'default_currency': self.default_currency,
            'minimum_payout_amount': float(self.minimum_payout_amount) if self.minimum_payout_amount else 10.0,
            'business_name': self.business_name,
            'email': self.email,
            'phone': self.phone,
            'country': self.country,
            'stripe_dashboard_url': self.stripe_dashboard_url,
            'last_stripe_sync': my_date_time(self.last_stripe_sync),
            'activated_at': my_date_time(self.activated_at),
            'disabled_at': my_date_time(self.disabled_at),
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
