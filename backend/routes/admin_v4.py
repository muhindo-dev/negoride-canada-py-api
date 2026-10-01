"""v4 admin API — foundation modules (spec §19): settings & feature flags,
audit log, notification delivery log + broadcast, unified rides (list, detail,
timeline, payments, refunds, actions) and the Command Center KPIs.

Role-based (spec §19.14): super_admin, ops, safety_reviewer, finance, support.
Every mutating action writes audit_logs.
"""
from datetime import datetime, timedelta

from flask import Blueprint, request
from sqlalchemy import func

from backend.models import db
from backend.models.money import Refund, RidePayment
from backend.models.negotiation import Negotiation
from backend.models.notification import Notification, NotificationDelivery
from backend.models.platform import AuditLog, TripEvent, WebhookEvent
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.models.user import AdminUser
from backend.services import ride_actions as RA
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services import trip_state_machine as TSM
from backend.services.audit import audit
from backend.services.payments import payment_service as PS
from backend.utils.auth import admin_role_required
from backend.utils.response import error_response, paginated_response, success_response

admin_v4_bp = Blueprint('admin_v4', __name__)


def _body():
    return request.get_json(silent=True) or request.form or {}


def _page():
    page = max(1, request.args.get('page', 1, type=int))
    per = min(200, max(1, request.args.get('per_page', 25, type=int)))
    return page, per


# ── Settings & feature flags ────────────────────────────────────────────────

@admin_v4_bp.route('/api/admin/settings', methods=['GET'])
@admin_role_required()
def settings_list(admin):
    items = S.all_settings()
    cat = request.args.get('category')
    if cat:
        items = [i for i in items if i['category'] == cat]
    return success_response('Settings', {'items': items,
                                         'categories': sorted({i['category'] for i in S.all_settings()})})


@admin_v4_bp.route('/api/admin/settings', methods=['PUT', 'POST'])
@admin_role_required('super_admin', 'ops', 'finance')
def settings_update(admin):
    data = _body()
    values = data.get('values') or ({data['key']: data.get('value')} if data.get('key') else {})
    if not values:
        return error_response('Provide {"values": {key: value}}')
    changed = {}
    try:
        for key, value in values.items():
            before, after = S.set_value(key, value, actor_id=admin.id)
            if before != after:
                changed[key] = {'before': before, 'after': after}
                audit('settings.update', admin, 'app_setting', key, before={'value': before}, after={'value': after})
    except (TypeError, ValueError) as e:
        db.session.rollback()
        return error_response(f'Invalid value: {e}')
    db.session.commit()
    return success_response(f'{len(changed)} setting(s) updated', {'changed': changed})


# ── Audit log ───────────────────────────────────────────────────────────────

@admin_v4_bp.route('/api/admin/audit-logs', methods=['GET'])
@admin_role_required('super_admin', 'ops', 'safety_reviewer', 'finance', 'support')
def audit_logs(admin):
    page, per = _page()
    q = AuditLog.query
    for f in ('action', 'entity_type', 'entity_id', 'actor_id'):
        v = request.args.get(f)
        if v:
            q = q.filter(getattr(AuditLog, f).like(f'{v}%') if f == 'action' else getattr(AuditLog, f) == v)
    total = q.count()
    rows = q.order_by(AuditLog.id.desc()).offset((page - 1) * per).limit(per).all()
    names = {u.id: u.name for u in AdminUser.query.filter(AdminUser.id.in_({r.actor_id for r in rows if r.actor_id}))}
    items = []
    for r in rows:
        d = r.to_dict()
        d['actor_name'] = names.get(r.actor_id)
        items.append(d)
    return paginated_response(items, total, page, per)


# ── Notifications log & broadcast ──────────────────────────────────────────

@admin_v4_bp.route('/api/admin/notifications', methods=['GET'])
@admin_role_required('super_admin', 'ops', 'support', 'safety_reviewer')
def notifications_log(admin):
    page, per = _page()
    q = Notification.query
    if request.args.get('user_id'):
        q = q.filter_by(user_id=request.args.get('user_id', type=int))
    if request.args.get('event_key'):
        q = q.filter(Notification.event_key.like(request.args['event_key'] + '%'))
    total = q.count()
    rows = q.order_by(Notification.id.desc()).offset((page - 1) * per).limit(per).all()
    ids = [r.id for r in rows]
    deliveries = {}
    for d in NotificationDelivery.query.filter(NotificationDelivery.notification_id.in_(ids)).all() if ids else []:
        deliveries.setdefault(d.notification_id, []).append(d.to_dict())
    names = {u.id: u.name for u in AdminUser.query.filter(AdminUser.id.in_({r.user_id for r in rows}))} if rows else {}
    items = []
    for r in rows:
        d = r.to_dict()
        d['user_name'] = names.get(r.user_id)
        d['deliveries'] = deliveries.get(r.id, [])
        items.append(d)
    return paginated_response(items, total, page, per)


