"""Unified ride API (spec §4.4, §6, §7).

    GET  /api/rides/active
    GET  /api/rides/{type}/{id}
    GET  /api/rides/{type}/{id}/timeline
    POST /api/rides/{type}/{id}/en-route        driver  → DRIVER_EN_ROUTE
    POST /api/rides/{type}/{id}/arrived         driver  → DRIVER_ARRIVED   {lat, lng}
    POST /api/rides/{type}/{id}/start           driver  → IN_PROGRESS / CHECKED_IN  {pin}
    POST /api/rides/{type}/{id}/complete        driver  → COMPLETED / DROPPED_OFF   {lat, lng}
    POST /api/rides/{type}/{id}/cancel          either  {reason_code, note}
    GET  /api/rides/{type}/{id}/cancel-preview  either
    POST /api/rides/{type}/{id}/no-show         driver  → CUSTOMER_NO_SHOW / NO_SHOW
    POST /api/rides/{type}/{id}/driver-no-show  customer → DRIVER_NO_SHOW
    POST /api/rides/{type}/{id}/pay             customer → Checkout URL (authorization hold)
    POST /api/rides/{type}/{id}/payment/sync    customer → re-check payment status
    POST /api/rides/{type}/{id}/dispute         either  {reason}
    POST /api/rides/rideshare_trip/{id}/publish | /boarding    driver

{type}: carhire | scheduled | rideshare_trip | rideshare_booking (aliases accepted).
Every failure returns {code: 0, message, data: {error_code, ...}} and changes nothing.
"""
from datetime import datetime

from flask import Blueprint, request

from backend.models import db
from backend.services import rides as R
from backend.services import ride_actions as RA
from backend.services import trip_state_machine as TSM
from backend.services.payments import payment_service as PS
from backend.utils.auth import jwt_required_with_user
from backend.utils.idempotency import idempotent
from backend.utils.response import error_response, success_response

rides_bp = Blueprint('rides', __name__)

# endpoint action → target stage per ride type
ACTION_TARGETS = {
    'en-route': {'carhire': 'DRIVER_EN_ROUTE', 'scheduled': 'DRIVER_EN_ROUTE'},
    'arrived': {'carhire': 'DRIVER_ARRIVED', 'scheduled': 'DRIVER_ARRIVED', 'rideshare_booking': 'DRIVER_ARRIVED'},
    'start': {'carhire': 'IN_PROGRESS', 'scheduled': 'IN_PROGRESS', 'rideshare_booking': 'CHECKED_IN',
              'rideshare_trip': 'IN_PROGRESS'},
    'complete': {'carhire': 'COMPLETED', 'scheduled': 'COMPLETED', 'rideshare_booking': 'DROPPED_OFF',
                 'rideshare_trip': 'COMPLETED'},
    'publish': {'rideshare_trip': 'PUBLISHED'},
    'boarding': {'rideshare_trip': 'BOARDING'},
}


def _body():
    return request.get_json(silent=True) or request.form or {}


def _err(e):
    if isinstance(e, TSM.TransitionError):
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code, **e.data}, status_code=e.status)
    if isinstance(e, PS.PaymentError):
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    if isinstance(e, R.RideNotFound):
        return error_response(str(e), data={'error_code': 'not_found'}, status_code=404)
    raise e


def _load_for(user, ride_type, ride_id):
    rt = R.normalize_type(ride_type)
    ride = R.load(rt, ride_id)
    role = R.role_of(user, rt, ride)
    if role is None:
        raise TSM.TransitionError('You are not part of this ride.', code='forbidden', status=403)
    return rt, ride, role


@rides_bp.route('/api/rides/active', methods=['GET'])
@jwt_required_with_user
def active(user):
    rt, ride = RA.find_active_for(user)
    if ride is None:
        return success_response('No active ride', None)
    return success_response('Active ride', RA.serialize(rt, ride, user))


@rides_bp.route('/api/rides/<ride_type>/<int:ride_id>', methods=['GET'])
@jwt_required_with_user
def show(user, ride_type, ride_id):
    try:
        rt, ride, _ = _load_for(user, ride_type, ride_id)
        TSM.ensure_stage(rt, ride)
        db.session.commit()
        return success_response('Ride', RA.serialize(rt, ride, user))
    except (TSM.TransitionError, R.RideNotFound) as e:
        return _err(e)


