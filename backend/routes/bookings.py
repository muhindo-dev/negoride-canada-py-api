from flask import Blueprint, request
from backend.models import db
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

bookings_bp = Blueprint('bookings', __name__)


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
    )
    db.session.add(booking)
    db.session.commit()

    # TODO: Notify admin via SMS

    return success_response("Booking created", booking.to_dict(), status_code=201)


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

    booking.final_price = booking.driver_proposed_price
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

    booking.final_price = booking.customer_proposed_price
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

    booking.status = 'in_progress'
    db.session.commit()

    return success_response("Trip started", booking.to_dict())


@bookings_bp.route('/api/bookings/<int:booking_id>/complete', methods=['POST'])
@jwt_required_with_user
def complete(user, booking_id):
    """Driver completes the trip."""
    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    data = request.get_json(silent=True) or request.form
    booking.status = 'completed'
    booking.driver_notes = data.get('driver_notes')
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
    db.session.commit()

    return success_response("Marked as paid", booking.to_dict())
