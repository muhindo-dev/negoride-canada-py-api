"""Car hire pick-a-driver, favourite-first and broadcast matching (spec §18.2).

The Negotiation model stays single-driver. A customer request is a
`ride_requests` row; each driver it is offered to gets a `ride_request_offers`
row:

  direct           negotiation created at once with the chosen driver
                   (same logic as legacy /api/negotiations-create: REQUESTED
                   stage + trip_event + `negotiation.new_request` to the driver)
  favourite_first  offered to the favourite driver for `carhire.favourite_first_s`
                   (45 s), then broadcast (experience_jobs.tick / delayed job)
  broadcast        offered to the nearest `carhire.broadcast_max_drivers` online,
                   approved drivers within `carhire.broadcast_radius_km`

Counter-offer marketplace (§21.2.2):
  • a driver who ACCEPTS the customer's price wins at once (first acceptor wins):
    the request row is locked (SELECT … FOR UPDATE), a negotiation is created at
    PRICE_AGREED, the request becomes `matched`, every other offer `withdrawn`;
  • a driver COUNTER does not match: the offer becomes `countered`
    (counter_cents, counter_expires_at = now + carhire.counter_offer_ttl_s) and
    the customer gets `carhire.request_countered`; the request stays open for
    other drivers. The customer accepts one counter
    (POST …/offers/{id}/accept → PRICE_AGREED at the counter price) or counters
    back (…/counter → `customer_countered`, driver gets
    `carhire.customer_countered` and accepts/counters via the driver endpoints).
Unanswered broadcasts expire after `carhire.broadcast_timeout_s`; live counters
extend the request's expiry and expire on their own.

Privacy before confirmation: first names only, no phone numbers, and driver
positions snapped to a ~200 m grid.
"""
import logging
from datetime import datetime, timedelta

from backend import jobs
from backend.models import db
from backend.models.experience import FavouriteDriver, RideRequest, RideRequestOffer
from backend.models.negotiation import Negotiation
from backend.models.negotiation_record import NegotiationRecord
from backend.models.user import AdminUser, resolve_media_url
from backend.services import geo_routes as G
from backend.services import realtime
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services import trip_state_machine as TSM

log = logging.getLogger('negoride.matching')

# service type → (applied flag, approval flag) — mirrors legacy /api/trips-drivers
SERVICE_MAP = {
    'car': ('is_car', 'is_car_approved'), 'special car': ('is_car', 'is_car_approved'),
    'special car hire': ('is_car', 'is_car_approved'), 'carhire': ('is_car', 'is_car_approved'),
    'bodaboda': ('is_boda', 'is_boda_approved'), 'boda': ('is_boda', 'is_boda_approved'),
    'courier': ('is_delivery', 'is_delivery_approved'), 'delivery': ('is_delivery', 'is_delivery_approved'),
    'movers': ('is_ambulance', 'is_ambulance_approved'), 'ambulance': ('is_ambulance', 'is_ambulance_approved'),
    'airport pickup': ('is_breakdown', 'is_breakdown_approved'), 'airport': ('is_breakdown', 'is_breakdown_approved'),
    'pickup': ('is_breakdown', 'is_breakdown_approved'), 'breakdown': ('is_breakdown', 'is_breakdown_approved'),
}
OPEN = ('favourite', 'broadcasting')
BUSY_STAGES = ('CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS')
GRID_DEG = 0.002          # ≈ 200 m


class MatchError(Exception):
    def __init__(self, message, code='match_error', status=400, data=None):
        super().__init__(message)
        self.message, self.code, self.status, self.data = message, code, status, data or {}


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def normalize_service(st):
    st = (st or 'car').strip().lower().replace('_', ' ')
    if st not in SERVICE_MAP:
        raise MatchError(f"Unknown service_type '{st}'.", code='bad_service_type')
    return st


def approximate(lat, lng):
    """Snap to a ~200 m grid (privacy before a ride is confirmed)."""
    return round(round(lat / GRID_DEG) * GRID_DEG, 4), round(round(lng / GRID_DEG) * GRID_DEG, 4)


def first_name(u):
    return (u.first_name or (u.name or '').split(' ')[0] or 'Driver').strip()


# ── supply ──────────────────────────────────────────────────────────────────

def _account_active_clause():
    from backend.services.account_service import active_account_clause
    return active_account_clause()


