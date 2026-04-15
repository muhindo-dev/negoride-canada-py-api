from flask import Blueprint, request
from backend.models import db
from backend.models.user_wallet import UserWallet
from backend.models.transaction import Transaction
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

wallet_bp = Blueprint('wallet', __name__)


@wallet_bp.route('/api/wallet', methods=['GET'])
@jwt_required_with_user
def get_wallet(user):
    """Get or create user's wallet."""
    wallet = UserWallet.query.filter_by(user_id=user.id).first()
    if not wallet:
        wallet = UserWallet(user_id=user.id, wallet_balance=0, total_earnings=0)
        db.session.add(wallet)
        db.session.commit()

    return success_response("Success", wallet.to_dict())


@wallet_bp.route('/api/wallet/transactions', methods=['GET'])
@jwt_required_with_user
def transactions(user):
    """Get transaction history with optional filters."""
    category = request.args.get('category')
    tx_type = request.args.get('type')
    negotiation_id = request.args.get('negotiation_id')

    q = Transaction.query.filter_by(user_id=user.id)

    if category:
        q = q.filter_by(category=category)
    if tx_type:
        q = q.filter_by(type=tx_type)
    if negotiation_id:
        q = q.filter_by(negotiation_id=negotiation_id)

    txns = q.order_by(Transaction.created_at.desc()).all()
    return success_response("Success", [t.to_dict() for t in txns])


@wallet_bp.route('/api/wallet/summary', methods=['GET'])
@jwt_required_with_user
def summary(user):
    """Wallet + statistics + recent 5 transactions."""
    wallet = UserWallet.query.filter_by(user_id=user.id).first()
    if not wallet:
        wallet = UserWallet(user_id=user.id, wallet_balance=0, total_earnings=0)
        db.session.add(wallet)
        db.session.commit()

    from sqlalchemy import func

    total_credits = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter_by(
        user_id=user.id, type='credit'
    ).scalar()
    total_debits = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter_by(
        user_id=user.id, type='debit'
    ).scalar()
    total_transactions = Transaction.query.filter_by(user_id=user.id).count()
    ride_earnings = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter_by(
        user_id=user.id, type='credit', category='ride_earning'
    ).scalar()

    recent = Transaction.query.filter_by(user_id=user.id).order_by(
        Transaction.created_at.desc()
    ).limit(5).all()

    return success_response("Success", {
        'wallet': {
            'balance': wallet.wallet_balance,
            'total_earnings': wallet.total_earnings,
        },
        'statistics': {
            'total_credits': int(total_credits),
            'total_debits': int(total_debits),
            'total_transactions': total_transactions,
            'ride_earnings': int(ride_earnings),
        },
        'recent_transactions': [t.to_dict() for t in recent],
    })


@wallet_bp.route('/api/wallet/earnings', methods=['GET'])
@jwt_required_with_user
def earnings(user):
    """Earnings stats by period."""
    from sqlalchemy import func
    from datetime import datetime, timedelta

    period = request.args.get('period', 'all')
    now = datetime.utcnow()

    q = Transaction.query.filter_by(user_id=user.id, type='credit', category='ride_earning')

    if period == 'today':
        q = q.filter(func.date(Transaction.created_at) == now.date())
    elif period == 'week':
        q = q.filter(Transaction.created_at >= now - timedelta(days=7))
    elif period == 'month':
        q = q.filter(Transaction.created_at >= now - timedelta(days=30))
    elif period == 'year':
        q = q.filter(Transaction.created_at >= now - timedelta(days=365))

    total_earnings = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.user_id == user.id,
        Transaction.type == 'credit',
        Transaction.category == 'ride_earning',
    )

    # Apply same date filter
    if period == 'today':
        total_earnings = total_earnings.filter(func.date(Transaction.created_at) == now.date())
    elif period == 'week':
        total_earnings = total_earnings.filter(Transaction.created_at >= now - timedelta(days=7))
    elif period == 'month':
        total_earnings = total_earnings.filter(Transaction.created_at >= now - timedelta(days=30))
    elif period == 'year':
        total_earnings = total_earnings.filter(Transaction.created_at >= now - timedelta(days=365))

    total = total_earnings.scalar()
    trip_count = q.count()
    avg = int(total / trip_count) if trip_count > 0 else 0

    return success_response("Success", {
        'period': period,
        'total_earnings': int(total),
        'trip_count': trip_count,
        'average_per_trip': avg,
    })
