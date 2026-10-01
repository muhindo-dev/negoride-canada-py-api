from datetime import datetime, timedelta
from flask import Blueprint, request
from sqlalchemy import func, or_
from backend.models import db
from backend.models.user import AdminUser
from backend.models.negotiation import Negotiation
from backend.models.negotiation_record import NegotiationRecord
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.payment import Payment
from backend.models.transaction import Transaction
from backend.models.payout_request import PayoutRequest
from backend.models.payout_account import PayoutAccount
from backend.models.user_wallet import UserWallet
from backend.models.chat_head import ChatHead
from backend.models.chat_message import ChatMessage
from backend.models.company import Company
from backend.models.route_stage import RouteStage
from backend.utils.auth import admin_required, admin_role_required
from backend.utils.response import success_response, error_response

admin_bp = Blueprint('admin', __name__)


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD & ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/dashboard', methods=['GET'])
@admin_required
def dashboard(user):
    """Admin dashboard with comprehensive statistics."""
    total_users = AdminUser.query.filter(AdminUser.deleted_at.is_(None)).count()
    total_customers = AdminUser.query.filter_by(user_type='Customer').filter(AdminUser.deleted_at.is_(None)).count()
    total_drivers = AdminUser.query.filter_by(user_type='Driver').filter(AdminUser.deleted_at.is_(None)).count()
    approved_drivers = AdminUser.query.filter(
        AdminUser.user_type == 'Driver',
        AdminUser.status == 1,
        AdminUser.deleted_at.is_(None)
    ).count()
    pending_drivers = AdminUser.query.filter_by(user_type='Pending Driver').count()
    online_drivers = AdminUser.query.filter(
        AdminUser.user_type == 'Driver',
        AdminUser.ready_for_trip == 'Yes'
    ).count()

    total_negotiations = Negotiation.query.count()
    active_negotiations = Negotiation.query.filter(
        Negotiation.status.in_(['Pending', 'Accepted', 'Started'])
    ).count()

    active_trips = Trip.query.filter(
        Trip.status.in_(['Active', 'Ongoing', 'Started', 'Pending'])
    ).count()
    completed_trips = Trip.query.filter_by(status='Completed').count()

    total_bookings = ScheduledBooking.query.count()
    pending_bookings = ScheduledBooking.query.filter_by(status='pending').count()

    total_revenue = db.session.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(Payment.status == 'succeeded').scalar()

    total_payments = Payment.query.count()
    pending_payouts = PayoutRequest.query.filter_by(status='pending').count()

    recent = Trip.query.order_by(Trip.created_at.desc()).limit(10).all()

    return success_response("Success", {
        'total_users': total_users,
        'total_customers': total_customers,
        'total_drivers': total_drivers,
        'approved_drivers': approved_drivers,
        'pending_drivers': pending_drivers,
        'online_drivers': online_drivers,
        'total_negotiations': total_negotiations,
        'active_negotiations': active_negotiations,
        'active_trips': active_trips,
        'completed_trips': completed_trips,
        'total_bookings': total_bookings,
        'pending_bookings': pending_bookings,
        'total_revenue': float(total_revenue),
        'total_payments': total_payments,
        'pending_payouts': pending_payouts,
        'recent_trips': [t.to_dict() for t in recent],
    })


@admin_bp.route('/api/admin/analytics', methods=['GET'])
@admin_required
def analytics(user):
    """Detailed analytics with time-based stats."""
    now = datetime.utcnow()
    period = request.args.get('period', 'month')

    if period == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start = now - timedelta(days=7)
    elif period == 'month':
        start = now - timedelta(days=30)
    elif period == 'year':
        start = now - timedelta(days=365)
    else:
        start = None

    user_q = AdminUser.query
    if start:
        user_q = user_q.filter(AdminUser.created_at >= start)
    new_users = user_q.count()
    new_drivers = user_q.filter_by(user_type='Driver').count()
    new_customers = user_q.filter_by(user_type='Customer').count()

    neg_q = Negotiation.query
    if start:
        neg_q = neg_q.filter(Negotiation.created_at >= start)
    new_negotiations = neg_q.count()
    completed_negotiations = neg_q.filter_by(status='Completed').count()
    cancelled_negotiations = neg_q.filter_by(status='Cancelled').count()

    pay_q = db.session.query(func.coalesce(func.sum(Payment.amount), 0))
    if start:
        pay_q = pay_q.filter(Payment.created_at >= start)
    revenue = pay_q.filter(Payment.status == 'succeeded').scalar()

    pay_count_q = Payment.query
    if start:
        pay_count_q = pay_count_q.filter(Payment.created_at >= start)
    payment_count = pay_count_q.filter(Payment.status == 'succeeded').count()

    book_q = ScheduledBooking.query
    if start:
        book_q = book_q.filter(ScheduledBooking.created_at >= start)
    new_bookings = book_q.count()
    completed_bookings = book_q.filter_by(status='completed').count()

    trip_q = Trip.query
    if start:
        trip_q = trip_q.filter(Trip.created_at >= start)
    new_trips = trip_q.count()

    return success_response("Success", {
        'period': period,
        'users': {'new_users': new_users, 'new_drivers': new_drivers, 'new_customers': new_customers},
        'negotiations': {'total': new_negotiations, 'completed': completed_negotiations, 'cancelled': cancelled_negotiations},
        'revenue': {'total': float(revenue), 'payment_count': payment_count},
        'bookings': {'total': new_bookings, 'completed': completed_bookings},
        'trips': {'total': new_trips},
    })


@admin_bp.route('/api/admin/revenue-chart', methods=['GET'])
@admin_required
def revenue_chart(user):
    """Revenue data grouped by day for charts."""
    days = int(request.args.get('days', 30))
    now = datetime.utcnow()
    start = now - timedelta(days=days)

    results = db.session.query(
        func.date(Payment.created_at).label('date'),
        func.sum(Payment.amount).label('revenue'),
        func.count(Payment.id).label('count')
    ).filter(
        Payment.status == 'succeeded',
        Payment.created_at >= start
    ).group_by(func.date(Payment.created_at)).order_by(func.date(Payment.created_at)).all()

    chart_data = [{'date': str(r.date), 'revenue': float(r.revenue or 0), 'count': r.count} for r in results]
    return success_response("Success", chart_data)


@admin_bp.route('/api/admin/user-growth', methods=['GET'])
@admin_required
def user_growth(user):
    """User registration data grouped by day for charts."""
    days = int(request.args.get('days', 30))
    now = datetime.utcnow()
    start = now - timedelta(days=days)

    results = db.session.query(
        func.date(AdminUser.created_at).label('date'),
        func.count(AdminUser.id).label('count')
    ).filter(AdminUser.created_at >= start).group_by(
        func.date(AdminUser.created_at)
    ).order_by(func.date(AdminUser.created_at)).all()

    chart_data = [{'date': str(r.date), 'count': r.count} for r in results]
    return success_response("Success", chart_data)