def online_drivers(lat, lng, service_type='car', radius_km=None, exclude_ids=(), limit=50):
    """Online, approved, active, not-busy drivers within radius → [(distance_m, driver)] nearest first."""
    service_type = normalize_service(service_type)
    radius_km = radius_km or S.get_int('carhire.broadcast_radius_km', 15)
    _, approved_key = SERVICE_MAP[service_type]
    dlat = radius_km / 111.0
    import math
    dlng = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    stale = datetime.utcnow() - timedelta(minutes=30)
    q = AdminUser.query.filter(
        AdminUser.ready_for_trip == 'Yes', _account_active_clause(),   # effective account status (§15)
        getattr(AdminUser, approved_key) == 'Yes',
        AdminUser.current_latitude.between(lat - dlat, lat + dlat),
        AdminUser.current_longitude.between(lng - dlng, lng + dlng),
        (AdminUser.last_location_update.is_(None)) | (AdminUser.last_location_update >= stale))
    if exclude_ids:
        q = q.filter(~AdminUser.id.in_(list(exclude_ids)))
    rows = q.limit(500).all()
    busy = set()
    if rows:
        busy = {d for (d,) in db.session.query(Negotiation.driver_id).filter(
            Negotiation.driver_id.in_([r.id for r in rows]), Negotiation.trip_stage.in_(BUSY_STAGES))}
    out = []
    for d in rows:
        if d.id in busy:
            continue
        dist = G.haversine_m((lat, lng), (float(d.current_latitude), float(d.current_longitude)))
        if dist <= radius_km * 1000:
            out.append((dist, d))
    out.sort(key=lambda x: x[0])
    return out[:limit]


def driver_card(d, pickup=None, dist=None, favourite_ids=()):
    """'Choose a driver' card — first name, photo, rating, car, ETA; approximate location only."""
    veh = R.vehicle_card(d) or {}
    lat, lng = float(d.current_latitude), float(d.current_longitude)
    alat, alng = approximate(lat, lng)
    card = {
        'id': d.id, 'first_name': first_name(d), 'avatar': resolve_media_url(d.avatar),
        'rating': float(d.rating) if d.rating else None, 'rating_count': d.rating_count or 0,
        'car': {k: veh.get(k) for k in ('make', 'model', 'color', 'year', 'seats')},
        'approx_location': {'lat': alat, 'lng': alng, 'precision_m': 200},
        'is_favourite': d.id in favourite_ids,
    }
    if pickup is not None and dist is not None:
        est = G.estimate((lat, lng), pickup)
        card['distance_m'] = int(round(dist / 100.0) * 100)
        card['eta_seconds'] = est['seconds']
        card['eta_minutes'] = max(1, round(est['seconds'] / 60))
    return card


def nearby(customer, lat, lng, service_type='car', limit=20):
    radius = S.get_int('carhire.nearby_radius_km', 10)
    favs = favourite_ids(customer.id)
    return [driver_card(d, (lat, lng), dist, favs)
            for dist, d in online_drivers(lat, lng, service_type, radius, exclude_ids=(customer.id,), limit=limit)]


# ── favourites ──────────────────────────────────────────────────────────────

def favourite_ids(customer_id):
    return {f.driver_id for f in FavouriteDriver.query.filter_by(customer_id=customer_id)}


def list_favourites(customer):
    out = []
    for f in FavouriteDriver.query.filter_by(customer_id=customer.id).order_by(FavouriteDriver.id.desc()):
        d = db.session.get(AdminUser, f.driver_id)
        if not d:
            continue
        veh = R.vehicle_card(d) or {}
        out.append({'driver_id': d.id, 'first_name': first_name(d), 'avatar': resolve_media_url(d.avatar),
                    'rating': float(d.rating) if d.rating else None, 'rating_count': d.rating_count or 0,
                    'car': {k: veh.get(k) for k in ('make', 'model', 'color')},
                    'online': d.ready_for_trip == 'Yes', 'added_at': _iso(f.created_at)})
    return out


def add_favourite(customer, driver_id):
    try:
        driver_id = int(driver_id)
    except (TypeError, ValueError):
        raise MatchError('driver_id is required.', code='bad_driver')
    if driver_id == customer.id:
        raise MatchError("You can't add yourself.", code='self')
    d = db.session.get(AdminUser, driver_id)
    if not d or not d.is_approved_driver():
        raise MatchError('Driver not found.', code='not_found', status=404)
    if not FavouriteDriver.query.filter_by(customer_id=customer.id, driver_id=driver_id).first():
        db.session.add(FavouriteDriver(customer_id=customer.id, driver_id=driver_id))
        db.session.commit()
    return True


def remove_favourite(customer, driver_id):
    n = FavouriteDriver.query.filter_by(customer_id=customer.id, driver_id=int(driver_id)).delete()
    db.session.commit()
    return n


# ── negotiation creation (same logic as legacy /api/negotiations-create) ────

