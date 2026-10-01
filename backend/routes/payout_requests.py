from datetime import datetime
from flask import Blueprint, request
from backend.models import db
from backend.models.payout_request import PayoutRequest
from backend.models.payout_account import PayoutAccount
from backend.models.user_wallet import UserWallet
from backend.services import wallet_service
from backend.utils.auth import jwt_required_with_user
from backend.utils.idempotency import idempotent
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
        'total_paid_out': float(total_paid or 0),
        'total_fees_paid': float(total_fees or 0),
        'available_balance': float(available_balance or 0),
        'pending_balance': float(pending_balance or 0),
    })


@payout_requests_bp.route('/api/payout-requests', methods=['POST'])
@jwt_required_with_user
@idempotent
def create(user):
    """Create a payout (withdrawal) request.

    Amount is in DOLLARS. The funds are RESERVED immediately: the wallet is debited
    atomically (row-locked) and a debit transaction is written, so a driver can never
    request more than their balance nor request the same balance twice. A cancel or an
    admin rejection refunds the reservation.
    """
    data = request.get_json(silent=True) or request.form

    raw = data.get('amount')
    if raw is None:
        return error_response("Amount is required")
    try:
        amount = wallet_service.money(raw)  # dollars, 2dp
    except Exception:
        return error_response("Invalid amount")
    if amount <= 0:
        return error_response("Amount must be greater than zero")

    # Payout account must be fully onboarded (Stripe active + payouts enabled).
    account = PayoutAccount.query.filter_by(user_id=user.id, status='active').first()
    if not account or not account.payouts_enabled:
        return error_response(
            "Your payout account isn't ready yet. Complete payout setup and verification first."
        )

    # Pay-later background-check fee (spec §14.3): recover it from the wallet first
    # (partial recovery allowed); a payout cannot leave a fronted fee unpaid.
    from backend.services import onboarding_service
    onboarding_service.settle_bgc_deductions(user.id)
    outstanding = onboarding_service.outstanding_deduction_cents(user.id)
    if outstanding > 0:
        return error_response(
            f"Your background check fee (${outstanding / 100:.2f} remaining) is recovered from your earnings "
            "before you can withdraw.",
            data={'error_code': 'bgc_fee_outstanding', 'outstanding_cents': outstanding}, status_code=409)

    min_payout = wallet_service.money(account.minimum_payout_amount or 10)
    if amount < min_payout:
        return error_response(f"Minimum payout is ${min_payout}")

    method = data.get('payout_method', 'standard')
    fee = wallet_service.money(0)  # standard payouts are free; instant fees (if any) set here
    net = wallet_service.money(amount - fee)

    payout = PayoutRequest(
        user_id=user.id,
        payout_account_id=account.id,
        amount=amount,
        fee_amount=fee,
        net_amount=net,
        currency=(account.default_currency or 'CAD'),
        payout_method=method,
        description=data.get('description'),
        status='pending',
        requested_at=datetime.utcnow(),
    )
    db.session.add(payout)
    db.session.flush()  # assign payout.id for the deterministic debit reference

    # Reserve the funds now (atomic, balance-checked, idempotent).
    try:
        wallet_service.debit(
            user.id, amount, 'withdrawal', f'withdrawal-{payout.id}',
            f'Withdrawal request #{payout.id}',
        )
    except ValueError as exc:
        db.session.rollback()
        return error_response(str(exc))

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
    payout.cancelled_at = datetime.utcnow()
    # Return the reserved funds to the wallet (idempotent on refund-<id>).
    wallet_service.refund_to_wallet(
        payout.user_id, payout.amount, f'refund-{payout.id}',
        f'Refund for cancelled withdrawal #{payout.id}',
    )
    db.session.commit()

    return success_response("Payout request cancelled", payout.to_dict())


# Admin payout endpoints are in backend/routes/admin.py