# ═══════════════════════════════════════════════════════════════════════════
# USERS MANAGEMENT (FULL CRUD)
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/users', methods=['GET'])
@admin_required
def users_index(user):
    """List all users with search, filter, and pagination."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    user_type = request.args.get('user_type')
    search = request.args.get('search')
    status = request.args.get('status')
    sort_by = request.args.get('sort_by', 'created_at')
    sort_order = request.args.get('sort_order', 'desc')

    q = AdminUser.query
    if user_type:
        q = q.filter_by(user_type=user_type)
    if status is not None:
        q = q.filter_by(status=int(status))
    account_status = request.args.get('account_status')
    if account_status == 'active':
        q = q.filter(or_(AdminUser.account_status == 'active',
                         db.and_(AdminUser.account_status.is_(None), AdminUser.status == 1)))
    elif account_status:
        q = q.filter(AdminUser.account_status == account_status)
    if search:
        search_term = f'%{search}%'
        q = q.filter(or_(
            AdminUser.name.ilike(search_term),
            AdminUser.email.ilike(search_term),
            AdminUser.phone_number.ilike(search_term),
            AdminUser.username.ilike(search_term),
        ))

    col = getattr(AdminUser, sort_by, AdminUser.created_at)
    q = q.order_by(col.desc() if sort_order == 'desc' else col.asc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    return success_response("Success", {
        'data': [u.to_dict() for u in pagination.items],
        'total': pagination.total,
        'current_page': pagination.page,
        'last_page': pagination.pages,
        'per_page': per_page,
    })


@admin_bp.route('/api/admin/users/<int:user_id>', methods=['GET'])
@admin_required
def users_show(user, user_id):
    """Get detailed user info including wallet and activity."""
    target = AdminUser.query.get(user_id)
    if not target:
        return error_response("User not found", status_code=404)

    user_data = target.to_dict()
    wallet = UserWallet.query.filter_by(user_id=user_id).first()
    user_data['wallet'] = wallet.to_dict() if wallet else None

    payout = PayoutAccount.query.filter_by(user_id=user_id).first()
    user_data['payout_account'] = payout.to_dict() if payout else None

    user_data['negotiation_count'] = Negotiation.query.filter(
        or_(Negotiation.customer_id == user_id, Negotiation.driver_id == user_id)
    ).count()
    user_data['trip_count'] = Trip.query.filter(
        or_(Trip.driver_id == user_id, Trip.customer_id == user_id)
    ).count()
    user_data['booking_count'] = ScheduledBooking.query.filter(
        or_(ScheduledBooking.customer_id == user_id, ScheduledBooking.driver_id == user_id)
    ).count()

    return success_response("Success", user_data)


@admin_bp.route('/api/admin/users/<int:user_id>/update', methods=['POST', 'PUT'])
@admin_role_required('super_admin', 'ops')
def users_update(user, user_id):
    """Compatibility wrapper; sensitive account edits use the strict V4 profile API."""
    target = AdminUser.query.get(user_id)
    if not target:
        return error_response("User not found", status_code=404)

    data = request.get_json(silent=True) or request.form
    from backend.routes.admin_identity import PROFILE_EDIT_FIELDS
    allowed = set(PROFILE_EDIT_FIELDS) | {'marketing_opt_in', 'reason_text'}
    if set(data) - allowed:
        return error_response("Use the dedicated account workflow for status, driver approval, roles, and finance changes.",
                              data={'error_code': 'field_not_editable'}, status_code=400)
    return error_response("Use the V4 user profile editor for audited profile changes.",
                          data={'error_code': 'use_v4_profile'}, status_code=410)


@admin_bp.route('/api/admin/users/<int:user_id>/reset-password', methods=['POST'])
@admin_role_required('super_admin', 'ops')
def users_reset_password(user, user_id):
    """Compatibility alias for sending a secure one-time reset link."""
    return error_response("Use the V4 password reset link action; admins cannot set a user's password.",
                          data={'error_code': 'use_v4_reset_link'}, status_code=410)


@admin_bp.route('/api/admin/users/<int:user_id>/approve-driver', methods=['POST'])
@admin_role_required('super_admin', 'ops', 'safety_reviewer')
def approve_driver(user, user_id):
    """Approve a pending driver application.
    
    Optional POST body:
      services: list of service keys to approve e.g. ["car", "delivery"]
                If omitted, approves whatever is_* flags are set to 'Yes'.
                If none are set, defaults to approving 'car'.
    """
    target = AdminUser.query.get(user_id)
    if not target:
        return error_response("User not found", status_code=404)

    target.user_type = 'Driver'
    target.status = 1

    body = request.get_json(silent=True) or {}
    all_svcs = ['car', 'boda', 'ambulance', 'police', 'delivery', 'breakdown', 'firebrugade']

    # Admin may explicitly pass which services to approve
    requested = body.get('services') or []
    if requested:
        # Admin chose specific services — mark those as Yes + Approved
        for svc in all_svcs:
            if svc in requested:
                setattr(target, f'is_{svc}', 'Yes')
                setattr(target, f'is_{svc}_approved', 'Yes')
            else:
                setattr(target, f'is_{svc}_approved', 'No')
    else:
        # Auto-approve whatever the driver applied for
        any_approved = False
        for svc in all_svcs:
            if getattr(target, f'is_{svc}') == 'Yes':
                setattr(target, f'is_{svc}_approved', 'Yes')
                any_approved = True
        # Fallback: if driver never filled services, default to car
        if not any_approved:
            target.is_car = 'Yes'
            target.is_car_approved = 'Yes'

    target.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Driver approved", target.to_dict())


@admin_bp.route('/api/admin/users/<int:user_id>/reject-driver', methods=['POST'])
@admin_role_required('super_admin', 'ops', 'safety_reviewer')
def reject_driver(user, user_id):
    """Reject a pending driver application."""
    target = AdminUser.query.get(user_id)
    if not target:
        return error_response("User not found", status_code=404)
    target.user_type = 'Customer'
    target.status = 1
    # Clear all service approval flags on rejection
    for svc in ['car', 'boda', 'ambulance', 'police', 'delivery', 'breakdown', 'firebrugade']:
        setattr(target, f'is_{svc}_approved', 'No')
    target.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Driver application rejected", target.to_dict())


@admin_bp.route('/api/admin/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_role_required('super_admin', 'ops', 'safety_reviewer', 'support')
def toggle_status(user, user_id):
    """Activate/deactivate a user."""
    target = AdminUser.query.get(user_id)
    if not target:
        return error_response("User not found", status_code=404)
    from backend.services import account_service
    data = request.get_json(silent=True) or request.form or {}
    bad = account_service.validate_admin_reason(data)
    if bad is not None:
        return error_response(bad[0], data={'error_code': bad[1]})
    want = 'active' if not target.is_account_active() else 'deactivated'
    res = account_service.set_status(target, want, actor=user, reason_code=data.get('reason_code'),
                                     reason_text=str(data.get('reason_text')).strip(), source='admin:legacy_toggle')
    payload = target.to_dict()
    payload['status_change'] = res   # {applied, deferred, account_status, ...}
    msg = ("Deactivation scheduled — it applies when the user's current ride ends"
           if res and res.get('deferred') else "Status updated")
    return success_response(msg, payload)


@admin_bp.route('/api/admin/users/<int:user_id>/delete', methods=['POST', 'DELETE'])
@admin_role_required('super_admin', 'ops')
def users_delete(user, user_id):
    """Soft-delete a user only after an audited, reasoned admin action."""
    target = AdminUser.query.get(user_id)
    if not target:
        return error_response("User not found", status_code=404)
    if target.id == user.id:
        return error_response("Cannot delete yourself")
    data = request.get_json(silent=True) or request.form or {}
    reason = str(data.get('reason_text') or data.get('reason') or '').strip()
    if len(reason) < 5:
        return error_response("A reason of at least 5 characters is required", data={'error_code': 'reason_required'})
    from backend.services import account_service as A
    _, active_ride = A.active_ride(target)
    if active_ride is not None:
        return error_response("This user has an active ride. Deactivate the account after the ride ends.",
                              data={'error_code': 'active_ride'}, status_code=409)
    from backend.services.audit import audit
    before = {'deleted_at': str(target.deleted_at) if target.deleted_at else None,
              'account_status': target.effective_account_status(), 'token_version': target.token_version}
    target.deleted_at = datetime.utcnow()
    target.status = 0
    target.account_status = 'deactivated'
    target.token_version = (target.token_version or 0) + 1   # revoke every session
    target.ready_for_trip = 'No'
    target.updated_at = datetime.utcnow()
    audit('admin.user_soft_deleted', user, 'user', target.id, before=before,
          after={'deleted_at': str(target.deleted_at), 'account_status': target.effective_account_status(),
                 'token_version': target.token_version}, meta={'reason': reason})
    db.session.commit()
    return success_response("User deleted")


@admin_bp.route('/api/admin/users/<int:user_id>/wallet', methods=['GET'])
@admin_role_required('super_admin', 'finance')
def users_wallet(user, user_id):
    """Get user's wallet and recent transactions."""
    wallet = UserWallet.query.filter_by(user_id=user_id).first()
    transactions = Transaction.query.filter_by(user_id=user_id).order_by(
        Transaction.created_at.desc()
    ).limit(50).all()
    return success_response("Success", {
        'wallet': wallet.to_dict() if wallet else {'wallet_balance': 0, 'total_earnings': 0},
        'transactions': [t.to_dict() for t in transactions],
    })