def create_negotiation(customer, driver, req, stage=None):
    """Create the single-driver Negotiation for a request. Caller commits.
    stage=None → REQUESTED (driver is notified by the state machine effects);
    stage='NEGOTIATING' → the driver already answered (no 'new request' push)."""
    from backend.routes.negotiations import _record_created
    neg = Negotiation(
        customer_id=customer.id, customer_name=customer.name, driver_id=driver.id, driver_name=driver.name,
        pickup_lat=str(req.pickup_lat), pickup_lng=str(req.pickup_lng), pickup_address=req.pickup_address,
        dropoff_lat=str(req.dropoff_lat) if req.dropoff_lat is not None else None,
        dropoff_lng=str(req.dropoff_lng) if req.dropoff_lng is not None else None,
        dropoff_address=req.dropoff_address, initial_price=int(req.offer_cents),
        status='Active', is_active='Yes', customer_accepted='Accepted', customer_driver='Pending')
    db.session.add(neg)
    db.session.flush()
    db.session.add(NegotiationRecord(
        negotiation_id=neg.id, customer_id=customer.id, driver_id=driver.id, last_negotiator_id=customer.id,
        first_negotiator_id=customer.id, price=int(req.offer_cents), price_accepted='No',
        message_type='Negotiation', message_body=req.note))
    if stage is None:
        _record_created(neg, customer, {'service_type': req.service_type, 'request_mode': req.mode})
    else:
        neg.service_type = (req.service_type or 'car')[:40]
        neg.request_mode = req.mode[:20]
        TSM.record_creation('carhire', neg, actor=customer, actor_type='customer', stage=stage,
                            meta={'initial_price_cents': neg.initial_price, 'ride_request_id': req.id})
    return neg


# ── requests ────────────────────────────────────────────────────────────────

def _point(d, name, required=True):
    d = d or {}
    try:
        lat, lng = float(d.get('lat')), float(d.get('lng'))
    except (TypeError, ValueError):
        if required:
            raise MatchError(f'{name} needs lat and lng.', code=f'bad_{name}')
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise MatchError(f'Invalid {name} coordinates.', code=f'bad_{name}')
    return {'lat': lat, 'lng': lng, 'address': (d.get('address') or '')[:500] or None}


def create_request(customer, data):
    mode = (data.get('mode') or 'broadcast').strip().lower()
    if mode not in ('direct', 'favourite_first', 'broadcast'):
        raise MatchError("mode must be direct, favourite_first or broadcast.", code='bad_mode')
    if mode == 'direct' and not S.flag('pick_a_driver'):
        raise MatchError('Choosing a driver is not available right now.', code='feature_off', status=403)
    if mode == 'favourite_first' and not S.flag('favourite_first'):
        raise MatchError('Favourite-first requests are not available right now.', code='feature_off', status=403)
    service_type = normalize_service(data.get('service_type'))
    pickup = _point(data.get('pickup'), 'pickup')
    dropoff = _point(data.get('dropoff'), 'dropoff', required=False)
    try:
        offer = int(data.get('offer_cents'))
    except (TypeError, ValueError):
        raise MatchError('offer_cents is required.', code='bad_offer')
    floor = max(50, S.get_int('pricing.min_fare_cents', 500))
    if offer < floor or offer > 10_000_00:
        from backend.utils.money import fmt
        raise MatchError(f'Your offer must be at least {fmt(floor)}.', code='offer_too_low',
                         data={'min_cents': floor})
    now = datetime.utcnow()
    req = RideRequest(customer_id=customer.id, mode=mode, status='favourite', service_type=service_type,
                      pickup_lat=pickup['lat'], pickup_lng=pickup['lng'], pickup_address=pickup['address'],
                      dropoff_lat=dropoff['lat'] if dropoff else None, dropoff_lng=dropoff['lng'] if dropoff else None,
                      dropoff_address=dropoff['address'] if dropoff else None, offer_cents=offer,
                      note=(data.get('note') or '')[:500] or None, created_at=now)
    if dropoff:
        req.distance_m = int(G.haversine_m((pickup['lat'], pickup['lng']), (dropoff['lat'], dropoff['lng'])))
    result = {'negotiation': None, 'offers_sent': 0, 'favourite_unavailable': False}

    if mode == 'direct':
        driver = _approved_driver(data.get('driver_id'), customer)
        _, approved_key = SERVICE_MAP[service_type]
        if getattr(driver, approved_key) != 'Yes' and driver.user_type != 'Driver':
            raise MatchError('This driver does not offer that service.', code='service_mismatch')
        req.status = 'matched'
        req.matched_driver_id = driver.id
        req.matched_at = now
        db.session.add(req)
        db.session.flush()
        neg = create_negotiation(customer, driver, req)
        req.negotiation_id = neg.id
        db.session.flush()
        db.session.add(RideRequestOffer(request_id=req.id, driver_id=driver.id, status='accepted',
                                        offered_at=now, responded_at=None))
        db.session.commit()
        result['negotiation'] = neg
        return req, result

    db.session.add(req)
    db.session.flush()
    if mode == 'favourite_first':
        fav = _pick_favourite(customer, data.get('driver_id'), pickup, service_type)
        if fav:
            dist, driver = fav
            req.favourite_driver_id = driver.id
            req.favourite_until = now + timedelta(seconds=S.get_int('carhire.favourite_first_s', 45))
            _offer(req, driver, dist, favourite=True)
            result['offers_sent'] = 1
            db.session.commit()
            jobs.enqueue_in(S.get_int('carhire.favourite_first_s', 45) + 1,
                            'backend.services.matching_service.favourite_timeout_job', req.id)
            return req, result
        result['favourite_unavailable'] = True
    result['offers_sent'] = broadcast(req)
    db.session.commit()
    if result['offers_sent'] == 0:
        raise MatchError('No drivers are available near you right now. Try again in a few minutes.',
                         code='no_drivers', status=409, data={'request_id': req.id})
    return req, result