@admin_v4_bp.route('/api/admin/notifications/stats', methods=['GET'])
@admin_role_required()
def notifications_stats(admin):
    since = datetime.utcnow() - timedelta(days=request.args.get('days', 7, type=int))
    rows = (db.session.query(NotificationDelivery.channel, NotificationDelivery.status, func.count())
            .filter(NotificationDelivery.queued_at >= since)
            .group_by(NotificationDelivery.channel, NotificationDelivery.status).all())
    out = {}
    for ch, st, n in rows:
        out.setdefault(ch, {})[st] = n
    return success_response('Delivery stats', out)


@admin_v4_bp.route('/api/admin/notifications/broadcast', methods=['POST'])
@admin_role_required('super_admin', 'ops')
def broadcast(admin):
    """Compose a broadcast segmented by role (customers/drivers/all) and city/province."""
    from backend.services.notify import notify
    data = _body()
    title, body = (data.get('title') or '').strip(), (data.get('body') or '').strip()
    if not title or not body:
        return error_response('title and body are required')
    q = AdminUser.query.filter(AdminUser.deleted_at.is_(None), AdminUser.status == 1)
    role = data.get('role', 'all')
    if role == 'drivers':
        q = q.filter(AdminUser.user_type == 'Driver')
    elif role == 'customers':
        q = q.filter(AdminUser.user_type == 'Customer')
    if data.get('province'):
        q = q.filter(AdminUser.province == data['province'])
    if data.get('city'):
        q = q.filter(AdminUser.current_address.like(f"%{data['city']}%"))
    if data.get('marketing_only', True):
        q = q.filter(AdminUser.marketing_opt_in.is_(True))
    ids = [u.id for u in q.with_entities(AdminUser.id).limit(50000)]
    if data.get('dry_run'):
        return success_response('Dry run', {'recipients': len(ids)})
    for i in range(0, len(ids), 500):
        notify('broadcast', ids[i:i + 500], {'title': title, 'body': body, 'route': data.get('route') or 'home'})
    audit('notifications.broadcast', admin, 'broadcast', None, meta={'title': title, 'recipients': len(ids),
                                                                       'role': role})
    db.session.commit()
    return success_response(f'Broadcast queued to {len(ids)} user(s)', {'recipients': len(ids)})


# ── Rides (unified) ─────────────────────────────────────────────────────────

_MODELS = {'carhire': Negotiation, 'scheduled': ScheduledBooking, 'rideshare_trip': Trip,
           'rideshare_booking': TripBooking}


def _row_summary(rt, r):
    pickup, dropoff = R.addresses(rt, r)
    drv = R.driver_id(rt, r)
    cids = R.customer_ids(rt, r)
    users = {u.id: u.name for u in AdminUser.query.filter(AdminUser.id.in_([x for x in [drv] + cids if x]))}
    return {
        'ride_type': rt, 'id': r.id, 'stage': R.current_stage(rt, r), 'legacy_status': r.status,
        'pickup': pickup, 'dropoff': dropoff, 'fare_cents': R.fare_cents(rt, r),
        'driver_id': drv, 'driver_name': users.get(drv),
        'customer_ids': cids, 'customer_name': users.get(cids[0]) if cids else None,
        'created_at': r.created_at.strftime('%Y-%m-%dT%H:%M:%SZ') if r.created_at else None,
        'stage_changed_at': r.stage_changed_at.strftime('%Y-%m-%dT%H:%M:%SZ') if r.stage_changed_at else None,
        'disputed': bool(getattr(r, 'disputed_at', None)),
    }


@admin_v4_bp.route('/api/admin/rides', methods=['GET'])
@admin_role_required()
def rides_list(admin):
    page, per = _page()
    types = [t for t in (request.args.get('type') or '').split(',') if t] or list(_MODELS)
    stage = request.args.get('stage')
    user_id = request.args.get('user_id', type=int)
    since = request.args.get('since')
    items = []
    total = 0
    for rt in types:
        model = _MODELS.get(rt)
        if not model:
            continue
        q = model.query
        if stage:
            q = q.filter(model.trip_stage.in_(stage.split(',')))
        if request.args.get('active') == '1':
            q = q.filter(model.trip_stage.in_(TSM.ACTIVE_STAGES[rt]))
        if request.args.get('disputed') == '1' and hasattr(model, 'disputed_at'):
            q = q.filter(model.disputed_at.isnot(None))
        if user_id:
            if hasattr(model, 'customer_id'):
                q = q.filter((model.customer_id == user_id) | (model.driver_id == user_id))
            else:
                q = q.filter(model.driver_id == user_id)
        if since:
            q = q.filter(model.created_at >= since)
        total += q.count()
        for r in q.order_by(model.id.desc()).limit(page * per).all():
            items.append(_row_summary(rt, r))
    items.sort(key=lambda x: x['created_at'] or '', reverse=True)
    items = items[(page - 1) * per: page * per]
    return paginated_response(items, total, page, per)