@admin_bp.route('/api/admin/users/<int:user_id>/wallet/adjust', methods=['POST'])
@admin_role_required('super_admin', 'finance')
def users_wallet_adjust(user, user_id):
    """Admin adjusts user's wallet balance."""
    import math
    import uuid
    data = request.get_json(silent=True) or request.form
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return error_response("Amount must be a valid number")
    tx_type = data.get('type', 'credit')
    reason = str(data.get('reason') or '').strip()

    if not math.isfinite(amount) or amount <= 0:
        return error_response("Amount must be a finite positive number")
    if tx_type not in ('credit', 'debit'):
        return error_response("Type must be 'credit' or 'debit'")
    if len(reason) < 5:
        return error_response("A reason of at least 5 characters is required", data={'error_code': 'reason_required'})

    wallet = UserWallet.query.filter_by(user_id=user_id).first()
    if not wallet:
        wallet = UserWallet(user_id=user_id, wallet_balance=0, total_earnings=0)
        db.session.add(wallet)
        db.session.flush()

    balance_before = float(wallet.wallet_balance or 0)
    if tx_type == 'credit':
        wallet.wallet_balance = balance_before + amount
    else:
        if balance_before < amount:
            return error_response("Insufficient balance for debit")
        wallet.wallet_balance = balance_before - amount

    target_user = AdminUser.query.get(user_id)
    tx = Transaction(
        user_id=user_id,
        user_type='driver' if target_user and target_user.user_type == 'Driver' else 'customer',
        type=tx_type,
        category='bonus' if tx_type == 'credit' else 'penalty',
        amount=amount,
        balance_before=balance_before,
        balance_after=float(wallet.wallet_balance),
        reference=f'admin-adj-{uuid.uuid4().hex[:12]}',
        description=f'Admin adjustment: {reason}',
        status='completed',
    )
    db.session.add(tx)
    db.session.flush()
    from backend.services.audit import audit
    audit('admin.user_wallet_adjusted', user, 'user', user_id,
          before={'wallet_balance': balance_before},
          after={'wallet_balance': float(wallet.wallet_balance), 'adjustment': amount, 'type': tx_type},
          meta={'reason': reason, 'transaction_id': tx.id})
    db.session.commit()
    return success_response("Wallet adjusted", {
        'wallet': wallet.to_dict(),
        'transaction': tx.to_dict(),
    })


