import os
import uuid
from datetime import datetime

from flask import Blueprint, request, current_app
from werkzeug.utils import secure_filename
from backend.models import db
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

bookings_bp = Blueprint('bookings', __name__)


def _is_courier(booking_or_data):
    service = ''
    if isinstance(booking_or_data, dict):
        service = str(booking_or_data.get('service_type', '')).strip().lower()
    else:
        service = str(getattr(booking_or_data, 'service_type', '')).strip().lower()
    return service in ('courier', 'delivery')


def _to_bool(value):
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _save_booking_image(booking_id: int, image_file, prefix: str):
    ext = image_file.filename.rsplit('.', 1)[-1].lower() if '.' in image_file.filename else 'jpg'
    if ext not in ('jpg', 'jpeg', 'png', 'webp'):
        return None, "Unsupported image format"

    filename = secure_filename(
        f"{prefix}_{booking_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.{ext}"
    )
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'courier_proofs')
    os.makedirs(upload_dir, exist_ok=True)
    image_file.save(os.path.join(upload_dir, filename))
    return f"courier_proofs/{filename}", None


@bookings_bp.route('/api/bookings', methods=['GET'])
@jwt_required_with_user
def index(user):
    """List bookings – admin (id=1) sees all, others see own."""
    status = request.args.get('status')

    if user.id == 1:
        q = ScheduledBooking.query
    else:
        q = ScheduledBooking.query.filter(
            (ScheduledBooking.customer_id == user.id) |
            (ScheduledBooking.driver_id == user.id)
        )

    if status:
        q = q.filter_by(status=status)

    bookings = q.order_by(ScheduledBooking.created_at.desc()).all()
    return success_response("Success", [b.to_dict() for b in bookings])


@bookings_bp.route('/api/bookings', methods=['POST'])
@jwt_required_with_user
def create(user):
    """Create a scheduled booking."""
    data = request.get_json(silent=True) or request.form

    customer_proposed_price = int(data.get('customer_proposed_price', 0))
    if customer_proposed_price < 50:
        return error_response("Minimum price is $0.50 (50 cents)")

    passengers = int(data.get('passengers', 1))
    if passengers < 1 or passengers > 10:
        return error_response("Passengers must be between 1 and 10")

    luggage = int(data.get('luggage', 0))
    if luggage > 20:
        return error_response("Maximum 20 pieces of luggage")

    guidelines_accepted = _to_bool(data.get('community_guidelines_accepted', False))
    guidelines_accepted_at = datetime.utcnow() if guidelines_accepted else None

    if _is_courier(data) and not guidelines_accepted:
        return error_response("You must accept community guidelines for courier orders")

    booking = ScheduledBooking(
        customer_id=user.id,
        service_type=data.get('service_type'),
        automobile_type=data.get('automobile_type'),
        pickup_lat=data.get('pickup_lat'),
        pickup_lng=data.get('pickup_lng'),
        pickup_place_name=data.get('pickup_place_name'),
        pickup_address=data.get('pickup_address'),
        pickup_description=data.get('pickup_description'),
        destination_lat=data.get('destination_lat'),
        destination_lng=data.get('destination_lng'),
        destination_place_name=data.get('destination_place_name'),
        destination_address=data.get('destination_address'),
        destination_description=data.get('destination_description'),
        passengers=passengers,
        luggage=luggage,
        luggage_weight_lbs=data.get('luggage_weight_lbs'),
        luggage_description=data.get('luggage_description'),
        message=data.get('message'),
        scheduled_at=data.get('scheduled_at'),
        customer_proposed_price=customer_proposed_price,
        status='pending',
        community_guidelines_accepted=guidelines_accepted,
        community_guidelines_accepted_at=guidelines_accepted_at,
    )
    db.session.add(booking)
    db.session.commit()

    # TODO: Notify admin via SMS

    return success_response("Booking created", booking.to_dict(), status_code=201)