@admin_v4_bp.route('/api/admin/rides/<ride_type>/<int:ride_id>', methods=['GET'])
@admin_role_required()
def ride_detail(admin, ride_type, ride_id):
    try:
        rt = R.normalize_type(ride_type)
        ride = R.load(rt, ride_id)
    except R.RideNotFound as e:
        return error_response(str(e), status_code=404)
    data = RA.serialize(rt, ride, admin)
    data['summary'] = _row_summary(rt, ride)
    data['payments'] = [p.to_dict() for p in RidePayment.query.filter_by(ride_type=rt, ride_id=ride.id)
                        .order_by(RidePayment.id.desc())]
    data['refunds'] = [r.to_dict() for r in Refund.query.filter_by(ride_type=rt, ride_id=ride.id)
                       .order_by(Refund.id.desc())]
    data['pin'] = getattr(ride, 'ride_pin', None)
    try:
        from backend.models.money import Receipt
        from backend.services import receipts as RC
        rc = Receipt.query.filter_by(ride_type=rt, ride_id=ride.id).first()
        data['receipt'] = rc.to_dict() if rc else None
        data['tip_receipts'] = RC.tips_section(rt, ride.id)
    except Exception:
        data['receipt'] = None
    rp = PS.latest_payment(rt, ride.id) if rt != 'rideshare_trip' else None
    data['safety_settlement'] = ({'status': rp.settlement_status, 'due_at': rp.settle_due_at.strftime('%Y-%m-%dT%H:%M:%SZ')
                                  if rp.settle_due_at else None, 'held_cents': PS.held_cents(rp),
                                  'decision': (rp.meta or {}).get('safety_settlement')}
                                 if rp is not None and rp.settlement_status else None)
    if rt == 'carhire':
        from backend.models.negotiation_record import NegotiationRecord
        data['negotiation_history'] = [r.to_dict() for r in NegotiationRecord.query
                                       .filter_by(negotiation_id=ride.id).order_by(NegotiationRecord.id.asc())]
    audit('personal_data.view', admin, rt, ride.id)   # PIPEDA: log admin access to personal data
    db.session.commit()
    return success_response('Ride', data)


@admin_v4_bp.route('/api/admin/rides/<ride_type>/<int:ride_id>/transition', methods=['POST'])
@admin_role_required('super_admin', 'ops')
def ride_transition(admin, ride_type, ride_id):
    data = _body()
    reason = (data.get('reason') or '').strip()
    if len(reason) < 5:
        return error_response('A reason is required for admin overrides.')
    try:
        rt = R.normalize_type(ride_type)
        ride = R.load(rt, ride_id)
        TSM.ensure_stage(rt, ride)
        before = {'stage': ride.trip_stage, 'status': ride.status}
        res = TSM.transition(rt, ride_id, data.get('to_stage'), actor=admin, actor_type='admin',
                             meta={'admin_reason': reason}, commit=False)
        audit('ride.admin_transition', admin, rt, ride_id, before=before,
              after={'stage': res.to_stage, 'status': res.ride.status}, meta={'reason': reason})
        db.session.commit()
        return success_response('Stage updated', res.to_dict())
    except TSM.TransitionError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code, **e.data}, status_code=e.status)
    except R.RideNotFound as e:
        return error_response(str(e), status_code=404)


@admin_v4_bp.route('/api/admin/rides/<ride_type>/<int:ride_id>/cancel', methods=['POST'])
@admin_role_required('super_admin', 'ops')
def ride_cancel(admin, ride_type, ride_id):
    data = _body()
    reason = (data.get('reason') or '').strip()
    if len(reason) < 5:
        return error_response('A reason is required.')
    policy_reason = data.get('policy_reason') or 'customer_cancel'   # which §7 row applies
    if policy_reason not in ('customer_cancel', 'driver_cancel', 'safety', 'expired', 'driver_no_show'):
        return error_response('Invalid policy_reason')
    try:
        rt = R.normalize_type(ride_type)
        result, decision = RA.cancel(rt, ride_id, actor=admin, actor_type='admin', reason=policy_reason,
                                     reason_code='admin', note=reason, commit=False)
        audit('ride.admin_cancel', admin, rt, ride_id, after={'stage': result.to_stage},
              meta={'reason': reason, 'policy': decision.to_dict() if decision else None})
        db.session.commit()
        return success_response('Ride cancelled', {'transition': result.to_dict(),
                                                   'policy': decision.to_dict() if decision else None})
    except TSM.TransitionError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)


