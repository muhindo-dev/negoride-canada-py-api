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
