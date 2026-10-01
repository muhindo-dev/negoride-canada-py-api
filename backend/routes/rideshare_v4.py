"""Rideshare self-booking (spec §18.1).

Customer
    GET  /api/rideshare/search?from_lat&from_lng&to_lat&to_lng&date=YYYY-MM-DD&seats
    GET  /api/rideshare/trips/{id}
    POST /api/rideshare/trips/{id}/book        {seats, offered_price_per_seat_cents?, pickup{lat,lng,address}, note}
    GET  /api/rideshare/my-bookings?page&per_page&scope=upcoming|past|all
Driver
    POST /api/rideshare/bookings/{id}/respond  {approve: bool, reason}
    GET  /api/rideshare/trips/{id}/manifest
    PUT  /api/rideshare/trips/{id}/settings    {booking_mode, allow_seat_negotiation, min_seat_price_cents, pets_ok, luggage_size}

Per-passenger Arrived / Picked up (PIN) / Drop-off / No-show use the unified ride API:
    POST /api/rides/rideshare_booking/{id}/arrived | start {pin} | complete | no-show
Payment: POST /api/rides/rideshare_booking/{id}/pay.
"""
from datetime import datetime, timedelta

from flask import Blueprint, request

from backend.models import db
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.services import rides as R
from backend.services import rideshare_service as RS
from backend.services import settings_service as S
from backend.services import trip_state_machine as TSM
from backend.utils.auth import jwt_required_with_user
from backend.utils.idempotency import idempotent
from backend.utils.response import error_response, success_response

rideshare_v4_bp = Blueprint('rideshare_v4', __name__)


def _body():
    return request.get_json(silent=True) or request.form or {}


def _err(e):
    db.session.rollback()
    if isinstance(e, RS.BookingError):
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    if isinstance(e, TSM.TransitionError):
        return error_response(e.message, data={'error_code': e.code, **e.data}, status_code=e.status)
    if isinstance(e, R.RideNotFound):
        return error_response(str(e), data={'error_code': 'not_found'}, status_code=404)
    raise e


def _pt(lat_key, lng_key):
    lat, lng = request.args.get(lat_key), request.args.get(lng_key)
    if lat in (None, '') or lng in (None, ''):
        return None
    try:
        lat, lng = float(lat), float(lng)
    except ValueError:
        raise RS.BookingError(f'Invalid {lat_key}/{lng_key}.', code='bad_location')
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise RS.BookingError(f'Invalid {lat_key}/{lng_key}.', code='bad_location')
    return lat, lng


def _day_range(text, user):
    if not text:
        return None, None
    from zoneinfo import ZoneInfo
    try:
        day = datetime.strptime(text[:10], '%Y-%m-%d')
    except ValueError:
        raise RS.BookingError('date must be YYYY-MM-DD.', code='bad_date')
    # The search date is selected in the device's current local timezone.
    # Device registration may still be in flight on the first Home visit, so
    # accept a validated IANA zone on this read endpoint before falling back
    # to the saved account timezone.
    requested_tz = (request.args.get('timezone') or '').strip()[:80]
    try:
        tz = ZoneInfo(requested_tz or user.timezone or 'America/Toronto')
    except Exception:
        try:
            tz = ZoneInfo(user.timezone or 'America/Toronto')
        except Exception:
            tz = ZoneInfo('America/Toronto')
    utc = ZoneInfo('UTC')
    start = day.replace(tzinfo=tz).astimezone(utc).replace(tzinfo=None)
    return start, start + timedelta(days=1)


def _feature():
    if not S.flag('rideshare_self_booking'):
        return error_response('Rideshare booking is not available right now.',
                              data={'error_code': 'feature_off'}, status_code=403)
    return None


@rideshare_v4_bp.route('/api/rideshare/search', methods=['GET'])
@jwt_required_with_user
def search(user):
    off = _feature()
    if off:
        return off
    try:
        frm, to = _pt('from_lat', 'from_lng'), _pt('to_lat', 'to_lng')
        start, end = _day_range(request.args.get('date'), user)
        seats = max(1, min(8, int(request.args.get('seats') or 1)))
    except RS.BookingError as e:
        return _err(e)
    except ValueError:
        return error_response('Invalid seats.', data={'error_code': 'bad_seats'})
    trips = RS.search(frm, to, start, end, seats)
    trips = [t for t in trips if not (t['driver'] and t['driver']['id'] == user.id)]
    return success_response(f'{len(trips)} trip(s) found', {'trips': trips, 'count': len(trips)})


def _trip_or_404(trip_id):
    trip = db.session.get(Trip, trip_id)
    if not trip:
        raise R.RideNotFound('Trip not found')
    return trip


@rideshare_v4_bp.route('/api/rideshare/trips/<int:trip_id>', methods=['GET'])
@jwt_required_with_user
def trip_detail(user, trip_id):
    try:
        trip = _trip_or_404(trip_id)
        if (trip.trip_stage or R.derive_stage('rideshare_trip', trip)) == 'DRAFT' and trip.driver_id != user.id \
                and not user.get_admin_roles():
            raise R.RideNotFound('Trip not found')     # drafts are private to their driver
    except R.RideNotFound as e:
        return _err(e)
    card = RS.trip_card(trip)
    card['is_bookable'] = RS.is_bookable(trip) and trip.driver_id != user.id
    mine = (TripBooking.query.filter(TripBooking.trip_id == trip.id, TripBooking.customer_id == user.id)
            .order_by(TripBooking.id.desc()).first())
    card['my_booking'] = _booking_out(mine) if mine else None
    return success_response('Trip', card)


