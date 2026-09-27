import os
from datetime import datetime
from flask import Blueprint, request, current_app
from werkzeug.utils import secure_filename
from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.negotiation_record import NegotiationRecord
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

negotiations_bp = Blueprint('negotiations', __name__)


def _is_participant(negotiation: Negotiation, user_id: int) -> bool:
    return user_id in (negotiation.customer_id, negotiation.driver_id)


def _is_paid(negotiation: Negotiation) -> bool:
    status = (negotiation.payment_status or '').lower()
    return negotiation.stripe_paid == 'Yes' or status in ('paid', 'completed')


def _v4_error(e):
    """TransitionError → the legacy {code:0,message} envelope."""
    db.session.rollback()
    return error_response(e.message, data={'error_code': e.code, **getattr(e, 'data', {})},
                          status_code=e.status if e.status != 409 else 400)


def _record_created(negotiation, user, data):
    """v4: opening stage + event (spec §4). The driver is notified after commit."""
    from backend.services import trip_state_machine as TSM
    negotiation.service_type = (data.get('service_type') or data.get('automobile') or 'car')[:40]
    negotiation.request_mode = (data.get('request_mode') or 'direct')[:20]
    negotiation.agreed_price_cents = None
    TSM.record_creation('carhire', negotiation, actor=user, actor_type='customer',
                        meta={'initial_price_cents': negotiation.initial_price})


# ---------------------------------------------------------------------------
# Legacy endpoints (ApiChatController)
# ---------------------------------------------------------------------------

@negotiations_bp.route('/api/negotiations', methods=['GET'])
@jwt_required_with_user
def index(user):
    """List user's negotiations with optional filters + stats."""
    status = request.args.get('status')
    sort_by = request.args.get('sort_by', 'created_at')
    sort_order = request.args.get('sort_order', 'desc')
    per_page = int(request.args.get('per_page', 50))

    q = Negotiation.query.filter(
        (Negotiation.customer_id == user.id) | (Negotiation.driver_id == user.id)
    )

    if status == 'active':
        q = q.filter(Negotiation.status.in_(['Active', 'Pending', 'Accepted', 'Started']))
    elif status == 'completed':
        q = q.filter(Negotiation.status == 'Completed')
    elif status == 'canceled':
        q = q.filter(Negotiation.status == 'Cancelled')

    col = getattr(Negotiation, sort_by, Negotiation.created_at)
    q = q.order_by(col.desc() if sort_order == 'desc' else col.asc())
    negotiations = q.limit(per_page).all()

    # Stats
    all_q = Negotiation.query.filter(
        (Negotiation.customer_id == user.id) | (Negotiation.driver_id == user.id)
    )
    total = all_q.count()
    active = all_q.filter(Negotiation.status.in_(['Active', 'Pending', 'Accepted', 'Started'])).count()
    completed = all_q.filter(Negotiation.status == 'Completed').count()
    canceled = all_q.filter(Negotiation.status == 'Cancelled').count()

    return success_response("Success", {
        'negotiations': [n.to_dict() for n in negotiations],
        'stats': {
            'total': total,
            'active': active,
            'completed': completed,
            'canceled': canceled,
        },
    })