# ═══════════════════════════════════════════════════════════════════════════
# NEGOTIATIONS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/negotiations', methods=['GET'])
@admin_required
def negotiations_index(user):
    """List all negotiations with search and filter."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    status = request.args.get('status')
    search = request.args.get('search')
    payment_status = request.args.get('payment_status')

    q = Negotiation.query
    if status:
        q = q.filter_by(status=status)
    if payment_status:
        q = q.filter_by(payment_status=payment_status)
    if search:
        search_term = f'%{search}%'
        q = q.filter(or_(
            Negotiation.customer_name.ilike(search_term),
            Negotiation.driver_name.ilike(search_term),
            Negotiation.pickup_address.ilike(search_term),
            Negotiation.dropoff_address.ilike(search_term),
        ))

    pagination = q.order_by(Negotiation.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return success_response("Success", {
        'data': [n.to_dict() for n in pagination.items],
        'total': pagination.total,
        'current_page': pagination.page,
        'last_page': pagination.pages,
        'per_page': per_page,
    })


@admin_bp.route('/api/admin/negotiations/<int:neg_id>', methods=['GET'])
@admin_required
def negotiations_show(user, neg_id):
    """Get negotiation detail with records and payment."""
    neg = Negotiation.query.get(neg_id)
    if not neg:
        return error_response("Negotiation not found", status_code=404)

    data = neg.to_dict()
    records = NegotiationRecord.query.filter_by(negotiation_id=neg_id).order_by(
        NegotiationRecord.created_at.asc()
    ).all()
    data['records_list'] = [r.to_dict() for r in records]

    payment = Payment.query.filter_by(negotiation_id=neg_id).first()
    data['payment'] = payment.to_dict() if payment else None

    customer = AdminUser.query.get(neg.customer_id) if neg.customer_id else None
    driver = AdminUser.query.get(neg.driver_id) if neg.driver_id else None
    data['customer'] = customer.to_dict() if customer else None
    data['driver'] = driver.to_dict() if driver else None
    return success_response("Success", data)


@admin_bp.route('/api/admin/negotiations/<int:neg_id>/update-status', methods=['POST'])
@admin_required
def negotiations_update_status(user, neg_id):
    """Admin sets a negotiation's legacy status. Routed through the v4 state
    machine (one trip_event per step, actor admin, reason required) — never a
    raw column write. 'Cancelled' applies the §7 cancellation policy."""
    neg = Negotiation.query.get(neg_id)
    if not neg:
        return error_response("Negotiation not found", status_code=404)
    data = _legacy_body()
    new_status = data.get('status')
    valid_statuses = ['Pending', 'Accepted', 'Started', 'Completed', 'Cancelled']
    if new_status not in valid_statuses:
        return error_response(f"Status must be one of: {', '.join(valid_statuses)}")
    return _legacy_set_status(user, 'carhire', neg_id, new_status, data, "Negotiation status updated")


@admin_bp.route('/api/admin/negotiations/<int:neg_id>/cancel', methods=['POST'])
@admin_required
def negotiations_cancel(user, neg_id):
    """Admin cancels a negotiation (state machine + refund policy + notifications)."""
    if not Negotiation.query.get(neg_id):
        return error_response("Negotiation not found", status_code=404)
    return _legacy_cancel(user, 'carhire', neg_id, _legacy_body(), "Negotiation cancelled")


# ═══════════════════════════════════════════════════════════════════════════
# TRIPS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/trips', methods=['GET'])
@admin_required
def trips_index(user):
    """List all trips with search and filter."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    status = request.args.get('status')
    search = request.args.get('search')
    driver_id = request.args.get('driver_id')

    q = Trip.query
    if status:
        q = q.filter_by(status=status)
    if driver_id:
        q = q.filter_by(driver_id=int(driver_id))
    if search:
        search_term = f'%{search}%'
        q = q.filter(or_(
            Trip.start_name.ilike(search_term),
            Trip.end_name.ilike(search_term),
            Trip.car_model.ilike(search_term),
            Trip.vehicel_reg_number.ilike(search_term),
        ))

    pagination = q.order_by(Trip.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return success_response("Success", {
        'data': [t.to_dict() for t in pagination.items],
        'total': pagination.total,
        'current_page': pagination.page,
        'last_page': pagination.pages,
        'per_page': per_page,
    })


@admin_bp.route('/api/admin/trips/<int:trip_id>', methods=['GET'])
@admin_required
def trips_show(user, trip_id):
    """Get trip detail with bookings."""
    trip = Trip.query.get(trip_id)
    if not trip:
        return error_response("Trip not found", status_code=404)

    data = trip.to_dict()
    bookings = TripBooking.query.filter_by(trip_id=trip_id).all()
    data['bookings'] = [b.to_dict() for b in bookings]

    driver = AdminUser.query.get(trip.driver_id) if trip.driver_id else None
    data['driver'] = driver.to_dict() if driver else None
    return success_response("Success", data)


@admin_bp.route('/api/admin/trips/<int:trip_id>/update-status', methods=['POST'])
@admin_required
def trips_update_status(user, trip_id):
    """Admin sets a rideshare trip's legacy status through the state machine."""
    if not Trip.query.get(trip_id):
        return error_response("Trip not found", status_code=404)
    data = _legacy_body()
    new_status = data.get('status')
    valid = ['Active', 'Ongoing', 'Started', 'Completed', 'Canceled', 'Cancelled']
    if new_status not in valid:
        return error_response(f"Status must be one of: {', '.join(valid)}")
    return _legacy_set_status(user, 'rideshare_trip', trip_id, new_status, data, "Trip status updated")


@admin_bp.route('/api/admin/trips/<int:trip_id>/cancel', methods=['POST'])
@admin_required
def trips_cancel(user, trip_id):
    """Admin cancels a rideshare trip: CANCELLED_BY_DRIVER cascade — every
    passenger is cancelled and refunded 100 %."""
    if not Trip.query.get(trip_id):
        return error_response("Trip not found", status_code=404)
    return _legacy_cancel(user, 'rideshare_trip', trip_id, _legacy_body(), "Trip cancelled")


# ═══════════════════════════════════════════════════════════════════════════
# BOOKINGS MANAGEMENT (SCHEDULED BOOKINGS)
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/bookings', methods=['GET'])
@admin_required
def bookings_index(user):
    """List all scheduled bookings with search and filter."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    status = request.args.get('status')
    search = request.args.get('search')
    payment_status = request.args.get('payment_status')

    q = ScheduledBooking.query
    if status:
        q = q.filter_by(status=status)
    if payment_status:
        q = q.filter_by(payment_status=payment_status)
    if search:
        search_term = f'%{search}%'
        q = q.filter(or_(
            ScheduledBooking.pickup_address.ilike(search_term),
            ScheduledBooking.destination_address.ilike(search_term),
            ScheduledBooking.pickup_place_name.ilike(search_term),
            ScheduledBooking.destination_place_name.ilike(search_term),
        ))

    pagination = q.order_by(ScheduledBooking.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return success_response("Success", {
        'data': [b.to_dict() for b in pagination.items],
        'total': pagination.total,
        'current_page': pagination.page,
        'last_page': pagination.pages,
        'per_page': per_page,
    })


@admin_bp.route('/api/admin/bookings/<int:booking_id>', methods=['GET'])
@admin_required
def bookings_show(user, booking_id):
    """Get booking detail."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)
    data = booking.to_dict()
    customer = AdminUser.query.get(booking.customer_id) if booking.customer_id else None
    driver = AdminUser.query.get(booking.driver_id) if booking.driver_id else None
    data['customer'] = customer.to_dict() if customer else None
    data['driver'] = driver.to_dict() if driver else None
    return success_response("Success", data)


@admin_bp.route('/api/admin/bookings/<int:booking_id>/update-status', methods=['POST'])
@admin_required
def bookings_update_status(user, booking_id):
    """Admin sets a scheduled booking's legacy status through the state machine."""
    if not ScheduledBooking.query.get(booking_id):
        return error_response("Booking not found", status_code=404)
    data = _legacy_body()
    new_status = data.get('status')
    valid = ['pending', 'price_negotiating', 'price_accepted', 'driver_assigned', 'confirmed', 'in_progress',
             'completed', 'cancelled']
    if new_status not in valid:
        return error_response(f"Status must be one of: {', '.join(valid)}")
    return _legacy_set_status(user, 'scheduled', booking_id, new_status, data, "Booking status updated")


@admin_bp.route('/api/admin/bookings/<int:booking_id>/assign-driver', methods=['POST'])
@admin_required
def bookings_assign_driver(user, booking_id):
    """Admin assigns (or reassigns) the driver — same rules as the v4
    POST /api/admin/rides/scheduled/{id}/reassign (before pickup only, approved
    active driver, audited, parties notified). A reason is required when
    replacing an already-assigned driver."""
    from backend.services import ride_actions as RA
    from backend.services import trip_state_machine as TSM
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)
    data = _legacy_body()
    reason = (data.get('reason') or '').strip()
    if booking.driver_id and len(reason) < 5:
        return error_response('A reason is required to replace the assigned driver.',
                              data={'error_code': 'reason_required'})
    try:
        RA.reassign_driver('scheduled', booking_id, data.get('driver_id'), user,
                           reason or 'Driver assigned from the admin bookings page')
    except TSM.TransitionError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    db.session.expire_all()
    return success_response("Driver assigned", ScheduledBooking.query.get(booking_id).to_dict())


