from flask import Blueprint, request
from backend.models import db
from backend.models.payout_request import PayoutRequest
from backend.models.payout_account import PayoutAccount
from backend.models.user_wallet import UserWallet
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

payout_requests_bp = Blueprint('payout_requests', __name__)


@payout_requests_bp.route('/api/payout-requests', methods=['GET'])
@jwt_required_with_user
def index(user):
    """List user's payout requests."""
    requests_list = PayoutRequest.query.filter_by(user_id=user.id).order_by(
        PayoutRequest.created_at.desc()
    ).all()
    return success_response("Success", [r.to_dict() for r in requests_list])


@payout_requests_bp.route('/api/payout-requests/statistics', methods=['GET'])
@jwt_required_with_user
def statistics(user):
    """Payout statistics."""
    from sqlalchemy import func

    base = PayoutRequest.query.filter_by(user_id=user.id)

    total_requests = base.count()
    pending_requests = base.filter_by(status='pending').count()
    completed_requests = base.filter_by(status='completed').count()
    failed_requests = base.filter_by(status='failed').count()

    total_paid = db.session.query(func.coalesce(func.sum(PayoutRequest.amount), 0)).filter_by(
        user_id=user.id, status='completed'
    ).scalar()
    total_fees = db.session.query(func.coalesce(func.sum(PayoutRequest.fee_amount), 0)).filter_by(
        user_id=user.id, status='completed'
    ).scalar()

    wallet = UserWallet.query.filter_by(user_id=user.id).first()
    available_balance = wallet.wallet_balance if wallet else 0

    pending_balance = db.session.query(func.coalesce(func.sum(PayoutRequest.amount), 0)).filter_by(
        user_id=user.id, status='pending'
    ).scalar()

    return success_response("Success", {
        'total_requests': total_requests,
        'pending_requests': pending_requests,
        'completed_requests': completed_requests,
        'failed_requests': failed_requests,
        'total_paid_out': int(total_paid),
        'total_fees_paid': int(total_fees),
        'available_balance': available_balance,
        'pending_balance': int(pending_balance),
    })


@payout_requests_bp.route('/api/payout-requests', methods=['POST'])
@jwt_required_with_user
def create(user):
    """Create a payout request."""
    data = request.get_json(silent=True) or request.form

    amount = data.get('amount')
    if amount is None:
        return error_response("Amount is required")
    amount = int(float(amount))
    if amount < 10:
        return error_response("Minimum payout is $0.10 (10 cents)")

    # Check active payout account
    account = PayoutAccount.query.filter_by(user_id=user.id, is_active=True).first()
    if not account:
        return error_response("No active payout account. Set up your payout account first.")

    # Check wallet balance
    wallet = UserWallet.query.filter_by(user_id=user.id).first()
    if not wallet or wallet.wallet_balance < amount:
        return error_response("Insufficient wallet balance")

    payout = PayoutRequest(
        user_id=user.id,
        payout_account_id=account.id,
        amount=amount,
        payout_method=data.get('payout_method', 'standard'),
        description=data.get('description'),
        status='pending',
    )
    db.session.add(payout)
    db.session.commit()

    return success_response("Payout request created", payout.to_dict(), status_code=201)


@payout_requests_bp.route('/api/payout-requests/<int:payout_id>', methods=['GET'])
@jwt_required_with_user
def show(user, payout_id):
    """Get single payout request."""
    payout = PayoutRequest.query.get(payout_id)
    if not payout or payout.user_id != user.id:
        return error_response("Payout request not found", status_code=404)

    return success_response("Success", payout.to_dict())


@payout_requests_bp.route('/api/payout-requests/<int:payout_id>/cancel', methods=['POST'])
@jwt_required_with_user
def cancel(user, payout_id):
    """Cancel a pending payout request."""
    payout = PayoutRequest.query.get(payout_id)
    if not payout or payout.user_id != user.id:
        return error_response("Payout request not found", status_code=404)

    if payout.status != 'pending':
        return error_response("Only pending payout requests can be cancelled")

    payout.status = 'cancelled'
    db.session.commit()

    return success_response("Payout request cancelled", payout.to_dict())


# Admin payout endpoints are in backend/routes/admin.py