def _approved_driver(driver_id, customer):
    try:
        driver = db.session.get(AdminUser, int(driver_id))
    except (TypeError, ValueError):
        raise MatchError('driver_id is required for a direct request.', code='bad_driver')
    if not driver or driver.id == customer.id:
        raise MatchError('Driver not found.', code='not_found', status=404)
    if not driver.is_approved_driver() or not driver.is_account_active():
        raise MatchError('This driver is not available for trips.', code='driver_unavailable', status=409)
    return driver


def _pick_favourite(customer, driver_id, pickup, service_type):
    favs = favourite_ids(customer.id)
    if driver_id not in (None, ''):
        try:
            driver_id = int(driver_id)
        except (TypeError, ValueError):
            raise MatchError('Invalid driver_id.', code='bad_driver')
        if driver_id not in favs:
            raise MatchError('That driver is not in your favourites.', code='not_favourite')
        favs = {driver_id}
    if not favs:
        return None
    candidates = [c for c in online_drivers(pickup['lat'], pickup['lng'], service_type,
                                            exclude_ids=(customer.id,), limit=500) if c[1].id in favs]
    return candidates[0] if candidates else None


def _offer(req, driver, dist, favourite=False):
    now = datetime.utcnow()
    est = G.estimate((float(driver.current_latitude), float(driver.current_longitude)),
                     (float(req.pickup_lat), float(req.pickup_lng)))
    o = RideRequestOffer(request_id=req.id, driver_id=driver.id, status='offered', is_favourite=favourite,
                         distance_m=int(dist), eta_s=est['seconds'], offered_at=now)
    db.session.add(o)
    db.session.flush()
    from backend.services.notify import notify
    from backend.utils.money import fmt
    ctx = {'ride_type': 'carhire_request', 'request_id': req.id, 'price': fmt(req.offer_cents),
           'distance_km': round(dist / 1000, 1), 'favourite': favourite}
    notify('negotiation.new_request', [driver.id], ctx, dedupe_key=f'rr-{req.id}-{driver.id}')
    jobs.enqueue_after_commit('backend.services.matching_service.emit_offer', req.id, driver.id)
    return o


def emit_offer(request_id, driver_id):
    req = db.session.get(RideRequest, request_id)
    if req and req.status in OPEN:
        realtime.to_user(driver_id, 'carhire.request_offered', incoming_card(req, driver_id))


def broadcast(req, now=None):
    """Offer the request to the nearest online drivers. Caller commits. Returns offers sent."""
    now = now or datetime.utcnow()
    already = {o.driver_id for o in RideRequestOffer.query.filter_by(request_id=req.id)}
    n = S.get_int('carhire.broadcast_max_drivers', 10)
    drivers = online_drivers(float(req.pickup_lat), float(req.pickup_lng), req.service_type,
                             exclude_ids=already | {req.customer_id}, limit=n)
    for dist, d in drivers:
        _offer(req, d, dist)
    req.status = 'broadcasting'
    req.broadcast_at = now
    req.expires_at = now + timedelta(seconds=S.get_int('carhire.broadcast_timeout_s', 180))
    open_left = RideRequestOffer.query.filter_by(request_id=req.id, status='offered').count()
    if not drivers and not open_left:
        req.status = 'no_drivers'
    jobs.enqueue_after_commit('backend.services.matching_service.emit_request_update', req.id)
    return len(drivers)


def emit_request_update(request_id):
    req = db.session.get(RideRequest, request_id)
    if req:
        realtime.to_user(req.customer_id, 'carhire.request_updated', request_out(req))


def _lock_request(request_id):
    req = (RideRequest.query.filter(RideRequest.id == int(request_id)).with_for_update()
           .populate_existing().first())
    if not req:
        raise MatchError('Request not found.', code='not_found', status=404)
    return req


LIVE_OFFER = ('offered', 'customer_countered')          # the driver may act
COUNTER_LIVE = ('countered', 'customer_countered')       # a counter is on the table


def _ttl():
    return S.get_int('carhire.counter_offer_ttl_s', 90)


def _price(v, name='price_cents'):
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise MatchError(f'Invalid {name}.', code='bad_counter')
    if v < 50 or v > 10_000_00:
        raise MatchError('The price must be between $0.50 and $10,000.', code='bad_counter')
    return v


def _counter_expired(o, now):
    return o.status in COUNTER_LIVE and o.counter_expires_at is not None and o.counter_expires_at <= now


