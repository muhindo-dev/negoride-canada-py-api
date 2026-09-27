from flask import Blueprint, request
from backend.models import db
from backend.models.user import AdminUser
from backend.models.route_stage import RouteStage
from backend.models.company import Company
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response
import importlib, math

resources_bp = Blueprint('resources', __name__)


@resources_bp.route('/api/route-stages', methods=['GET'])
@jwt_required_with_user
def route_stages(user):
    """Get all route stages."""
    stages = RouteStage.query.all()
    return success_response("Success", [s.to_dict() for s in stages])


@resources_bp.route('/api/drivers', methods=['GET'])
@jwt_required_with_user
def drivers(user):
    """Get all active drivers."""
    drivers = AdminUser.query.filter_by(user_type='Driver', status=1).all()
    return success_response("Success", [d.to_dict() for d in drivers])


@resources_bp.route('/api/saccos', methods=['GET'])
@jwt_required_with_user
def saccos(user):
    """Get all saccos/companies."""
    companies = Company.query.all()
    return success_response("Success", [c.to_dict() for c in companies])


@resources_bp.route('/api/sacco-join-request', methods=['POST'])
@jwt_required_with_user
def sacco_join_request(user):
    """Request to join a sacco."""
    data = request.get_json(silent=True) or request.form
    sacco_id = data.get('sacco_id')
    if not sacco_id:
        return error_response("sacco_id is required")

    company = Company.query.get(sacco_id)
    if not company:
        return error_response("Company not found", status_code=404)

    user.company_id = company.id
    db.session.commit()

    return success_response("Sussesfully", None)  # Match Laravel's typo


# ---------------------------------------------------------------------------
# Important contacts
# ---------------------------------------------------------------------------

@resources_bp.route('/api/important-contacts', methods=['GET', 'POST'])
@jwt_required_with_user
def important_contacts(user):
    """Get emergency/important contacts sorted by distance."""
    limit = request.args.get('limit') or (request.form.get('limit') if request.method == 'POST' else None)
    service_type = request.args.get('service_type') or (request.form.get('service_type') if request.method == 'POST' else None)
    search = request.args.get('search') or (request.form.get('search') if request.method == 'POST' else None)

    q = AdminUser.query.filter(AdminUser.user_type.in_([
        'ambulance', 'police', 'delivery', 'breakdown', 'firebrugade'
    ]))

    if service_type and service_type != 'all':
        q = q.filter_by(user_type=service_type)
    if search:
        q = q.filter(AdminUser.name.ilike(f'%{search}%'))

    contacts = q.all()

    # Sort by distance if user has location
    user_lat = float(user.current_latitude) if user.current_latitude else None
    user_lng = float(user.current_longitude) if user.current_longitude else None

    result = []
    for c in contacts:
        cd = c.to_dict()
        # v4 (spec §8.1): additive category/province fields
        cd.setdefault('category', c.user_type)
        cd.setdefault('province', getattr(c, 'province', None))
        if user_lat and user_lng and c.current_latitude and c.current_longitude:
            cd['distance'] = _haversine(user_lat, user_lng, float(c.current_latitude), float(c.current_longitude))
        else:
            cd['distance'] = None
        result.append(cd)

    result.sort(key=lambda x: x.get('distance') or 999999)

    if limit:
        result = result[:int(limit)]

    # v4 (spec §8.1): curated help contacts (911, 988, police non-emergency by
    # province, roadside, NegoRide support). Additive — old clients ignore it.
    province = (request.args.get('province') or getattr(user, 'province', None) or '').upper()[:2] or None
    try:
        from backend.services import safety_service
        help_list = safety_service.help_contacts(province)
        support = safety_service.support_contact()
    except Exception:
        help_list, support = [], None

    return success_response("Success", {
        'contacts': result,
        'user_location': {'latitude': user.current_latitude, 'longitude': user.current_longitude},
        'total_count': len(result),
        'filters_applied': {'service_type': service_type, 'search': search},
        'help_contacts': help_list,
        'support': support,
        'province': province,
        'emergency_number': '911',
    })


@resources_bp.route('/api/contacts-statistics', methods=['GET'])
@resources_bp.route('/api/important-contacts/statistics', methods=['GET'])
@jwt_required_with_user
def contacts_statistics(user):
    """Count of contacts by service type."""
    from sqlalchemy import func

    total = AdminUser.query.filter(AdminUser.user_type.in_([
        'ambulance', 'police', 'delivery', 'breakdown', 'firebrugade'
    ])).count()

    by_type = {}
    for stype in ['ambulance', 'police', 'delivery', 'breakdown', 'firebrugade']:
        by_type[stype] = AdminUser.query.filter_by(user_type=stype).count()

    with_location = AdminUser.query.filter(
        AdminUser.user_type.in_(['ambulance', 'police', 'delivery', 'breakdown', 'firebrugade']),
        AdminUser.current_latitude.isnot(None),
        AdminUser.current_longitude.isnot(None),
    ).count()

    return success_response("Success", {
        'total_contacts': total,
        'by_service_type': by_type,
        'contacts_with_location': with_location,
    })


# ---------------------------------------------------------------------------
# Unauthenticated utility routes
# ---------------------------------------------------------------------------

@resources_bp.route('/api/users', methods=['GET'])
@jwt_required_with_user
def search_users(user):
    """Search users by name. Requires auth; returns a PII-safe projection so the
    directory can't be harvested for emails/phones/national IDs."""
    q = request.args.get('q', '')
    users = AdminUser.query.filter(AdminUser.name.ilike(f'%{q}%')).limit(20).all()
    return success_response("Success", [u.to_public_dict() for u in users])


@resources_bp.route('/api/ajax', methods=['GET'])
@jwt_required_with_user
def ajax_search(user):
    """Dynamic model AJAX search. Requires auth; AdminUser results use the
    PII-safe projection."""
    model_name = request.args.get('model')
    q = request.args.get('q', '')
    search_by_1 = request.args.get('search_by_1', 'name')

    if not model_name:
        return error_response("model parameter is required")

    # Only allow safe model names
    allowed_models = {
        'AdminUser': AdminUser,
        'Company': Company,
        'RouteStage': RouteStage,
    }

    model_cls = allowed_models.get(model_name)
    if not model_cls:
        return error_response("Model not found")

    col = getattr(model_cls, search_by_1, None)
    if col is None:
        return error_response("Invalid search column")

    items = model_cls.query.filter(col.ilike(f'%{q}%')).limit(20).all()
    serialize = (lambda i: i.to_public_dict()) if model_cls is AdminUser else (lambda i: i.to_dict())
    return success_response("Success", [serialize(i) for i in items])


# Dynamic model query (match Laravel's /api/api/{model})
@resources_bp.route('/api/api/<model_name>', methods=['GET'])
@jwt_required_with_user
def dynamic_model(user, model_name):
    """Dynamic model query matching Laravel's /api/api/{model}."""
    allowed_models = {
        'AdminUser': AdminUser,
        'Trip': Trip,
        'TripBooking': TripBooking,
        'Company': Company,
        'RouteStage': RouteStage,
    }

    model_cls = allowed_models.get(model_name)
    if not model_cls:
        return error_response("Model not found")

    q = model_cls.query

    # Apply query filters from q_ prefixed params
    for key, val in request.args.items():
        if key.startswith('q_'):
            col_name = key[2:]
            col = getattr(model_cls, col_name, None)
            if col is not None:
                q = q.filter(col == val)

    items = q.limit(100).all()
    return success_response("Success", [i.to_dict() for i in items])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine(lat1, lon1, lat2, lon2):
    """Haversine formula – returns distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