@admin_v4_bp.route('/api/admin/rides/<ride_type>/<int:ride_id>/settle-safety', methods=['POST'])
@admin_role_required('super_admin', 'ops', 'safety_reviewer', 'finance')
def ride_settle_safety(admin, ride_type, ride_id):
    """Decide a safety-ended ride's payment (§7.1): charge `amount_cents`
    (pro-rated, 0 = nothing) and release/refund the rest. {amount_cents, reason}."""
    data = _body()
    try:
        rt = R.normalize_type(ride_type)
        R.load(rt, ride_id)
        out = PS.settle_safety(rt, ride_id, data.get('amount_cents'), data.get('reason') or '', admin)
    except R.RideNotFound as e:
        return error_response(str(e), status_code=404)
    except PS.PaymentError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    except Exception as e:   # provider refusal
        from backend.services.payments.gateway import GatewayError
        if isinstance(e, GatewayError):
            db.session.rollback()
            return error_response(f'Stripe refused: {e}', data={'error_code': 'gateway_error'}, status_code=502)
        raise
    rp = PS.latest_payment(rt, ride_id)
    return success_response('Safety settlement applied', {**out, 'payment': rp.to_dict() if rp else None})


@admin_v4_bp.route('/api/admin/rides/<ride_type>/<int:ride_id>/receipt/issue', methods=['POST'])
@admin_role_required('super_admin', 'finance', 'ops', 'support')
def ride_issue_receipt(admin, ride_type, ride_id):
    """Issue (and email) the receipt of a completed, paid ride now — for rides
    the sweeper would pick up anyway, or after fixing a capture. Runs as a job
    (202); returns the receipt when it already exists / was issued."""
    from backend import jobs
    from backend.services import receipts as RC
    try:
        rt = R.normalize_type(ride_type)
        ride = R.load(rt, ride_id)
    except R.RideNotFound as e:
        return error_response(str(e), status_code=404)
    if rt not in RC.RECEIPT_RIDE_TYPES:
        return error_response('Receipts are issued per car hire, scheduled ride or seat booking.',
                              data={'error_code': 'unsupported'})
    stage = R.current_stage(rt, ride)
    existing = RC.find_receipt(rt, ride_id)
    if existing is None:
        if stage not in ('COMPLETED', 'DROPPED_OFF', 'CLOSED') and not PS.latest_payment(rt, ride_id):
            return error_response(f'The ride is {stage}; there is nothing to receipt.',
                                  data={'error_code': 'not_completed', 'stage': stage}, status_code=409)
        audit('receipt.issue_requested', admin, rt, ride_id)
        db.session.commit()
        jobs.enqueue('backend.services.trip_effects.issue_receipt_safe', rt, ride_id)
        db.session.rollback()
        existing = RC.find_receipt(rt, ride_id)
    return success_response('Receipt issued' if existing else 'Receipt queued', {
        'queued': existing is None, 'receipt': RC.receipt_payload(existing, viewer='customer') if existing else None},
        status_code=200 if existing else 202)


@admin_v4_bp.route('/api/admin/readiness', methods=['GET'])
@admin_role_required()
def readiness(admin):
    """Launch blockers / warnings (configuration only, no vendor calls)."""
    from backend.services import readiness as RD
    return success_response('Readiness', RD.report())


@admin_v4_bp.route('/api/admin/ride-payments/<int:rp_id>/refund', methods=['POST'])
@admin_role_required('super_admin', 'finance')
def ride_payment_refund(admin, rp_id):
    data = _body()
    rp = db.session.get(RidePayment, rp_id)
    if not rp:
        return error_response('Payment not found', status_code=404)
    try:
        amount = int(data.get('amount_cents') or 0)
    except (TypeError, ValueError):
        return error_response('amount_cents must be an integer')
    key = request.headers.get('Idempotency-Key') or data.get('idempotency_key') or f'{amount}-{datetime.utcnow():%Y%m%d%H%M}'
    try:
        refunded = PS.manual_refund(rp, amount, data.get('reason') or '', admin, key,
                                    clawback=bool(data.get('clawback')))
    except PS.PaymentError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    return success_response('Refund issued' if refunded else 'Refund already processed',
                            {'refunded_cents': refunded, 'payment': db.session.get(RidePayment, rp_id).to_dict()})