@negotiations_bp.route('/api/negotiations', methods=['POST'])
@jwt_required_with_user
def create_legacy(user):
    """Legacy create – ApiChatController style (dollars → cents)."""
    data = request.get_json(silent=True) or request.form
    driver_id = data.get('driver_id')
    driver = AdminUser.query.get(driver_id) if driver_id else None

    price_raw = data.get('price', 0)
    try:
        price_cents = int(float(price_raw) * 100)
    except (TypeError, ValueError):
        price_cents = 0

    negotiation = Negotiation(
        customer_id=user.id,
        customer_name=user.name,
        driver_id=driver_id,
        driver_name=driver.name if driver else None,
        pickup_lat=data.get('pickup_lat'),
        pickup_lng=data.get('pickup_lng'),
        pickup_address=data.get('pickup_address'),
        dropoff_lat=data.get('dropoff_lat'),
        dropoff_lng=data.get('dropoff_lng'),
        dropoff_address=data.get('dropoff_address'),
        initial_price=price_cents,
        status='Active',
        is_active='Yes',
        customer_accepted='Accepted',
        customer_driver='Pending',
    )
    db.session.add(negotiation)
    db.session.flush()

    # Initial record
    record = NegotiationRecord(
        negotiation_id=negotiation.id,
        customer_id=user.id,
        driver_id=driver_id,
        last_negotiator_id=user.id,
        first_negotiator_id=user.id,
        price=price_cents,
        price_accepted='No',
        message_type=data.get('message_type', 'Negotiation'),
        message_body=data.get('message_body'),
    )
    db.session.add(record)
    _record_created(negotiation, user, data)
    db.session.commit()

    return success_response("Negotiation created", negotiation.to_dict(), status_code=201)


# ---------------------------------------------------------------------------
# Enhanced endpoints (ApiNegotiationController)
# ---------------------------------------------------------------------------

@negotiations_bp.route('/api/negotiations-create', methods=['POST'])
@jwt_required_with_user
def create(user):
    """Enhanced create – validates driver online, price ≥ 50 cents."""
    data = request.get_json(silent=True) or request.form
    driver_id = data.get('driver_id')

    if not driver_id:
        return error_response("driver_id is required")

    driver = AdminUser.query.get(driver_id)
    if not driver:
        return error_response("Driver not found", status_code=404)

    # SECURITY: cannot start a trip with an unapproved (still-under-review) driver.
    if not driver.is_approved_driver():
        return error_response("This driver is not available for trips.")

    initial_price = int(data.get('initial_price', 0))
    if initial_price < 50:
        return error_response("Minimum price is $0.50 (50 cents)")

    negotiation = Negotiation(
        customer_id=user.id,
        customer_name=user.name,
        driver_id=driver.id,
        driver_name=driver.name,
        pickup_lat=data.get('pickup_lat'),
        pickup_lng=data.get('pickup_lng'),
        pickup_address=data.get('pickup_address'),
        dropoff_lat=data.get('dropoff_lat'),
        dropoff_lng=data.get('dropoff_lng'),
        dropoff_address=data.get('dropoff_address'),
        initial_price=initial_price,
        status='Active',
        is_active='Yes',
        customer_accepted='Accepted',
        customer_driver='Pending',
    )
    db.session.add(negotiation)
    db.session.flush()

    record = NegotiationRecord(
        negotiation_id=negotiation.id,
        customer_id=user.id,
        driver_id=driver.id,
        last_negotiator_id=user.id,
        first_negotiator_id=user.id,
        price=initial_price,
        price_accepted='No',
        message_type='Negotiation',
        message_body=data.get('message_body'),
    )
    db.session.add(record)
    _record_created(negotiation, user, data)
    db.session.commit()

    return success_response("Negotiation created", negotiation.to_dict(), status_code=201)


@negotiations_bp.route('/api/negotiation-updates', methods=['POST'])
@jwt_required_with_user
def poll_updates(user):
    """Poll for negotiation updates."""
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id') or data.get('id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    return success_response("Success", negotiation.to_dict())


@negotiations_bp.route('/api/negotiations-records', methods=['GET'])
@jwt_required_with_user
def records_get(user):
    """Get negotiation records."""
    negotiation_id = request.args.get('negotiation_id')

    if negotiation_id:
        negotiation = Negotiation.query.get(negotiation_id)
        if not negotiation:
            return error_response("Negotiation not found", status_code=404)
        if not _is_participant(negotiation, user.id):
            return error_response("Forbidden", status_code=403)

        records = NegotiationRecord.query.filter_by(
            negotiation_id=negotiation_id
        ).order_by(NegotiationRecord.created_at.asc()).all()
    else:
        records = NegotiationRecord.query.filter(
            (NegotiationRecord.customer_id == user.id) |
            (NegotiationRecord.driver_id == user.id)
        ).order_by(NegotiationRecord.created_at.desc()).all()

    return success_response("Success", [r.to_dict() for r in records])