def _booking_out(b, with_trip=False):
    stage = b.trip_stage or R.derive_stage('rideshare_booking', b)
    out = {
        'id': b.id, 'trip_id': b.trip_id, 'stage': stage, 'legacy_status': b.status,
        'seats': int(b.slot_count or 1), 'price_per_seat_cents': b.price_per_seat_cents,
        'offered_price_per_seat_cents': b.offered_price_per_seat_cents,
        'total_cents': R.fare_cents('rideshare_booking', b), 'currency': 'cad',
        'request_status': b.request_status,
        'request_expires_at': RS._iso(b.request_expires_at),
        'pickup': {'address': b.pickup_address,
                   'lat': float(b.pickup_lat) if b.pickup_lat is not None else None,
                   'lng': float(b.pickup_lng) if b.pickup_lng is not None else None},
        'note': b.customer_note,
        'created_at': RS._iso(b.created_at),
        'next_action': RS.next_action(b),
    }
    if with_trip:
        trip = db.session.get(Trip, b.trip_id)
        out['trip'] = RS.trip_card(trip) if trip else None
    return out


@rideshare_v4_bp.route('/api/rideshare/trips/<int:trip_id>/book', methods=['POST'])
@jwt_required_with_user
@idempotent
def book(user, trip_id):
    off = _feature()
    if off:
        return off
    data = _body()
    pickup = data.get('pickup') if isinstance(data.get('pickup'), dict) else None
    if pickup:
        try:
            pickup = {'lat': float(pickup['lat']), 'lng': float(pickup['lng']),
                      'address': (pickup.get('address') or '')[:500] or None}
        except (KeyError, TypeError, ValueError):
            return error_response('pickup needs lat and lng.', data={'error_code': 'bad_pickup'})
    try:
        booking = RS.create_booking(user, trip_id, seats=data.get('seats', 1),
                                    offered_price_per_seat_cents=data.get('offered_price_per_seat_cents'),
                                    pickup=pickup, note=(data.get('note') or None))
    except (RS.BookingError, TSM.TransitionError) as e:
        return _err(e)
    booking = db.session.get(TripBooking, booking.id)
    msg = 'Request sent — the driver has {} min to approve'.format(S.get_int('rideshare.request_timeout_min')) \
        if booking.trip_stage == 'REQUESTED' else 'Seat reserved — pay to confirm'
    return success_response(msg, {'booking': _booking_out(booking, with_trip=True),
                                  'next_action': RS.next_action(booking)}, status_code=201)


@rideshare_v4_bp.route('/api/rideshare/bookings/<int:booking_id>/respond', methods=['POST'])
@jwt_required_with_user
@idempotent
def respond(user, booking_id):
    data = _body()
    approve = data.get('approve')
    if not isinstance(approve, bool):
        approve = str(approve).strip().lower() in ('1', 'true', 'yes')
    try:
        b = db.session.get(TripBooking, booking_id)
        if not b:
            raise RS.BookingError('Booking not found.', code='not_found', status=404)
        if (b.trip_stage or '') != 'REQUESTED':
            raise RS.BookingError('This booking is not waiting for approval.', code='not_requested', status=409)
        RS.respond_to_request(user, booking_id, approve, reason=(data.get('reason') or None))
        db.session.commit()
    except (RS.BookingError, TSM.TransitionError) as e:
        return _err(e)
    db.session.rollback()
    b = db.session.get(TripBooking, booking_id)
    return success_response('Request approved' if approve else 'Request declined', {'booking': _booking_out(b)})


@rideshare_v4_bp.route('/api/rideshare/my-bookings', methods=['GET'])
@jwt_required_with_user
def my_bookings(user):
    try:
        page = max(1, int(request.args.get('page') or 1))
        per_page = max(1, min(100, int(request.args.get('per_page') or 20)))
    except ValueError:
        page, per_page = 1, 20
    scope = (request.args.get('scope') or 'all').lower()
    q = TripBooking.query.filter(TripBooking.customer_id == user.id)
    active = ('REQUESTED', 'PENDING_PAYMENT', 'CONFIRMED', 'DRIVER_ARRIVED', 'CHECKED_IN', 'RIDING')
    if scope == 'upcoming':
        q = q.filter(TripBooking.trip_stage.in_(active))
    elif scope == 'past':
        q = q.filter(~TripBooking.trip_stage.in_(active))
    total = q.count()
    rows = q.order_by(TripBooking.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return success_response('My bookings', {'items': [_booking_out(b, with_trip=True) for b in rows],
                                            'page': page, 'per_page': per_page, 'total': total})


def _driver_trip(user, trip_id):
    trip = _trip_or_404(trip_id)
    if trip.driver_id != user.id and not user.has_admin_role('ops', 'support'):
        raise RS.BookingError('Only the driver of this trip can do this.', code='forbidden', status=403)
    return trip


@rideshare_v4_bp.route('/api/rideshare/trips/<int:trip_id>/manifest', methods=['GET'])
@jwt_required_with_user
def manifest(user, trip_id):
    try:
        trip = _driver_trip(user, trip_id)
    except (RS.BookingError, R.RideNotFound) as e:
        return _err(e)
    return success_response('Manifest', RS.manifest(trip))


@rideshare_v4_bp.route('/api/rideshare/trips/<int:trip_id>/settings', methods=['PUT', 'POST'])
@jwt_required_with_user
def trip_settings(user, trip_id):
    try:
        trip = _driver_trip(user, trip_id)
        RS.update_settings(trip, _body())
        db.session.commit()
    except (RS.BookingError, R.RideNotFound) as e:
        return _err(e)
    return success_response('Trip settings saved', RS.trip_card(trip))