@admin_v4_bp.route('/api/admin/ride-payments', methods=['GET'])
@admin_role_required('super_admin', 'finance', 'ops')
def ride_payments(admin):
    page, per = _page()
    q = RidePayment.query
    for f in ('capture_status', 'purpose', 'ride_type'):
        if request.args.get(f):
            q = q.filter(getattr(RidePayment, f) == request.args[f])
    total = q.count()
    rows = q.order_by(RidePayment.id.desc()).offset((page - 1) * per).limit(per).all()
    return paginated_response([r.to_dict() for r in rows], total, page, per)


@admin_v4_bp.route('/api/admin/refunds', methods=['GET'])
@admin_role_required('super_admin', 'finance', 'ops')
def refunds(admin):
    page, per = _page()
    q = Refund.query
    total = q.count()
    rows = q.order_by(Refund.id.desc()).offset((page - 1) * per).limit(per).all()
    return paginated_response([r.to_dict() for r in rows], total, page, per)


@admin_v4_bp.route('/api/admin/webhook-events', methods=['GET'])
@admin_role_required('super_admin', 'finance')
def webhook_events(admin):
    page, per = _page()
    q = WebhookEvent.query
    if request.args.get('provider'):
        q = q.filter_by(provider=request.args['provider'])
    if request.args.get('status'):
        q = q.filter_by(status=request.args['status'])
    total = q.count()
    rows = q.order_by(WebhookEvent.id.desc()).offset((page - 1) * per).limit(per).all()
    return paginated_response([r.to_dict(exclude=('payload',)) for r in rows], total, page, per)


# ── Command Center KPIs (spec §19.1.1) ──────────────────────────────────────

@admin_v4_bp.route('/api/admin/command-center', methods=['GET'])
@admin_role_required()
def command_center(admin):
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    online = AdminUser.query.filter(AdminUser.ready_for_trip == 'Yes',
                                    AdminUser.last_location_update >= now - timedelta(minutes=10)).count()
    by_stage = {}
    for rt, model in _MODELS.items():
        for st, n in (db.session.query(model.trip_stage, func.count())
                      .filter(model.trip_stage.in_(TSM.ACTIVE_STAGES[rt])).group_by(model.trip_stage)):
            by_stage[st] = by_stage.get(st, 0) + n
    rides_today = sum(m.query.filter(m.created_at >= today).count() for rt, m in _MODELS.items()
                      if rt != 'rideshare_trip')
    completed_today = (TripEvent.query.filter(TripEvent.created_at >= today,
                                              TripEvent.to_stage.in_(['COMPLETED', 'DROPPED_OFF'])).count())
    cancelled_today = (TripEvent.query.filter(TripEvent.created_at >= today,
                                              TripEvent.to_stage.in_(['CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_DRIVER',
                                                                      'CUSTOMER_NO_SHOW', 'DRIVER_NO_SHOW',
                                                                      'EXPIRED', 'NO_SHOW'])).count())
    gmv_today = db.session.query(func.coalesce(func.sum(RidePayment.amount_captured_cents), 0)) \
        .filter(RidePayment.captured_at >= today, RidePayment.purpose == 'ride').scalar()
    # average pickup time: CONFIRMED → DRIVER_ARRIVED today
    pickups = []
    arrived = TripEvent.query.filter(TripEvent.created_at >= today, TripEvent.to_stage == 'DRIVER_ARRIVED',
                                     TripEvent.ride_type == 'carhire').limit(500).all()
    for ev in arrived:
        conf = TripEvent.query.filter_by(ride_type='carhire', ride_id=ev.ride_id, to_stage='CONFIRMED').first()
        if conf:
            pickups.append((ev.created_at - conf.created_at).total_seconds())
    open_sos = 0
    try:
        from backend.models.safety import SafetyIncident
        open_sos = SafetyIncident.query.filter(SafetyIncident.status.in_(['open', 'acknowledged'])).count()
    except Exception:
        pass
    finished = completed_today + cancelled_today
    return success_response('Command center', {
        'online_drivers': online,
        'active_rides_by_stage': by_stage,
        'active_rides': sum(by_stage.values()),
        'rides_today': rides_today,
        'completed_today': completed_today,
        'cancelled_today': cancelled_today,
        'completion_rate': round(completed_today / finished, 3) if finished else None,
        'gmv_today_cents': int(gmv_today or 0),
        'avg_pickup_seconds': round(sum(pickups) / len(pickups)) if pickups else None,
        'open_sos': open_sos,
        'generated_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
    })


