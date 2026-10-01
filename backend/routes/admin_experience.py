"""Admin — ratings explorer and reports & analytics (spec §19.1.9, §19.1.13).
Roles: ops, support (+ super_admin). All date params are UTC ISO dates/datetimes.

    GET  /api/admin/ratings                     explorer (filters, paging)
    GET  /api/admin/ratings/lowest-drivers      ?min_count=10&limit=50
    GET  /api/admin/ratings/trend-alerts        ?drop=0.3&min_recent=3
    POST /api/admin/ratings/{id}/hide           {reason}  (mandatory, audited, score recomputed)
    POST /api/admin/ratings/{id}/unhide         {reason}
    GET  /api/admin/reports/demand-heatmap      ?from&to&cell_deg=0.01
    GET  /api/admin/reports/supply-demand       ?from&to&tz=America/Toronto
    GET  /api/admin/reports/negotiations        ?from&to
    GET  /api/admin/reports/cohorts             ?from&to&weeks=8
    GET  /api/admin/reports/earnings-distribution ?from&to&bucket_cents
    GET  /api/admin/analytics/latency           ?name=autocomplete_latency_ms&days=7
"""
from datetime import datetime, timedelta

from flask import Blueprint, request

from backend.models import db
from backend.models.experience import RideRating
from backend.models.user import AdminUser
from backend.services import insights_service as INS
from backend.services import ratings_service as RS
from backend.services.audit import audit
from backend.utils.auth import admin_role_required
from backend.utils.response import error_response, success_response

admin_experience_bp = Blueprint('admin_experience', __name__)
ROLES = ('ops', 'support')


def _dt(name, default):
    v = request.args.get(name)
    if not v:
        return default
    v = v.strip().replace('Z', '').replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            d = datetime.strptime(v[:19], fmt)
            if fmt == '%Y-%m-%d' and name == 'to':
                d += timedelta(days=1)       # inclusive end date
            return d
        except ValueError:
            continue
    raise ValueError(f'Invalid {name} date')


def _range(default_days=30, max_days=400):
    now = datetime.utcnow()
    until = _dt('to', now + timedelta(minutes=1))
    since = _dt('from', until - timedelta(days=default_days))
    if since >= until:
        raise ValueError('from must be before to')
    if (until - since).days > max_days:
        raise ValueError(f'Range too large (max {max_days} days)')
    return since, until


def _bad(e):
    return error_response(str(e), data={'error_code': 'bad_request'})


def _int_arg(name, default, lo, hi):
    try:
        return max(lo, min(hi, int(request.args.get(name, default))))
    except (TypeError, ValueError):
        return default


def _name(uid):
    u = db.session.get(AdminUser, uid) if uid else None
    return {'id': u.id, 'name': u.name, 'first_name': u.first_name} if u else None


def _rating_row(r):
    d = r.to_dict()
    d['rater'] = _name(r.rater_id)
    d['ratee'] = _name(r.ratee_id)
    return d


# ── ratings explorer ────────────────────────────────────────────────────────

@admin_experience_bp.route('/api/admin/ratings', methods=['GET'])
@admin_role_required(*ROLES)
def ratings_explorer(admin):
    a = request.args
    q = RideRating.query
    for col in ('rater_id', 'ratee_id', 'ride_id'):
        if a.get(col):
            q = q.filter(getattr(RideRating, col) == int(a[col]))
    if a.get('driver_id'):
        q = q.filter(RideRating.ratee_id == int(a['driver_id']), RideRating.role == 'customer')
    if a.get('ride_type'):
        q = q.filter(RideRating.ride_type == a['ride_type'])
    if a.get('role') in ('customer', 'driver'):
        q = q.filter(RideRating.role == a['role'])
    if a.get('stars'):
        q = q.filter(RideRating.stars == int(a['stars']))
    if a.get('min_stars'):
        q = q.filter(RideRating.stars >= int(a['min_stars']))
    if a.get('max_stars'):
        q = q.filter(RideRating.stars <= int(a['max_stars']))
    if a.get('hidden') in ('0', '1', 'true', 'false'):
        q = q.filter(RideRating.hidden_by_admin.is_(a['hidden'] in ('1', 'true')))
    if a.get('has_comment') in ('1', 'true'):
        q = q.filter(RideRating.comment.isnot(None), RideRating.comment != '')
    if a.get('tag'):
        q = q.filter(RideRating.tags.like(f'%"{a["tag"]}"%'))
    if a.get('with_tip') in ('1', 'true'):
        q = q.filter(RideRating.tip_cents > 0)
    try:
        if a.get('from'):
            q = q.filter(RideRating.created_at >= _dt('from', None))
        if a.get('to'):
            q = q.filter(RideRating.created_at < _dt('to', None))
    except ValueError as e:
        return _bad(e)
    page = _int_arg('page', 1, 1, 100000)
    per_page = _int_arg('per_page', 25, 1, 200)
    total = q.count()
    rows = q.order_by(RideRating.created_at.desc(), RideRating.id.desc()).offset((page - 1) * per_page) \
        .limit(per_page).all()
    return success_response('Ratings', {'items': [_rating_row(r) for r in rows], 'page': page,
                                        'per_page': per_page, 'total': total})