@rides_bp.route('/api/rides/<ride_type>/<int:ride_id>/timeline', methods=['GET'])
@jwt_required_with_user
def timeline(user, ride_type, ride_id):
    try:
        rt, ride, _ = _load_for(user, ride_type, ride_id)
        return success_response('Timeline', RA.timeline(rt, ride.id))
    except (TSM.TransitionError, R.RideNotFound) as e:
        return _err(e)


def _do_transition(user, ride_type, ride_id, action):
    data = _body()
    try:
        rt, ride, role = _load_for(user, ride_type, ride_id)
        target = ACTION_TARGETS[action].get(rt)
        if not target:
            return error_response(f"'{action}' is not available for {rt} rides.",
                                  data={'error_code': 'unsupported_action'}, status_code=400)
        meta = {}
        if data.get('odometer_km') not in (None, ''):
            meta['odometer_km'] = data.get('odometer_km')
        TSM.ensure_stage(rt, ride)
        result = TSM.transition(rt, ride.id, target, actor=user, lat=data.get('lat', data.get('latitude')),
                                lng=data.get('lng', data.get('longitude')), pin=data.get('pin'), meta=meta)
        ride = R.load(rt, ride.id)
        return success_response(f'Ride is now {target.replace("_", " ").lower()}',
                                {'transition': result.to_dict(), 'ride': RA.serialize(rt, ride, user, False)})
    except (TSM.TransitionError, R.RideNotFound) as e:
        return _err(e)


for _action in ACTION_TARGETS:
    def _make(action):
        @jwt_required_with_user
        @idempotent
        def view(user, ride_type, ride_id):
            return _do_transition(user, ride_type, ride_id, action)
        view.__name__ = f'ride_{action.replace("-", "_")}'
        return view
    rides_bp.add_url_rule(f'/api/rides/<ride_type>/<int:ride_id>/{_action}', view_func=_make(_action),
                          methods=['POST'])


@rides_bp.route('/api/rides/<ride_type>/<int:ride_id>/cancel-preview', methods=['GET'])
@jwt_required_with_user
def cancel_preview(user, ride_type, ride_id):
    try:
        rt, ride, role = _load_for(user, ride_type, ride_id)
        TSM.ensure_stage(rt, ride)
        if rt == 'rideshare_trip':
            n = len(R.customer_ids(rt, ride))
            return success_response('Preview', {'allowed': True, 'rule_id': 'rideshare_driver_cancelled',
                                                'fee_cents': 0, 'explanation':
                                                    f'All {n} passenger(s) get a 100 % refund. '
                                                    'This counts as a reliability strike.' if n else
                                                    'No passengers have booked yet.'})
        return success_response('Preview', RA.preview(rt, ride, role).to_dict())
    except (TSM.TransitionError, R.RideNotFound) as e:
        return _err(e)


@rides_bp.route('/api/rides/<ride_type>/<int:ride_id>/cancel', methods=['POST'])
@jwt_required_with_user
@idempotent
def cancel(user, ride_type, ride_id):
    data = _body()
    try:
        rt, ride, role = _load_for(user, ride_type, ride_id)
        reason = 'safety' if data.get('reason_code') == 'safety' and role == 'customer' else None
        result, decision = RA.cancel(rt, ride.id, actor=user, reason=reason,
                                     reason_code=(data.get('reason_code') or '')[:40] or None,
                                     note=(data.get('note') or '')[:1000] or None)
        return success_response('Ride cancelled', {
            'transition': result.to_dict(),
            'policy': decision.to_dict() if decision else None,
            'ride': RA.serialize(rt, R.load(rt, ride.id), user, False),
        })
    except (TSM.TransitionError, R.RideNotFound) as e:
        return _err(e)


