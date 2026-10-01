"""Ride registry — one adapter over the four ride-like models so the state
machine, payments, safety and tracking code can treat them uniformly.

ride_type            model              what it is
───────────────────  ─────────────────  ─────────────────────────────────────────
carhire              Negotiation        on-demand negotiated ride (§4.1)
scheduled            ScheduledBooking   scheduled car hire / airport / courier / movers
rideshare_trip       Trip               the driver's published journey (§4.2)
rideshare_booking    TripBooking        one customer's seat booking on a Trip
"""
import math
from decimal import Decimal

from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.models.user import AdminUser

MODELS = {
    'carhire': Negotiation,
    'scheduled': ScheduledBooking,
    'rideshare_trip': Trip,
    'rideshare_booking': TripBooking,
}
RIDE_TYPES = tuple(MODELS)

# URL aliases accepted by /api/rides/{type}/{id}
ALIASES = {
    'carhire': 'carhire', 'car-hire': 'carhire', 'negotiation': 'carhire',
    'scheduled': 'scheduled', 'booking': 'scheduled',
    'rideshare_trip': 'rideshare_trip', 'rideshare-trip': 'rideshare_trip', 'trip': 'rideshare_trip',
    'rideshare_booking': 'rideshare_booking', 'rideshare-booking': 'rideshare_booking',
    'seat': 'rideshare_booking',
}


class RideNotFound(Exception):
    pass


def normalize_type(ride_type):
    t = ALIASES.get((ride_type or '').strip().lower())
    if not t:
        raise RideNotFound(f"Unknown ride type '{ride_type}'")
    return t


def load(ride_type, ride_id, lock=False):
    model = MODELS[normalize_type(ride_type)]
    q = model.query.filter(model.id == int(ride_id))
    if lock:
        q = q.with_for_update()
    ride = q.first()
    if ride is None:
        raise RideNotFound('Ride not found')
    return ride


def type_of(ride):
    for t, model in MODELS.items():
        if isinstance(ride, model):
            return t
    raise RideNotFound('Unknown ride object')


# ── parties ─────────────────────────────────────────────────────────────────

def customer_ids(ride_type, ride):
    if ride_type == 'rideshare_trip':
        rows = TripBooking.query.filter(
            TripBooking.trip_id == ride.id,
            ~TripBooking.status.in_(['Canceled', 'Cancelled'])).all()
        return sorted({int(b.customer_id) for b in rows if b.customer_id})
    cid = getattr(ride, 'customer_id', None)
    return [int(cid)] if cid else []


def driver_id(ride_type, ride):
    d = getattr(ride, 'driver_id', None)
    if not d and ride_type == 'rideshare_booking':
        trip = db.session.get(Trip, ride.trip_id)
        d = trip.driver_id if trip else None
    return int(d) if d else None


def role_of(user, ride_type, ride):
    """'customer' | 'driver' | 'admin' | None."""
    if user is None:
        return None
    uid = int(user.id)
    if driver_id(ride_type, ride) == uid:
        return 'driver'
    if uid in customer_ids(ride_type, ride):
        return 'customer'
    if user.get_admin_roles():
        return 'admin'
    return None


def all_party_ids(ride_type, ride):
    ids = set(customer_ids(ride_type, ride))
    d = driver_id(ride_type, ride)
    if d:
        ids.add(d)
    return sorted(ids)


# ── geography ───────────────────────────────────────────────────────────────

def _f(v):
    try:
        if v is None or v == '':
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _gps(text):
    if not text:
        return None
    try:
        a, b = str(text).split(',')[:2]
        return float(a), float(b)
    except (ValueError, TypeError):
        return None


def pickup_point(ride_type, ride):
    if ride_type in ('carhire', 'scheduled'):
        lat, lng = _f(ride.pickup_lat), _f(ride.pickup_lng)
        return (lat, lng) if lat is not None and lng is not None else None
    if ride_type == 'rideshare_booking':
        lat, lng = _f(ride.pickup_lat), _f(ride.pickup_lng)
        if lat is not None and lng is not None:
            return lat, lng
        trip = db.session.get(Trip, ride.trip_id)
        return _gps(trip.start_gps) if trip else None
    return _gps(ride.start_gps)


