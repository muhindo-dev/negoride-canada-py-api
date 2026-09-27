from flask import Blueprint, request
from datetime import datetime
from backend.models import db
from backend.models.user import AdminUser
from backend.models.negotiation import Negotiation
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

location_bp = Blueprint('location', __name__)


def _online_block_reason(user):
    """v4: expired documents, pending suspensions etc. (account_service) block going online."""
    try:
        from backend.services import account_service
    except ImportError:
        return None
    ok, reason = account_service.can_go_online(user)
    return None if ok else reason


@location_bp.route('/api/go-on-off', methods=['POST'])
@jwt_required_with_user
def go_on_off(user):
    """Toggle driver online/offline. Updates GPS and last_location_update."""
    data = request.get_json(silent=True) or request.form
    # Standard field names are latitude/longitude; lati/long kept as aliases.
    lati = data.get('latitude', data.get('lati'))
    long_ = data.get('longitude', data.get('long'))
    status = data.get('status')

    if not all([lati, long_, status]):
        return error_response("latitude, longitude, and status are required")

    if status not in ('online', 'offline'):
        return error_response("Status must be 'online' or 'offline'")

    # SECURITY: only an APPROVED driver may go online. Applicants awaiting review
    # must not be able to receive/serve trips.
    if status == 'online' and not user.is_approved_driver():
        return error_response(
            "Your driver application is still under review. "
            "You can go online once it has been approved."
        )
    if status == 'online':
        reason = _online_block_reason(user)
        if reason:
            return error_response(reason, data={'error_code': 'cannot_go_online'})

    # ready_for_trip is the real DB column (varchar 'Yes'/'No')
    user.current_latitude = lati
    user.current_longitude = long_
    user.current_address = f"{lati},{long_}"
    user.ready_for_trip = 'Yes' if status == 'online' else 'No'
    user.last_location_update = datetime.utcnow()

    db.session.commit()

    return success_response(f"Success!, you are now {status}.", status)


@location_bp.route('/api/update-online-status', methods=['POST'])
@jwt_required_with_user
def update_online_status(user):
    """Flexible status update. If no status param, returns current."""
    data = request.get_json(silent=True) or request.form
    status = data.get('status')
    lat = data.get('latitude') or data.get('lati')
    lng = data.get('longitude') or data.get('long')

    if lat:
        user.current_latitude = lat
    if lng:
        user.current_longitude = lng

    if status:
        if status not in ('online', 'offline'):
            return error_response("Status must be 'online' or 'offline'")
        # SECURITY: only an APPROVED driver may go online (see go_on_off).
        if status == 'online' and not user.is_approved_driver():
            return error_response(
                "Your driver application is still under review. "
                "You can go online once it has been approved."
            )
        if status == 'online':
            reason = _online_block_reason(user)
            if reason:
                return error_response(reason, data={'error_code': 'cannot_go_online'})
        user.ready_for_trip = 'Yes' if status == 'online' else 'No'
        if lat or lng:
            user.last_location_update = datetime.utcnow()
    else:
        # Return current status
        db.session.commit()
        return success_response("Success", 'online' if user.ready_for_trip == 'Yes' else 'offline')

    db.session.commit()
    return success_response("Success", 'online' if user.ready_for_trip == 'Yes' else 'offline')


@location_bp.route('/api/refresh-status', methods=['POST'])
@jwt_required_with_user
def refresh_status(user):
    """Get driver status + active trip info."""
    data = request.get_json(silent=True) or request.form
    lati = data.get('latitude', data.get('lati'))
    long_ = data.get('longitude', data.get('long'))

    if lati:
        user.current_latitude = lati
    if long_:
        user.current_longitude = long_

    # Check for active trip (negotiation)
    active_trip = Negotiation.query.filter(
        Negotiation.driver_id == user.id,
        Negotiation.status.in_(['Accepted', 'Started']),
    ).order_by(Negotiation.created_at.desc()).first()

    db.session.commit()

    return success_response("Success", {
        'status': 'online' if user.ready_for_trip == 'Yes' else 'offline',
        'has_trip': 'Yes' if active_trip else 'No',
        'trip': active_trip.to_dict() if active_trip else None,
    })


@location_bp.route('/api/update-location', methods=['POST'])
@jwt_required_with_user
def update_location(user):
    """Update user's GPS coordinates."""
    data = request.get_json(silent=True) or request.form
    lat = data.get('latitude', data.get('lati'))
    lng = data.get('longitude', data.get('long'))

    if lat is None or lng is None:
        return error_response("latitude and longitude are required")

    # v4: one pipeline for every position (breadcrumbs, live map, ETA, arrival
    # detection, safety checks) — see services/tracking.py
    from backend.services import tracking
    try:
        tracking.ingest(user, data)
    except tracking.LocationError as e:
        db.session.rollback()
        return error_response(str(e))

    return success_response("Success", {
        'latitude': user.current_latitude,
        'longitude': user.current_longitude,
        'current_address': user.current_address,
        'updated_at': str(user.updated_at),
    })


@location_bp.route('/api/important-contacts/update-location', methods=['POST'])
@jwt_required_with_user
def update_location_alt(user):
    """Duplicate route – same as update-location."""
    data = request.get_json(silent=True) or request.form
    lat = data.get('latitude')
    lng = data.get('longitude')

    if lat:
        user.current_latitude = str(lat)
    if lng:
        user.current_longitude = str(lng)
    db.session.commit()

    return success_response("Success", {
        'latitude': user.current_latitude,
        'longitude': user.current_longitude,
        'current_address': user.current_address,
        'updated_at': str(user.updated_at),
    })
