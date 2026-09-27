import os
from flask import Blueprint, request, current_app
from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.trip_booking import TripBooking
from backend.models.payment import Payment
from backend.services import wallet_service
from backend.utils.response import success_response, error_response

webhooks_bp = Blueprint('webhooks', __name__)

STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')


@webhooks_bp.route('/api/webhooks/stripe', methods=['POST'])
def stripe_webhook():
    """Stripe webhook (spec §2.5): verify the signature, persist the raw event
    to webhook_events FIRST (unique on the Stripe event id, so replays are
    no-ops), then process it asynchronously."""
    import json
    import stripe
    from datetime import datetime
    from backend import jobs
    from backend.models.platform import WebhookEvent

    secret = os.environ.get('STRIPE_WEBHOOK_SECRET', '') or STRIPE_WEBHOOK_SECRET
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature', '')

    # NEVER trust an unsigned webhook. Without signature verification, anyone
    # could POST a forged `checkout.session.completed` and mark orders paid for
    # free. If the signing secret isn't configured, refuse the event outright.
    if not secret:
        current_app.logger.error(
            'Stripe webhook rejected: STRIPE_WEBHOOK_SECRET is not configured.')
        return error_response("Webhook signing secret not configured.", status_code=503)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return error_response("Invalid signature", status_code=400)

    event_id = event.get('id') or ''
    existing = WebhookEvent.query.filter_by(provider='stripe', event_id=event_id).first()
    if existing:
        return {'success': True, 'duplicate': True}, 200
    row = WebhookEvent(provider='stripe', event_id=event_id, event_type=event.get('type'),
                       payload=payload, signature_valid=True, status='received', received_at=datetime.utcnow())
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()   # concurrent delivery of the same event
        return {'success': True, 'duplicate': True}, 200

    jobs.enqueue(process_stripe_event, row.id)
    return {'success': True}, 200


def process_stripe_event(webhook_event_id):
    """Job: route one stored Stripe event. v4 ride payments first; anything
    else (pre-v4 Checkout sessions) goes through the legacy handlers."""
    import json
    from datetime import datetime
    from backend.models.platform import WebhookEvent
    from backend.services.payments import payment_service

    row = db.session.get(WebhookEvent, webhook_event_id)
    if not row or row.status == 'processed':
        return
    row.attempts = (row.attempts or 0) + 1
    event = json.loads(row.payload)
    try:
        handled = payment_service.handle_stripe_event(event)
        if not handled:
            event_type = event.get('type', '')
            data_obj = event.get('data', {}).get('object', {})
            if event_type == 'checkout.session.completed':
                _handle_checkout_completed(data_obj)
            elif event_type == 'payment_link.payment_completed':
                _handle_payment_link_completed(data_obj)
        row = db.session.get(WebhookEvent, webhook_event_id)
        row.status, row.processed_at, row.error = 'processed', datetime.utcnow(), None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        row = db.session.get(WebhookEvent, webhook_event_id)
        row.status, row.error = 'failed', str(exc)[:2000]
        db.session.commit()
        raise


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
            # Credit the driver their net earning (idempotent, keyed on booking id).
            if booking.driver_id:
                wallet_service.credit_ride_earning(
                    booking.driver_id, amount, booking_id=booking.id,
                    service_fee_pct=_service_fee_pct(),
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


def _service_fee_pct():
    try:
        return int(os.environ.get('SERVICE_FEE_PERCENTAGE', 10))
    except (TypeError, ValueError):
        return 10


def _mark_negotiation_paid(negotiation, reference, amount):
    """Mark a negotiation paid and credit the driver. Fully idempotent.

    `amount` is CENTS (Stripe amount_total / negotiation price). Crediting is keyed
    on the negotiation id inside wallet_service, so this is safe to run more than
    once AND still credits even if the status-poll path flipped stripe_paid first.
    """
    if negotiation.stripe_paid != 'Yes':
        negotiation.stripe_paid = 'Yes'
        negotiation.payment_status = 'paid'

    _record_payment(
        customer_id=negotiation.customer_id,
        driver_id=negotiation.driver_id,
        amount=amount,
        reference=reference,
        negotiation_id=negotiation.id,
    )

    if negotiation.driver_id:
        wallet_service.credit_ride_earning(
            negotiation.driver_id, amount, negotiation_id=negotiation.id,
            service_fee_pct=_service_fee_pct(),
        )

    db.session.commit()


def _record_payment(customer_id, driver_id, amount, reference, negotiation_id=None):
    """Record a Payment audit row. `amount` is CENTS; Payment stores DOLLARS.

    Idempotent: stripe_payment_intent_id is UNIQUE, so a replayed webhook that
    tries to insert the same reference is skipped instead of raising.
    """
    if Payment.query.filter_by(stripe_payment_intent_id=reference).first():
        return  # already recorded for this Stripe reference

    gross = wallet_service.cents_to_dollars(amount)
    pct = _service_fee_pct()
    service_fee = wallet_service.money(gross * pct / 100)
    driver_amount = wallet_service.money(gross - service_fee)

    payment = Payment(
        negotiation_id=negotiation_id or 0,
        customer_id=customer_id or 0,
        driver_id=driver_id or 0,
        stripe_payment_intent_id=reference,
        amount=gross,
        service_fee=service_fee,
        driver_amount=driver_amount,
        status='succeeded',
        payment_type='ride_payment',
        currency='cad',
        description=f'Payment for negotiation #{negotiation_id}' if negotiation_id else 'Payment',
    )
    db.session.add(payment)