@admin_bp.route('/api/admin/bookings/<int:booking_id>/cancel', methods=['POST'])
@admin_required
def bookings_cancel(user, booking_id):
    """Admin cancels a scheduled booking (state machine + refund policy)."""
    if not ScheduledBooking.query.get(booking_id):
        return error_response("Booking not found", status_code=404)
    return _legacy_cancel(user, 'scheduled', booking_id, _legacy_body(), "Booking cancelled")


@admin_bp.route('/api/admin/bookings/<int:booking_id>/mark-paid', methods=['POST'])
@admin_required
def bookings_mark_paid(user, booking_id):
    """Admin marks a booking paid outside Stripe (cash, e-transfer, comp):
    records an offline RidePayment (provider 'offline', captured) and confirms
    the booking through the state machine. Body: {amount_cents?, reason}."""
    from backend.services import trip_state_machine as TSM
    from backend.services.audit import audit
    from backend.services.payments import payment_service as PS
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)
    data = _legacy_body()
    reason = (data.get('reason') or data.get('note') or '').strip()
    if len(reason) < 5:
        return error_response('A reason is required (e.g. "Paid cash at the office").',
                              data={'error_code': 'reason_required'})
    TSM.ensure_stage('scheduled', booking)
    stage = booking.trip_stage
    if stage not in ('REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT'):
        return error_response(f'A booking in stage {stage} cannot be marked paid.',
                              data={'error_code': 'bad_stage', 'stage': stage}, status_code=409)
    try:
        rp = PS.record_offline_payment('scheduled', booking, user, data.get('amount_cents'), note=reason)
        if not booking.agreed_price:
            booking.agreed_price = rp.fare_cents
        db.session.flush()
        TSM.walk_to('scheduled', booking_id, 'CONFIRMED', actor=user, actor_type='admin', legacy=False,
                    meta={'admin_reason': reason, 'ride_payment_id': rp.id, 'offline_payment': True})
    except PS.PaymentError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    except TSM.TransitionError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code, **e.data}, status_code=e.status)
    audit('ride.admin_mark_paid', user, 'scheduled', booking_id, before={'stage': stage},
          after={'stage': 'CONFIRMED', 'ride_payment_id': rp.id, 'amount_cents': rp.amount_captured_cents},
          meta={'reason': reason})
    db.session.commit()
    db.session.expire_all()
    return success_response("Marked as paid", ScheduledBooking.query.get(booking_id).to_dict())


# ── legacy admin → state machine helpers ────────────────────────────────────

def _legacy_body():
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict() if request.form else {}
    return data or {}


# legacy status → target v4 stage, per ride type (None = cancel through the policy)
_LEGACY_TARGET = {
    'carhire': {'Pending': 'NEGOTIATING', 'Accepted': 'PRICE_AGREED', 'Started': 'IN_PROGRESS',
                'Completed': 'COMPLETED', 'Cancelled': None},
    'scheduled': {'pending': 'REQUESTED', 'price_negotiating': 'NEGOTIATING', 'price_accepted': 'PRICE_AGREED',
                  'driver_assigned': 'PRICE_AGREED', 'confirmed': 'CONFIRMED', 'in_progress': 'IN_PROGRESS',
                  'completed': 'COMPLETED', 'cancelled': None},
    'rideshare_trip': {'Active': 'PUBLISHED', 'Ongoing': 'IN_PROGRESS', 'Started': 'IN_PROGRESS',
                       'Completed': 'COMPLETED', 'Canceled': None, 'Cancelled': None},
}


def _legacy_set_status(admin, ride_type, ride_id, new_status, data, message):
    """Map a legacy status to its v4 stage and walk there as admin. Returns the
    legacy response shape (the row's to_dict()) or a clear error."""
    from backend.services import rides as R
    from backend.services import trip_state_machine as TSM
    from backend.services.audit import audit
    target = _LEGACY_TARGET[ride_type].get(new_status, 'unknown')
    if target is None:
        return _legacy_cancel(admin, ride_type, ride_id, data, message)
    reason = (data.get('reason') or '').strip()
    if len(reason) < 5:
        return error_response('A reason (at least 5 characters) is required for admin status changes.',
                              data={'error_code': 'reason_required'})
    ride = R.load(ride_type, ride_id)
    stage = TSM.ensure_stage(ride_type, ride)
    if ride_type == 'carhire' and new_status == 'Accepted' and TSM.payment_secured(ride_type, ride):
        target = 'CONFIRMED'
    before = {'stage': stage, 'status': ride.status}
    # No-op only when already there, or when the ride is already past the target
    # with the same legacy status (e.g. 'Accepted' on a CONFIRMED ride). A ride at
    # DRIVER_ARRIVED also reads 'Started', but admin 'Started' must still move it
    # forward to IN_PROGRESS.
    same_legacy = TSM.legacy_status(ride_type, stage, ride.status) == new_status
    if stage == target or (same_legacy and TSM.shortest_path(ride_type, stage, target) is None):
        db.session.commit()
        return success_response(message, R.load(ride_type, ride_id).to_dict())
    if target in TSM.PAYMENT_GATED.get(ride_type, ()) and S_flag('pay_before_trip') \
            and not TSM.payment_secured(ride_type, ride):
        return error_response('This ride is not paid. Mark it paid (offline payment) or let the customer pay '
                              'before moving it on.', data={'error_code': 'payment_required', 'stage': stage},
                              status_code=402)
    if TSM.is_terminal(ride_type, stage):
        return error_response(f'The ride is already {stage} and cannot change.',
                              data={'error_code': 'terminal', 'stage': stage}, status_code=409)
    try:
        TSM.walk_to(ride_type, ride_id, target, actor=admin, actor_type='admin', legacy=False,
                    meta={'admin_reason': reason, 'legacy_admin_status': new_status})
    except TSM.TransitionError as e:
        db.session.rollback()
        return error_response(f'{e.message} Use a status the ride can reach from {stage}.',
                              data={'error_code': e.code, 'stage': stage, **e.data}, status_code=e.status)
    ride = R.load(ride_type, ride_id)
    audit('ride.admin_legacy_status', admin, ride_type, ride_id, before=before,
          after={'stage': ride.trip_stage, 'status': ride.status}, meta={'reason': reason, 'status': new_status})
    db.session.commit()
    return success_response(message, R.load(ride_type, ride_id).to_dict())