@admin_v4_bp.route('/api/admin/alerts', methods=['GET'])
@admin_role_required()
def alerts_feed(admin):
    """Latest noteworthy events for the Command Center feed."""
    limit = min(100, request.args.get('limit', 30, type=int))
    evs = (TripEvent.query.filter(TripEvent.to_stage.in_([
        'CANCELLED_BY_DRIVER', 'DRIVER_NO_SHOW', 'CUSTOMER_NO_SHOW', 'EXPIRED', 'COMPLETED']))
        .order_by(TripEvent.id.desc()).limit(limit).all())
    items = [{'kind': 'ride', 'severity': 'info' if e.to_stage == 'COMPLETED' else 'warning',
              'text': f'{e.ride_type} #{e.ride_id}: {e.from_stage} → {e.to_stage}', 'ride_type': e.ride_type,
              'ride_id': e.ride_id, 'at': e.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')} for e in evs]
    try:
        from backend.models.safety import SafetyIncident
        for inc in SafetyIncident.query.order_by(SafetyIncident.id.desc()).limit(10):
            items.append({'kind': 'sos', 'severity': 'critical' if inc.status == 'open' else 'info',
                          'text': f'SOS #{inc.id} ({inc.status})', 'incident_id': inc.id,
                          'at': inc.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')})
    except Exception:
        pass
    # Ride-PIN lockouts (possible wrong-car / brute force) and missing on-call config
    for a in (AuditLog.query.filter(AuditLog.action.in_(['ride.pin_locked', 'safety.oncall_missing']))
              .order_by(AuditLog.id.desc()).limit(10)):
        pin = a.action == 'ride.pin_locked'
        items.append({'kind': 'pin_locked' if pin else 'oncall_not_configured', 'severity': 'critical',
                      'text': (f'Ride PIN locked on {a.entity_type} #{a.entity_id}' if pin
                               else 'SOS escalation skipped: no on-call phones configured'),
                      'ride_type': a.entity_type if pin else None,
                      'ride_id': int(a.entity_id) if pin and a.entity_id and str(a.entity_id).isdigit() else None,
                      'at': a.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')})
    items.sort(key=lambda x: x['at'], reverse=True)
    return success_response('Alerts', items[:limit])


# ── Ride chat log (disputes/safety only), reassignment, templates, view-as ──

@admin_v4_bp.route('/api/admin/rides/<ride_type>/<int:ride_id>/chat', methods=['GET'])
@admin_role_required('super_admin', 'ops', 'safety_reviewer', 'support')
def ride_chat_log(admin, ride_type, ride_id):
    """In-app chat between the ride's parties during the ride window. Only
    available when the ride is disputed or has a safety incident (privacy);
    every view is audited."""
    from backend.models.chat_head import ChatHead
    from backend.models.chat_message import ChatMessage
    try:
        rt = R.normalize_type(ride_type)
        ride = R.load(rt, ride_id)
    except R.RideNotFound as e:
        return error_response(str(e), status_code=404)
    has_incident = False
    try:
        from backend.models.safety import SafetyIncident
        has_incident = SafetyIncident.query.filter_by(ride_type=rt, ride_id=ride.id).count() > 0
    except Exception:
        pass
    if not getattr(ride, 'disputed_at', None) and not has_incident:
        return error_response('Chat logs are only available for disputed rides or safety incidents.',
                              data={'error_code': 'not_disputed'}, status_code=403)
    parties = R.all_party_ids(rt, ride)
    if len(parties) < 2:
        return success_response('Chat log', {'messages': [], 'negotiation': []})
    a, b = parties[0], parties[1]
    start = (ride.created_at or datetime.utcnow()) - timedelta(hours=1)
    end = (getattr(ride, 'completed_at', None) or getattr(ride, 'cancelled_at', None) or datetime.utcnow()) \
        + timedelta(hours=2)
    heads = ChatHead.query.filter(((ChatHead.customer_id == a) & (ChatHead.product_owner_id == b)) |
                                  ((ChatHead.customer_id == b) & (ChatHead.product_owner_id == a))).all()
    msgs = []
    if heads:
        rows = (ChatMessage.query.filter(ChatMessage.chat_head_id.in_([h.id for h in heads]),
                                         ChatMessage.created_at >= start, ChatMessage.created_at <= end)
                .order_by(ChatMessage.created_at.asc()).limit(1000).all())
        msgs = [{'id': m.id, 'sender_id': m.sender_id, 'receiver_id': m.receiver_id, 'body': m.body,
                 'type': m.type, 'photo': m.photo, 'audio': m.audio,
                 'at': m.created_at.strftime('%Y-%m-%dT%H:%M:%SZ') if m.created_at else None} for m in rows]
    negotiation = []
    if rt == 'carhire':
        from backend.models.negotiation_record import NegotiationRecord
        negotiation = [r.to_dict() for r in NegotiationRecord.query.filter_by(negotiation_id=ride.id)
                       .order_by(NegotiationRecord.id.asc())]
    audit('personal_data.chat_log_view', admin, rt, ride.id, meta={'messages': len(msgs)})
    db.session.commit()
    return success_response('Chat log', {'messages': msgs, 'negotiation': negotiation,
                                         'window': {'from': start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                                                    'to': end.strftime('%Y-%m-%dT%H:%M:%SZ')}})


@admin_v4_bp.route('/api/admin/rides/<ride_type>/<int:ride_id>/reassign', methods=['POST'])
@admin_role_required('super_admin', 'ops')
def ride_reassign(admin, ride_type, ride_id):
    """Reassign the driver before pickup (car hire / scheduled). Reason required,
    audited, both drivers and the customer are notified in realtime."""
    data = _body()
    reason = (data.get('reason') or '').strip()
    if len(reason) < 5:
        return error_response('A reason is required.')
    try:
        payload = RA.reassign_driver(ride_type, ride_id, data.get('driver_id'), admin, reason)
    except R.RideNotFound as e:
        return error_response(str(e), status_code=404)
    except TSM.TransitionError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    return success_response('Driver reassigned', payload)


@admin_v4_bp.route('/api/admin/notifications/templates', methods=['GET'])
@admin_role_required()
def notification_templates(admin):
    """The notification catalogue: copy in EN/FR, channels, groups, plus any admin
    overrides (PUT/DELETE /api/admin/notifications/templates/{event_key})."""
    from backend.services.notify import catalogue as C
    from backend.models.notification import NotificationTemplateOverride as O
    ov = {}
    for o in O.query.all():
        ov.setdefault(o.event_key, {})[o.lang] = _override_row(o)
    items = [{'event_key': k, 'group': v['group'], 'channels': list(v['channels']), 'critical': v['critical'],
              'sms_fallback': v['sms_fallback'], 'route': v['route'], 'android_channel': v['android_channel'],
              'mandatory': v['group'] in C.MANDATORY_GROUPS, 'title': v['title'], 'body': v['body'],
              'overrides': ov.get(k, {})}
             for k, v in sorted(C.CATALOGUE.items())]
    return success_response('Templates', {'items': items, 'mandatory_groups': list(C.MANDATORY_GROUPS),
                                          'mutable_groups': list(C.MUTABLE_GROUPS)})


def _override_row(o):
    return {'event_key': o.event_key, 'lang': o.lang, 'title': o.title, 'body': o.body, 'updated_by': o.updated_by,
            'updated_at': (o.updated_at or o.created_at).strftime('%Y-%m-%dT%H:%M:%SZ')}


def _template_key(event_key):
    from backend.services.notify import catalogue as C
    if event_key not in C.CATALOGUE:
        return None
    return C.CATALOGUE[event_key]


@admin_v4_bp.route('/api/admin/notifications/templates/<event_key>', methods=['GET'])
@admin_role_required()
def notification_template_get(admin, event_key):
    from backend.models.notification import NotificationTemplateOverride as O
    spec = _template_key(event_key)
    if spec is None:
        return error_response('Unknown event', data={'error_code': 'not_found'}, status_code=404)
    overrides = {o.lang: _override_row(o) for o in O.query.filter_by(event_key=event_key)}
    return success_response('Template', {'event_key': event_key, 'group': spec['group'],
                                         'channels': list(spec['channels']), 'default': {'title': spec['title'],
                                                                                         'body': spec['body']},
                                         'overrides': overrides})


@admin_v4_bp.route('/api/admin/notifications/templates/<event_key>', methods=['PUT'])
@admin_role_required('super_admin', 'ops')
def notification_template_put(admin, event_key):
    """Override the copy of one event {lang: en|fr, title?, body?} (Jinja2, the
    same variables as the catalogue). Empty fields fall back to the default."""
    from jinja2 import Environment, TemplateSyntaxError
    from backend.models.notification import NotificationTemplateOverride as O
    spec = _template_key(event_key)
    if spec is None:
        return error_response('Unknown event', data={'error_code': 'not_found'}, status_code=404)
    data = _body()
    lang = (data.get('lang') or 'en').lower()
    if lang not in ('en', 'fr'):
        return error_response('lang must be en or fr', data={'error_code': 'bad_lang'})
    title, body = data.get('title'), data.get('body')
    if title is None and body is None:
        return error_response('Provide title and/or body.', data={'error_code': 'empty'})
    for name, tpl, limit in (('title', title, 255), ('body', body, 2000)):
        if tpl is None:
            continue
        if len(str(tpl)) > limit:
            return error_response(f'{name} is too long (max {limit}).', data={'error_code': 'too_long'})
        try:
            Environment().parse(str(tpl))
        except TemplateSyntaxError as e:
            return error_response(f'{name}: template error — {e.message}', data={'error_code': 'bad_template'})
    row = O.query.filter_by(event_key=event_key, lang=lang).first()
    before = _override_row(row) if row else None
    if row is None:
        row = O(event_key=event_key, lang=lang, created_at=datetime.utcnow())
        db.session.add(row)
    if title is not None:
        row.title = str(title)
    if body is not None:
        row.body = str(body)
    row.updated_by = admin.id
    row.updated_at = datetime.utcnow()
    db.session.flush()
    audit('notifications.template_override', admin, 'notification_template', f'{event_key}:{lang}', before=before,
          after=_override_row(row))
    db.session.commit()
    return success_response('Template saved', _override_row(row))


@admin_v4_bp.route('/api/admin/notifications/templates/<event_key>', methods=['DELETE'])
@admin_role_required('super_admin', 'ops')
def notification_template_delete(admin, event_key):
    """Remove the override (?lang=en|fr, default both) — back to the catalogue copy."""
    from backend.models.notification import NotificationTemplateOverride as O
    q = O.query.filter_by(event_key=event_key)
    if request.args.get('lang'):
        q = q.filter_by(lang=request.args['lang'].lower())
    rows = q.all()
    for r in rows:
        audit('notifications.template_reset', admin, 'notification_template', f'{r.event_key}:{r.lang}',
              before=_override_row(r))
        db.session.delete(r)
    db.session.commit()
    return success_response('Template reset', {'removed': len(rows)})


@admin_v4_bp.route('/api/admin/notifications/templates/<event_key>/preview', methods=['POST'])
@admin_role_required()
def notification_template_preview(admin, event_key):
    """Render {lang, title?, body?, context?} (unsaved draft or the effective
    template) with sample context — nothing is sent."""
    from backend.services.notify import dispatcher as D
    spec = _template_key(event_key)
    if spec is None:
        return error_response('Unknown event', data={'error_code': 'not_found'}, status_code=404)
    data = _body()
    lang = (data.get('lang') or 'en').lower()
    title_t, body_t = D.template_for(spec, event_key, lang if lang in ('en', 'fr') else 'en')
    if data.get('title') is not None:
        title_t = data['title']
    if data.get('body') is not None:
        body_t = data['body']
    sample = {'driver_first': 'Amara', 'customer_first': 'Sam', 'price': '$20.00', 'eta_min': 4, 'pin': '4821',
              'wait_until': '10:42', 'vehicle': 'Grey Toyota Corolla ABC 123', 'amount': '$12.00', 'route':
              'Toronto → Ottawa', 'departure': 'Fri Oct 02, 08:00', 'minutes': 60, 'pickup': 'Union Station',
              'is_customer': True, 'earning': '$18.00', 'cancelled_by': 'driver', 'refund_text': 'Full refund issued.',
              'name': 'Sam', 'document': 'Terms', 'reason': 'Example reason', 'number': 'NR-2026-000123',
              'total': '$22.00', 'ride_id': 42, 'ride_type': 'carhire', 'other_first': 'Amara'}
    sample.update(data.get('context') or {})
    return success_response('Preview', {'title': D.render(title_t, sample), 'body': D.render(body_t, sample),
                                        'context': sample})


@admin_v4_bp.route('/api/admin/users/<int:user_id>/view-as', methods=['GET'])
@admin_role_required('super_admin', 'ops', 'support')
def view_as(admin, user_id):
    """Impersonation-free 'view as' (spec §19.1.5): what the user currently sees —
    profile, account status, active ride (as that user), unread notifications,
    pending legal documents. Read-only; no token is issued. Audited."""
    u = db.session.get(AdminUser, user_id)
    if not u:
        return error_response('User not found', status_code=404)
    rt, ride = RA.find_active_for(u)
    unread = (Notification.query.filter_by(user_id=u.id).filter(Notification.read_at.is_(None))
              .order_by(Notification.id.desc()).limit(20).all())
    pending_legal = []
    try:
        from backend.services import legal_service
        pending_legal = [getattr(d, 'to_dict', lambda: d)() if not isinstance(d, dict) else d
                         for d in (legal_service.pending_for(u) or [])]
    except Exception:
        pending_legal = None
    audit('personal_data.view_as', admin, 'user', u.id)
    db.session.commit()
    return success_response('View as', {
        'profile': u.to_dict(),
        'account_status': u.effective_account_status(),
        'active_ride': RA.serialize(rt, ride, u) if ride is not None else None,
        'unread_notifications': [n.to_dict() for n in unread],
        'pending_legal_documents': pending_legal,
    })
