from flask import Blueprint, request
from backend.models import db
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.models.trip_note import TripNote
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

trips_bp = Blueprint('trips', __name__)


def _int(val):
    """Convert a value to int, returning None for empty/null/invalid inputs.

    MySQL rejects empty strings for INTEGER columns; this ensures we always
    pass either a real integer or NULL rather than an empty string.
    """
    if val is None or val == '':
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _str(val):
    """Return None instead of an empty string for optional text columns."""
    if val is None or val == '':
        return None
    return str(val).strip()


def _trip_notes_add_impl(user):
    """Shared implementation for adding a trip note."""
    data = request.get_json(silent=True) or request.form or {}

    # Accept both snake_case and camelCase payload keys.
    trip_id = data.get('trip_id') or data.get('tripId')
    note_raw = data.get('note') or data.get('note_text') or data.get('noteText')
    note_text = note_raw.strip() if isinstance(note_raw, str) else ''

    if not trip_id:
        return error_response("Trip ID is required.")

    if not note_text or len(note_text) < 3:
        return error_response("Note must be at least 3 characters long.")

    trip = Trip.query.get(trip_id)
    if not trip:
        return error_response("Trip not found.", status_code=404)

    # Verify user has access (driver or passenger)
    is_driver = (trip.driver_id == user.id)
    is_passenger = TripBooking.query.filter_by(trip_id=trip.id, customer_id=user.id).first() is not None

    if not is_driver and not is_passenger:
        return error_response("You do not have access to this trip.")

    note_type = 'driver' if is_driver else 'passenger'

    note = TripNote(
        trip_id=trip.id,
        user_id=user.id,
        note=note_text,
        note_type=note_type,
    )

    try:
        db.session.add(note)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return error_response(f"Failed to add note: {str(e)}")

    return success_response("Note added successfully.", {
        'id': note.id,
        'note': note.note,
        'note_type': note.note_type,
        'created_at': note.created_at.strftime('%Y-%m-%d %H:%M:%S') if note.created_at else None,
        'author_name': user.name,
        'author_id': user.id,
    })


@trips_bp.route('/api/trips', methods=['GET'])
@jwt_required_with_user
def index(user):
    """Get all trips for the current user."""
    if user.user_type in ('Driver', 'Admin', 'Super Admin'):
        trips = Trip.query.filter_by(driver_id=user.id).order_by(Trip.created_at.desc()).all()
    else:
        trips = Trip.query.filter_by(status='Active').order_by(Trip.created_at.desc()).all()

    return success_response("Success", [t.to_dict() for t in trips])


@trips_bp.route('/api/trips-bookings', methods=['GET'])
@jwt_required_with_user
def list_bookings(user):
    """Get trip bookings for the current user (customer or driver), enriched with trip + contact info."""
    if user.user_type in ('Driver', 'Admin', 'Super Admin'):
        trip_ids = [t.id for t in Trip.query.with_entities(Trip.id).filter_by(driver_id=user.id).all()]
        bookings = (TripBooking.query.filter(TripBooking.trip_id.in_(trip_ids))
                    .order_by(TripBooking.created_at.desc()).all()) if trip_ids else []
    else:
        bookings = (TripBooking.query.filter_by(customer_id=user.id)
                    .order_by(TripBooking.created_at.desc()).all())

    # Pre-fetch related records in bulk to avoid N+1 queries
    trip_ids_needed = list({b.trip_id for b in bookings})
    user_ids_needed = list({uid for b in bookings for uid in (b.driver_id, b.customer_id) if uid})
    trips_map = {t.id: t for t in Trip.query.filter(Trip.id.in_(trip_ids_needed)).all()} if trip_ids_needed else {}
    users_map = {u.id: u for u in AdminUser.query.filter(AdminUser.id.in_(user_ids_needed)).all()} if user_ids_needed else {}

    result = []
    for b in bookings:
        d = b.to_dict()
        trip = trips_map.get(b.trip_id)
        if trip:
            d['start_name'] = trip.start_name or ''
            d['end_name'] = trip.end_name or ''
            d['start_gps'] = trip.start_gps or ''
            d['end_gps'] = trip.end_pgs or ''
            d['trip_text'] = f"{trip.start_name or ''} → {trip.end_name or ''}"
        else:
            d['start_name'] = ''
            d['end_name'] = ''
            d['start_gps'] = ''
            d['end_gps'] = ''
        driver = users_map.get(b.driver_id)
        customer = users_map.get(b.customer_id)
        d['driver_contact'] = driver.phone_number or '' if driver else ''
        d['driver_text'] = f"{driver.first_name or ''} {driver.last_name or ''}".strip() if driver else ''
        d['customer_contact'] = customer.phone_number or '' if customer else ''
        d['customer_text'] = f"{customer.first_name or ''} {customer.last_name or ''}".strip() if customer else ''
        result.append(d)

    return success_response("Success", result)


