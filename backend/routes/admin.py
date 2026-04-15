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
from backend.utils.auth import admin_required, jwt_required_with_user
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
@jwt_required_with_user
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
@jwt_required_with_user
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
@admin_required
def users_update(user, user_id):
    """Admin updates any user's profile."""
    target = AdminUser.query.get(user_id)
    if not target:
        return error_response("User not found", status_code=404)

    data = request.get_json(silent=True) or request.form
    updatable = [
        'first_name', 'last_name', 'name', 'email', 'phone_number',
        'user_type', 'date_of_birth', 'sex', 'current_address',
        'country_name', 'country_code', 'country_short_name', 'automobile',
        'max_passengers', 'ready_for_trip',
        'driving_license_number', 'nin',
        'driving_license_issue_date', 'driving_license_validity',
        'driving_license_issue_authority',
        'is_car', 'is_boda', 'is_ambulance', 'is_police', 'is_delivery',
        'is_breakdown', 'is_firebrugade',
        'is_car_approved', 'is_boda_approved', 'is_ambulance_approved',
        'is_police_approved', 'is_delivery_approved', 'is_breakdown_approved',
        'is_firebrugade_approved',
    ]
    for field in updatable:
        if field in data and data[field] is not None:
            setattr(target, field, data[field])
    if 'status' in data:
        target.status = int(data['status'])

    target.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("User updated", target.to_dict())