def respond(driver, request_id, accept=True, counter_cents=None):
    """Driver answers an offer. Returns (request, negotiation|None).

    • accept (no counter) on an `offered` offer → the customer's price is taken:
      match immediately (first acceptor wins, others withdrawn).
    • accept on a `customer_countered` offer → the customer's counter is taken: match.
    • counter_cents → the offer becomes `countered`; the customer sees it in the
      live offer list (`carhire.request_countered`) and the request STAYS OPEN
      for other drivers (spec §21.2.2 counter-offer marketplace).
    • decline → `declined` (favourite declines broadcast at once)."""
    req = _lock_request(request_id)
    offer = (RideRequestOffer.query.filter_by(request_id=req.id, driver_id=driver.id)
             .with_for_update().populate_existing().first())
    if not offer:
        raise MatchError('This request was not offered to you.', code='forbidden', status=403)
    now = datetime.utcnow()
    if _counter_expired(offer, now):
        offer.status = 'expired'
        db.session.commit()
    if req.status not in OPEN or offer.status not in LIVE_OFFER:
        taken = req.status == 'matched' and req.matched_driver_id != driver.id
        if taken:
            raise MatchError('Another driver already took this request.', code='already_taken', status=409)
        if req.status in OPEN and offer.status == 'countered':
            raise MatchError('Your counter-offer is waiting for the rider.', code='awaiting_customer', status=409,
                             data={'counter_cents': int(offer.counter_cents or 0)})
        raise MatchError('This request is no longer available.', code='not_available', status=409)

    if not accept:
        offer.status = 'declined'
        offer.responded_at = now
        db.session.flush()
        open_left = RideRequestOffer.query.filter(RideRequestOffer.request_id == req.id,
                                                  RideRequestOffer.status.in_(LIVE_OFFER + COUNTER_LIVE)).count()
        if req.status == 'favourite' and offer.is_favourite:
            broadcast(req, now)
        elif req.status == 'broadcasting' and not open_left:
            _expire(req, now, reason='All nearby drivers declined.')
        if offer.counter_round:
            jobs.enqueue_after_commit('backend.services.matching_service.emit_offer_update', req.id, offer.id)
        db.session.commit()
        return req, None

    if counter_cents not in (None, ''):
        counter_cents = _price(counter_cents, 'counter_cents')
        on_table = int(offer.customer_counter_cents) if offer.status == 'customer_countered' \
            else int(req.offer_cents)
        if counter_cents != on_table:
            _driver_counter(req, offer, driver, counter_cents, now)
            db.session.commit()
            return req, None
    agreed = int(offer.customer_counter_cents) if offer.status == 'customer_countered' else int(req.offer_cents)
    neg = _match(req, offer, driver, agreed, now, accepted_by=driver)
    return req, neg


def _driver_counter(req, offer, driver, counter_cents, now):
    from backend.services.notify import notify
    from backend.utils.money import fmt
    offer.status, offer.counter_by, offer.counter_cents = 'countered', 'driver', counter_cents
    offer.counter_round = int(offer.counter_round or 0) + 1
    offer.responded_at = now
    offer.counter_expires_at = now + timedelta(seconds=_ttl())
    if req.expires_at is None or req.expires_at < offer.counter_expires_at:
        req.expires_at = offer.counter_expires_at        # keep the request open while a counter is live
    db.session.flush()
    card = offer_card(offer, driver)
    notify('carhire.request_countered', [req.customer_id],
           {'id': req.id, 'request_id': req.id, 'offer_id': offer.id, 'price': fmt(counter_cents),
            'driver_first': card['driver']['first_name'], 'rating': card['driver']['rating'],
            'eta_min': card['eta_min'], 'counter_cents': counter_cents},
           dedupe_key=f'rr-counter-{offer.id}-{offer.counter_round}')
    jobs.enqueue_after_commit('backend.services.matching_service.emit_countered', req.id, offer.id)


def emit_countered(request_id, offer_id):
    o = db.session.get(RideRequestOffer, offer_id)
    req = db.session.get(RideRequest, request_id)
    if o and req and o.status == 'countered':
        payload = offer_card(o)
        realtime.to_user(req.customer_id, 'carhire.request_countered', {'request_id': req.id, **payload})


def emit_offer_update(request_id, offer_id):
    o = db.session.get(RideRequestOffer, offer_id)
    req = db.session.get(RideRequest, request_id)
    if o and req:
        realtime.to_user(req.customer_id, 'carhire.offer_updated', {'request_id': req.id, **offer_card(o)})