@negotiations_bp.route('/api/negotiations-records', methods=['POST'])
@jwt_required_with_user
def records_post(user):
    """Add a negotiation record (counter-offer / message / voice note)."""
    data = request.get_json(silent=True) or request.form

    negotiation_id = data.get('negotiation_id')
    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)
    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    price_raw = data.get('price', 0)
    try:
        price_cents = int(float(price_raw) * 100)
    except (TypeError, ValueError):
        price_cents = 0

    # Handle audio file upload
    audio_url = None
    if 'audio' in request.files:
        audio_file = request.files['audio']
        if audio_file and audio_file.filename:
            ext = audio_file.filename.rsplit('.', 1)[-1].lower() if '.' in audio_file.filename else 'm4a'
            if ext not in ('m4a', 'aac', 'mp3', 'wav', 'ogg', 'opus', 'webm'):
                return error_response("Unsupported audio format")
            filename = secure_filename(
                f"voice_{negotiation.id}_{user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{ext}"
            )
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'audio')
            os.makedirs(upload_dir, exist_ok=True)
            filepath = os.path.join(upload_dir, filename)
            audio_file.save(filepath)
            audio_url = f"audio/{filename}"

    record = NegotiationRecord(
        negotiation_id=negotiation.id,
        customer_id=negotiation.customer_id,
        driver_id=negotiation.driver_id,
        last_negotiator_id=user.id,
        first_negotiator_id=negotiation.customer_id or user.id,
        price=price_cents,
        price_accepted=data.get('price_accepted', 'No'),
        message_type=data.get('message_type', 'Negotiation'),
        message_body=data.get('message_body'),
        audio_url=audio_url,
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
    )
    db.session.add(record)

    # v4: a counter-offer moves REQUESTED → NEGOTIATING and pings the other party.
    from backend.services import trip_state_machine as TSM
    from backend.services.notify import notify
    from backend.services import realtime
    from backend.utils.money import fmt
    stage = TSM.ensure_stage('carhire', negotiation)
    is_offer = (record.message_type or 'Negotiation') == 'Negotiation' and price_cents > 0
    if is_offer and stage in ('PRICE_AGREED', 'AWAITING_PAYMENT', 'CONFIRMED', 'DRIVER_EN_ROUTE',
                              'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS', 'COMPLETED', 'CLOSED'):
        db.session.rollback()
        return error_response("The price is already agreed — offers can no longer change.",
                              data={'error_code': 'price_locked'})
    if TSM.is_terminal('carhire', stage):
        db.session.rollback()
        return error_response("This negotiation has ended.", data={'error_code': 'ended'})
    negotiation.updated_at = datetime.utcnow()
    if is_offer and stage == 'REQUESTED':
        try:
            TSM.transition('carhire', negotiation.id, 'NEGOTIATING', actor=user, commit=False, ride=negotiation,
                           meta={'price_cents': price_cents})
        except TSM.TransitionError:
            pass
    db.session.flush()
    if is_offer:
        other = negotiation.driver_id if user.id == negotiation.customer_id else negotiation.customer_id
        notify('negotiation.counter_offer', [other], {
            'ride_type': 'carhire', 'ride_id': negotiation.id, 'price': fmt(price_cents),
            'from_name': (user.first_name or (user.name or '').split(' ')[0] or 'NegoRide user')})
    db.session.commit()
    realtime.to_ride('carhire', negotiation.id, 'negotiation.updated',
                     {'negotiation_id': negotiation.id, 'record': record.to_dict()})
    for uid in (negotiation.customer_id, negotiation.driver_id):
        realtime.to_user(uid, 'negotiation.updated', {'negotiation_id': negotiation.id, 'record': record.to_dict()})

    return success_response("Record added", record.to_dict(), status_code=201)