@rides_bp.route('/api/rides/<ride_type>/<int:ride_id>/no-show', methods=['POST'])
@jwt_required_with_user
@idempotent
def no_show(user, ride_type, ride_id):
    try:
        rt, ride, role = _load_for(user, ride_type, ride_id)
        if role != 'driver':
            return error_response('Only the driver can record a no-show.', data={'error_code': 'forbidden'},
                                  status_code=403)
        result, decision = RA.cancel(rt, ride.id, actor=user, reason='customer_no_show')
        return success_response('No-show recorded', {'transition': result.to_dict(),
                                                     'policy': decision.to_dict() if decision else None})
    except (TSM.TransitionError, R.RideNotFound) as e:
        return _err(e)


@rides_bp.route('/api/rides/<ride_type>/<int:ride_id>/driver-no-show', methods=['POST'])
@jwt_required_with_user
@idempotent
def driver_no_show(user, ride_type, ride_id):
    try:
        rt, ride, role = _load_for(user, ride_type, ride_id)
        if role != 'customer':
            return error_response('Only the customer can report a driver no-show.',
                                  data={'error_code': 'forbidden'}, status_code=403)
        result, decision = RA.cancel(rt, ride.id, actor=user, reason='driver_no_show')
        return success_response('Driver no-show recorded', {'transition': result.to_dict(),
                                                            'policy': decision.to_dict() if decision else None})
    except (TSM.TransitionError, R.RideNotFound) as e:
        return _err(e)


@rides_bp.route('/api/rides/<ride_type>/<int:ride_id>/pay', methods=['POST'])
@jwt_required_with_user
@idempotent
def pay(user, ride_type, ride_id):
    try:
        rt, ride, role = _load_for(user, ride_type, ride_id)
        if role != 'customer':
            return error_response('Only the customer can pay for this ride.', data={'error_code': 'forbidden'},
                                  status_code=403)
        rp = PS.start_payment(rt, ride, user, force_new=bool(_body().get('force_new')))
        return success_response('Payment ready', {
            'ride_payment_id': rp.id, 'status': rp.capture_status, 'secured': rp.is_secured,
            'checkout_url': rp.checkout_url if not rp.is_secured else None,
            'amount_cents': (rp.meta or {}).get('amount') or rp.amount_authorized_cents,
            'fare_cents': rp.fare_cents, 'fees_cents': rp.fees_cents, 'capture_method': rp.capture_method,
            'success_url_prefix': '/api/payment-success', 'cancel_url_prefix': '/api/payment-cancel',
        })
    except (TSM.TransitionError, PS.PaymentError, R.RideNotFound) as e:
        return _err(e)


@rides_bp.route('/api/rides/<ride_type>/<int:ride_id>/payment/sync', methods=['POST'])
@jwt_required_with_user
def payment_sync(user, ride_type, ride_id):
    try:
        rt, ride, role = _load_for(user, ride_type, ride_id)
        rp = PS.latest_payment(rt, ride.id)
        if rp and not rp.is_secured:
            PS.sync_from_provider(rp)
            rp = PS.latest_payment(rt, ride.id)
        ride = R.load(rt, ride.id)
        return success_response('Payment status', {
            'status': rp.capture_status if rp else 'none', 'secured': bool(rp and rp.is_secured),
            'stage': R.current_stage(rt, ride)})
    except (TSM.TransitionError, R.RideNotFound) as e:
        return _err(e)