@trips_bp.route('/api/trips-create', methods=['POST'])
@jwt_required_with_user
def create(user):
    """Create a new trip."""
    data = request.get_json(silent=True) or request.form

    trip = Trip(
        driver_id=user.id,
        start_name=_str(data.get('start_name') or data.get('start_location')),
        end_name=_str(data.get('end_name') or data.get('end_location')),
        start_gps=_str(data.get('start_gps')),
        end_pgs=_str(data.get('end_pgs') or data.get('end_gps')),
        start_address=_str(data.get('start_address')),
        end_address=_str(data.get('end_address')),
        start_stage_id=_int(data.get('start_stage_id')),
        end_stage_id=_int(data.get('end_stage_id')),
        scheduled_start_time=_str(data.get('scheduled_start_time') or data.get('date')),
        scheduled_end_time=_str(data.get('scheduled_end_time')),
        start_time=_str(data.get('start_time')),
        end_time=_str(data.get('end_time')),
        vehicel_reg_number=_str(data.get('vehicel_reg_number')),
        car_model=_str(data.get('car_model')),
        price=_int(data.get('price')),
        slots=_int(data.get('slots')) or 1,
        details=_str(data.get('details')),
        status='Active',
    )

    db.session.add(trip)
    db.session.commit()

    return success_response("Trip created", trip.to_dict(), status_code=201)


@trips_bp.route('/api/trips-update', methods=['POST'])
@jwt_required_with_user
def update(user):
    """Update a trip."""
    data = request.get_json(silent=True) or request.form
    trip_id = data.get('trip_id')

    trip = Trip.query.get(trip_id)
    if not trip:
        return error_response("Trip not found", status_code=404)

    if trip.driver_id != user.id and user.user_type not in ('Admin', 'Super Admin'):
        return error_response("Unauthorized", status_code=403)

    updatable_str = ['start_name', 'end_name', 'start_gps', 'end_pgs', 'start_address',
                     'end_address', 'scheduled_start_time', 'scheduled_end_time',
                     'vehicel_reg_number', 'car_model', 'status', 'details']
    updatable_int = ['start_stage_id', 'end_stage_id', 'price', 'slots']

    for field in updatable_str:
        if field in data:
            setattr(trip, field, _str(data[field]))
    for field in updatable_int:
        if field in data:
            val = _int(data[field])
            if val is not None:
                setattr(trip, field, val)

    db.session.commit()
    return success_response("Trip updated", trip.to_dict())


import math

def _haversine(lat1, lon1, lat2, lon2):
    """Calculate distance in km between two GPS points."""
    R = 6371  # Earth radius in km
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# Map automobile type → (is_X field, is_X_approved field)
_AUTOMOBILE_MAP = {
    'car': ('is_car', 'is_car_approved'),
    'special car': ('is_car', 'is_car_approved'),
    'special car hire': ('is_car', 'is_car_approved'),
    'bodaboda': ('is_boda', 'is_boda_approved'),
    'boda': ('is_boda', 'is_boda_approved'),
    'courier': ('is_delivery', 'is_delivery_approved'),
    'delivery': ('is_delivery', 'is_delivery_approved'),
    'movers': ('is_ambulance', 'is_ambulance_approved'),
    'ambulance': ('is_ambulance', 'is_ambulance_approved'),
    'airport pickup': ('is_breakdown', 'is_breakdown_approved'),
    'pickup': ('is_breakdown', 'is_breakdown_approved'),
    'breakdown': ('is_breakdown', 'is_breakdown_approved'),
    'police': ('is_police', 'is_police_approved'),
    'firebrugade': ('is_firebrugade', 'is_firebrugade_approved'),
}