@negotiations_bp.route('/api/negotiations-accept', methods=['POST'])
@jwt_required_with_user
def accept(user):
    """Accept / start negotiation based on message_type.

    Flutter sends:
      message_type='Accept'   → price agreed (v4: REQUESTED/NEGOTIATING → PRICE_AGREED)
      message_type='Started'  → driver starts the trip (v4: walks CONFIRMED →
                                EN_ROUTE → ARRIVED → IN_PROGRESS, payment required)

    All stage/status changes go through the trip state machine, so v3 and v4
    apps produce the same trip_events.
    """
    from backend.services import trip_state_machine as TSM
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    message_type = data.get('message_type', '')
    stage = TSM.ensure_stage('carhire', negotiation)

    try:
        if message_type == 'Started':
            if user.id != negotiation.driver_id:
                return error_response("Only the assigned driver can start this trip", status_code=403)
            if stage == 'IN_PROGRESS':
                return success_response("Negotiation updated", negotiation.to_dict())
            TSM.walk_to('carhire', negotiation.id, 'IN_PROGRESS', actor=user, legacy=True)

        elif message_type == 'Accept':
            if stage in ('PRICE_AGREED', 'AWAITING_PAYMENT', 'CONFIRMED'):
                return success_response("Negotiation updated", negotiation.to_dict())  # idempotent accept
            # Agreed price = the price of the offer on the table (the last record).
            last_record = (
                NegotiationRecord.query
                .filter_by(negotiation_id=negotiation.id)
                .filter(NegotiationRecord.price > 0)
                .order_by(NegotiationRecord.id.desc())
                .first()
            )
            record_count = NegotiationRecord.query.filter_by(negotiation_id=negotiation.id).count()
            # You cannot "accept" your own offer (the other party must agree to it).
            if last_record and last_record.last_negotiator_id == user.id and record_count > 1:
                return error_response("Waiting for the other party to respond to your offer.",
                                      data={'error_code': 'own_offer'})
            agreed = (last_record.price if last_record and last_record.price else None) or negotiation.initial_price
            negotiation.agreed_price = agreed            # legacy column (stores cents)
            negotiation.agreed_price_cents = agreed
            negotiation.customer_accepted = 'Accepted'
            negotiation.customer_driver = 'Accepted'
            negotiation.updated_at = datetime.utcnow()
            TSM.transition('carhire', negotiation.id, 'PRICE_AGREED', actor=user, ride=negotiation,
                           meta={'agreed_price_cents': agreed})
        else:
            if (negotiation.customer_accepted == 'Accepted'
                    and negotiation.customer_driver == 'Accepted'
                    and stage in ('REQUESTED', 'NEGOTIATING')):
                TSM.transition('carhire', negotiation.id, 'PRICE_AGREED', actor=user, ride=negotiation)
    except TSM.TransitionError as e:
        return _v4_error(e)

    negotiation = Negotiation.query.get(negotiation.id)
    return success_response("Negotiation updated", negotiation.to_dict())


@negotiations_bp.route('/api/negotiations-cancel', methods=['POST'])
@jwt_required_with_user
def cancel(user):
    """Cancel a negotiation / ride (v4: refund policy applies — see /api/rides/.../cancel-preview)."""
    from backend.services import trip_state_machine as TSM
    from backend.services.ride_actions import cancel as cancel_ride
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    try:
        cancel_ride('carhire', negotiation.id, actor=user, reason_code=(data.get('reason_code') or 'legacy_cancel'),
                    note=data.get('reason') or data.get('note'), legacy=True)
    except TSM.TransitionError as e:
        return _v4_error(e)

    return success_response("Negotiation cancelled", Negotiation.query.get(negotiation.id).to_dict())