def _legacy_cancel(admin, ride_type, ride_id, data, message):
    """Admin cancellation: ride_actions.cancel(actor_type='admin') — refund policy,
    terminal stage, hold released / refund in a job, parties notified."""
    from backend.services import ride_actions as RA
    from backend.services import rides as R
    from backend.services import trip_state_machine as TSM
    from backend.services.audit import audit
    reason = (data.get('reason') or data.get('note') or '').strip()
    if len(reason) < 5:
        return error_response('A cancellation reason (at least 5 characters) is required.',
                              data={'error_code': 'reason_required'})
    policy_reason = data.get('policy_reason') or 'customer_cancel'
    if policy_reason not in ('customer_cancel', 'driver_cancel', 'safety', 'expired', 'driver_no_show'):
        return error_response('Invalid policy_reason', data={'error_code': 'bad_policy_reason'})
    try:
        before = R.load(ride_type, ride_id)
        before = {'stage': TSM.ensure_stage(ride_type, before), 'status': before.status}
        result, decision = RA.cancel(ride_type, ride_id, actor=admin, actor_type='admin', reason=policy_reason,
                                     reason_code='admin', note=reason, commit=False)
        audit('ride.admin_cancel', admin, ride_type, ride_id, before=before,
              after={'stage': result.to_stage, 'status': result.ride.status},
              meta={'reason': reason, 'policy': decision.to_dict() if decision else None, 'legacy_admin': True})
        db.session.commit()
    except TSM.TransitionError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code, **e.data}, status_code=e.status)
    return success_response(message, R.load(ride_type, ride_id).to_dict())


def S_flag(name):
    from backend.services import settings_service as S
    return S.flag(name)


