"""Ratings, reviews, tips and the driver profile card (spec §17).

    POST /api/rides/{type}/{id}/rating    party   {stars, tags[], comment, tip_cents?}
    GET  /api/rides/{type}/{id}/rating    party   my rating + other party status
    GET  /api/ratings/tags                any     fixed tag lists (EN/FR) per rater role
    GET  /api/drivers/{id}/profile-card   any     public driver card (first name only)
"""
from flask import Blueprint, request

from backend.models import db
from backend.services import ratings_service as RS
from backend.services import rides as R
from backend.utils.auth import jwt_required_with_user
from backend.utils.idempotency import idempotent
from backend.utils.response import error_response, success_response

ratings_bp = Blueprint('ratings_v4', __name__)


def _err(e):
    db.session.rollback()
    if isinstance(e, RS.RatingError):
        return error_response(e.message, data={'error_code': e.code, **e.data}, status_code=e.status)
    if isinstance(e, R.RideNotFound):
        return error_response(str(e), data={'error_code': 'not_found'}, status_code=404)
    raise e


@ratings_bp.route('/api/rides/<ride_type>/<int:ride_id>/rating', methods=['POST'])
@jwt_required_with_user
@idempotent
def rate(user, ride_type, ride_id):
    data = request.get_json(silent=True) or request.form or {}
    try:
        rating, extra = RS.submit(user, ride_type, ride_id, data)
    except (RS.RatingError, R.RideNotFound) as e:
        return _err(e)
    out = {'rating': {**RS._public(rating), 'tip_cents': rating.tip_cents, 'visible_at':
                      rating.visible_at.strftime('%Y-%m-%dT%H:%M:%SZ') if rating.visible_at else None},
           'ask_what_went_wrong': bool(extra.get('ask_what_went_wrong')),
           'safety_report': extra.get('safety_report'),
           'tip': extra.get('tip')}
    return success_response('Thanks for your rating', out, status_code=201)


@ratings_bp.route('/api/rides/<ride_type>/<int:ride_id>/rating', methods=['GET'])
@jwt_required_with_user
def rating_status(user, ride_type, ride_id):
    try:
        return success_response('Rating', RS.status_for(user, ride_type, ride_id))
    except (RS.RatingError, R.RideNotFound) as e:
        return _err(e)


@ratings_bp.route('/api/ratings/tags', methods=['GET'])
@jwt_required_with_user
def tags(user):
    return success_response('Rating tags', RS.tag_catalogue())


@ratings_bp.route('/api/drivers/<int:driver_id>/profile-card', methods=['GET'])
@jwt_required_with_user
def profile_card(user, driver_id):
    card = RS.profile_card(driver_id)
    if not card:
        return error_response('Driver not found', data={'error_code': 'not_found'}, status_code=404)
    return success_response('Driver profile', card)