def dropoff_point(ride_type, ride):
    if ride_type == 'carhire':
        lat, lng = _f(ride.dropoff_lat), _f(ride.dropoff_lng)
    elif ride_type == 'scheduled':
        lat, lng = _f(ride.destination_lat), _f(ride.destination_lng)
    else:
        trip = ride if ride_type == 'rideshare_trip' else db.session.get(Trip, ride.trip_id)
        return _gps(trip.end_pgs) if trip else None
    return (lat, lng) if lat is not None and lng is not None else None


def addresses(ride_type, ride):
    if ride_type == 'carhire':
        return ride.pickup_address, ride.dropoff_address
    if ride_type == 'scheduled':
        return ride.pickup_address, ride.destination_address
    trip = ride if ride_type == 'rideshare_trip' else db.session.get(Trip, ride.trip_id)
    pickup = (getattr(ride, 'pickup_address', None) if ride_type == 'rideshare_booking' else None) \
        or (trip.start_address or trip.start_name if trip else None)
    return pickup, (trip.end_address or trip.end_name) if trip else None


def haversine_m(a, b):
    if not a or not b:
        return None
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(h))


# ── money ───────────────────────────────────────────────────────────────────

def fare_cents(ride_type, ride):
    """The agreed fare in integer cents (0 if unknown)."""
    from backend.utils.money import legacy_price_to_cents
    if ride_type == 'carhire':
        if ride.agreed_price_cents:
            return int(ride.agreed_price_cents)
        # Legacy code stores CENTS in the DECIMAL agreed_price column.
        legacy = legacy_price_to_cents(ride.agreed_price)
        return int(legacy or ride.initial_price or 0)
    if ride_type == 'scheduled':
        return int(ride.agreed_price or ride.driver_proposed_price or ride.customer_proposed_price or 0)
    if ride_type == 'rideshare_booking':
        if ride.total_cents:
            return int(ride.total_cents)
        seats = int(ride.slot_count or 1)
        if ride.price_per_seat_cents:
            return int(ride.price_per_seat_cents) * seats
        trip = db.session.get(Trip, ride.trip_id)
        if trip and trip.price_per_seat_cents:
            return int(trip.price_per_seat_cents) * seats
        if trip and trip.price:
            return int(Decimal(trip.price) * 100) * seats  # legacy: dollars per seat
        return 0
    if ride_type == 'rideshare_trip':
        return 0
    return 0


# ── stage derivation for rows created before v4 ────────────────────────────

def derive_stage(ride_type, ride):
    """Infer a v4 stage for legacy rows that have no trip_stage yet."""
    st = (ride.status or '').strip()
    low = st.lower()
    if ride_type == 'carhire':
        paid = (ride.stripe_paid == 'Yes') or (ride.payment_status or '') == 'paid'
        if low in ('active', 'pending'):
            n = len(ride.records_list or [])
            return 'NEGOTIATING' if n > 1 else 'REQUESTED'
        if low in ('accepted', 'accept'):
            return 'CONFIRMED' if paid else 'PRICE_AGREED'
        if low in ('started', 'ongoing'):
            return 'IN_PROGRESS'
        if low == 'completed':
            return 'COMPLETED'
        if low == 'declined':
            return 'CANCELLED_BY_DRIVER'
        if low in ('cancelled', 'canceled'):
            return 'CANCELLED_BY_DRIVER' if (ride.cancelled_by or '') == 'driver' else 'CANCELLED_BY_CUSTOMER'
        return 'REQUESTED'
    if ride_type == 'scheduled':
        return {
            'pending': 'REQUESTED', 'price_negotiating': 'NEGOTIATING',
            'price_accepted': 'PRICE_AGREED', 'driver_assigned': 'PRICE_AGREED',
            'confirmed': 'CONFIRMED', 'in_progress': 'IN_PROGRESS',
            'completed': 'COMPLETED', 'cancelled': 'CANCELLED_BY_CUSTOMER',
        }.get(low, 'REQUESTED')
    if ride_type == 'rideshare_trip':
        return {'pending': 'DRAFT', 'active': 'PUBLISHED', 'scheduled': 'PUBLISHED',
                'ongoing': 'IN_PROGRESS', 'started': 'IN_PROGRESS',
                'completed': 'COMPLETED', 'canceled': 'CANCELLED_BY_DRIVER',
                'cancelled': 'CANCELLED_BY_DRIVER'}.get(low, 'PUBLISHED')
    # rideshare_booking
    paid = (ride.stripe_paid == 'Yes') or (ride.payment_status or '').lower() == 'paid'
    return {'pending': 'CONFIRMED' if paid else 'PENDING_PAYMENT',
            'reserved': 'CONFIRMED', 'confirmed': 'CONFIRMED',
            'ongoing': 'RIDING', 'started': 'RIDING',
            'completed': 'DROPPED_OFF', 'canceled': 'CANCELLED_BY_CUSTOMER',
            'cancelled': 'CANCELLED_BY_CUSTOMER'}.get(low, 'PENDING_PAYMENT')