def customer_counter(customer, request_id, offer_id, price_cents):
    """Customer counters one driver's counter-offer. The driver gets
    `carhire.customer_countered` and may accept or counter again."""
    from backend.services.notify import notify
    from backend.utils.money import fmt
    req = _lock_request(request_id)
    if req.customer_id != customer.id:
        raise MatchError('Request not found.', code='not_found', status=404)
    price = _price(price_cents)
    offer = (RideRequestOffer.query.filter_by(id=int(offer_id), request_id=req.id)
             .with_for_update().populate_existing().first())
    if not offer:
        raise MatchError('Offer not found.', code='not_found', status=404)
    now = datetime.utcnow()
    if req.status not in OPEN:
        raise MatchError('This request is no longer open.', code='not_open', status=409)
    if _counter_expired(offer, now):
        offer.status = 'expired'
        db.session.commit()
        raise MatchError('This offer has expired.', code='offer_expired', status=409)
    if offer.status != 'countered':
        raise MatchError('You can counter only a driver\'s live counter-offer.', code='not_counterable',
                         status=409)
    if price == int(offer.counter_cents or 0):
        raise MatchError('That is the driver\'s price — accept the offer instead.', code='same_price')
    offer.status, offer.counter_by, offer.customer_counter_cents = 'customer_countered', 'customer', price
    offer.counter_round = int(offer.counter_round or 0) + 1
    offer.counter_expires_at = now + timedelta(seconds=_ttl())
    if req.expires_at is None or req.expires_at < offer.counter_expires_at:
        req.expires_at = offer.counter_expires_at
    db.session.flush()
    notify('carhire.customer_countered', [offer.driver_id],
           {'id': req.id, 'request_id': req.id, 'offer_id': offer.id, 'price': fmt(price),
            'customer_first': first_name(customer), 'price_cents': price},
           dedupe_key=f'rr-ccounter-{offer.id}-{offer.counter_round}')
    jobs.enqueue_after_commit('backend.services.matching_service.emit_customer_countered', req.id, offer.driver_id)
    db.session.commit()
    return req, offer


def emit_customer_countered(request_id, driver_id):
    req = db.session.get(RideRequest, request_id)
    if req and req.status in OPEN:
        realtime.to_user(driver_id, 'carhire.customer_countered', incoming_card(req, driver_id))


def accept_offer(customer, request_id, offer_id):
    """Customer accepts a driver's counter-offer: negotiation with that driver at
    PRICE_AGREED (agreed price = the counter), every other offer withdrawn."""
    req = _lock_request(request_id)
    if req.customer_id != customer.id:
        raise MatchError('Request not found.', code='not_found', status=404)
    offer = (RideRequestOffer.query.filter_by(id=int(offer_id), request_id=req.id)
             .with_for_update().populate_existing().first())
    if not offer:
        raise MatchError('Offer not found.', code='not_found', status=404)
    now = datetime.utcnow()
    if req.status not in OPEN:
        raise MatchError('This request is no longer open.', code='not_open', status=409,
                         data={'negotiation_id': req.negotiation_id})
    if _counter_expired(offer, now):
        offer.status = 'expired'
        db.session.commit()
        raise MatchError('This offer has expired.', code='offer_expired', status=409)
    if offer.status != 'countered':
        raise MatchError('Only a driver\'s live counter-offer can be accepted.', code='not_acceptable',
                         status=409)
    driver = db.session.get(AdminUser, offer.driver_id)
    if not driver or not driver.is_account_active():
        raise MatchError('This driver is no longer available.', code='driver_unavailable', status=409)
    neg = _match(req, offer, driver, int(offer.counter_cents), now, accepted_by=customer)
    return req, neg


def _match(req, offer, driver, agreed, now, accepted_by):
    """Create the negotiation at PRICE_AGREED with `driver` and close the request."""
    customer = db.session.get(AdminUser, req.customer_id)
    neg = create_negotiation(customer, driver, req, stage='NEGOTIATING')
    if agreed != int(req.offer_cents):
        by_driver = offer.counter_by != 'customer'
        db.session.add(NegotiationRecord(
            negotiation_id=neg.id, customer_id=customer.id, driver_id=driver.id,
            last_negotiator_id=driver.id if by_driver else customer.id, first_negotiator_id=customer.id,
            price=agreed, price_accepted='Yes', message_type='Negotiation'))
    neg.agreed_price = agreed
    neg.agreed_price_cents = agreed
    neg.customer_accepted = 'Accepted'
    neg.customer_driver = 'Accepted'
    offer.status = 'accepted'
    offer.responded_at = now
    db.session.flush()
    TSM.transition('carhire', neg.id, 'PRICE_AGREED', actor=accepted_by, ride=neg, commit=False,
                   meta={'agreed_price_cents': agreed, 'ride_request_id': req.id, 'offer_id': offer.id,
                         'counter_round': int(offer.counter_round or 0)})
    req.status = 'matched'
    req.matched_driver_id = driver.id
    req.matched_at = now
    req.negotiation_id = neg.id
    withdrawn = []
    for o in RideRequestOffer.query.filter(RideRequestOffer.request_id == req.id, RideRequestOffer.id != offer.id,
                                           RideRequestOffer.status.in_(LIVE_OFFER + COUNTER_LIVE)):
        o.status = 'withdrawn'
        o.responded_at = now
        withdrawn.append(o.driver_id)
    db.session.commit()
    for d in withdrawn:
        realtime.to_user(d, 'carhire.request_withdrawn', {'request_id': req.id, 'reason': 'taken'})
    realtime.to_user(req.customer_id, 'carhire.request_matched', {
        'request_id': req.id, 'negotiation_id': neg.id, 'offer_id': offer.id, 'agreed_cents': agreed,
        'counter_cents': offer.counter_cents, 'agreed': True, 'driver': driver_card(driver)})
    realtime.to_user(driver.id, 'carhire.request_matched', {'request_id': req.id, 'negotiation_id': neg.id,
                                                            'agreed_cents': agreed})
    return neg


