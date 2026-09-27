from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Import all models so SQLAlchemy knows about them
from backend.models.user import AdminUser
from backend.models.negotiation import Negotiation
from backend.models.negotiation_record import NegotiationRecord
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.payment import Payment
from backend.models.transaction import Transaction
from backend.models.user_wallet import UserWallet
from backend.models.payout_account import PayoutAccount
from backend.models.payout_request import PayoutRequest
from backend.models.chat_head import ChatHead
from backend.models.chat_message import ChatMessage
from backend.models.trip_note import TripNote
from backend.models.company import Company
from backend.models.route_stage import RouteStage
from backend.models.call_log import CallLog

# ── v4 models ──────────────────────────────────────────────────────────────
from backend.models.platform import (  # noqa: E402,F401
    AppSetting, AuditLog, WebhookEvent, IdempotencyKey, TripEvent, AnalyticsEvent)
from backend.models.notification import (  # noqa: E402,F401
    Notification, NotificationDelivery, NotificationPreference, DeviceToken)
from backend.models.money import (  # noqa: E402,F401
    RidePayment, Refund, DocumentSequence, Receipt, CreditNote, TaxRate, DriverStrike)
from backend.models.safety import (  # noqa: E402,F401
    SafetyIncident, SafetyIncidentLocation, TrustedContact, SafetyReport, SafetySettings,
    SafetyCheck, HelpContact, RideLocation, RideShareLink, Recording, RecordingChunk)
from backend.models.identity import (  # noqa: E402,F401
    PhoneVerification, UserDevice, LegalDocument, LegalAcceptance, DriverApplication,
    DriverDocument, BackgroundCheck, SupportTicket, SupportTicketMessage)
from backend.models.experience import RideRating, FavouriteDriver, Referral  # noqa: E402,F401
