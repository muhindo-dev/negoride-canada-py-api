import json
import os
import uuid
from flask import Blueprint, request
from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.trip_booking import TripBooking
from backend.models.payment import Payment
from backend.models.transaction import Transaction
from backend.models.user_wallet import UserWallet
from backend.utils.response import success_response, error_response

webhooks_bp = Blueprint('webhooks', __name__)

STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')


@webhooks_bp.route('/api/webhooks/stripe', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events."""
    import stripe
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')

    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature', '')

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except (ValueError, stripe.error.SignatureVerificationError):
            return error_response("Invalid signature", status_code=400)
    else:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return error_response("Invalid payload", status_code=400)

    event_type = event.get('type', '')
    data_obj = event.get('data', {}).get('object', {})

    if event_type == 'checkout.session.completed':
        _handle_checkout_completed(data_obj)
    elif event_type == 'payment_link.payment_completed':
        _handle_payment_link_completed(data_obj)

    return {'success': True}, 200


def _handle_checkout_completed(session):
    """Handle checkout.session.completed event."""
    metadata = session.get('metadata', {})
    session_id = session.get('id')
    amount = session.get('amount_total', 0)

    booking_id = metadata.get('booking_id')
    negotiation_id = metadata.get('negotiation_id')

    if booking_id:
        booking = TripBooking.query.get(int(booking_id))
        if booking:
            booking.payment_status = 'paid'
            booking.stripe_paid = 'Yes'
            booking.status = 'Reserved'

            _record_payment(
                customer_id=booking.customer_id,
                driver_id=booking.driver_id,
                amount=amount,
                reference=session_id,
                negotiation_id=None,
            )
            db.session.commit()

    elif negotiation_id:
        neg = Negotiation.query.get(int(negotiation_id))
        if neg:
            _mark_negotiation_paid(neg, session_id, amount)
    else:
        neg = Negotiation.query.filter_by(stripe_id=session_id).first()
        if neg:
            _mark_negotiation_paid(neg, session_id, amount)


def _handle_payment_link_completed(link_obj):
    """Handle payment_link.payment_completed event (legacy)."""
    link_id = link_obj.get('id')
    neg = Negotiation.query.filter_by(stripe_id=link_id).first()
    if neg:
        _mark_negotiation_paid(neg, link_id, neg.agreed_price or neg.initial_price or 0)


def _mark_negotiation_paid(negotiation, reference, amount):
    """Mark a negotiation as paid and distribute to wallet."""
    if negotiation.stripe_paid == 'Yes':
        return  # Idempotent

    negotiation.stripe_paid = 'Yes'
    negotiation.payment_status = 'paid'

    _record_payment(
        customer_id=negotiation.customer_id,
        driver_id=negotiation.driver_id,
        amount=amount,
        reference=reference,
        negotiation_id=negotiation.id,
    )

    # Credit driver wallet
    if negotiation.driver_id:
        wallet = UserWallet.query.filter_by(user_id=negotiation.driver_id).first()
        if not wallet:
            wallet = UserWallet(user_id=negotiation.driver_id, wallet_balance=0, total_earnings=0)
            db.session.add(wallet)
            db.session.flush()

        service_fee_pct = int(os.environ.get('SERVICE_FEE_PERCENTAGE', 10))
        service_fee = int(amount * service_fee_pct / 100)
        driver_amount = amount - service_fee

        balance_before = wallet.wallet_balance
        wallet.wallet_balance += driver_amount
        wallet.total_earnings += driver_amount

        tx = Transaction(
            user_id=negotiation.driver_id,
            user_type='driver',
            type='credit',
            category='ride_earning',
            amount=driver_amount,
            balance_before=balance_before,
            balance_after=wallet.wallet_balance,
            reference=f'earning-{reference}-{uuid.uuid4().hex[:8]}',
            description=f'Earning for negotiation #{negotiation.id}',
            status='completed',
            negotiation_id=negotiation.id,
        )
        db.session.add(tx)

    db.session.commit()


def _record_payment(customer_id, driver_id, amount, reference, negotiation_id=None):
    """Record a payment entry."""
    service_fee_pct = int(os.environ.get('SERVICE_FEE_PERCENTAGE', 10))
    service_fee = round(amount * service_fee_pct / 100, 2)
    driver_amount = round(amount - service_fee, 2)

    payment = Payment(
        negotiation_id=negotiation_id or 0,
        customer_id=customer_id or 0,
        driver_id=driver_id or 0,
        stripe_payment_intent_id=reference,
        amount=amount / 100 if amount > 1000 else amount,  # Convert cents to dollars if needed
        service_fee=service_fee / 100 if service_fee > 1000 else service_fee,
        driver_amount=driver_amount / 100 if driver_amount > 1000 else driver_amount,
        status='succeeded',
        payment_type='ride_payment',
        currency='cad',
        description=f'Payment for negotiation #{negotiation_id}' if negotiation_id else 'Payment',
    )
    db.session.add(payment)