@admin_experience_bp.route('/api/admin/ratings/lowest-drivers', methods=['GET'])
@admin_role_required(*ROLES)
def lowest_drivers(admin):
    return success_response('Lowest-rated drivers', {'drivers': INS.lowest_rated_drivers(
        _int_arg('min_count', 10, 1, 10000), _int_arg('limit', 50, 1, 500))})


@admin_experience_bp.route('/api/admin/ratings/trend-alerts', methods=['GET'])
@admin_role_required(*ROLES)
def trend_alerts(admin):
    try:
        drop = float(request.args['drop']) if request.args.get('drop') else None
    except ValueError:
        return _bad('Invalid drop')
    return success_response('Rating trend alerts', {'alerts': INS.rating_trend_alerts(
        drop, _int_arg('min_recent', 3, 1, 1000))})


def _set_hidden(admin, rating_id, hidden):
    data = request.get_json(silent=True) or request.form or {}
    reason = (data.get('reason') or '').strip()
    if len(reason) < 5:
        return error_response('A reason (at least 5 characters) is required.', data={'error_code': 'reason_required'})
    r = RideRating.query.filter_by(id=rating_id).with_for_update().first()
    if not r:
        return error_response('Rating not found', data={'error_code': 'not_found'}, status_code=404)
    before = r.to_dict()
    r.hidden_by_admin = hidden
    r.hidden_by = admin.id if hidden else None
    r.hidden_reason = reason[:500] if hidden else None
    db.session.flush()
    score = RS.on_visibility_changed(r)      # recompute + re-evaluate the rating rules
    audit('rating.hidden' if hidden else 'rating.unhidden', admin, 'ride_rating', r.id, before=before,
          after=r.to_dict(), meta={'reason': reason, 'ratee_score': score})
    db.session.commit()
    return success_response('Rating hidden' if hidden else 'Rating restored',
                            {'rating': _rating_row(r), 'ratee_score': score})


@admin_experience_bp.route('/api/admin/ratings/<int:rating_id>/hide', methods=['POST'])
@admin_role_required(*ROLES)
def hide_rating(admin, rating_id):
    return _set_hidden(admin, rating_id, True)


@admin_experience_bp.route('/api/admin/ratings/<int:rating_id>/unhide', methods=['POST'])
@admin_role_required(*ROLES)
def unhide_rating(admin, rating_id):
    return _set_hidden(admin, rating_id, False)


# ── reports ─────────────────────────────────────────────────────────────────

@admin_experience_bp.route('/api/admin/reports/demand-heatmap', methods=['GET'])
@admin_role_required(*ROLES)
def demand_heatmap(admin):
    try:
        since, until = _range(7)
        cell = float(request.args.get('cell_deg') or 0.01)
    except ValueError as e:
        return _bad(e)
    cell = max(0.002, min(0.5, cell))
    cells = INS.demand_cells(since, until, cell)
    return success_response('Demand heatmap', {'from': since.isoformat() + 'Z', 'to': until.isoformat() + 'Z',
                                               'cell_size_deg': cell, 'cells': cells,
                                               'total_requests': sum(c['count'] for c in cells)})


@admin_experience_bp.route('/api/admin/reports/supply-demand', methods=['GET'])
@admin_role_required(*ROLES)
def supply_demand(admin):
    try:
        since, until = _range(7, max_days=92)
    except ValueError as e:
        return _bad(e)
    return success_response('Supply vs demand', INS.supply_vs_demand(since, until, request.args.get('tz') or 'UTC'))


@admin_experience_bp.route('/api/admin/reports/negotiations', methods=['GET'])
@admin_role_required(*ROLES)
def negotiations_report(admin):
    try:
        since, until = _range(30)
    except ValueError as e:
        return _bad(e)
    return success_response('Negotiation analytics', INS.negotiation_analytics(since, until))


@admin_experience_bp.route('/api/admin/reports/cohorts', methods=['GET'])
@admin_role_required(*ROLES)
def cohorts(admin):
    try:
        since, until = _range(84)
    except ValueError as e:
        return _bad(e)
    return success_response('Cohort retention', INS.cohort_retention(since, until, _int_arg('weeks', 8, 1, 26)))


@admin_experience_bp.route('/api/admin/reports/earnings-distribution', methods=['GET'])
@admin_role_required(*ROLES, 'finance')
def earnings(admin):
    try:
        since, until = _range(30)
    except ValueError as e:
        return _bad(e)
    bucket = _int_arg('bucket_cents', 0, 0, 10_000_000) or None
    return success_response('Driver earnings distribution', INS.earnings_distribution(since, until, bucket))


@admin_experience_bp.route('/api/admin/analytics/latency', methods=['GET'])
@admin_role_required(*ROLES)
def latency(admin):
    name = (request.args.get('name') or 'autocomplete_latency_ms').strip().lower()
    if not INS.NAME_RE.match(name):
        return _bad('Invalid name')
    return success_response('Latency', INS.latency_stats(name, _int_arg('days', 7, 1, 90)))
