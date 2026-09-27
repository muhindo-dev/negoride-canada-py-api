"""Car hire pick-a-driver + experience helpers (spec §16, §18.2, §21.2, §21.3).

Customer
    GET    /api/carhire/nearby-drivers?lat&lng&service_type
    POST   /api/carhire/requests                 {mode, driver_id?, pickup{lat,lng,address}, dropoff{…}, offer_cents, service_type, note?}
    GET    /api/carhire/requests/{id}
    POST   /api/carhire/requests/{id}/cancel
    GET    /api/favourite-drivers
    POST   /api/favourite-drivers                {driver_id}
    DELETE /api/favourite-drivers/{driver_id}
    GET    /api/pricing/fair-range?from_lat&from_lng&to_lat&to_lng&service_type
Driver
    GET    /api/carhire/requests/incoming
    POST   /api/carhire/requests/{id}/accept     {counter_cents?}
    POST   /api/carhire/requests/{id}/decline
    GET    /api/driver/demand-heatmap?lat&lng&radius_km
Parties
    GET    /api/rides/{type}/{id}/eta            polling fallback for `ride.eta_updated`
Anyone
    GET    /api/places/popular?province=&kind=
    POST   /api/analytics/events                 {events:[{name, value_num?, props?}]}  (auth optional)
"""
from flask import Blueprint, request

from backend.models import db
from backend.models.experience import RideRequest, RideRequestOffer
from backend.services import eta as ETA
from backend.services import insights_service as INS
from backend.services import matching_service as M
from backend.services import popular_places
from backend.services import rides as R
from backend.utils.auth import get_current_user, jwt_required_with_user
from backend.utils.idempotency import idempotent
from backend.utils.response import error_response, success_response

carhire_v4_bp = Blueprint('carhire_v4', __name__)


def _body():
    return request.get_json(silent=True) or request.form or {}


def _err(e):
    db.session.rollback()
    if isinstance(e, (M.MatchError,)):
        return error_response(e.message, data={'error_code': e.code, **e.data}, status_code=e.status)
    if isinstance(e, INS.InsightError):
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    if isinstance(e, R.RideNotFound):
        return error_response(str(e), data={'error_code': 'not_found'}, status_code=404)
    from backend.services import trip_state_machine as TSM
    if isinstance(e, TSM.TransitionError):
        return error_response(e.message, data={'error_code': e.code, **e.data}, status_code=e.status)
    raise e


def _coord(name, lo, hi, required=True):
    v = request.args.get(name)
    if v in (None, ''):
        if required:
            raise INS.InsightError(f'{name} is required.', code='bad_location')
        return None
    try:
        f = float(v)
    except ValueError:
        raise INS.InsightError(f'Invalid {name}.', code='bad_location')
    if not lo <= f <= hi:
        raise INS.InsightError(f'Invalid {name}.', code='bad_location')
    return f


# ── pick a driver ───────────────────────────────────────────────────────────

@carhire_v4_bp.route('/api/carhire/nearby-drivers', methods=['GET'])
@jwt_required_with_user
def nearby_drivers(user):
    from backend.services import settings_service as S
    if not S.flag('pick_a_driver'):
        return error_response('Choosing a driver is not available right now.',
                              data={'error_code': 'feature_off'}, status_code=403)
    try:
        lat, lng = _coord('lat', -90, 90), _coord('lng', -180, 180)
        drivers = M.nearby(user, lat, lng, request.args.get('service_type') or 'car')
    except (INS.InsightError, M.MatchError) as e:
        return _err(e)
    return success_response(f'{len(drivers)} driver(s) nearby', {'drivers': drivers, 'count': len(drivers)})


@carhire_v4_bp.route('/api/carhire/requests', methods=['POST'])
@jwt_required_with_user
@idempotent
def create_request(user):
    try:
        req, res = M.create_request(user, _body())
    except (M.MatchError, R.RideNotFound) as e:
        return _err(e)
    neg = res['negotiation']
    msg = {'direct': 'Request sent to your driver', 'favourite_first': 'Request sent to your favourite driver first',
           'broadcast': 'Request sent to nearby drivers'}[req.mode]
    if res['favourite_unavailable']:
        msg = 'Your favourite driver is offline — request sent to nearby drivers'
    return success_response(msg, {'request': M.request_out(req), 'negotiation': neg.to_dict() if neg else None,
                                  'offers_sent': res['offers_sent'],
                                  'favourite_unavailable': res['favourite_unavailable']}, status_code=201)


@carhire_v4_bp.route('/api/carhire/requests/incoming', methods=['GET'])
@jwt_required_with_user
def incoming(user):
    items = M.incoming(user)
    return success_response(f'{len(items)} open request(s)', {'requests': items})


@carhire_v4_bp.route('/api/carhire/requests/<int:request_id>', methods=['GET'])
@jwt_required_with_user
def show_request(user, request_id):
    req = db.session.get(RideRequest, request_id)
    if req and req.customer_id == user.id:
        return success_response('Request', M.request_out(req))
    if req and RideRequestOffer.query.filter_by(request_id=req.id, driver_id=user.id).first():
        return success_response('Request', M.incoming_card(req, user.id))
    return error_response('Request not found', data={'error_code': 'not_found'}, status_code=404)


@carhire_v4_bp.route('/api/carhire/requests/<int:request_id>/cancel', methods=['POST'])
@jwt_required_with_user
@idempotent
def cancel_request(user, request_id):
    try:
        req = M.cancel(user, request_id)
    except M.MatchError as e:
        return _err(e)
    return success_response('Request cancelled', M.request_out(req))