@trips_bp.route('/api/trips-drivers', methods=['POST'])
@jwt_required_with_user
def get_drivers(user):
    """Get available online drivers, filtered by automobile type and sorted by distance."""
    data = request.get_json(silent=True) or request.form

    automobile = (data.get('automobile') or '').strip().lower()
    current_address = data.get('current_address', '')

    if not automobile:
        return error_response("You have not specified your automobile.")

    if automobile not in _AUTOMOBILE_MAP:
        return error_response(
            "Invalid automobile type. Accepted types are: Special Car, Airport Pickup, Movers, Courier."
        )

    if not current_address or ',' not in current_address:
        return error_response("You have not specified your current address.")

    parts = current_address.split(',')
    if len(parts) != 2:
        return error_response("Invalid GPS coordinates format.")

    try:
        customer_lat = float(parts[0].strip())
        customer_lng = float(parts[1].strip())
    except ValueError:
        return error_response("Invalid GPS coordinates.")

    field_key, _ = _AUTOMOBILE_MAP[automobile]

    # Base query: active drivers who are online, excluding the requesting user
    query = AdminUser.query.filter(
        AdminUser.status == 1,
        AdminUser.id != user.id,
        AdminUser.ready_for_trip == 'Yes',
    )

    # For car/special car: any Driver who is online (in Canada all drivers have cars)
    if automobile in ('car', 'special car', 'special car hire'):
        query = query.filter(
            db.or_(
                AdminUser.user_type.ilike('%driver%'),
                AdminUser.is_car == 'Yes',
            )
        )
    else:
        query = query.filter(getattr(AdminUser, field_key) == 'Yes')

    drivers = query.order_by(AdminUser.updated_at.desc()).limit(1000).all()

    result = []
    for d in drivers:
        # Try current_latitude/current_longitude first, fall back to parsing current_address
        d_lat = None
        d_lng = None
        if d.current_latitude is not None and d.current_longitude is not None:
            try:
                d_lat = float(d.current_latitude)
                d_lng = float(d.current_longitude)
            except (ValueError, TypeError):
                pass

        if d_lat is None or d_lng is None:
            addr = (d.current_address or '')
            if ',' not in addr:
                continue
            d_parts = addr.split(',')
            if len(d_parts) != 2:
                continue
            try:
                d_lat = float(d_parts[0].strip())
                d_lng = float(d_parts[1].strip())
            except ValueError:
                continue

        if d_lat is None or d_lng is None:
            continue
        if d_lat == 0 and d_lng == 0:
            continue

        distance = round(_haversine(customer_lat, customer_lng, d_lat, d_lng), 2)

        # Estimate travel time
        min_time_h = distance / 80
        max_time_h = distance / 60

        def _fmt(hours):
            h = int(hours)
            m = int((hours - h) * 60)
            if h < 1:
                return f"{m} minutes"
            return f"{h}hr and {m}min"

        driver_dict = d.to_dict()
        driver_dict['distance'] = distance
        driver_dict['min_time'] = _fmt(min_time_h)
        driver_dict['max_time'] = _fmt(max_time_h)
        result.append((distance, driver_dict))

    # Sort by distance (closest first)
    result.sort(key=lambda x: x[0])
    data_list = [item[1] for item in result]

    message = (f"Found {len(data_list)} drivers nearby, sorted by distance."
               if data_list else "No available drivers found in your area.")

    return success_response(message, data_list)


@trips_bp.route('/api/trips-driver-bookings', methods=['GET'])
@jwt_required_with_user
def driver_bookings(user):
    """Get driver's trip bookings."""
    trips = Trip.query.filter_by(driver_id=user.id).all()
    trip_ids = [t.id for t in trips]
    if not trip_ids:
        return success_response("Success", [])
    bookings = TripBooking.query.filter(TripBooking.trip_id.in_(trip_ids)).order_by(TripBooking.created_at.desc()).all()

    return success_response("Success", [b.to_dict() for b in bookings])


