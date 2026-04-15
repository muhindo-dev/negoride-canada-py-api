"""Stripe payment service — Checkout Sessions, Connect, webhook handling."""
import os
import stripe

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')


def create_checkout_session(
    amount_cents: int,
    currency: str = 'cad',
    success_url: str = None,
    cancel_url: str = None,
    metadata: dict = None,
    customer_email: str = None,
    connected_account_id: str = None,
):
    """Create a Stripe Checkout Session.

    Args:
        amount_cents: Price in cents (e.g., 5000 = $50.00)
        currency: Currency code (default: cad)
        success_url: Redirect URL after successful payment
        cancel_url: Redirect URL if customer cancels
        metadata: Dict with negotiation_id or booking_id
        customer_email: Pre-fill customer email
        connected_account_id: Stripe Connect account for destination charges

    Returns:
        dict with session.id and session.url
    """
    base_url = os.environ.get('APP_URL', 'https://negoride.ugnews24.info')

    params = {
        'mode': 'payment',
        'payment_method_types': ['card'],
        'line_items': [{
            'price_data': {
                'currency': currency,
                'unit_amount': amount_cents,
                'product_data': {
                    'name': 'NegoRide Canada - Ride Payment',
                },
            },
            'quantity': 1,
        }],
        'success_url': success_url or f'{base_url}/api/payment-success?session_id={{CHECKOUT_SESSION_ID}}',
        'cancel_url': cancel_url or f'{base_url}/api/payment-cancel',
    }

    if metadata:
        params['metadata'] = metadata
    if customer_email:
        params['customer_email'] = customer_email

    if connected_account_id:
        params['payment_intent_data'] = {
            'transfer_data': {
                'destination': connected_account_id,
            },
        }

    session = stripe.checkout.Session.create(**params)
    return {
        'session_id': session.id,
        'url': session.url,
        'stripe_id': session.id,
    }


def create_negotiation_payment(negotiation):
    """Create a Checkout Session for a car-hire negotiation."""
    price = negotiation.agreed_price or negotiation.initial_price or 0

    result = create_checkout_session(
        amount_cents=price,
        metadata={
            'negotiation_id': str(negotiation.id),
            'type': 'car_hire',
        },
    )

    negotiation.stripe_id = result['stripe_id']
    negotiation.stripe_url = result['url']
    negotiation.payment_status = 'pending'
    return result


def create_booking_payment(booking, customer_email=None):
    """Create a Checkout Session for a rideshare trip booking."""
    price = booking.total_price or 0

    result = create_checkout_session(
        amount_cents=price,
        metadata={
            'booking_id': str(booking.id),
            'type': 'rideshare',
        },
        customer_email=customer_email,
    )

    booking.stripe_id = result['stripe_id']
    booking.stripe_url = result['url']
    booking.payment_status = 'pending'
    return result


def create_scheduled_booking_payment(booking, customer_email=None):
    """Create a Checkout Session for a scheduled booking."""
    price = booking.final_price or booking.customer_proposed_price or 0

    result = create_checkout_session(
        amount_cents=price,
        metadata={
            'scheduled_booking_id': str(booking.id),
            'type': 'scheduled_booking',
        },
        customer_email=customer_email,
    )

    booking.stripe_id = result.get('stripe_id')
    booking.stripe_url = result['url']
    booking.payment_status = 'pending'
    return result


def check_session_status(session_id: str) -> dict:
    """Check a Checkout Session's payment status."""
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        return {
            'status': session.payment_status,
            'is_paid': session.payment_status == 'paid',
            'amount_total': session.amount_total,
            'currency': session.currency,
            'url': session.url,
        }
    except stripe.error.StripeError as e:
        return {
            'status': 'error',
            'is_paid': False,
            'error': str(e),
        }


def verify_webhook_signature(payload: str, sig_header: str) -> dict:
    """Verify a Stripe webhook signature and return the event."""
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
    if not webhook_secret:
        import json
        return json.loads(payload)
    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