@carhire_v4_bp.route('/api/carhire/requests/<int:request_id>/accept', methods=['POST'])
@jwt_required_with_user
@idempotent
def accept_request(user, request_id):
    data = _body()
    try:
        req, neg = M.respond(user, request_id, accept=True, counter_cents=data.get('counter_cents'))
    except Exception as e:  # MatchError / TransitionError
        return _err(e)
    db.session.rollback()
    from backend.models.negotiation import Negotiation
    neg = db.session.get(Negotiation, neg.id)
    return success_response('You got the ride' if neg.trip_stage != 'NEGOTIATING' else 'Counter-offer sent',
                            {'request_id': req.id, 'negotiation': neg.to_dict()})


@carhire_v4_bp.route('/api/carhire/requests/<int:request_id>/decline', methods=['POST'])
@jwt_required_with_user
@idempotent
def decline_request(user, request_id):
    try:
        req, _ = M.respond(user, request_id, accept=False)
    except M.MatchError as e:
        return _err(e)
    return success_response('Request declined', {'request_id': req.id})


# ── favourites ──────────────────────────────────────────────────────────────

@carhire_v4_bp.route('/api/favourite-drivers', methods=['GET'])
@jwt_required_with_user
def favourites(user):
    return success_response('Favourite drivers', {'drivers': M.list_favourites(user)})


@carhire_v4_bp.route('/api/favourite-drivers', methods=['POST'])
@jwt_required_with_user
def add_favourite(user):
    try:
        M.add_favourite(user, _body().get('driver_id'))
    except M.MatchError as e:
        return _err(e)
    return success_response('Added to favourites', {'drivers': M.list_favourites(user)}, status_code=201)


@carhire_v4_bp.route('/api/favourite-drivers/<int:driver_id>', methods=['DELETE'])
@jwt_required_with_user
def remove_favourite(user, driver_id):
    M.remove_favourite(user, driver_id)
    return success_response('Removed from favourites', {'drivers': M.list_favourites(user)})


# ── ETA polling fallback (§16) ──────────────────────────────────────────────

@carhire_v4_bp.route('/api/rides/<ride_type>/<int:ride_id>/eta', methods=['GET'])
@jwt_required_with_user
def ride_eta(user, ride_type, ride_id):
    try:
        rt = R.normalize_type(ride_type)
        ride = R.load(rt, ride_id)
    except R.RideNotFound as e:
        return _err(e)
    role = R.role_of(user, rt, ride)
    if role is None:
        return error_response('You are not part of this ride.', data={'error_code': 'forbidden'}, status_code=403)
    stage = R.current_stage(rt, ride)
    data = {'ride_type': rt, 'ride_id': ride.id, 'stage': stage,
            'eta': ETA.current(rt, ride) if stage in ETA.ETA_STAGES else None, 'driver_location': None}
    confirmed = stage in ETA.ETA_STAGES or stage == 'DRIVER_ARRIVED'
    did = R.driver_id(rt, ride)
    if confirmed and did:
        from backend.models.user import AdminUser
        d = db.session.get(AdminUser, did)
        if d and d.current_latitude is not None:
            data['driver_location'] = {'lat': float(d.current_latitude), 'lng': float(d.current_longitude),
                                       'at': d.last_location_update.strftime('%Y-%m-%dT%H:%M:%SZ')
                                       if d.last_location_update else None}
    return success_response('ETA', data)


# ── fair-price hint + demand heatmap (§21.2) ────────────────────────────────

@carhire_v4_bp.route('/api/pricing/fair-range', methods=['GET'])
@jwt_required_with_user
def fair_range(user):
    try:
        o = (_coord('from_lat', -90, 90), _coord('from_lng', -180, 180))
        d = (_coord('to_lat', -90, 90), _coord('to_lng', -180, 180))
        st = M.normalize_service(request.args.get('service_type') or 'car')
    except (INS.InsightError, M.MatchError) as e:
        return _err(e)
    return success_response('Fair price range', INS.fair_range(o, d, st))


@carhire_v4_bp.route('/api/driver/demand-heatmap', methods=['GET'])
@jwt_required_with_user
def driver_heatmap(user):
    if not user.is_approved_driver() and not user.get_admin_roles():
        return error_response('Only drivers can see the demand map.', data={'error_code': 'forbidden'},
                              status_code=403)
    try:
        lat, lng = _coord('lat', -90, 90), _coord('lng', -180, 180)
        radius = _coord('radius_km', 0, 1000, required=False) or 10
    except INS.InsightError as e:
        return _err(e)
    return success_response('Demand heatmap', INS.driver_heatmap(lat, lng, radius))


# ── instant address search support (§21.3) ──────────────────────────────────

@carhire_v4_bp.route('/api/places/popular', methods=['GET'])
def places_popular():
    province = request.args.get('province')
    if province and province.strip().upper() not in popular_places.PROVINCES:
        return error_response('Unknown province code.', data={'error_code': 'bad_province'})
    items = popular_places.popular(province, request.args.get('kind'))
    return success_response('Popular places', {'places': items, 'count': len(items), 'version': 1})


@carhire_v4_bp.route('/api/analytics/events', methods=['POST'])
def analytics_events():
    user = get_current_user()   # optional auth
    ip = (request.headers.get('X-Forwarded-For', '') or request.remote_addr or '').split(',')[0].strip()
    data = _body()
    events = data.get('events') if isinstance(data, dict) else None
    if events is None and isinstance(data, dict) and data.get('name'):
        events = [data]
    try:
        res = INS.ingest_events(user, ip, events)
    except INS.InsightError as e:
        return _err(e)
    return success_response('Events recorded', res, status_code=202)