@trips_bp.route('/api/trips-bookings-create', methods=['POST'])
@jwt_required_with_user
def create_booking(user):
    """Create a trip booking."""
    data = request.get_json(silent=True) or request.form

    trip = Trip.query.get(data.get('trip_id'))
    if not trip:
        return error_response("Trip not found", status_code=404)

    booking = TripBooking(
        trip_id=trip.id,
        customer_id=user.id,
        driver_id=trip.driver_id or 0,
        start_stage_id=data.get('start_stage_id') or trip.start_stage_id or 0,
        end_stage_id=data.get('end_stage_id') or trip.end_stage_id or 0,
        slot_count=data.get('slot_count') or data.get('seats', 1),
        price=data.get('price', trip.price),
        customer_note=data.get('customer_note'),
        status='Pending',
    )

    db.session.add(booking)
    db.session.commit()

    return success_response("Booking created", booking.to_dict(), status_code=201)


@trips_bp.route('/api/trips-bookings-update', methods=['POST'])
@jwt_required_with_user
def update_booking(user):
    """Update a trip booking."""
    data = request.get_json(silent=True) or request.form
    booking_id = data.get('booking_id')

    booking = TripBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    for field in ['status', 'slot_count', 'price', 'driver_notes', 'customer_note']:
        if field in data and data[field] is not None:
            setattr(booking, field, data[field])

    db.session.commit()
    return success_response("Booking updated", booking.to_dict())


@trips_bp.route('/api/trips-booking-status-update', methods=['POST'])
@jwt_required_with_user
def update_booking_status(user):
    """Update trip booking status."""
    data = request.get_json(silent=True) or request.form
    booking_id = data.get('booking_id')
    new_status = data.get('status')

    booking = TripBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    booking.status = new_status
    db.session.commit()

    return success_response("Booking status updated", booking.to_dict())


@trips_bp.route('/api/get-available-trips', methods=['POST'])
@jwt_required_with_user
def search_available(user):
    """Search for available trips by location."""
    data = request.get_json(silent=True) or request.form

    trips = Trip.query.filter_by(status='Active').order_by(Trip.created_at.desc()).all()

    return success_response("Success", [t.to_dict() for t in trips])


# ==============================================================================
# TRIP NOTES
# ==============================================================================

@trips_bp.route('/api/trip-notes', methods=['GET'])
@jwt_required_with_user
def trip_notes_get(user):
    """Get all notes for a trip."""
    trip_id = request.args.get('trip_id')
    if not trip_id:
        return error_response("Trip ID is required.")

    trip = Trip.query.get(trip_id)
    if not trip:
        return error_response("Trip not found.", status_code=404)

    # Verify user has access (driver or passenger)
    has_access = (trip.driver_id == user.id) or \
        TripBooking.query.filter_by(trip_id=trip.id, customer_id=user.id).first() is not None

    if not has_access:
        return error_response("You do not have access to this trip.")

    notes = TripNote.query.filter_by(trip_id=trip.id).order_by(TripNote.created_at.desc()).all()

    formatted_notes = []
    for note in notes:
        author = AdminUser.query.get(note.user_id)
        formatted_notes.append({
            'id': note.id,
            'note': note.note,
            'note_type': note.note_type,
            'created_at': note.created_at.strftime('%Y-%m-%d %H:%M:%S') if note.created_at else None,
            'author_name': author.name if author else 'Unknown',
            'author_id': note.user_id,
        })

    return success_response("Success", {'notes': formatted_notes, 'total': len(formatted_notes)})


@trips_bp.route('/api/trip-notes', methods=['POST'])
@jwt_required_with_user
def trip_notes_add_legacy(user):
    """Backward-compatible add endpoint for clients posting to /api/trip-notes."""
    return _trip_notes_add_impl(user)


@trips_bp.route('/api/trip-notes-add', methods=['POST'])
@jwt_required_with_user
def trip_notes_add(user):
    """Add a new note to a trip."""
    return _trip_notes_add_impl(user)