@bookings_bp.route('/api/bookings/courier-batch', methods=['POST'])
@jwt_required_with_user
def create_courier_batch(user):
    """Create chained courier bookings in one batch for multi-parcel delivery."""
    data = request.get_json(silent=True) or request.form
    service_type = (data.get('service_type') or '').strip().lower()
    if service_type not in ('courier', 'delivery'):
        return error_response("service_type must be courier or delivery")

    if not _to_bool(data.get('community_guidelines_accepted', False)):
        return error_response("You must accept community guidelines before creating courier batch")

    parcels = data.get('parcels')
    if not isinstance(parcels, list) or len(parcels) == 0:
        return error_response("parcels must be a non-empty list")

    if len(parcels) > 150:
        return error_response("Maximum 150 parcel stops per batch")

    batch_id = uuid.uuid4().hex[:16]
    now = datetime.utcnow()
    created = []

    for idx, parcel in enumerate(parcels, start=1):
        try:
            customer_price = int(parcel.get('customer_proposed_price', data.get('customer_proposed_price', 0)))
        except Exception:
            customer_price = 0

        if customer_price < 50:
            return error_response(f"Parcel #{idx}: minimum price is $0.50 (50 cents)")

        booking = ScheduledBooking(
            customer_id=user.id,
            service_type='courier',
            automobile_type=data.get('automobile_type', 'Courier'),
            pickup_lat=parcel.get('pickup_lat') or data.get('pickup_lat'),
            pickup_lng=parcel.get('pickup_lng') or data.get('pickup_lng'),
            pickup_place_name=parcel.get('pickup_place_name') or data.get('pickup_place_name'),
            pickup_address=parcel.get('pickup_address') or data.get('pickup_address'),
            pickup_description=parcel.get('pickup_description') or data.get('pickup_description'),
            destination_lat=parcel.get('destination_lat'),
            destination_lng=parcel.get('destination_lng'),
            destination_place_name=parcel.get('destination_place_name'),
            destination_address=parcel.get('destination_address'),
            destination_description=parcel.get('destination_description'),
            passengers=1,
            luggage=int(parcel.get('luggage', data.get('luggage', 1)) or 1),
            luggage_weight_lbs=int(parcel.get('luggage_weight_lbs', data.get('luggage_weight_lbs', 0)) or 0),
            luggage_description=parcel.get('luggage_description') or data.get('luggage_description'),
            message=parcel.get('message') or data.get('message'),
            scheduled_at=parcel.get('scheduled_at') or data.get('scheduled_at'),
            customer_proposed_price=customer_price,
            status='pending',
            community_guidelines_accepted=True,
            community_guidelines_accepted_at=now,
            courier_batch_id=batch_id,
            courier_sequence=idx,
            courier_total=len(parcels),
        )
        db.session.add(booking)
        created.append(booking)

    db.session.flush()

    for i in range(len(created) - 1):
        created[i].courier_next_booking_id = created[i + 1].id

    db.session.commit()

    return success_response("Courier batch created", {
        'batch_id': batch_id,
        'total': len(created),
        'bookings': [b.to_dict() for b in created],
    }, status_code=201)


