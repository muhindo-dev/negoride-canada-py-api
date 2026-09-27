"""Wallet service — the single, authoritative money layer.

MONEY UNITS (read this before touching balances):
  * Wallet balances, Transaction.amount, Payment.amount and PayoutRequest.amount
    are all DOLLARS stored as Numeric(10,2).
  * Stripe amounts and negotiation prices (agreed_price / initial_price) are CENTS
    (integers). Convert with `cents_to_dollars()` at the boundary — NEVER add cents
    straight into a dollar balance (that was the historical 100x over-credit bug).

EVERY mutation goes through credit()/debit(), which:
  * lock the wallet row (SELECT ... FOR UPDATE) so concurrent writers serialise and
    a balance can never be double-spent or over-withdrawn;
  * write a Transaction row with balance_before / balance_after for a full audit trail;
  * are IDEMPOTENT on a DETERMINISTIC `reference` (e.g. earning-neg-42, withdrawal-9,
    refund-9). The UNIQUE index on transactions.reference is the final backstop, so a
    replayed Stripe webhook or a retried request can never move money twice.

Callers own the surrounding transaction: these helpers flush but do NOT commit.
"""
from decimal import Decimal, ROUND_HALF_UP

from backend.models import db
from backend.models.user_wallet import UserWallet
from backend.models.transaction import Transaction
from backend.models.user import AdminUser

CENTS = Decimal('0.01')


def money(x) -> Decimal:
    """Coerce to a 2-decimal dollar amount (half-up rounding)."""
    return Decimal(str(x or 0)).quantize(CENTS, rounding=ROUND_HALF_UP)


def cents_to_dollars(cents) -> Decimal:
    """Stripe/negotiation CENTS -> dollar amount."""
    return (Decimal(int(cents or 0)) / Decimal(100)).quantize(CENTS, rounding=ROUND_HALF_UP)


def _user_type(user_id) -> str:
    u = AdminUser.query.get(user_id)
    return 'driver' if (u and u.user_type in ('Driver', 'Pending Driver')) else 'customer'


def get_or_create_wallet(user_id: int, lock: bool = False) -> UserWallet:
    q = UserWallet.query.filter_by(user_id=user_id)
    if lock:
        q = q.with_for_update()
    wallet = q.first()
    if wallet:
        return wallet
    wallet = UserWallet(user_id=user_id, wallet_balance=0, total_earnings=0)
    db.session.add(wallet)
    db.session.flush()
    if lock:  # re-read under a row lock now that the row exists
        wallet = UserWallet.query.filter_by(user_id=user_id).with_for_update().first()
    return wallet


def _tx_exists(reference: str) -> bool:
    return db.session.query(Transaction.id).filter_by(reference=reference).first() is not None


def balance_of(user_id: int) -> Decimal:
    wallet = UserWallet.query.filter_by(user_id=user_id).first()
    return money(wallet.wallet_balance) if wallet else money(0)


def credit(user_id, amount_dollars, category, reference, description,
           negotiation_id=None, booking_id=None, payment_id=None,
           add_to_earnings=True):
    """Idempotently add money to a wallet. Returns (Transaction|None, created: bool)."""
    amount = money(amount_dollars)
    if amount <= 0:
        return None, False
    wallet = get_or_create_wallet(user_id, lock=True)   # lock FIRST so we serialise
    if _tx_exists(reference):                            # then the idempotency check
        return None, False
    balance_before = money(wallet.wallet_balance)
    wallet.wallet_balance = balance_before + amount
    if add_to_earnings:
        wallet.total_earnings = money(wallet.total_earnings) + amount
    tx = Transaction(
        user_id=user_id, user_type=_user_type(user_id),
        type='credit', category=category, amount=amount,
        balance_before=balance_before, balance_after=wallet.wallet_balance,
        reference=reference, description=description, status='completed',
        negotiation_id=negotiation_id, booking_id=booking_id, payment_id=payment_id,
    )
    db.session.add(tx)
    db.session.flush()
    return tx, True


def debit(user_id, amount_dollars, category, reference, description,
          negotiation_id=None, booking_id=None, payment_id=None):
    """Idempotently, atomically remove money from a wallet.

    Returns (Transaction|None, created: bool). Raises ValueError on insufficient funds.
    """
    amount = money(amount_dollars)
    if amount <= 0:
        raise ValueError("Amount must be greater than zero")
    wallet = get_or_create_wallet(user_id, lock=True)   # lock FIRST
    if _tx_exists(reference):
        return None, False                              # already applied — idempotent
    balance_before = money(wallet.wallet_balance)
    if balance_before < amount:
        raise ValueError("Insufficient wallet balance")
    wallet.wallet_balance = balance_before - amount
    tx = Transaction(
        user_id=user_id, user_type=_user_type(user_id),
        type='debit', category=category, amount=amount,
        balance_before=balance_before, balance_after=wallet.wallet_balance,
        reference=reference, description=description, status='completed',
        negotiation_id=negotiation_id, booking_id=booking_id, payment_id=payment_id,
    )
    db.session.add(tx)
    db.session.flush()
    return tx, True


def credit_ride_earning(driver_id, gross_cents, negotiation_id=None, booking_id=None,
                        payment_id=None, service_fee_pct=10):
    """Idempotently credit a driver for a CONFIRMED ride payment.

    `gross_cents` is the Stripe/negotiation amount in CENTS. We convert to dollars,
    take the platform fee, and credit the NET to the driver. Keyed on the
    negotiation/booking id so the webhook and the status-poll path (and retries)
    can never double-credit or miss a credit.
    """
    gross = cents_to_dollars(gross_cents)
    fee = money(gross * Decimal(service_fee_pct) / Decimal(100))
    net = money(gross - fee)
    if net <= 0:
        return None, False
    if negotiation_id:
        ref = f'earning-neg-{negotiation_id}'
    elif booking_id:
        ref = f'earning-booking-{booking_id}'
    else:
        ref = f'earning-pay-{payment_id}'
    return credit(
        driver_id, net, 'ride_earning', ref,
        f'Ride earning (net of {service_fee_pct}% platform fee)',
        negotiation_id=negotiation_id, booking_id=booking_id, payment_id=payment_id,
    )


def refund_to_wallet(user_id, amount_dollars, reference, description,
                     negotiation_id=None, booking_id=None):
    """Idempotently return reserved funds to a wallet (payout cancel/reject).

    Does NOT count as earnings. Safe to call more than once for the same reference.
    """
    return credit(
        user_id, amount_dollars, 'refund', reference, description,
        negotiation_id=negotiation_id, booking_id=booking_id, add_to_earnings=False,
    )