def cancel(customer, request_id):
    req = _lock_request(request_id)
    if req.customer_id != customer.id:
        raise MatchError('Request not found.', code='not_found', status=404)
    if req.status not in OPEN and req.status != 'no_drivers':
        raise MatchError('This request can no longer be cancelled here.', code='not_open', status=409,
                         data={'negotiation_id': req.negotiation_id})
    now = datetime.utcnow()
    req.status = 'cancelled'
    ids = _close_offers(req, 'withdrawn', now)
    db.session.commit()
    for d in ids:
        realtime.to_user(d, 'carhire.request_withdrawn', {'request_id': req.id, 'reason': 'cancelled'})
    return req


def _close_offers(req, status, now):
    ids = []
    for o in RideRequestOffer.query.filter(RideRequestOffer.request_id == req.id,
                                           RideRequestOffer.status.in_(('offered', 'countered',
                                                                        'customer_countered'))):
        o.status = status
        o.responded_at = now
        ids.append(o.driver_id)
    return ids


def _expire(req, now, reason='No driver accepted your request in time.'):
    req.status = 'expired'
    ids = _close_offers(req, 'expired', now)
    from backend.services.notify import notify
    notify('ride.expired', [req.customer_id], {'reason': reason, 'request_id': req.id,
                                               'ride_type': 'carhire_request'})
    jobs.enqueue_after_commit('backend.services.matching_service.emit_request_update', req.id)
    for d in ids:
        jobs.enqueue_after_commit('backend.services.matching_service.emit_withdrawn', req.id, d)


def emit_withdrawn(request_id, driver_id):
    realtime.to_user(driver_id, 'carhire.request_withdrawn', {'request_id': request_id, 'reason': 'expired'})


# ── periodic ────────────────────────────────────────────────────────────────

def favourite_timeout_job(request_id):
    req = _lock_request(request_id)
    if req.status == 'favourite' and req.favourite_until and req.favourite_until <= datetime.utcnow():
        broadcast(req)
    db.session.commit()


def tick(now=None):
    """favourite-first timeouts → broadcast; expire unanswered broadcasts."""
    now = now or datetime.utcnow()
    done = {'broadcast': 0, 'expired': 0}
    for r in RideRequest.query.filter(RideRequest.status == 'favourite',
                                      RideRequest.favourite_until <= now).limit(100).all():
        try:
            req = _lock_request(r.id)
            if req.status == 'favourite':
                broadcast(req, now)
                done['broadcast'] += 1
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception('favourite timeout failed for request %s', r.id)
    done['counters_expired'] = expire_counters(now)
    for r in RideRequest.query.filter(RideRequest.status == 'broadcasting',
                                      RideRequest.expires_at <= now).limit(200).all():
        try:
            req = _lock_request(r.id)
            if req.status == 'broadcasting':
                _expire(req, now)
                done['expired'] += 1
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception('expire failed for request %s', r.id)
    return done


def expire_counters(now=None):
    """Counters nobody answered within carhire.counter_offer_ttl_s expire; the
    request stays open for other drivers."""
    now = now or datetime.utcnow()
    n = 0
    rows = (RideRequestOffer.query.filter(RideRequestOffer.status.in_(COUNTER_LIVE),
                                          RideRequestOffer.counter_expires_at <= now).limit(200).all())
    for o in rows:
        o.status = 'expired'
        o.responded_at = now
        req = db.session.get(RideRequest, o.request_id)
        if req is not None:
            jobs.enqueue_after_commit('backend.services.matching_service.emit_offer_update', req.id, o.id)
            jobs.enqueue_after_commit('backend.services.matching_service.emit_withdrawn', req.id, o.driver_id)
        n += 1
    db.session.commit()
    return n


# ── views ───────────────────────────────────────────────────────────────────

def _mini_user(uid):
    u = db.session.get(AdminUser, uid) if uid else None
    if not u:
        return None
    return {'id': u.id, 'first_name': first_name(u), 'avatar': resolve_media_url(u.avatar),
            'rating': float(u.rating) if u.rating else None, 'rating_count': u.rating_count or 0}


