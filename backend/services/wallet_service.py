"""Wallet service — balance operations, transaction recording."""
from backend.models import db
from backend.models.user_wallet import UserWallet
from backend.models.transaction import Transaction


def get_or_create_wallet(user_id: int) -> UserWallet:
    """Get user's wallet, creating one if it doesn't exist."""
    wallet = UserWallet.query.filter_by(user_id=user_id).first()
    if not wallet:
        wallet = UserWallet(user_id=user_id, wallet_balance=0, total_earnings=0)
        db.session.add(wallet)
        db.session.flush()
    return wallet


def credit(
    user_id: int,
    amount: int,
    category: str,
    reference: str = None,
    description: str = None,
    negotiation_id: int = None,
    payment_id: int = None,
) -> Transaction:
    """Credit (add money to) a user's wallet."""
    wallet = get_or_create_wallet(user_id)
    balance_before = wallet.wallet_balance

    wallet.wallet_balance += amount
    wallet.total_earnings += amount

    tx = Transaction(
        user_id=user_id,
        type='credit',
        category=category,
        amount=amount,
        balance_before=balance_before,
        balance_after=wallet.wallet_balance,
        reference=reference,
        description=description,
        status='completed',
        negotiation_id=negotiation_id,
        payment_id=payment_id,
    )
    db.session.add(tx)
    return tx


def debit(
    user_id: int,
    amount: int,
    category: str,
    reference: str = None,
    description: str = None,
    negotiation_id: int = None,
    payment_id: int = None,
) -> Transaction:
    """Debit (subtract money from) a user's wallet.

    Raises ValueError if insufficient balance.
    """
    wallet = get_or_create_wallet(user_id)
    if wallet.wallet_balance < amount:
        raise ValueError("Insufficient wallet balance")

    balance_before = wallet.wallet_balance
    wallet.wallet_balance -= amount

    tx = Transaction(
        user_id=user_id,
        type='debit',
        category=category,
        amount=amount,
        balance_before=balance_before,
        balance_after=wallet.wallet_balance,
        reference=reference,
        description=description,
        status='completed',
        negotiation_id=negotiation_id,
        payment_id=payment_id,
    )
    db.session.add(tx)
    return tx


def distribute_ride_payment(
    driver_id: int,
    amount: int,
    negotiation_id: int = None,
    payment_id: int = None,
    reference: str = None,
):
    """Credit the driver's wallet after a ride payment is confirmed."""
    return credit(
        user_id=driver_id,
        amount=amount,
        category='ride_earning',
        reference=reference,
        description=f'Ride payment received',
        negotiation_id=negotiation_id,
        payment_id=payment_id,
    )
