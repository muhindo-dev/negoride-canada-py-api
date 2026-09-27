"""Pay-before-trip, capture, cancellation settlement and refunds (spec §6, §7).

Lifecycle of a car-hire payment:
  PRICE_AGREED/AWAITING_PAYMENT ─ start_payment() ─▶ Checkout (capture_method=manual)
  webhook / poll ─ record_intent() ─▶ capture_status=authorized ─▶ ride CONFIRMED
  COMPLETED ─ capture_for_completion() ─▶ captured, driver wallet credited, receipt
  cancelled ─ settle_cancellation() ─▶ partial capture of the fee (rest released)
                                        or PaymentIntent cancel (full release)
                                        or Refund when money was already captured
  admin ─ manual_refund() ─▶ Refund + credit note + audit (+ optional clawback)

Every provider call uses a deterministic idempotency key; every DB effect is
guarded by a unique constraint, so jobs and webhooks may safely run twice.
"""
import logging
from datetime import datetime, timedelta

from backend.models import db
from backend.models.money import Refund, RidePayment
from backend.models.user import AdminUser
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services.payments.gateway import GatewayError, get_gateway
from backend.utils.money import fmt, pct_of

log = logging.getLogger('negoride.payments')


class PaymentError(Exception):
    def __init__(self, message, code='payment_error', status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


PAYABLE_STAGES = {
    'carhire': ('PRICE_AGREED', 'AWAITING_PAYMENT'),
    'scheduled': ('PRICE_AGREED', 'AWAITING_PAYMENT'),
    'rideshare_booking': ('PENDING_PAYMENT',),
}


def latest_payment(ride_type, ride_id, purpose='ride'):
    return (RidePayment.query.filter_by(ride_type=ride_type, ride_id=ride_id, purpose=purpose)
            .order_by(RidePayment.id.desc()).first())


def amounts_for(ride_type, ride):
    fare = R.fare_cents(ride_type, ride)
    fees = S.get_int('pricing.booking_fee_cents') if ride_type in ('carhire', 'scheduled') else 0
    return fare, fees


def _capture_method(ride_type, ride):
    """Rideshare seats booked more than N days ahead are charged immediately
    (card authorizations expire after ~7 days) and refunded per policy."""
    limit = timedelta(days=S.get_int('rideshare.charge_now_after_days'))
    if ride_type == 'rideshare_booking':
        trip = R.load('rideshare_trip', ride.trip_id)
        if trip.departure_at and trip.departure_at - datetime.utcnow() > limit:
            return 'automatic'
    if ride_type == 'scheduled' and ride.scheduled_at and ride.scheduled_at - datetime.utcnow() > limit:
        return 'automatic'  # same ~7-day authorization limit applies to far-future scheduled rides
    return 'manual'


def start_payment(ride_type, ride, customer, force_new=False):
    """Create (or reuse) the Checkout Session that authorizes the ride fare."""
    from backend.services.trip_state_machine import ensure_stage, transition, TransitionError
    stage = ensure_stage(ride_type, ride)
    existing = latest_payment(ride_type, ride.id)
    if existing and existing.is_secured:
        return existing
    if stage not in PAYABLE_STAGES.get(ride_type, ()):
        raise PaymentError(f'This ride cannot be paid for right now (stage {stage}).', code='not_payable', status=409)
    if int(customer.id) not in R.customer_ids(ride_type, ride):
        raise PaymentError('Only the customer can pay for this ride.', code='forbidden', status=403)

    fare, fees = amounts_for(ride_type, ride)
    total = fare + fees
    if total < 50:
        raise PaymentError('The agreed price is too low to charge (minimum $0.50).', code='amount_too_low')

    if existing and existing.capture_status == 'pending' and existing.checkout_url and not force_new \
            and existing.amount_authorized_cents == 0 and (existing.meta or {}).get('amount') == total:
        return existing

    method = _capture_method(ride_type, ride)
    rp = RidePayment(ride_type=ride_type, ride_id=ride.id, customer_id=customer.id,
                     driver_id=R.driver_id(ride_type, ride), purpose='ride', capture_method=method,
                     fare_cents=fare, fees_cents=fees, capture_status='pending', meta={'amount': total})
    db.session.add(rp)
    db.session.flush()
    metadata = {'ride_payment_id': str(rp.id), 'ride_type': ride_type, 'ride_id': str(ride.id), 'v': '4'}
    if ride_type == 'carhire':
        metadata['negotiation_id'] = str(ride.id)
    pickup, dropoff = R.addresses(ride_type, ride)
    desc = f"NegoRide ride #{ride.id}" + (f" — {(pickup or '')[:40]} → {(dropoff or '')[:40]}" if pickup else '')
    try:
        res = get_gateway().create_checkout(
            amount_cents=total, currency='cad', capture_method=method, metadata=metadata,
            description=desc[:120], customer_email=customer.email,
            idempotency_key=f'rp-{rp.id}-checkout')
    except GatewayError as e:
        db.session.rollback()
        raise PaymentError(f'Could not start the payment: {e}', code='gateway_error', status=502)
    rp.checkout_session_id = res['session_id']
    rp.checkout_url = res['url']
    rp.intent_id = res.get('intent_id')
    rp.idempotency_key = f'rp-{rp.id}-checkout'

    _sync_legacy_pending(ride_type, ride, rp)
    if stage == 'PRICE_AGREED':
        try:
            transition(ride_type, ride.id, 'AWAITING_PAYMENT', actor=customer, commit=False, ride=ride)
        except TransitionError:
            pass
    db.session.commit()
    return rp


def _sync_legacy_pending(ride_type, ride, rp):
    """Keep the fields the v3 app reads (stripe_url / payment_status) current."""
    if ride_type == 'carhire':
        ride.stripe_id = rp.checkout_session_id
        ride.stripe_session_id = rp.checkout_session_id
        ride.stripe_url = rp.checkout_url
        if ride.payment_status != 'paid':
            ride.payment_status = 'pending'
    elif ride_type in ('scheduled', 'rideshare_booking'):
        ride.stripe_id = rp.checkout_session_id
        ride.stripe_url = rp.checkout_url
        if (ride.payment_status or '').lower() != 'paid':
            ride.payment_status = 'pending'


def _sync_legacy_paid(ride_type, ride, rp):
    now = datetime.utcnow()
    if ride_type == 'carhire':
        ride.stripe_paid = 'Yes'
        ride.payment_status = 'paid'
        ride.payment_completed_at = ride.payment_completed_at or now
    elif ride_type == 'scheduled':
        ride.stripe_paid = True
        ride.payment_status = 'paid'
        ride.payment_completed_at = ride.payment_completed_at or now
    elif ride_type == 'rideshare_booking':
        ride.stripe_paid = 'Yes'
        ride.payment_status = 'paid'
        ride.payment_completed_at = ride.payment_completed_at or now


# ── authorization ───────────────────────────────────────────────────────────

def find_by_session(session_id):
    return RidePayment.query.filter_by(checkout_session_id=session_id).first()


def record_intent(rp, intent):
    """Apply a PaymentIntent snapshot (from webhook or poll). Idempotent.
    Returns True if the ride was newly confirmed."""
    from backend.services.trip_state_machine import ensure_stage, transition, TransitionError, is_terminal
    rp = RidePayment.query.filter_by(id=rp.id).with_for_update().first()
    rp.intent_id = rp.intent_id or intent['id']
    status = intent['status']
    rp.payment_method_brand = intent.get('brand') or rp.payment_method_brand
    rp.payment_method_last4 = intent.get('last4') or rp.payment_method_last4
    newly = False

    if status in ('requires_capture', 'succeeded') and rp.capture_status in ('pending', 'failed'):
        now = datetime.utcnow()
        rp.authorized_at = now
        if status == 'requires_capture':
            rp.capture_status = 'authorized'
            rp.amount_authorized_cents = int(intent.get('amount_capturable') or intent.get('amount') or 0)
            rp.auth_expires_at = intent.get('capture_before') or (now + timedelta(days=7))
        else:
            rp.capture_status = 'captured'
            rp.amount_authorized_cents = int(intent.get('amount') or 0)
            rp.amount_captured_cents = int(intent.get('amount_received') or intent.get('amount') or 0)
            rp.captured_at = now
        rp.failure_reason = None
        newly = True
    elif status in ('requires_payment_method', 'canceled') and rp.capture_status == 'pending':
        rp.capture_status = 'failed' if status != 'canceled' else 'canceled'
        rp.failure_reason = intent.get('last_payment_error') or status

    if rp.purpose != 'ride':
        db.session.commit()
        if newly:
            _on_non_ride_paid(rp)
        return newly

    ride = R.load(rp.ride_type, rp.ride_id, lock=True)
    stage = ensure_stage(rp.ride_type, ride)
    confirmed = False
    if newly:
        if is_terminal(rp.ride_type, stage):
            # Paid after the ride expired/cancelled — release the money at once.
            db.session.commit()
            _release_or_refund_full(rp, reason='late_payment')
            return False
        _sync_legacy_paid(rp.ride_type, ride, rp)
        if stage in ('PRICE_AGREED', 'AWAITING_PAYMENT', 'PENDING_PAYMENT'):
            try:
                transition(rp.ride_type, ride.id, 'CONFIRMED', actor=None, commit=False, ride=ride,
                           meta={'ride_payment_id': rp.id, 'amount_cents': rp.amount_authorized_cents})
                confirmed = True
            except TransitionError as e:
                log.warning('Payment authorized but ride %s/%s not confirmed: %s', rp.ride_type, ride.id, e)
    elif rp.capture_status == 'failed':
        from backend.services.notify import notify
        notify('payment.failed', [rp.customer_id], {'ride_type': rp.ride_type, 'ride_id': rp.ride_id})
    db.session.commit()
    return confirmed


def sync_from_provider(rp):
    """Poll path (app 'check payment'): read the session/intent and apply it."""
    gw = get_gateway()
    try:
        intent_id = rp.intent_id
        if not intent_id and rp.checkout_session_id:
            sess = gw.get_session(rp.checkout_session_id)
            intent_id = sess.get('intent_id')
        if not intent_id:
            return False
        return record_intent(rp, gw.get_intent(intent_id))
    except GatewayError as e:
        log.info('sync_from_provider(%s): %s', rp.id, e)
        return False


def _on_non_ride_paid(rp):
    """Tips and background-check fees."""
    from backend.services import wallet_service
    if rp.purpose == 'tip' and rp.driver_id:
        wallet_service.credit(rp.driver_id, wallet_service.cents_to_dollars(rp.amount_captured_cents or rp.amount_authorized_cents),
                              'tip', f'tip-{rp.id}', f'Tip for ride #{rp.ride_id} (100 % to driver)',
                              negotiation_id=rp.ride_id if rp.ride_type == 'carhire' else None)
        db.session.commit()
    elif rp.purpose == 'background_check':
        try:
            from backend.services import onboarding_service
            onboarding_service.on_background_check_fee_paid(rp)
        except ImportError:
            log.warning('onboarding_service not available for background-check payment %s', rp.id)


# ── completion capture ──────────────────────────────────────────────────────

def capture_for_completion(ride_type, ride_id):
    """Job at COMPLETED (car hire) / DROPPED_OFF (seat): capture, credit the
    driver, then issue the receipt. Safe to run twice."""
    ride = R.load(ride_type, ride_id)
    rp = latest_payment(ride_type, ride_id)
    gw = get_gateway()
    fare, fees = rp.fare_cents if rp else R.fare_cents(ride_type, ride), rp.fees_cents if rp else 0

    if rp and rp.capture_status == 'authorized':
        amount = min(rp.amount_authorized_cents, fare + fees)  # never more than authorized
        try:
            intent = gw.capture(rp.intent_id, amount, idempotency_key=f'rp-{rp.id}-capture')
        except GatewayError as e:
            rp.failure_reason = f'capture failed: {e}'
            db.session.commit()
            log.error('Capture failed for ride payment %s: %s', rp.id, e)
            raise
        rp.amount_captured_cents = int(intent.get('amount_received') or amount)
        rp.capture_status = 'captured' if rp.amount_captured_cents >= rp.amount_authorized_cents else 'partially_captured'
        rp.captured_at = datetime.utcnow()
        db.session.commit()

    captured = rp.amount_captured_cents if rp else 0
    if rp and captured > 0:
        _credit_driver_fare(ride_type, ride, rp, fare_cents=min(fare, captured))
        _legacy_payment_row(ride_type, ride, rp, captured)
        db.session.commit()
    return captured


def _credit_driver_fare(ride_type, ride, rp, fare_cents):
    from backend.services import wallet_service
    driver = R.driver_id(ride_type, ride)
    if not driver or fare_cents <= 0:
        return
    pct = S.get_int('pricing.commission_pct')
    if ride_type == 'carhire':
        wallet_service.credit_ride_earning(driver, fare_cents, negotiation_id=ride.id, service_fee_pct=pct)
    elif ride_type == 'rideshare_booking':
        wallet_service.credit_ride_earning(driver, fare_cents, booking_id=ride.id, service_fee_pct=pct)
    else:
        net = fare_cents - pct_of(fare_cents, pct)
        wallet_service.credit(driver, wallet_service.cents_to_dollars(net), 'ride_earning',
                              f'earning-{ride_type}-{ride.id}',
                              f'Ride earning (net of {pct}% platform fee)')


def _legacy_payment_row(ride_type, ride, rp, amount_cents):
    """Mirror car-hire captures into the legacy `payments` table (the old admin
    Payments page reads it). That table is keyed to negotiations (FK), so only
    car hire is mirrored; v4 reporting uses ride_payments. Runs in a SAVEPOINT
    so a mirror failure can never poison the money flow."""
    if ride_type != 'carhire':
        return
    try:
        from backend.routes.webhooks import _record_payment
        with db.session.begin_nested():
            _record_payment(customer_id=rp.customer_id, driver_id=rp.driver_id or 0, amount=amount_cents,
                            reference=rp.intent_id or f'rp-{rp.id}', negotiation_id=ride.id)
            db.session.flush()
    except Exception as e:
        log.warning('legacy payment mirror failed: %s', e)


# ── cancellation settlement ─────────────────────────────────────────────────

def settle_cancellation(ride_type, ride_id, decision):
    """Apply a refund_policy Decision (dict) to the ride's payment. Idempotent."""
    from backend.services import wallet_service
    from backend.services.notify import notify
    ride = R.load(ride_type, ride_id)
    rp = latest_payment(ride_type, ride_id)
    fee = int(decision.get('fee_cents') or 0)
    released = refunded = 0

    if rp and rp.capture_status == 'pending':
        if rp.checkout_session_id:
            get_gateway().expire_session(rp.checkout_session_id)
        rp.capture_status = 'canceled'
        rp.canceled_at = datetime.utcnow()
    elif rp and rp.capture_status == 'authorized':
        gw = get_gateway()
        fee = min(fee, rp.amount_authorized_cents)
        if fee > 0:
            intent = gw.capture(rp.intent_id, fee, idempotency_key=f'rp-{rp.id}-cancel-capture')
            rp.amount_captured_cents = int(intent.get('amount_received') or fee)
            rp.capture_status = 'partially_captured'
            rp.captured_at = datetime.utcnow()
        else:
            gw.cancel(rp.intent_id, idempotency_key=f'rp-{rp.id}-cancel')
            rp.capture_status = 'canceled'
            rp.canceled_at = datetime.utcnow()
        released = rp.amount_authorized_cents - fee
        if released > 0:
            _refund_row(rp, released, 'release', decision.get('rule_id'), decision.get('explanation'),
                        key=f'rp-{rp.id}-release', provider_id=rp.intent_id)
    elif rp and rp.capture_status in ('captured', 'partially_captured'):
        refund_amount = max(0, rp.amount_captured_cents - rp.amount_refunded_cents - fee)
        if refund_amount > 0:
            refunded = _provider_refund(rp, refund_amount, decision.get('rule_id'), decision.get('explanation'),
                                        key=f'rp-{rp.id}-cancel-refund')
    db.session.commit()

    driver = R.driver_id(ride_type, ride)
    share = int(decision.get('driver_share_cents') or 0)
    if driver and fee > 0 and share > 0:
        wallet_service.credit(driver, wallet_service.cents_to_dollars(min(share, fee)), 'cancellation_fee',
                              f'cancel-fee-{ride_type}-{ride.id}',
                              f"Cancellation fee for ride #{ride.id} ({decision.get('rule_id')})")
    credit = int(decision.get('credit_cents') or 0)
    cid = (R.customer_ids(ride_type, ride) or [None])[0]
    if credit > 0 and cid:
        wallet_service.credit(cid, wallet_service.cents_to_dollars(credit), 'ride_credit',
                              f'credit-{ride_type}-{ride.id}', 'Apology ride credit (driver no-show)',
                              add_to_earnings=False)
    db.session.commit()

    back = released + refunded
    if back > 0 and cid:
        notify('refund.issued', [cid], {'amount': fmt(back), 'released': released > 0 and not refunded,
                                        'ride_type': ride_type, 'ride_id': ride.id,
                                        'explanation': decision.get('explanation')})
        db.session.commit()
    return {'fee_cents': fee, 'released_cents': released, 'refunded_cents': refunded}


def _refund_row(rp, amount, kind, rule_id, reason, key, provider_id=None, actor=None, actor_type='system'):
    existing = Refund.query.filter_by(idempotency_key=key).first()
    if existing:
        return existing
    r = Refund(ride_payment_id=rp.id, ride_type=rp.ride_type, ride_id=rp.ride_id, customer_id=rp.customer_id,
               amount_cents=int(amount), kind=kind, rule_id=rule_id, reason=reason, idempotency_key=key,
               provider_refund_id=provider_id, status='succeeded', processed_at=datetime.utcnow(),
               initiated_by=getattr(actor, 'id', actor), initiated_by_type=actor_type)
    db.session.add(r)
    db.session.flush()
    return r


def _provider_refund(rp, amount, rule_id, reason, key, actor=None, actor_type='system'):
    existing = Refund.query.filter_by(idempotency_key=key).first()
    if existing:
        return 0
    res = get_gateway().refund(rp.intent_id, amount, idempotency_key=key, reason='requested_by_customer')
    r = _refund_row(rp, amount, 'refund', rule_id, reason, key, provider_id=res.get('id'), actor=actor,
                    actor_type=actor_type)
    rp.amount_refunded_cents = (rp.amount_refunded_cents or 0) + int(amount)
    _mark_legacy_refunded(rp)
    _issue_credit_note(r.id)
    return int(amount)


def _mark_legacy_refunded(rp):
    if rp.amount_refunded_cents >= rp.amount_captured_cents and rp.ride_type == 'carhire':
        ride = R.load(rp.ride_type, rp.ride_id)
        ride.payment_status = 'refunded'


def _issue_credit_note(refund_id):
    from backend import jobs
    jobs.enqueue_after_commit('backend.services.trip_effects.issue_credit_note_safe', refund_id)


def _release_or_refund_full(rp, reason):
    gw = get_gateway()
    if rp.capture_status == 'authorized':
        gw.cancel(rp.intent_id, idempotency_key=f'rp-{rp.id}-cancel')
        rp.capture_status = 'canceled'
        rp.canceled_at = datetime.utcnow()
        _refund_row(rp, rp.amount_authorized_cents, 'release', reason, 'Payment arrived after the ride ended',
                    key=f'rp-{rp.id}-release')
    elif rp.capture_status in ('captured', 'partially_captured'):
        _provider_refund(rp, rp.amount_captured_cents - rp.amount_refunded_cents, reason,
                         'Payment arrived after the ride ended', key=f'rp-{rp.id}-late-refund')
    db.session.commit()


# ── manual (admin) refunds ──────────────────────────────────────────────────

def manual_refund(rp, amount_cents, reason, actor, idempotency_key, clawback=False):
    """Admin full/partial refund with mandatory reason (spec §7.3). Audited."""
    from backend.services.audit import audit
    from backend.services import wallet_service
    from backend.services.notify import notify
    if not reason or len(reason.strip()) < 5:
        raise PaymentError('A reason (at least 5 characters) is required.', code='reason_required')
    amount_cents = int(amount_cents)
    refundable = (rp.amount_captured_cents or 0) - (rp.amount_refunded_cents or 0)
    if rp.capture_status == 'authorized':
        raise PaymentError('This payment is still an authorization hold — cancel the ride to release it.',
                           code='not_captured', status=409)
    if amount_cents <= 0 or amount_cents > refundable:
        raise PaymentError(f'Refund must be between $0.01 and {fmt(refundable)}.', code='bad_amount')
    before = rp.to_dict()
    key = f'admin-refund-{rp.id}-{idempotency_key}'
    try:
        refunded = _provider_refund(rp, amount_cents, 'admin_manual', reason.strip(), key=key, actor=actor,
                                    actor_type='admin')
    except GatewayError as e:
        raise PaymentError(f'Stripe refused the refund: {e}', code='gateway_error', status=502)
    clawed = 0
    if clawback and refunded and rp.driver_id:
        pct = S.get_int('pricing.commission_pct')
        clawed = amount_cents - pct_of(amount_cents, pct)
        bal = wallet_service.balance_of(rp.driver_id)
        take = min(wallet_service.cents_to_dollars(clawed), bal)
        if take > 0:
            wallet_service.debit(rp.driver_id, take, 'clawback', f'clawback-{key}',
                                 f'Clawback for refund on ride #{rp.ride_id}')
    if refunded:   # a replay of the same idempotency key moves no money and is not re-audited
        audit('payment.manual_refund', actor, 'ride_payment', rp.id, before=before, after=rp.to_dict(),
              meta={'amount_cents': amount_cents, 'reason': reason, 'clawback_cents': clawed})
    db.session.commit()
    if refunded:
        notify('refund.issued', [rp.customer_id], {'amount': fmt(amount_cents), 'released': False,
                                                   'ride_type': rp.ride_type, 'ride_id': rp.ride_id})
        db.session.commit()
    return refunded


# ── tips & fees ─────────────────────────────────────────────────────────────

def start_extra_payment(purpose, ride_type, ride_id, customer, amount_cents, driver_id=None, description=None):
    """Immediate-capture Checkout for a tip (100 % to driver) or background-check fee."""
    if amount_cents < 50:
        raise PaymentError('Minimum amount is $0.50.', code='amount_too_low')
    rp = RidePayment(ride_type=ride_type, ride_id=ride_id, customer_id=customer.id, driver_id=driver_id,
                     purpose=purpose, capture_method='automatic', fare_cents=amount_cents,
                     tip_cents=amount_cents if purpose == 'tip' else 0, capture_status='pending')
    db.session.add(rp)
    db.session.flush()
    try:
        res = get_gateway().create_checkout(
            amount_cents=amount_cents, currency='cad', capture_method='automatic',
            metadata={'ride_payment_id': str(rp.id), 'purpose': purpose, 'v': '4'},
            description=description or f'NegoRide {purpose.replace("_", " ")}',
            customer_email=customer.email, idempotency_key=f'rp-{rp.id}-checkout')
    except GatewayError as e:
        db.session.rollback()
        raise PaymentError(f'Could not start the payment: {e}', code='gateway_error', status=502)
    rp.checkout_session_id, rp.checkout_url = res['session_id'], res['url']
    db.session.commit()
    return rp


# ── webhook routing ─────────────────────────────────────────────────────────

def handle_stripe_event(event):
    """Process one verified Stripe event (called from the webhook job).
    Returns True if a v4 RidePayment handled it."""
    etype = event.get('type', '')
    obj = (event.get('data') or {}).get('object') or {}
    meta = obj.get('metadata') or {}
    rp = None
    if meta.get('ride_payment_id'):
        rp = db.session.get(RidePayment, int(meta['ride_payment_id']))
    elif obj.get('object') == 'checkout.session':
        rp = find_by_session(obj.get('id'))
    elif obj.get('object') == 'payment_intent':
        rp = RidePayment.query.filter_by(intent_id=obj.get('id')).first()
    if rp is None:
        return False

    if etype in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        intent_id = obj.get('payment_intent')
        if intent_id:
            rp.intent_id = rp.intent_id or intent_id
            db.session.commit()
            record_intent(rp, get_gateway().get_intent(intent_id))
    elif etype in ('payment_intent.amount_capturable_updated', 'payment_intent.succeeded',
                   'payment_intent.payment_failed', 'payment_intent.canceled'):
        record_intent(rp, {'id': obj.get('id'), 'status': obj.get('status'), 'amount': obj.get('amount'),
                           'amount_capturable': obj.get('amount_capturable'),
                           'amount_received': obj.get('amount_received'),
                           'last_payment_error': ((obj.get('last_payment_error') or {}).get('message'))})
    elif etype == 'checkout.session.expired':
        if rp.capture_status == 'pending':
            rp.capture_status = 'expired'
            db.session.commit()
    return True