# ═══════════════════════════════════════════════════════════════════════════
# TRIP BOOKINGS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/trip-bookings', methods=['GET'])
@admin_required
def trip_bookings_index(user):
    """List all trip bookings."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    status = request.args.get('status')
    trip_id = request.args.get('trip_id')

    q = TripBooking.query
    if status:
        q = q.filter_by(status=status)
    if trip_id:
        q = q.filter_by(trip_id=int(trip_id))

    pagination = q.order_by(TripBooking.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return success_response("Success", {
        'data': [b.to_dict() for b in pagination.items],
        'total': pagination.total,
        'current_page': pagination.page,
        'last_page': pagination.pages,
        'per_page': per_page,
    })


# ═══════════════════════════════════════════════════════════════════════════
# PAYMENTS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/payments', methods=['GET'])
@admin_required
def payments_index(user):
    """List all payments with search and filter."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    status = request.args.get('status')
    payment_type = request.args.get('payment_type')
    search = request.args.get('search')

    q = Payment.query
    if status:
        q = q.filter_by(status=status)
    if payment_type:
        q = q.filter_by(payment_type=payment_type)
    if search:
        search_term = f'%{search}%'
        q = q.filter(or_(
            Payment.stripe_payment_intent_id.ilike(search_term),
            Payment.description.ilike(search_term),
        ))

    pagination = q.order_by(Payment.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return success_response("Success", {
        'data': [p.to_dict() for p in pagination.items],
        'total': pagination.total,
        'current_page': pagination.page,
        'last_page': pagination.pages,
        'per_page': per_page,
    })


@admin_bp.route('/api/admin/payments/<int:payment_id>', methods=['GET'])
@admin_required
def payments_show(user, payment_id):
    """Get payment detail."""
    payment = Payment.query.get(payment_id)
    if not payment:
        return error_response("Payment not found", status_code=404)
    data = payment.to_dict()
    customer = AdminUser.query.get(payment.customer_id) if payment.customer_id else None
    driver = AdminUser.query.get(payment.driver_id) if payment.driver_id else None
    data['customer'] = customer.to_dict() if customer else None
    data['driver'] = driver.to_dict() if driver else None
    neg = Negotiation.query.get(payment.negotiation_id) if payment.negotiation_id else None
    data['negotiation'] = neg.to_dict() if neg else None
    return success_response("Success", data)


# ═══════════════════════════════════════════════════════════════════════════
# WALLETS & TRANSACTIONS
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/wallets', methods=['GET'])
@admin_required
def wallets_index(user):
    """List all user wallets."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    pagination = UserWallet.query.order_by(UserWallet.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    wallets = []
    for w in pagination.items:
        wd = w.to_dict()
        u = AdminUser.query.get(w.user_id)
        wd['user_name'] = u.name if u else None
        wd['user_type'] = u.user_type if u else None
        wallets.append(wd)

    return success_response("Success", {
        'data': wallets,
        'total': pagination.total,
        'current_page': pagination.page,
        'last_page': pagination.pages,
        'per_page': per_page,
    })


@admin_bp.route('/api/admin/transactions', methods=['GET'])
@admin_required
def transactions_index(user):
    """List all transactions."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    user_id = request.args.get('user_id')
    tx_type = request.args.get('type')
    category = request.args.get('category')

    q = Transaction.query
    if user_id:
        q = q.filter_by(user_id=int(user_id))
    if tx_type:
        q = q.filter_by(type=tx_type)
    if category:
        q = q.filter_by(category=category)

    pagination = q.order_by(Transaction.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return success_response("Success", {
        'data': [t.to_dict() for t in pagination.items],
        'total': pagination.total,
        'current_page': pagination.page,
        'last_page': pagination.pages,
        'per_page': per_page,
    })


# ═══════════════════════════════════════════════════════════════════════════
# PAYOUT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/payout-requests', methods=['GET'])
@admin_required
def payout_requests_index(user):
    """List all payout requests."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    status = request.args.get('status')

    q = PayoutRequest.query
    if status:
        q = q.filter_by(status=status)

    pagination = q.order_by(PayoutRequest.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    payouts = []
    for p in pagination.items:
        pd = p.to_dict()
        u = AdminUser.query.get(p.user_id)
        pd['user_name'] = u.name if u else None
        payouts.append(pd)

    return success_response("Success", {
        'data': payouts,
        'total': pagination.total,
        'current_page': pagination.page,
        'last_page': pagination.pages,
        'per_page': per_page,
    })


@admin_bp.route('/api/admin/payout-requests/<int:payout_id>/approve', methods=['POST'])
@admin_required
def payout_approve(user, payout_id):
    """Admin approves a payout request."""
    payout = PayoutRequest.query.get(payout_id)
    if not payout:
        return error_response("Payout request not found", status_code=404)
    if payout.status != 'pending':
        return error_response("Only pending requests can be approved")
    payout.status = 'processing'
    payout.processing_at = datetime.utcnow()
    data = request.get_json(silent=True) or {}
    payout.admin_notes = data.get('notes', '')
    db.session.commit()
    return success_response("Payout approved for processing", payout.to_dict())


@admin_bp.route('/api/admin/payout-requests/<int:payout_id>/complete', methods=['POST'])
@admin_required
def payout_complete(user, payout_id):
    """Admin completes a payout: transfers the net amount to the driver's Stripe
    Connect account (money actually leaves the platform balance)."""
    import os
    import stripe
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')

    payout = PayoutRequest.query.get(payout_id)
    if not payout:
        return error_response("Payout request not found", status_code=404)
    if payout.status == 'completed':
        return success_response("Payout already completed", payout.to_dict())
    if payout.status not in ('pending', 'processing'):
        return error_response(f"Cannot complete a {payout.status} payout")

    account = PayoutAccount.query.filter_by(user_id=payout.user_id).first()
    if not account or not account.stripe_account_id or not account.payouts_enabled:
        return error_response(
            "Driver has no active Stripe payout account — cannot transfer funds."
        )

    # Funds were already reserved (wallet debited) at request time. Now move the
    # net amount from the platform balance to the driver's connected account;
    # Stripe then pays it out to their bank per their payout schedule.
    net_cents = int(round(float(payout.net_amount or payout.amount) * 100))
    try:
        transfer = stripe.Transfer.create(
            amount=net_cents,
            currency=(payout.currency or 'cad').lower(),
            destination=account.stripe_account_id,
            description=f'NegoRide payout #{payout.id}',
            metadata={'payout_id': str(payout.id), 'user_id': str(payout.user_id)},
        )
    except stripe.error.StripeError as e:
        payout.status = 'processing'
        payout.failure_reason = str(e)
        db.session.commit()
        return error_response(f"Stripe transfer failed: {str(e)}")

    payout.stripe_transfer_id = transfer.id
    payout.status = 'completed'
    payout.processed_at = datetime.utcnow()
    from backend.services.audit import audit
    from backend.services.notify import notify
    audit('payout.complete', user, 'payout_request', payout.id, after={'status': 'completed',
                                                                      'stripe_transfer_id': transfer.id})
    notify('payout.sent', [payout.user_id], {'amount': f"${float(payout.net_amount or payout.amount):,.2f}",
                                             'id': payout.id}, dedupe_key=f'payout-{payout.id}')
    db.session.commit()
    return success_response("Payout completed", payout.to_dict())


@admin_bp.route('/api/admin/payout-requests/<int:payout_id>/reject', methods=['POST'])
@admin_required
def payout_reject(user, payout_id):
    """Admin rejects a payout request and refunds the reserved funds."""
    from backend.services import wallet_service
    payout = PayoutRequest.query.get(payout_id)
    if not payout:
        return error_response("Payout request not found", status_code=404)
    if payout.status in ('completed', 'failed', 'cancelled'):
        return error_response(f"Cannot reject a {payout.status} payout")
    data = request.get_json(silent=True) or request.form
    payout.status = 'failed'
    payout.failure_reason = data.get('reason', 'Rejected by admin')
    payout.failed_at = datetime.utcnow()
    # Return the reserved funds to the driver's wallet (idempotent on refund-<id>).
    wallet_service.refund_to_wallet(
        payout.user_id, payout.amount, f'refund-{payout.id}',
        f'Refund for rejected withdrawal #{payout.id}',
    )
    db.session.commit()
    return success_response("Payout rejected", payout.to_dict())


# ═══════════════════════════════════════════════════════════════════════════
# CHAT MONITORING
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/chats', methods=['GET'])
@admin_required
def chats_index(user):
    """List all chat heads."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    pagination = ChatHead.query.order_by(ChatHead.updated_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    chats = []
    for ch in pagination.items:
        cd = ch.to_dict()
        cd['message_count'] = ChatMessage.query.filter_by(chat_head_id=ch.id).count()
        chats.append(cd)

    return success_response("Success", {
        'data': chats,
        'total': pagination.total,
        'current_page': pagination.page,
        'last_page': pagination.pages,
        'per_page': per_page,
    })


@admin_bp.route('/api/admin/chats/<int:chat_id>/messages', methods=['GET'])
@admin_required
def chats_messages(user, chat_id):
    """View messages in a chat."""
    messages = ChatMessage.query.filter_by(chat_head_id=chat_id).order_by(
        ChatMessage.created_at.asc()
    ).all()
    return success_response("Success", [m.to_dict() for m in messages])


# ═══════════════════════════════════════════════════════════════════════════
# COMPANIES & ROUTE STAGES
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/companies', methods=['GET'])
@admin_required
def companies_index(user):
    """List all companies."""
    companies = Company.query.order_by(Company.created_at.desc()).all()
    return success_response("Success", [c.to_dict() for c in companies])


@admin_bp.route('/api/admin/companies', methods=['POST'])
@admin_required
def companies_create(user):
    """Create a company."""
    data = request.get_json(silent=True) or request.form
    company = Company(
        name=data.get('name'), short_name=data.get('short_name'),
        details=data.get('details'),
        phone_number=data.get('phone_number'), email=data.get('email'),
        address=data.get('address'), type=data.get('type'),
        administrator_id=user.id,
    )
    db.session.add(company)
    db.session.commit()
    return success_response("Company created", company.to_dict(), status_code=201)


@admin_bp.route('/api/admin/companies/<int:company_id>', methods=['PUT', 'POST'])
@admin_required
def companies_update(user, company_id):
    """Update a company."""
    company = Company.query.get(company_id)
    if not company:
        return error_response("Company not found", status_code=404)
    data = request.get_json(silent=True) or request.form
    for field in ['name', 'short_name', 'details', 'phone_number', 'phone_number_2',
                  'email', 'address', 'website', 'subdomain', 'color', 'welcome_message',
                  'type', 'logo', 'p_o_box', 'can_send_messages', 'has_valid_lisence']:
        if field in data and data[field] is not None:
            setattr(company, field, data[field])
    db.session.commit()
    return success_response("Company updated", company.to_dict())


@admin_bp.route('/api/admin/route-stages', methods=['GET'])
@admin_required
def route_stages_index(user):
    """List all route stages."""
    stages = RouteStage.query.all()
    return success_response("Success", [s.to_dict() for s in stages])


@admin_bp.route('/api/admin/route-stages', methods=['POST'])
@admin_required
def route_stages_create(user):
    """Create a route stage."""
    data = request.get_json(silent=True) or request.form
    stage = RouteStage(
        name=data.get('name'), latitute=data.get('latitute'),
        longitude=data.get('longitude'), details=data.get('details'),
    )
    db.session.add(stage)
    db.session.commit()
    return success_response("Route stage created", stage.to_dict(), status_code=201)


@admin_bp.route('/api/admin/route-stages/<int:stage_id>', methods=['PUT', 'POST'])
@admin_required
def route_stages_update(user, stage_id):
    """Update a route stage."""
    stage = RouteStage.query.get(stage_id)
    if not stage:
        return error_response("Route stage not found", status_code=404)
    data = request.get_json(silent=True) or request.form
    for field in ['name', 'latitute', 'longitude', 'details']:
        if field in data and data[field] is not None:
            setattr(stage, field, data[field])
    db.session.commit()
    return success_response("Route stage updated", stage.to_dict())


@admin_bp.route('/api/admin/route-stages/<int:stage_id>/delete', methods=['POST', 'DELETE'])
@admin_required
def route_stages_delete(user, stage_id):
    """Delete a route stage."""
    stage = RouteStage.query.get(stage_id)
    if not stage:
        return error_response("Route stage not found", status_code=404)
    db.session.delete(stage)
    db.session.commit()
    return success_response("Route stage deleted")


@admin_bp.route('/api/admin/companies/<int:company_id>/delete', methods=['POST', 'DELETE'])
@admin_required
def companies_delete(user, company_id):
    """Delete a company."""
    company = Company.query.get(company_id)
    if not company:
        return error_response("Company not found", status_code=404)
    db.session.delete(company)
    db.session.commit()
    return success_response("Company deleted")


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/system/health', methods=['GET'])
@admin_required
def system_health(user):
    """System health check."""
    try:
        db.session.execute(db.text('SELECT 1'))
        db_status = 'connected'
    except Exception as e:
        db_status = f'error: {str(e)}'
    return success_response("Success", {
        'status': 'healthy',
        'database': db_status,
        'timestamp': datetime.utcnow().isoformat(),
    })


@admin_bp.route('/api/admin/system/counts', methods=['GET'])
@admin_required
def system_counts(user):
    """Quick counts of all entities."""
    return success_response("Success", {
        'users': AdminUser.query.count(),
        'negotiations': Negotiation.query.count(),
        'trips': Trip.query.count(),
        'trip_bookings': TripBooking.query.count(),
        'scheduled_bookings': ScheduledBooking.query.count(),
        'payments': Payment.query.count(),
        'transactions': Transaction.query.count(),
        'wallets': UserWallet.query.count(),
        'payout_accounts': PayoutAccount.query.count(),
        'payout_requests': PayoutRequest.query.count(),
        'chat_heads': ChatHead.query.count(),
        'chat_messages': ChatMessage.query.count(),
        'companies': Company.query.count(),
        'route_stages': RouteStage.query.count(),
    })


# ── Spec §2.8: every admin action is audited ────────────────────────────────
_AUDIT_REDACT = ('password', 'token', 'secret', 'otp', 'code', 'card', 'cvc')


_SNAPSHOT_MODELS = {
    'users': AdminUser, 'negotiations': Negotiation, 'trips': Trip, 'bookings': ScheduledBooking,
    'trip-bookings': TripBooking, 'payout-requests': PayoutRequest, 'companies': Company,
    'route-stages': RouteStage, 'payments': Payment,
}
_SNAPSHOT_HIDE = ('password', 'remember_token', 'token', 'secret', 'otp', 'stripe_url')


@admin_bp.before_request
def _snapshot_before_legacy_admin_action():
    """Capture a 'before' row snapshot for the audit log (cheap: one PK lookup)."""
    from flask import g
    g._admin_audit_before = None
    try:
        if request.method in ('GET', 'HEAD', 'OPTIONS') or '/api/admin/' not in request.path:
            return
        parts = request.path.split('/api/admin/')[-1].split('/')
        model = _SNAPSHOT_MODELS.get(parts[0])
        if model is None or len(parts) < 2 or not parts[1].isdigit():
            return
        row = db.session.get(model, int(parts[1]))
        if row is not None and hasattr(row, 'to_dict'):
            snap = row.to_dict()
            import json
            g._admin_audit_before = json.loads(json.dumps(
                {k: ('[redacted]' if any(t in k.lower() for t in _SNAPSHOT_HIDE) else v)
                 for k, v in snap.items() if not isinstance(v, (list, dict))}, default=str))
    except Exception:
        db.session.rollback()


@admin_bp.after_request
def _audit_legacy_admin_actions(response):
    """Audit every successful state-changing request on the legacy admin API
    (the v4 admin blueprints audit explicitly with before/after snapshots)."""
    try:
        if request.method in ('GET', 'HEAD', 'OPTIONS') or response.status_code >= 400:
            return response
        from backend.services.audit import audit
        from backend.utils.auth import get_current_user
        actor = get_current_user()
        if actor is None:
            return response
        payload = request.get_json(silent=True) or (request.form.to_dict() if request.form else {})
        safe = {k: ('[redacted]' if any(t in k.lower() for t in _AUDIT_REDACT) else v)
                for k, v in (payload or {}).items()} if isinstance(payload, dict) else {}
        view_args = request.view_args or {}
        entity_id = next(iter(view_args.values()), None)
        entity_type = request.path.split('/api/admin/')[-1].split('/')[0] if '/api/admin/' in request.path else None
        from flask import g
        audit(f'admin_legacy.{request.endpoint.split(".")[-1]}', actor, entity_type, entity_id,
              before=getattr(g, '_admin_audit_before', None), after=safe or None,
              meta={'method': request.method, 'path': request.path})
        db.session.commit()
    except Exception:
        db.session.rollback()
    return response