@negotiations_bp.route('/api/negotiations-complete', methods=['POST'])
@jwt_required_with_user
def complete(user):
    """Complete or cancel a negotiation/trip.

    Flutter sends message_type='Complete' or message_type='Cancel'.
    """
    from backend.services import trip_state_machine as TSM
    from backend.services.ride_actions import cancel as cancel_ride
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    message_type = data.get('message_type', 'Complete')
    stage = TSM.ensure_stage('carhire', negotiation)

    try:
        if message_type == 'Cancel':
            cancel_ride('carhire', negotiation.id, actor=user, reason_code='legacy_cancel',
                        note=data.get('reason'), legacy=True)
            msg = "Trip cancelled"
        else:
            if user.id != negotiation.driver_id:
                return error_response("Only the assigned driver can complete this trip", status_code=403)
            if not _is_paid(negotiation) and not TSM.payment_secured('carhire', negotiation):
                return error_response("Payment must be completed before ending this trip")
            if stage != 'COMPLETED':
                TSM.walk_to('carhire', negotiation.id, 'COMPLETED', actor=user, legacy=True,
                            lat=data.get('latitude'), lng=data.get('longitude'))
            msg = "Trip completed"
    except TSM.TransitionError as e:
        return _v4_error(e)

    return success_response(msg, Negotiation.query.get(negotiation.id).to_dict())


@negotiations_bp.route('/api/negotiations-list', methods=['GET'])
@jwt_required_with_user
def list_all(user):
    """List all user's negotiations."""
    negotiations = Negotiation.query.filter(
        (Negotiation.customer_id == user.id) | (Negotiation.driver_id == user.id)
    ).order_by(Negotiation.created_at.desc()).all()

    return success_response("Success", [n.to_dict() for n in negotiations])