def request_out(req):
    offers = RideRequestOffer.query.filter_by(request_id=req.id).all()
    counts = {}
    for o in offers:
        counts[o.status] = counts.get(o.status, 0) + 1
    return {
        'id': req.id, 'mode': req.mode, 'status': req.status, 'service_type': req.service_type,
        'pickup': {'lat': float(req.pickup_lat), 'lng': float(req.pickup_lng), 'address': req.pickup_address},
        'dropoff': {'lat': float(req.dropoff_lat) if req.dropoff_lat is not None else None,
                    'lng': float(req.dropoff_lng) if req.dropoff_lng is not None else None,
                    'address': req.dropoff_address},
        'offer_cents': int(req.offer_cents), 'currency': 'cad', 'note': req.note,
        'favourite_driver': _mini_user(req.favourite_driver_id),
        'favourite_until': _iso(req.favourite_until), 'broadcast_at': _iso(req.broadcast_at),
        'expires_at': _iso(req.expires_at), 'negotiation_id': req.negotiation_id,
        'matched_driver': _mini_user(req.matched_driver_id), 'matched_at': _iso(req.matched_at),
        'offers': {'sent': len(offers), 'open': counts.get('offered', 0), 'declined': counts.get('declined', 0),
                   'countered': counts.get('countered', 0) + counts.get('customer_countered', 0)},
        # The live marketplace: every driver counter (and the customer's counter
        # back), newest first, with a per-offer expiry.
        'live_offers': [offer_card(o) for o in sorted(offers, key=lambda o: o.responded_at or o.offered_at,
                                                        reverse=True)
                        if o.status in COUNTER_LIVE and not _counter_expired(o, datetime.utcnow())],
        'counter_offer_ttl_s': _ttl(),
        'created_at': _iso(req.created_at),
    }


def offer_card(o, driver=None):
    """One driver's offer as the customer sees it (first name only, no phone)."""
    d = driver or db.session.get(AdminUser, o.driver_id)
    veh = (R.vehicle_card(d) or {}) if d else {}
    turn = 'customer' if o.status == 'countered' else ('driver' if o.status in ('customer_countered', 'offered')
                                                       else None)
    return {
        'offer_id': o.id, 'status': o.status, 'turn': turn,
        'driver': {'id': d.id if d else o.driver_id, 'first_name': first_name(d) if d else 'Driver',
                   'avatar': resolve_media_url(d.avatar) if d else None,
                   'rating': float(d.rating) if (d and d.rating) else None,
                   'rating_count': (d.rating_count or 0) if d else 0,
                   'vehicle': {k: veh.get(k) for k in ('make', 'model', 'color', 'year')}},
        'counter_cents': int(o.counter_cents) if o.counter_cents is not None else None,
        'customer_counter_cents': int(o.customer_counter_cents) if o.customer_counter_cents is not None else None,
        'counter_round': int(o.counter_round or 0),
        'eta_min': max(1, round(o.eta_s / 60)) if o.eta_s else None,
        'distance_m': o.distance_m,
        'expires_at': _iso(o.counter_expires_at),
        'accept_endpoint': f'/api/carhire/requests/{o.request_id}/offers/{o.id}/accept',
        'counter_endpoint': f'/api/carhire/requests/{o.request_id}/offers/{o.id}/counter',
    }


def incoming_card(req, driver_id):
    o = RideRequestOffer.query.filter_by(request_id=req.id, driver_id=driver_id).first()
    return {
        'request_id': req.id, 'service_type': req.service_type, 'offer_cents': int(req.offer_cents),
        'currency': 'cad', 'note': req.note,
        'pickup': {'lat': float(req.pickup_lat), 'lng': float(req.pickup_lng), 'address': req.pickup_address},
        'dropoff': {'lat': float(req.dropoff_lat) if req.dropoff_lat is not None else None,
                    'lng': float(req.dropoff_lng) if req.dropoff_lng is not None else None,
                    'address': req.dropoff_address},
        'trip_distance_m': req.distance_m,
        'distance_to_pickup_m': o.distance_m if o else None, 'eta_to_pickup_s': o.eta_s if o else None,
        'is_favourite': bool(o and o.is_favourite),
        'respond_by': _iso(req.favourite_until if req.status == 'favourite' else req.expires_at),
        'customer': _mini_user(req.customer_id),
        'offer_status': o.status if o else None,
        'my_counter_cents': int(o.counter_cents) if (o and o.counter_cents is not None) else None,
        'customer_counter_cents': int(o.customer_counter_cents) if (o and o.customer_counter_cents is not None)
        else None,
        'counter_expires_at': _iso(o.counter_expires_at) if o else None,
    }


def incoming(driver):
    rows = (db.session.query(RideRequest).join(RideRequestOffer, RideRequestOffer.request_id == RideRequest.id)
            .filter(RideRequestOffer.driver_id == driver.id, RideRequestOffer.status.in_(LIVE_OFFER),
                    RideRequest.status.in_(OPEN))
            .order_by(RideRequest.id.desc()).limit(50).all())
    return [incoming_card(r, driver.id) for r in rows]