@admin_bp.route('/api/admin/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def users_reset_password(user, user_id):
    """Admin resets a user's password."""
    target = AdminUser.query.get(user_id)
    if not target:
        return error_response("User not found", status_code=404)

    data = request.get_json(silent=True) or request.form
    new_password = data.get('new_password', 'NegoRide123!')
    target.set_password(new_password)
    target.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Password reset successfully")


@admin_bp.route('/api/admin/users/<int:user_id>/approve-driver', methods=['POST'])
@admin_required
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
@admin_required
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
@admin_required
def toggle_status(user, user_id):
    """Activate/deactivate a user."""
    target = AdminUser.query.get(user_id)
    if not target:
        return error_response("User not found", status_code=404)
    target.status = 0 if target.status == 1 else 1
    target.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Status updated", target.to_dict())


@admin_bp.route('/api/admin/users/<int:user_id>/delete', methods=['POST', 'DELETE'])
@admin_required
def users_delete(user, user_id):
    """Soft-delete a user."""
    target = AdminUser.query.get(user_id)
    if not target:
        return error_response("User not found", status_code=404)
    if target.id == user.id:
        return error_response("Cannot delete yourself")
    target.deleted_at = datetime.utcnow()
    target.status = 0
    target.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("User deleted")


@admin_bp.route('/api/admin/users/<int:user_id>/wallet', methods=['GET'])
@admin_required
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
@admin_required
def users_wallet_adjust(user, user_id):
    """Admin adjusts user's wallet balance."""
    import uuid
    data = request.get_json(silent=True) or request.form
    amount = float(data.get('amount', 0))
    tx_type = data.get('type', 'credit')
    reason = data.get('reason', 'Admin adjustment')

    if amount <= 0:
        return error_response("Amount must be positive")
    if tx_type not in ('credit', 'debit'):
        return error_response("Type must be 'credit' or 'debit'")

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
    """Admin updates negotiation status."""
    neg = Negotiation.query.get(neg_id)
    if not neg:
        return error_response("Negotiation not found", status_code=404)

    data = request.get_json(silent=True) or request.form
    new_status = data.get('status')
    valid_statuses = ['Pending', 'Accepted', 'Started', 'Completed', 'Cancelled']
    if new_status not in valid_statuses:
        return error_response(f"Status must be one of: {', '.join(valid_statuses)}")

    neg.status = new_status
    if new_status in ('Completed', 'Cancelled'):
        neg.is_active = 'No'
    neg.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Negotiation status updated", neg.to_dict())


@admin_bp.route('/api/admin/negotiations/<int:neg_id>/cancel', methods=['POST'])
@admin_required
def negotiations_cancel(user, neg_id):
    """Admin cancels a negotiation."""
    neg = Negotiation.query.get(neg_id)
    if not neg:
        return error_response("Negotiation not found", status_code=404)
    neg.status = 'Cancelled'
    neg.is_active = 'No'
    neg.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Negotiation cancelled", neg.to_dict())


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
    """Admin updates trip status."""
    trip = Trip.query.get(trip_id)
    if not trip:
        return error_response("Trip not found", status_code=404)
    data = request.get_json(silent=True) or request.form
    trip.status = data.get('status')
    trip.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Trip status updated", trip.to_dict())


@admin_bp.route('/api/admin/trips/<int:trip_id>/cancel', methods=['POST'])
@admin_required
def trips_cancel(user, trip_id):
    """Admin cancels a trip."""
    trip = Trip.query.get(trip_id)
    if not trip:
        return error_response("Trip not found", status_code=404)
    trip.status = 'Cancelled'
    trip.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Trip cancelled", trip.to_dict())


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
    """Admin updates booking status."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    data = request.get_json(silent=True) or request.form
    new_status = data.get('status')
    booking.status = new_status
    booking.updated_at = datetime.utcnow()

    if new_status == 'driver_assigned':
        booking.assigned_at = datetime.utcnow()
    elif new_status == 'confirmed':
        booking.confirmed_at = datetime.utcnow()
    elif new_status == 'in_progress':
        booking.started_at = datetime.utcnow()
    elif new_status == 'completed':
        booking.completed_at = datetime.utcnow()
    elif new_status == 'cancelled':
        booking.cancelled_at = datetime.utcnow()
        booking.cancellation_reason = data.get('reason')

    db.session.commit()
    return success_response("Booking status updated", booking.to_dict())


@admin_bp.route('/api/admin/bookings/<int:booking_id>/assign-driver', methods=['POST'])
@admin_required
def bookings_assign_driver(user, booking_id):
    """Admin assigns driver to booking."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)
    data = request.get_json(silent=True) or request.form
    driver = AdminUser.query.get(data.get('driver_id'))
    if not driver:
        return error_response("Driver not found", status_code=404)
    booking.driver_id = driver.id
    booking.assigned_by = user.id
    booking.status = 'driver_assigned'
    booking.assigned_at = datetime.utcnow()
    booking.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Driver assigned", booking.to_dict())


@admin_bp.route('/api/admin/bookings/<int:booking_id>/cancel', methods=['POST'])
@admin_required
def bookings_cancel(user, booking_id):
    """Admin cancels a booking."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)
    data = request.get_json(silent=True) or request.form
    booking.status = 'cancelled'
    booking.cancellation_reason = data.get('reason', 'Cancelled by admin')
    booking.cancelled_at = datetime.utcnow()
    booking.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Booking cancelled", booking.to_dict())


@admin_bp.route('/api/admin/bookings/<int:booking_id>/mark-paid', methods=['POST'])
@admin_required
def bookings_mark_paid(user, booking_id):
    """Admin force-marks booking as paid."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)
    booking.payment_status = 'paid'
    booking.stripe_paid = True
    booking.status = 'confirmed'
    booking.confirmed_at = datetime.utcnow()
    booking.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Marked as paid", booking.to_dict())


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
    """Admin marks payout as completed."""
    payout = PayoutRequest.query.get(payout_id)
    if not payout:
        return error_response("Payout request not found", status_code=404)
    payout.status = 'completed'
    payout.processed_at = datetime.utcnow()
    db.session.commit()
    return success_response("Payout completed", payout.to_dict())


@admin_bp.route('/api/admin/payout-requests/<int:payout_id>/reject', methods=['POST'])
@admin_required
def payout_reject(user, payout_id):
    """Admin rejects a payout request."""
    payout = PayoutRequest.query.get(payout_id)
    if not payout:
        return error_response("Payout request not found", status_code=404)
    data = request.get_json(silent=True) or request.form
    payout.status = 'failed'
    payout.failure_reason = data.get('reason', 'Rejected by admin')
    payout.failed_at = datetime.utcnow()
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