@negotiations_bp.route('/api/negotiations/<int:neg_id>/with-payment', methods=['GET'])
@jwt_required_with_user
def with_payment(user, neg_id):
    """Get negotiation with payment details."""
    negotiation = Negotiation.query.get(neg_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    from backend.models.payment import Payment
    payment = Payment.query.filter_by(negotiation_id=neg_id).first()

    return success_response("Success", {
        'negotiation': negotiation.to_dict(),
        'requires_payment': negotiation.status == 'Accepted',
        'payment_completed': negotiation.stripe_paid == 'Yes' if hasattr(negotiation, 'stripe_paid') else False,
        'payment': payment.to_dict() if payment else None,
    })


@negotiations_bp.route('/api/negotiations/<int:neg_id>/set-agreed-price', methods=['POST'])
@jwt_required_with_user
def set_agreed_price(user, neg_id):
    """Set agreed price (1000-1000000 cents)."""
    data = request.get_json(silent=True) or request.form
    agreed_price = int(data.get('agreed_price', 0))

    if agreed_price < 1000 or agreed_price > 1000000:
        return error_response("Agreed price must be between $10.00 and $10,000.00")

    negotiation = Negotiation.query.get(neg_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    negotiation.agreed_price = agreed_price
    db.session.commit()

    return success_response("Agreed price set", negotiation.to_dict())


@negotiations_bp.route('/api/negotiations-refresh-payment', methods=['POST'])
@jwt_required_with_user
def refresh_payment(user):
    """Generate/refresh Stripe payment link for negotiation."""
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    # v4: authorization hold via the payment service while the ride is payable.
    from backend.services import trip_state_machine as TSM
    from backend.services.payments import payment_service as PS
    stage = TSM.ensure_stage('carhire', negotiation)
    if stage in PS.PAYABLE_STAGES['carhire'] and negotiation.stripe_paid != 'Yes':
        if user.id != negotiation.customer_id:
            return error_response("Only the customer can pay for this ride", status_code=403)
        try:
            rp = PS.start_payment('carhire', negotiation, user,
                                  force_new=bool(data.get('force_regenerate', False)))
        except PS.PaymentError as e:
            db.session.rollback()
            return error_response(e.message, data={'error_code': e.code})
        negotiation = Negotiation.query.get(negotiation.id)
        return success_response("Payment link ready", {
            'negotiation_id': negotiation.id,
            'stripe_url': rp.checkout_url,
            'stripe_id': rp.checkout_session_id,
            'agreed_price': negotiation.agreed_price,
            'payment_status': 'paid' if rp.is_secured else 'pending',
            'stripe_paid': negotiation.stripe_paid,
            'is_paid': rp.is_secured,
            'ride_payment_id': rp.id,
            'capture_method': rp.capture_method,
        })

    # Already paid — no need to regenerate
    if negotiation.stripe_paid == 'Yes':
        return success_response("Already paid", {
            'negotiation_id': negotiation.id,
            'stripe_url': negotiation.stripe_url,
            'stripe_id': negotiation.stripe_id,
            'agreed_price': negotiation.agreed_price,
            'payment_status': 'paid',
            'stripe_paid': 'Yes',
            'is_paid': True,
        })

    force = data.get('force_regenerate', False)

    # Re-use existing session if not forcing regenerate and url exists
    if not force and negotiation.stripe_url and negotiation.stripe_session_id:
        return success_response("Payment link ready", {
            'negotiation_id': negotiation.id,
            'stripe_url': negotiation.stripe_url,
            'stripe_id': negotiation.stripe_id,
            'agreed_price': negotiation.agreed_price,
            'payment_status': negotiation.payment_status,
            'stripe_paid': negotiation.stripe_paid,
            'is_paid': False,
        })

    # Determine price in cents
    price_cents = 0
    if negotiation.agreed_price:
        price_cents = int(negotiation.agreed_price)
    elif negotiation.initial_price:
        price_cents = int(negotiation.initial_price)

    if price_cents < 50:
        return error_response("Price too low. Minimum is $0.50 (50 cents).")

    # Get customer email for Stripe
    customer_email = None
    try:
        customer = AdminUser.query.get(negotiation.customer_id)
        if customer:
            customer_email = customer.email
    except Exception:
        pass

    try:
        from backend.services.stripe_service import create_checkout_session

        result = create_checkout_session(
            amount_cents=price_cents,
            metadata={
                'negotiation_id': str(negotiation.id),
                'type': 'car_hire',
            },
            customer_email=customer_email,
        )

        negotiation.stripe_id = result['stripe_id']
        negotiation.stripe_session_id = result['session_id']
        negotiation.stripe_url = result['url']
        negotiation.payment_status = 'pending'
        db.session.commit()

        return success_response("Payment link generated", {
            'negotiation_id': negotiation.id,
            'stripe_url': negotiation.stripe_url,
            'stripe_id': negotiation.stripe_id,
            'agreed_price': negotiation.agreed_price,
            'payment_status': 'pending',
            'stripe_paid': negotiation.stripe_paid,
            'is_paid': False,
        })

    except Exception as e:
        return error_response(f"Failed to create payment session: {str(e)}")


@negotiations_bp.route('/api/negotiations-check-payment', methods=['POST'])
@jwt_required_with_user
def check_payment(user):
    """Check payment status for a negotiation — syncs with Stripe if session exists."""
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    # v4 ride payments (authorization hold): sync from the provider.
    from backend.services.payments import payment_service as PS
    rp = PS.latest_payment('carhire', negotiation.id)
    if rp is not None:
        if not rp.is_secured:
            PS.sync_from_provider(rp)
            rp = PS.latest_payment('carhire', negotiation.id)
        return success_response("Success", {
            'payment_status': 'paid' if rp.is_secured else ('failed' if rp.capture_status == 'failed' else 'pending'),
            'stripe_paid': 'Yes' if rp.is_secured else 'No',
            'is_paid': rp.is_secured,
            'stripe_url': rp.checkout_url,
            'capture_status': rp.capture_status,
        })

    # Already marked paid locally — return immediately
    if negotiation.stripe_paid == 'Yes':
        return success_response("Success", {
            'payment_status': 'paid',
            'stripe_paid': 'Yes',
            'is_paid': True,
            'stripe_url': negotiation.stripe_url,
        })

    # Sync with Stripe if we have a session
    if negotiation.stripe_session_id:
        try:
            from backend.services.stripe_service import check_session_status
            # Reuse the webhook's idempotent path so this poll ALSO credits the
            # driver's wallet (keyed on negotiation id) — otherwise a poll that
            # confirms payment before the webhook would leave the driver unpaid.
            from backend.routes.webhooks import _mark_negotiation_paid

            status_data = check_session_status(negotiation.stripe_session_id)

            if status_data.get('is_paid'):
                from datetime import datetime
                negotiation.payment_completed_at = datetime.utcnow()
                amount_cents = (
                    status_data.get('amount_total')
                    or negotiation.agreed_price
                    or negotiation.initial_price
                    or 0
                )
                _mark_negotiation_paid(
                    negotiation,
                    negotiation.stripe_session_id,
                    amount_cents,
                )  # records payment + credits driver + commits (all idempotent)

                return success_response("Success", {
                    'payment_status': 'paid',
                    'stripe_paid': 'Yes',
                    'is_paid': True,
                    'stripe_url': negotiation.stripe_url,
                })
        except Exception:
            # Stripe check failed — fall through to return current DB state
            db.session.rollback()

    # Auto-generate a Stripe session if none exists so the client gets a
    # payment URL.  Only do this for the customer on an accepted/started trip
    # that has a valid price.
    from backend.services import trip_state_machine as TSM
    if (user.id == negotiation.customer_id
            and TSM.ensure_stage('carhire', negotiation) in PS.PAYABLE_STAGES['carhire']):
        try:
            rp = PS.start_payment('carhire', negotiation, user)
            return success_response("Success", {
                'payment_status': 'pending', 'stripe_paid': 'No', 'is_paid': False,
                'stripe_url': rp.checkout_url, 'capture_status': rp.capture_status,
            })
        except PS.PaymentError:
            db.session.rollback()

    if (not negotiation.stripe_session_id
            and user.id == negotiation.customer_id
            and negotiation.status in ('Accepted', 'Started', 'Active')
            and not TSM.is_terminal('carhire', negotiation.trip_stage or 'REQUESTED')):
        price_cents = 0
        if negotiation.agreed_price:
            price_cents = int(negotiation.agreed_price)
        elif negotiation.initial_price:
            price_cents = int(negotiation.initial_price)

        if price_cents >= 50:
            customer_email = None
            try:
                customer = AdminUser.query.get(negotiation.customer_id)
                if customer:
                    customer_email = customer.email
            except Exception:
                pass

            try:
                from backend.services.stripe_service import create_checkout_session

                result = create_checkout_session(
                    amount_cents=price_cents,
                    metadata={
                        'negotiation_id': str(negotiation.id),
                        'type': 'car_hire',
                    },
                    customer_email=customer_email,
                )

                negotiation.stripe_id = result['stripe_id']
                negotiation.stripe_session_id = result['session_id']
                negotiation.stripe_url = result['url']
                negotiation.payment_status = 'pending'
                db.session.commit()

                return success_response("Success", {
                    'payment_status': 'pending',
                    'stripe_paid': negotiation.stripe_paid or 'No',
                    'is_paid': False,
                    'stripe_url': negotiation.stripe_url,
                })
            except Exception as e:
                # Session creation failed — fall through to return current state
                pass

    return success_response("Success", {
        'payment_status': negotiation.payment_status or 'unpaid',
        'stripe_paid': negotiation.stripe_paid or 'No',
        'is_paid': False,
        'stripe_url': negotiation.stripe_url,
    })


@negotiations_bp.route('/api/negotiations-test', methods=['GET'])
@jwt_required_with_user
def test(user):
    """Debug/test endpoint."""
    total = Negotiation.query.filter(
        (Negotiation.customer_id == user.id) | (Negotiation.driver_id == user.id)
    ).count()

    return success_response("Success", {
        'message': 'Negotiations API working',
        'user_id': user.id,
        'total_negotiations': total,
    })
