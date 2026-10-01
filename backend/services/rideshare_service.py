"""Rideshare seat booking (spec §18.1) — shared by the legacy
/api/trips-bookings-create endpoint and the v4 rideshare endpoints.

  • seat inventory is locked transactionally (SELECT … FOR UPDATE on the trip),
    so two customers can never book the last seat
  • Instant booking (default) → PENDING_PAYMENT; Request to book → REQUESTED
    (driver approves within 30 min, otherwise auto-declined)
  • optional price-per-seat negotiation within the driver's bounds
"""
from datetime import datetime, timedelta
from decimal import Decimal

from backend.models import db
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.services import settings_service as S
from backend.services import trip_state_machine as TSM


class BookingError(Exception):
    def __init__(self, message, code='booking_error', status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


HOLDING_STAGES = ('REQUESTED', 'PENDING_PAYMENT', 'CONFIRMED', 'DRIVER_ARRIVED', 'CHECKED_IN', 'RIDING')


def seat_price_cents(trip):
    if trip.price_per_seat_cents:
        return int(trip.price_per_seat_cents)
    if trip.price:
        return int(Decimal(trip.price) * 100)   # legacy: dollars per seat
    return 0


def seats_taken(trip_id, exclude_booking_id=None, locking=False):
    """Seats held on a trip. `locking=True` uses a locking read, which sees the
    latest committed rows even when the transaction's REPEATABLE READ snapshot
    was taken earlier (e.g. by the auth lookup) — required for the seat lock."""
    q = TripBooking.query.filter(TripBooking.trip_id == trip_id)
    if locking:
        q = q.with_for_update()
    rows = q.all()
    total = 0
    for b in rows:
        if exclude_booking_id and b.id == exclude_booking_id:
            continue
        stage = b.trip_stage or TSM.R.derive_stage('rideshare_booking', b)
        if stage in HOLDING_STAGES:
            total += int(b.slot_count or 1)
    return total


def seats_left(trip):
    return max(0, int(trip.slots or 0) - seats_taken(trip.id))


def is_bookable(trip):
    stage = trip.trip_stage or TSM.R.derive_stage('rideshare_trip', trip)
    if stage not in ('PUBLISHED', 'BOARDING'):
        return False
    if trip.departure_at and trip.departure_at < datetime.utcnow() - timedelta(minutes=5):
        return False
    return True


def create_booking(customer, trip_id, seats=1, offered_price_per_seat_cents=None, pickup=None, note=None,
                   commit=True):
    """Book seats on a published trip. Returns the TripBooking (PENDING_PAYMENT or REQUESTED)."""
    from backend.services.phone_verification import PHONE_REQUIRED_MESSAGE, ride_phone_block
    _pv_block = ride_phone_block(customer)   # ff.phone_required_signup (§11.2 #1)
    if _pv_block is not None:
        raise BookingError(PHONE_REQUIRED_MESSAGE, code='phone_verification_required', status=403)
    try:
        seats = int(seats or 1)
    except (TypeError, ValueError):
        raise BookingError('Invalid number of seats.')
    if seats < 1 or seats > 8:
        raise BookingError('You can book between 1 and 8 seats.')
    trip = Trip.query.filter(Trip.id == int(trip_id)).with_for_update().first()   # seat lock
    if not trip:
        raise BookingError('Trip not found.', code='not_found', status=404)
    TSM.ensure_stage('rideshare_trip', trip)
    if trip.driver_id == customer.id:
        raise BookingError("You can't book a seat on your own trip.", code='own_trip')
    if not is_bookable(trip):
        raise BookingError('This trip is no longer taking bookings.', code='not_bookable', status=409)
    existing = TripBooking.query.filter(TripBooking.trip_id == trip.id, TripBooking.customer_id == customer.id,
                                        TripBooking.trip_stage.in_(HOLDING_STAGES)).with_for_update().first()
    if existing:
        raise BookingError('You already have a booking on this trip.', code='duplicate', status=409)
    left = int(trip.slots or 0) - seats_taken(trip.id, locking=True)
    if seats > left:
        raise BookingError(f'Only {max(0, left)} seat(s) left on this trip.', code='sold_out', status=409)

    list_price = seat_price_cents(trip)
    per_seat = list_price
    negotiated = False
    if offered_price_per_seat_cents not in (None, '', 0):
        offer = int(offered_price_per_seat_cents)
        if not (trip.allow_seat_negotiation and S.flag('rideshare_seat_negotiation')):
            raise BookingError('The driver has fixed the price for this trip.', code='no_negotiation')
        floor = int(trip.min_seat_price_cents or list_price)
        if offer < floor or offer > list_price:
            from backend.utils.money import fmt
            raise BookingError(f'Offer must be between {fmt(floor)} and {fmt(list_price)} per seat.',
                               code='offer_out_of_bounds')
        per_seat, negotiated = offer, offer != list_price
    if per_seat < 50:
        raise BookingError('This trip has no valid seat price yet.', code='no_price')

    request_mode = trip.booking_mode == 'request' or negotiated
    booking = TripBooking(
        trip_id=trip.id, customer_id=customer.id, driver_id=trip.driver_id or 0,
        start_stage_id=trip.start_stage_id or 0, end_stage_id=trip.end_stage_id or 0,
        slot_count=seats, price=int(round(per_seat * seats / 100)),   # legacy column (dollars, display only)
        price_per_seat_cents=list_price, offered_price_per_seat_cents=per_seat if negotiated else None,
        total_cents=per_seat * seats, customer_note=note, status='Pending', payment_status='unpaid',
        stripe_paid='No',
        pickup_lat=(pickup or {}).get('lat'), pickup_lng=(pickup or {}).get('lng'),
        pickup_address=(pickup or {}).get('address'),
        pickup_order=None,
    )
    if request_mode:
        booking.request_status = 'pending'
        booking.request_expires_at = datetime.utcnow() + timedelta(minutes=S.get_int('rideshare.request_timeout_min'))
    db.session.add(booking)
    db.session.flush()
    booking.pickup_order = TripBooking.query.filter_by(trip_id=trip.id).count()
    TSM.record_creation('rideshare_booking', booking, actor=customer, actor_type='customer',
                        stage='REQUESTED' if request_mode else 'PENDING_PAYMENT',
                        meta={'seats': seats, 'per_seat_cents': per_seat, 'negotiated': negotiated})
    if commit:
        db.session.commit()
    return booking


def respond_to_request(driver, booking_id, approve, reason=None):
    booking = TripBooking.query.filter(TripBooking.id == int(booking_id)).with_for_update().first()
    if not booking:
        raise BookingError('Booking not found.', code='not_found', status=404)
    trip = Trip.query.filter(Trip.id == booking.trip_id).with_for_update().first()
    if trip.driver_id != driver.id and not driver.get_admin_roles():
        raise BookingError('Only the driver can respond to this request.', code='forbidden', status=403)
    if approve:
        booking.request_status = 'approved'
        TSM.transition('rideshare_booking', booking.id, 'PENDING_PAYMENT', actor=driver, ride=booking,
                       meta={'approved': True})
    else:
        booking.request_status = 'declined'
        from backend.services.ride_actions import cancel
        cancel('rideshare_booking', booking.id, actor=driver, reason='declined', reason_code='driver_declined',
               note=reason)
    return booking


# ── v4 search / cards / manifest / trip settings (spec §18.1) ───────────────

LUGGAGE_SIZES = ('none', 'small', 'medium', 'large')


def _gps(text):
    from backend.services.rides import _gps as g
    return g(text)


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def background_checked(user_id):
    from backend.models.identity import BackgroundCheck
    return BackgroundCheck.query.filter_by(user_id=user_id, status='clear').first() is not None


def trip_card(trip, origin=None, destination=None, left=None):
    """Public search-result card. First name only, no phone, no plate."""
    from backend.models.user import AdminUser, resolve_media_url
    from backend.services import rides as R
    drv = db.session.get(AdminUser, trip.driver_id) if trip.driver_id else None
    start, end = _gps(trip.start_gps), _gps(trip.end_pgs)
    price = seat_price_cents(trip)
    nego = bool(trip.allow_seat_negotiation) and S.flag('rideshare_seat_negotiation')
    veh = R.vehicle_card(drv) if drv else {}
    card = {
        'trip_id': trip.id,
        'stage': trip.trip_stage or TSM.R.derive_stage('rideshare_trip', trip),
        'departure_at': _iso(trip.departure_at),
        'departure_text': trip.scheduled_start_time,
        'pickup': {'name': trip.start_name, 'address': trip.start_address or trip.start_name,
                   'lat': start[0] if start else None, 'lng': start[1] if start else None},
        'dropoff': {'name': trip.end_name, 'address': trip.end_address or trip.end_name,
                    'lat': end[0] if end else None, 'lng': end[1] if end else None},
        'seats_total': int(trip.slots or 0),
        'seats_left': seats_left(trip) if left is None else left,
        'price_per_seat_cents': price,
        'currency': 'cad',
        'negotiation': {'allowed': nego, 'min_cents': int(trip.min_seat_price_cents or price) if nego else price,
                        'max_cents': price},
        'booking_mode': trip.booking_mode or 'instant',
        'driver': None,
        'car': {'model': trip.car_model or (veh or {}).get('model'), 'make': (veh or {}).get('make'),
                'color': (veh or {}).get('color'), 'year': (veh or {}).get('year')},
        'badges': {'verified': bool(drv and drv.is_approved_driver()),
                   'background_checked': bool(drv and background_checked(drv.id)),
                   'pets_ok': bool(trip.pets_ok), 'luggage_size': trip.luggage_size},
        'details': trip.details,
    }
    if drv:
        card['driver'] = {'id': drv.id, 'first_name': (drv.first_name or (drv.name or '').split(' ')[0] or 'Driver').strip(),
                          'avatar': resolve_media_url(drv.avatar),
                          'rating': float(drv.rating) if drv.rating else None, 'rating_count': drv.rating_count or 0}
    if origin and start:
        card['distance_from_origin_m'] = int(TSM.R.haversine_m(origin, start))
    if destination and end:
        card['distance_to_destination_m'] = int(TSM.R.haversine_m(destination, end))
    return card


def search(from_pt=None, to_pt=None, day_start_utc=None, day_end_utc=None, seats=1, radius_km=None, limit=50):
    """Published, bookable trips near origin / destination with ≥ `seats` seats left."""
    radius_m = (radius_km or S.get_int('rideshare.search_radius_km', 25)) * 1000
    now = datetime.utcnow()
    q = Trip.query.filter(Trip.trip_stage.in_(('PUBLISHED', 'BOARDING')),
                          Trip.departure_at.isnot(None),
                          Trip.departure_at >= now - timedelta(minutes=5))
    if day_start_utc:
        q = q.filter(Trip.departure_at >= day_start_utc)
    if day_end_utc:
        q = q.filter(Trip.departure_at < day_end_utc)
    out = []
    for trip in q.order_by(Trip.departure_at.asc()).limit(500).all():
        start, end = _gps(trip.start_gps), _gps(trip.end_pgs)
        if from_pt:
            if not start or TSM.R.haversine_m(from_pt, start) > radius_m:
                continue
        if to_pt:
            if not end or TSM.R.haversine_m(to_pt, end) > radius_m:
                continue
        left = seats_left(trip)
        if left < max(1, int(seats or 1)):
            continue
        out.append(trip_card(trip, from_pt, to_pt, left))
        if len(out) >= limit:
            break
    return out


def next_action(booking):
    stage = booking.trip_stage
    if stage == 'REQUESTED':
        return {'action': 'wait_for_approval', 'expires_at': _iso(booking.request_expires_at)}
    if stage == 'PENDING_PAYMENT':
        return {'action': 'pay', 'endpoint': f'/api/rides/rideshare_booking/{booking.id}/pay'}
    return {'action': 'none'}


PASSENGER_ACTIONS = {
    'REQUESTED': ['approve', 'decline'],
    'PENDING_PAYMENT': [],
    'CONFIRMED': ['arrived', 'start', 'no-show'],
    'DRIVER_ARRIVED': ['start', 'no-show'],
    'CHECKED_IN': ['complete'],
    'RIDING': ['complete'],
}


def _action_endpoint(booking_id, action):
    if action in ('approve', 'decline'):
        return f'/api/rideshare/bookings/{booking_id}/respond'
    return f'/api/rides/rideshare_booking/{booking_id}/{action}'


def manifest(trip):
    """Driver's ordered pickup list with per-passenger stage + actions (spec §4.2)."""
    from backend.services import rides as R
    rows = (TripBooking.query.filter(TripBooking.trip_id == trip.id)
            .order_by(TripBooking.pickup_order.asc(), TripBooking.id.asc()).all())
    now = datetime.utcnow()
    departed = bool(trip.departure_at and now >= trip.departure_at)
    passengers = []
    for b in rows:
        stage = b.trip_stage or R.derive_stage('rideshare_booking', b)
        if TSM.is_cancel_stage(stage):
            continue
        confirmed = stage not in ('REQUESTED', 'PENDING_PAYMENT')
        acts = [a for a in PASSENGER_ACTIONS.get(stage, []) if a != 'no-show' or departed]
        pt = (float(b.pickup_lat), float(b.pickup_lng)) if b.pickup_lat is not None and b.pickup_lng is not None \
            else _gps(trip.start_gps)
        passengers.append({
            'booking_id': b.id, 'pickup_order': b.pickup_order, 'stage': stage, 'seats': int(b.slot_count or 1),
            'customer': R.user_card(b.customer_id, full=confirmed),
            'pickup': {'address': b.pickup_address or trip.start_address or trip.start_name,
                       'lat': pt[0] if pt else None, 'lng': pt[1] if pt else None},
            'note': b.customer_note,
            'total_cents': R.fare_cents('rideshare_booking', b),
            'request_expires_at': _iso(b.request_expires_at) if stage == 'REQUESTED' else None,
            'pin_required': TSM.pin_required('rideshare_booking', b) if confirmed else False,
            'actions': [{'action': a, 'method': 'POST', 'endpoint': _action_endpoint(b.id, a)} for a in acts],
        })
    return {
        'trip_id': trip.id, 'stage': trip.trip_stage or R.derive_stage('rideshare_trip', trip),
        'departure_at': _iso(trip.departure_at), 'seats_total': int(trip.slots or 0),
        'seats_left': seats_left(trip), 'passengers': passengers,
    }


def update_settings(trip, data):
    """Driver trip settings: booking_mode, allow_seat_negotiation, min_seat_price_cents, pets_ok, luggage_size."""
    def _bool(v):
        return v if isinstance(v, bool) else str(v).strip().lower() in ('1', 'true', 'yes', 'on')
    if 'booking_mode' in data:
        mode = str(data['booking_mode'] or '').strip().lower()
        if mode not in ('instant', 'request'):
            raise BookingError("booking_mode must be 'instant' or 'request'.", code='bad_booking_mode')
        trip.booking_mode = mode
    if 'allow_seat_negotiation' in data:
        trip.allow_seat_negotiation = _bool(data['allow_seat_negotiation'])
    if 'min_seat_price_cents' in data:
        v = data['min_seat_price_cents']
        if v in (None, ''):
            trip.min_seat_price_cents = None
        else:
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise BookingError('Invalid min_seat_price_cents.', code='bad_min_price')
            price = seat_price_cents(trip)
            if v < 50 or (price and v > price):
                raise BookingError('The minimum seat price must be between $0.50 and the seat price.',
                                   code='bad_min_price')
            trip.min_seat_price_cents = v
    if 'pets_ok' in data:
        trip.pets_ok = _bool(data['pets_ok'])
    if 'luggage_size' in data:
        size = (str(data['luggage_size'] or '').strip().lower() or None)
        if size and size not in LUGGAGE_SIZES:
            raise BookingError(f"luggage_size must be one of {', '.join(LUGGAGE_SIZES)}.", code='bad_luggage')
        trip.luggage_size = size
    return trip