@rides_bp.route('/api/rides/<ride_type>/<int:ride_id>/dispute', methods=['POST'])
@jwt_required_with_user
@idempotent
def dispute(user, ride_type, ride_id):
    """Open a dispute (non-terminal overlay) within 72 h of completion."""
    from backend.models.identity import SupportTicket
    from backend.services import settings_service as S
    from backend.services.audit import audit
    data = _body()
    reason = (data.get('reason') or '').strip()
    if len(reason) < 5:
        return error_response('Please describe the problem (at least 5 characters).',
                              data={'error_code': 'reason_required'})
    try:
        rt, ride, role = _load_for(user, ride_type, ride_id)
        if not hasattr(ride, 'disputed_at'):
            return error_response('Disputes are not available for this ride type.',
                                  data={'error_code': 'unsupported'})
        ended = getattr(ride, 'completed_at', None) or getattr(ride, 'dropped_off_at', None) \
            or getattr(ride, 'cancelled_at', None)
        if ended and (datetime.utcnow() - ended).total_seconds() > S.get_int('ride.auto_close_h') * 3600:
            return error_response('Disputes must be opened within 72 hours of the trip.',
                                  data={'error_code': 'dispute_window_closed'})
        if ride.disputed_at:
            return error_response('A dispute is already open for this ride.', data={'error_code': 'already_open'},
                                  status_code=409)
        ride.disputed_at = datetime.utcnow()
        if hasattr(ride, 'dispute_reason'):
            ride.dispute_reason = reason
        from datetime import timedelta
        ticket = SupportTicket(user_id=user.id, type='dispute', ride_type=rt, ride_id=ride.id,
                               subject=f'Dispute on ride #{ride.id}', body=reason, priority='high',
                               sla_due_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(ticket)
        audit('ride.dispute_opened', user, rt, ride.id, meta={'reason': reason}, actor_type=role)
        db.session.commit()
        return success_response('Dispute opened — our team will review it within 24 hours.',
                                {'ticket_id': ticket.id})
    except (TSM.TransitionError, R.RideNotFound) as e:
        return _err(e)


@rides_bp.route('/api/rides/history', methods=['GET'])
@jwt_required_with_user
def history(user):
    """Unified trips history across car hire, scheduled bookings, rideshare seats
    (as customer) and rideshare trips (as driver). Query: page, per_page,
    type (comma list), status=active|completed|cancelled."""
    from backend.models.money import Receipt
    from backend.models.negotiation import Negotiation
    from backend.models.scheduled_booking import ScheduledBooking
    from backend.models.trip import Trip
    from backend.models.trip_booking import TripBooking
    from backend.utils.response import paginated_response
    page = max(1, request.args.get('page', 1, type=int))
    per = min(100, max(1, request.args.get('per_page', 20, type=int)))
    types = [t for t in (request.args.get('type') or '').split(',') if t] or list(R.RIDE_TYPES)
    status = request.args.get('status')
    uid = user.id
    queries = {
        'carhire': Negotiation.query.filter((Negotiation.customer_id == uid) | (Negotiation.driver_id == uid)),
        'scheduled': ScheduledBooking.query.filter((ScheduledBooking.customer_id == uid) |
                                                   (ScheduledBooking.driver_id == uid)),
        'rideshare_booking': TripBooking.query.filter(TripBooking.customer_id == uid),
        'rideshare_trip': Trip.query.filter(Trip.driver_id == uid),
    }
    rows = []
    for rt in types:
        q = queries.get(rt)
        if q is None:
            continue
        model = q.column_descriptions[0]['entity']
        for r in q.order_by(model.id.desc()).limit(page * per):
            stage = R.current_stage(rt, r)
            done = stage in ('COMPLETED', 'CLOSED', 'DROPPED_OFF')
            cancelled = TSM.is_cancel_stage(stage)
            if status == 'active' and (done or cancelled):
                continue
            if status == 'completed' and not done:
                continue
            if status == 'cancelled' and not cancelled:
                continue
            pickup, dropoff = R.addresses(rt, r)
            role = R.role_of(user, rt, r)
            other = R.driver_id(rt, r) if role == 'customer' else (R.customer_ids(rt, r) or [None])[0]
            rows.append({
                'ride_type': rt, 'id': r.id, 'stage': stage, 'legacy_status': r.status, 'role': role,
                'pickup': pickup, 'dropoff': dropoff, 'fare_cents': R.fare_cents(rt, r),
                'other_party': R.user_card(other) if other and rt != 'rideshare_trip' else None,
                'created_at': r.created_at.strftime('%Y-%m-%dT%H:%M:%SZ') if r.created_at else None,
                'completed': done, 'cancelled': cancelled,
            })
    rows.sort(key=lambda x: x['created_at'] or '', reverse=True)
    total = len(rows)
    items = rows[(page - 1) * per: page * per]
    receipts = {(rc.ride_type, rc.ride_id): rc.number for rc in Receipt.query.filter(
        Receipt.customer_id == uid).all()} if items else {}
    for it in items:
        it['receipt_number'] = receipts.get((it['ride_type'], it['id']))
    return paginated_response(items, total, page, per)