@bookings_bp.route('/api/bookings/<int:booking_id>', methods=['GET'])
@jwt_required_with_user
def show(user, booking_id):
    """Show a single booking."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    # Access control: customer, driver, or admin
    if user.id not in (booking.customer_id, booking.driver_id, 1):
        return error_response("Unauthorized", status_code=403)

    return success_response("Success", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/cancel', methods=['POST'])
@jwt_required_with_user
def cancel(user, booking_id):
    """Customer cancels booking."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    data = request.get_json(silent=True) or request.form
    booking.status = 'cancelled'
    booking.cancellation_reason = data.get('reason')
    db.session.commit()

    return success_response("Booking cancelled", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/propose-price', methods=['POST'])
@jwt_required_with_user
def propose_price(user, booking_id):
    """Driver proposes a counter-price."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    data = request.get_json(silent=True) or request.form
    price = int(data.get('price', 0))
    if price < 50:
        return error_response("Minimum price is $0.50 (50 cents)")

    booking.driver_proposed_price = price
    booking.status = 'price_negotiating'
    db.session.commit()

    # TODO: SMS to customer

    return success_response("Price proposed", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/accept-price', methods=['POST'])
@jwt_required_with_user
def accept_price(user, booking_id):
    """Customer accepts driver's proposed price. Generates Stripe link."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    booking.agreed_price = booking.driver_proposed_price
    booking.status = 'price_accepted'
    db.session.commit()

    # TODO: Generate Stripe Checkout Session via services/stripe_service.py

    return success_response("Price accepted", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/accept-original-price', methods=['POST'])
@jwt_required_with_user
def accept_original_price(user, booking_id):
    """Driver accepts customer's original price. Generates Stripe link."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    booking.agreed_price = booking.customer_proposed_price
    booking.status = 'price_accepted'
    db.session.commit()

    # TODO: Generate Stripe Checkout Session + SMS to customer

    return success_response("Original price accepted", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/assign-driver', methods=['POST'])
@jwt_required_with_user
def assign_driver(user, booking_id):
    """Admin assigns a driver to a booking (admin only, id=1)."""
    if user.id != 1:
        return error_response("Admin access required", status_code=403)

    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    data = request.get_json(silent=True) or request.form
    driver_id = data.get('driver_id')
    driver = AdminUser.query.get(driver_id)
    if not driver:
        return error_response("Driver not found", status_code=404)

    booking.driver_id = driver.id
    booking.status = 'driver_assigned'
    db.session.commit()

    # TODO: SMS to driver

    return success_response("Driver assigned", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/start', methods=['POST'])
@jwt_required_with_user
def start(user, booking_id):
    """Driver starts the trip."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    if booking.status not in ('confirmed',):
        return error_response("Booking must be confirmed and paid before starting")

    if user.id not in (booking.driver_id, 1):
        return error_response("Only assigned driver or admin can start this booking", status_code=403)

    if _is_courier(booking) and booking.courier_batch_id:
        previous_incomplete = ScheduledBooking.query.filter(
            ScheduledBooking.courier_batch_id == booking.courier_batch_id,
            ScheduledBooking.courier_sequence < booking.courier_sequence,
            ScheduledBooking.status != 'completed',
        ).count()
        if previous_incomplete > 0:
            return error_response(
                "Complete earlier courier stops first. Batch deliveries must be completed in order.",
                status_code=409,
            )

    booking.status = 'in_progress'
    booking.started_at = datetime.utcnow()
    db.session.commit()

    return success_response("Trip started", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/complete', methods=['POST'])
@jwt_required_with_user
def complete(user, booking_id):
    """Driver completes the trip."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    if user.id not in (booking.driver_id, 1):
        return error_response("Only assigned driver or admin can complete this booking", status_code=403)

    if _is_courier(booking):
        if not booking.pickup_proof_image:
            return error_response("Pickup proof photo is required before completing courier booking")
        if not booking.dropoff_proof_image:
            return error_response("Dropoff proof photo is required before completing courier booking")

    data = request.get_json(silent=True) or request.form
    booking.status = 'completed'
    booking.completed_at = datetime.utcnow()
    booking.driver_notes = data.get('driver_notes')

    # Auto-advance next booking in courier chain so the driver can continue.
    if _is_courier(booking) and booking.courier_next_booking_id:
        nxt = ScheduledBooking.query.get(booking.courier_next_booking_id)
        if nxt and nxt.status == 'pending':
            nxt.status = 'driver_assigned'
            nxt.driver_id = booking.driver_id
            nxt.assigned_at = datetime.utcnow()

    db.session.commit()

    return success_response("Trip completed", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/refresh-payment', methods=['POST'])
@jwt_required_with_user
def refresh_payment(user, booking_id):
    """Get/refresh Stripe payment link (customer only)."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    # TODO: Stripe Checkout Session via services/stripe_service.py

    return success_response("Payment link refreshed", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/check-payment', methods=['POST'])
@jwt_required_with_user
def check_payment(user, booking_id):
    """Verify Stripe payment status."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    # TODO: Sync with Stripe via services/stripe_service.py

    return success_response("Success", {
        'booking': booking.to_dict(),
        'payment_status': getattr(booking, 'payment_status', 'pending'),
        'is_paid': getattr(booking, 'stripe_paid', 'No') == 'Yes',
    })


@bookings_bp.route('/api/bookings/<int:booking_id>/mark-paid', methods=['POST'])
@jwt_required_with_user
def mark_paid(user, booking_id):
    """Admin force-marks a booking as paid (admin only, id=1)."""
    if user.id != 1:
        return error_response("Admin access required", status_code=403)

    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    booking.payment_status = 'paid'
    booking.stripe_paid = True
    booking.status = 'confirmed'
    booking.confirmed_at = datetime.utcnow()
    db.session.commit()

    return success_response("Marked as paid", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/pickup-proof', methods=['POST'])
@jwt_required_with_user
def upload_pickup_proof(user, booking_id):
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    if user.id not in (booking.driver_id, 1):
        return error_response("Only assigned driver or admin can upload pickup proof", status_code=403)

    image_file = request.files.get('photo') or request.files.get('image') or request.files.get('file')
    if not image_file or not image_file.filename:
        return error_response("photo file is required")

    saved, err = _save_booking_image(booking.id, image_file, 'pickup')
    if err:
        return error_response(err)

    booking.pickup_proof_image = saved
    booking.pickup_proof_uploaded_at = datetime.utcnow()
    db.session.commit()
    return success_response("Pickup proof uploaded", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/dropoff-proof', methods=['POST'])
@jwt_required_with_user
def upload_dropoff_proof(user, booking_id):
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    if user.id not in (booking.driver_id, 1):
        return error_response("Only assigned driver or admin can upload dropoff proof", status_code=403)

    image_file = request.files.get('photo') or request.files.get('image') or request.files.get('file')
    if not image_file or not image_file.filename:
        return error_response("photo file is required")

    saved, err = _save_booking_image(booking.id, image_file, 'dropoff')
    if err:
        return error_response(err)

    booking.dropoff_proof_image = saved
    booking.dropoff_proof_uploaded_at = datetime.utcnow()
    db.session.commit()
    return success_response("Dropoff proof uploaded", booking.to_dict())


@bookings_bp.route('/api/bookings/courier-batch/<batch_id>/next', methods=['GET'])
@jwt_required_with_user
def courier_batch_next(user, batch_id):
    """Get next pending stop in a courier batch for progress chaining."""
    q = ScheduledBooking.query.filter_by(courier_batch_id=batch_id)
    if user.id != 1:
        q = q.filter(
            (ScheduledBooking.customer_id == user.id) | (ScheduledBooking.driver_id == user.id)
        )

    next_booking = q.filter(ScheduledBooking.status != 'completed').order_by(
        ScheduledBooking.courier_sequence.asc()
    ).first()

    if not next_booking:
        return success_response("Batch completed", {'batch_id': batch_id, 'next_booking': None})

    return success_response("Success", {
        'batch_id': batch_id,
        'next_booking': next_booking.to_dict(),
    })