def current_stage(ride_type, ride):
    return ride.trip_stage or derive_stage(ride_type, ride)


# ── user cards (privacy-aware) ──────────────────────────────────────────────

def user_card(user_id, full=False):
    """Public card for the other party. Before confirmation only a first name
    (spec §18.2 privacy); phone numbers are never included — calls go through
    in-app WebRTC."""
    if not user_id:
        return None
    u = db.session.get(AdminUser, int(user_id))
    if not u:
        return None
    from backend.models.user import resolve_media_url
    first = (u.first_name or (u.name or '').split(' ')[0] or 'NegoRide user').strip()
    card = {
        'id': u.id,
        'first_name': first,
        'name': (u.name or first) if full else first,
        'avatar': resolve_media_url(u.avatar),
        'rating': float(u.rating) if u.rating else None,
        'rating_count': u.rating_count or 0,
    }
    return card


PHOTO_STAGES = ('CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS',
                'PUBLISHED', 'BOARDING', 'CHECKED_IN', 'RIDING')
PHOTO_TTL_S = 300


def vehicle_card(driver, ride_type=None, ride=None, viewer=None):
    """Vehicle details from the latest approved driver application (falls back
    to legacy user fields).

    Safety verification card (§8.4, owned by the safety agent): pass
    `ride_type`, `ride` and `viewer` to also get `photo_url` — a short-lived
    (5 min) signed URL of the approved application's `vehicle_front` photo. It is
    only issued to a party (customer/driver) of that ride while the ride is
    confirmed and not finished; otherwise `photo_url` is None."""
    if not driver:
        return None
    from backend.models.identity import DriverApplication
    app = DriverApplication.query.filter_by(user_id=driver.id).first()
    if app and (app.vehicle_plate or app.vehicle_make):
        card = {
            'make': app.vehicle_make, 'model': app.vehicle_model, 'year': app.vehicle_year,
            'color': app.vehicle_color, 'plate': app.vehicle_plate, 'seats': app.vehicle_seats,
        }
    else:
        card = {'make': None, 'model': driver.automobile, 'year': None, 'color': None,
                'plate': None, 'seats': driver.max_passengers}
    if ride is not None and viewer is not None:
        card['photo_url'] = vehicle_photo_url(driver, app, ride_type, ride, viewer)
    return card


def vehicle_photo_url(driver, app, ride_type, ride, viewer):
    if app is None or app.status != 'approved':
        return None
    if role_of(viewer, ride_type, ride) not in ('customer', 'driver'):
        return None
    if driver_id(ride_type, ride) != int(driver.id) or current_stage(ride_type, ride) not in PHOTO_STAGES:
        return None
    from backend.models.identity import DriverDocument
    doc = (DriverDocument.query.filter(DriverDocument.application_id == app.id,
                                       DriverDocument.type == 'vehicle_front',
                                       DriverDocument.status == 'approved')
           .order_by(DriverDocument.id.desc()).first())
    if not doc or not doc.file_path:
        return None
    from backend.services import private_storage as PS
    try:
        return PS.signed_url(doc.file_path, ttl_s=PHOTO_TTL_S, content_type=doc.mime_type or 'image/jpeg',
                             actor_id=viewer.id)
    except Exception:
        return None
