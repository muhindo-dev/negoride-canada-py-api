"""Admin Safety Center + Live Operations (spec §8.3, §9.1, §10.2, §19.1).

Roles: ops / safety_reviewer (super_admin passes every check). Recordings:
safety_reviewer only. Every write and every personal-data access is audited.

    GET  /api/admin/safety/incidents                      ?status=&kind=&page=&per_page=   (open first)
    GET  /api/admin/safety/incidents/<id>                 detail + timeline
    POST /api/admin/safety/incidents/<id>/acknowledge     {note?}
    POST /api/admin/safety/incidents/<id>/resolve         {note?}
    POST /api/admin/safety/incidents/<id>/false-alarm     {note?}
    POST /api/admin/safety/incidents/<id>/notes           {note}
    GET  /api/admin/safety/incidents/<id>/contact         phone numbers for one-click call (audited)
    GET  /api/admin/safety/incidents/<id>/report.pdf      police / insurance export (audited)
    GET  /api/admin/safety/checks                         ?status=
    GET  /api/admin/safety/reports                        ?status=&category=
    GET  /api/admin/safety/reports/<id>                   (+ attachment signed URLs, audited)
    POST /api/admin/safety/reports/<id>/review            {status: reviewing|resolved|dismissed, resolution?}
    GET  /api/admin/safety/recordings                     ?ride_type=&ride_id=&incident_id=&status=   safety_reviewer
    GET  /api/admin/safety/recordings/<id>                chunk signed URLs + stream_url (audited) safety_reviewer
    GET  /api/admin/safety/recordings/<id>/chunks/<seq>   authenticated audio stream (Range), EVERY fetch audited
    POST /api/admin/safety/recordings/<id>/hold           {legal_hold: bool}                        safety_reviewer
    GET|POST /api/admin/safety/help-contacts ; PUT|DELETE /api/admin/safety/help-contacts/<id>
    GET  /api/admin/live/drivers                          ?include_offline_active=1 (default 1)
    GET  /api/admin/live/rides                            open requests, rideshare trips, open SOS positions
    GET  /api/admin/rides/<type>/<id>/route               breadcrumbs for replay (?snap=1 → Roads API, cached)
"""
from datetime import datetime, timedelta

from flask import Blueprint, Response, request
from sqlalchemy import case

from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.platform import AuditLog, TripEvent
from backend.models.safety import (HelpContact, Recording, RideLocation, RideShareLink, SafetyCheck, SafetyIncident,
                                   SafetyIncidentLocation, SafetyReport)
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.trip import Trip
from backend.models.user import AdminUser
from backend.services import live_share
from backend.services import private_storage as PS
from backend.services import recording_service as RS
from backend.services import rides as R
from backend.services import safety_service as SS
from backend.services import trip_state_machine as TSM
from backend.services.audit import audit
from backend.utils.auth import admin_role_required
from backend.utils.response import error_response, success_response

admin_safety_bp = Blueprint('admin_safety', __name__)

SAFETY_ROLES = ('ops', 'safety_reviewer')
RECORDING_ROLES = ('safety_reviewer',)
SIGNED_TTL_S = 300


def _body():
    return request.get_json(silent=True) or request.form.to_dict() or {}


def _page():
    try:
        page = max(1, int(request.args.get('page', 1)))
        per = min(100, max(1, int(request.args.get('per_page', 25))))
    except ValueError:
        page, per = 1, 25
    return page, per


def _paged(q, page, per, fn):
    total = q.count()
    rows = q.offset((page - 1) * per).limit(per).all()
    return success_response('Success', {'items': [fn(r) for r in rows], 'total': total, 'page': page,
                                        'per_page': per, 'last_page': max(1, -(-total // per))})


def _nf(what='Not found.'):
    return error_response(what, data={'error_code': 'not_found'}, status_code=404)


# ── incidents ───────────────────────────────────────────────────────────────

@admin_safety_bp.route('/api/admin/safety/incidents', methods=['GET'])
@admin_role_required(*SAFETY_ROLES)
def incidents(admin):
    q = SafetyIncident.query
    st = request.args.get('status')
    if st == 'open':
        q = q.filter(SafetyIncident.status.in_(SS.OPEN_STATUSES))
    elif st:
        q = q.filter(SafetyIncident.status == st)
    if request.args.get('kind'):
        q = q.filter(SafetyIncident.kind == request.args['kind'])
    order = case((SafetyIncident.status == 'open', 0), (SafetyIncident.status == 'acknowledged', 1), else_=2)
    q = q.order_by(order, SafetyIncident.created_at.desc())
    page, per = _page()
    open_count = SafetyIncident.query.filter(SafetyIncident.status == 'open').count()
    resp, code = _paged(q, page, per, lambda i: SS.incident_dict(i, for_admin=True))
    data = resp.get_json()
    data['data']['open_count'] = open_count
    return success_response('Success', data['data'])


def _incident_detail(inc):
    d = SS.incident_dict(inc, for_admin=True)
    locs = (SafetyIncidentLocation.query.filter_by(incident_id=inc.id)
            .order_by(SafetyIncidentLocation.recorded_at).limit(2000).all())
    d['locations'] = [{'lat': float(x.lat), 'lng': float(x.lng), 'accuracy_m': x.accuracy_m, 'heading': x.heading,
                       'speed_mps': SS._f(x.speed_mps), 'battery_pct': x.battery_pct, 'at': SS.iso(x.recorded_at)}
                      for x in locs]
    timeline = [{'at': SS.iso(inc.created_at), 'type': 'incident', 'label': f'{inc.kind.upper()} triggered',
                 'by': inc.user_id}]
    events = []
    reports, recs, checks = [], [], []
    if inc.ride_type and inc.ride_id:
        events = TripEvent.query.filter_by(ride_type=inc.ride_type, ride_id=inc.ride_id).order_by(TripEvent.id).all()
        reports = SafetyReport.query.filter_by(ride_type=inc.ride_type, ride_id=inc.ride_id).all()
        recs = Recording.query.filter((Recording.incident_id == inc.id) |
                                      ((Recording.ride_type == inc.ride_type) &
                                       (Recording.ride_id == inc.ride_id))).all()
        checks = SafetyCheck.query.filter_by(ride_type=inc.ride_type, ride_id=inc.ride_id).all()
    else:
        recs = Recording.query.filter_by(incident_id=inc.id).all()
    for e in events:
        timeline.append({'at': SS.iso(e.created_at), 'type': 'trip_event', 'label': f'{e.from_stage} → {e.to_stage}',
                         'actor_type': e.actor_type, 'lat': SS._f(e.lat), 'lng': SS._f(e.lng)})
    audits = (AuditLog.query.filter_by(entity_type='safety_incident', entity_id=str(inc.id))
              .order_by(AuditLog.id).all())
    for a in audits:
        timeline.append({'at': SS.iso(a.created_at), 'type': 'audit', 'label': a.action, 'actor_id': a.actor_id,
                         'actor_type': a.actor_type})
    for c in checks:
        timeline.append({'at': SS.iso(c.created_at), 'type': 'safety_check', 'label': f'{c.kind} check → {c.status}'})
    timeline.sort(key=lambda x: x['at'] or '')
    d['trip_events'] = [e.to_dict() for e in events]
    d['timeline'] = timeline
    d['reports'] = [_report_dict(r) for r in reports]
    d['recordings'] = [r.to_dict() for r in recs]
    d['checks'] = [c.to_dict() for c in checks]
    links = RideShareLink.query.filter_by(ride_type=live_share.INCIDENT, ride_id=inc.id).all()
    d['share_links'] = [{'url': live_share.url_for_token(l.token), 'expires_at': SS.iso(l.expires_at),
                         'view_count': l.view_count, 'contacts_notified': len(l.shared_with or [])} for l in links]
    return d


@admin_safety_bp.route('/api/admin/safety/incidents/<int:iid>', methods=['GET'])
@admin_role_required(*SAFETY_ROLES)
def incident(admin, iid):
    inc = db.session.get(SafetyIncident, iid)
    if not inc:
        return _nf('Incident not found.')
    audit('safety.incident_viewed', admin, 'safety_incident', inc.id)
    db.session.commit()
    return success_response('Success', _incident_detail(inc))


def _status_action(admin, iid, status):
    inc = SafetyIncident.query.filter_by(id=iid).with_for_update().first()
    if not inc:
        db.session.rollback()
        return _nf('Incident not found.')
    try:
        SS.close_incident(inc, status, admin, note=_body().get('note'))
    except SS.SafetyError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    return success_response('Incident updated.', SS.incident_dict(inc, for_admin=True))


@admin_safety_bp.route('/api/admin/safety/incidents/<int:iid>/acknowledge', methods=['POST'])
@admin_role_required(*SAFETY_ROLES)
def acknowledge(admin, iid):
    return _status_action(admin, iid, 'acknowledged')


@admin_safety_bp.route('/api/admin/safety/incidents/<int:iid>/resolve', methods=['POST'])
@admin_role_required(*SAFETY_ROLES)
def resolve(admin, iid):
    return _status_action(admin, iid, 'resolved')


@admin_safety_bp.route('/api/admin/safety/incidents/<int:iid>/false-alarm', methods=['POST'])
@admin_role_required(*SAFETY_ROLES)
def false_alarm(admin, iid):
    return _status_action(admin, iid, 'false_alarm')


@admin_safety_bp.route('/api/admin/safety/incidents/<int:iid>/notes', methods=['POST'])
@admin_role_required(*SAFETY_ROLES)
def add_note(admin, iid):
    inc = db.session.get(SafetyIncident, iid)
    if not inc:
        return _nf('Incident not found.')
    note = (_body().get('note') or '').strip()
    if not note:
        return error_response('note is required.', data={'error_code': 'note_required'}, status_code=422)
    SS.append_note(inc, admin, note)
    audit('safety.incident_note', admin, 'safety_incident', inc.id, meta={'note': note[:2000]})
    db.session.commit()
    SS.emit_incident('safety.sos_updated', inc, {'type': 'note'})
    return success_response('Note added.', SS.incident_dict(inc, for_admin=True))


def _phone_of(u):
    from backend.utils.phone import safe_normalize
    return (u.phone_e164 or safe_normalize(u.phone_number)) if u else None


@admin_safety_bp.route('/api/admin/safety/incidents/<int:iid>/contact', methods=['GET'])
@admin_role_required(*SAFETY_ROLES)
def contact(admin, iid):
    inc = db.session.get(SafetyIncident, iid)
    if not inc:
        return _nf('Incident not found.')
    people = []
    u = db.session.get(AdminUser, inc.user_id)
    people.append({'user_id': inc.user_id, 'relation': 'reporter', 'role': inc.role, 'name': u.name if u else None,
                   'phone': _phone_of(u)})
    brief = SS.ride_brief(inc.ride_type, inc.ride_id)
    if brief:
        for pid in [brief['driver_id']] + list(brief['customer_ids']):
            if pid and pid != inc.user_id:
                p = db.session.get(AdminUser, pid)
                people.append({'user_id': pid, 'relation': 'driver' if pid == brief['driver_id'] else 'customer',
                               'name': p.name if p else None, 'phone': _phone_of(p)})
    audit('personal_data.access', admin, 'safety_incident', inc.id,
          meta={'fields': ['phone'], 'user_ids': [p['user_id'] for p in people], 'purpose': 'safety_call'})
    db.session.commit()
    return success_response('Success', {'incident_id': inc.id, 'people': people,
                                        'emergency_number': '911'})


REPORT_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
body{font-family:Helvetica,Arial,sans-serif;font-size:11px;color:#111}
h1{font-size:18px;margin:0 0 4px}h2{font-size:13px;border-bottom:1px solid #999;margin:16px 0 6px}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:3px 5px;text-align:left;vertical-align:top}
.muted{color:#666}.kv td:first-child{width:28%;font-weight:bold;background:#f4f4f4}
</style></head><body>
<h1>NegoRide Canada — Safety Incident Report #{{ i.id }}</h1>
<p class="muted">Generated {{ generated }} UTC by {{ admin }} · Confidential — for police / insurance use</p>
<h2>Incident</h2><table class="kv">
<tr><td>Type</td><td>{{ i.kind }} ({{ i.severity }})</td></tr>
<tr><td>Status</td><td>{{ i.status }}</td></tr>
<tr><td>Raised by</td><td>{{ i.user.name }} (user #{{ i.user_id }}, {{ i.role }})</td></tr>
<tr><td>Raised at</td><td>{{ i.created_at }}</td></tr>
<tr><td>First position</td><td>{{ i.lat }}, {{ i.lng }} (±{{ i.accuracy_m or '?' }} m) · battery {{ i.battery_pct or '?' }}%</td></tr>
<tr><td>Last position</td><td>{{ i.last_lat }}, {{ i.last_lng }} at {{ i.last_location_at }}</td></tr>
<tr><td>Acknowledged</td><td>{{ i.acknowledged_at or '—' }} (admin #{{ i.acknowledged_by or '—' }})</td></tr>
<tr><td>Escalated to on-call</td><td>{{ i.escalated_at or '—' }}</td></tr>
<tr><td>Closed</td><td>{{ i.resolved_at or '—' }} (admin #{{ i.resolved_by or '—' }})</td></tr>
</table>
{% if ride %}<h2>Ride</h2><table class="kv">
<tr><td>Ride</td><td>{{ ride.ride_type }} #{{ ride.ride_id }} — stage {{ ride.stage }}</td></tr>
<tr><td>Pickup</td><td>{{ ride.pickup_address }}</td></tr><tr><td>Drop-off</td><td>{{ ride.dropoff_address }}</td></tr>
<tr><td>Driver</td><td>{{ driver_name }} (user #{{ ride.driver_id }}) {{ vehicle }}</td></tr>
<tr><td>Customer(s)</td><td>{{ customers }}</td></tr></table>{% endif %}
<h2>Timeline</h2><table><tr><th>Time (UTC)</th><th>Type</th><th>Event</th></tr>
{% for t in timeline %}<tr><td>{{ t.at }}</td><td>{{ t.type }}</td><td>{{ t.label }}</td></tr>{% endfor %}</table>
<h2>Notes</h2><pre style="white-space:pre-wrap;font-family:inherit">{{ i.notes or '—' }}</pre>
<h2>Location trail ({{ locs|length }} points{% if locs|length > 300 %}, first 300 shown{% endif %})</h2>
<table><tr><th>Time (UTC)</th><th>Lat</th><th>Lng</th><th>Accuracy m</th></tr>
{% for l in locs[:300] %}<tr><td>{{ l.at }}</td><td>{{ l.lat }}</td><td>{{ l.lng }}</td><td>{{ l.accuracy_m or '' }}</td></tr>{% endfor %}</table>
<h2>Reports</h2>{% for r in reports %}<p>#{{ r.id }} {{ r.category }} ({{ r.status }}) — {{ r.description or '' }}</p>{% else %}<p>—</p>{% endfor %}
<h2>Audio recordings</h2>{% for r in recs %}<p>#{{ r.id }} by user #{{ r.user_id }} ({{ r.role }}), {{ r.started_at }} → {{ r.stopped_at or 'running' }}, {{ r.chunk_count }} chunks, status {{ r.status }}{% if r.legal_hold %}, LEGAL HOLD{% endif %}</p>{% else %}<p>—</p>{% endfor %}
</body></html>"""


@admin_safety_bp.route('/api/admin/safety/incidents/<int:iid>/report.pdf', methods=['GET'])
@admin_role_required(*SAFETY_ROLES)
def report_pdf(admin, iid):
    inc = db.session.get(SafetyIncident, iid)
    if not inc:
        return _nf('Incident not found.')
    from jinja2 import Environment
    d = _incident_detail(inc)
    ride = d.get('ride')
    driver_name = vehicle = customers = ''
    if ride:
        drv = db.session.get(AdminUser, ride['driver_id']) if ride['driver_id'] else None
        driver_name = drv.name if drv else ''
        v = R.vehicle_card(drv) if drv else None
        if v:
            vehicle = ' '.join(str(x) for x in (v.get('color'), v.get('make'), v.get('model'), v.get('plate')) if x)
        customers = ', '.join(f"{(db.session.get(AdminUser, c).name if db.session.get(AdminUser, c) else '')} (#{c})"
                              for c in ride['customer_ids'])
    html = Environment(autoescape=True).from_string(REPORT_HTML).render(
        i=d, ride=ride, driver_name=driver_name, vehicle=vehicle, customers=customers, timeline=d['timeline'],
        locs=d['locations'], reports=d['reports'], recs=d['recordings'],
        generated=datetime.utcnow().strftime('%Y-%m-%d %H:%M'), admin=admin.name or f'admin #{admin.id}')
    from weasyprint import HTML
    pdf = HTML(string=html).write_pdf()
    audit('safety.incident_report_exported', admin, 'safety_incident', inc.id, meta={'bytes': len(pdf)})
    db.session.commit()
    resp = Response(pdf, mimetype='application/pdf')
    resp.headers['Content-Disposition'] = f'attachment; filename="negoride-incident-{inc.id}.pdf"'
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


# ── checks ──────────────────────────────────────────────────────────────────

@admin_safety_bp.route('/api/admin/safety/checks', methods=['GET'])
@admin_role_required(*SAFETY_ROLES)
def checks(admin):
    q = SafetyCheck.query
    if request.args.get('status'):
        q = q.filter(SafetyCheck.status == request.args['status'])
    page, per = _page()
    return _paged(q.order_by(SafetyCheck.id.desc()), page, per, lambda c: c.to_dict())


# ── reports ─────────────────────────────────────────────────────────────────

def _report_dict(r, signed_for=None):
    d = r.to_dict()
    atts = []
    for a in (r.attachments or []):
        item = {'name': a.get('name'), 'content_type': a.get('content_type'), 'bytes': a.get('bytes')}
        if signed_for is not None and a.get('key'):
            item['url'] = PS.signed_url(a['key'], ttl_s=SIGNED_TTL_S, content_type=a.get('content_type'),
                                        actor_id=signed_for.id)
        atts.append(item)
    d['attachments'] = atts
    rep = db.session.get(AdminUser, r.reporter_id)
    d['reporter'] = {'id': r.reporter_id, 'name': rep.name if rep else None}
    if r.reported_user_id:
        ru = db.session.get(AdminUser, r.reported_user_id)
        d['reported_user'] = {'id': r.reported_user_id, 'name': ru.name if ru else None}
    return d


@admin_safety_bp.route('/api/admin/safety/reports', methods=['GET'])
@admin_role_required(*SAFETY_ROLES)
def reports(admin):
    q = SafetyReport.query
    if request.args.get('status'):
        q = q.filter(SafetyReport.status == request.args['status'])
    if request.args.get('category'):
        q = q.filter(SafetyReport.category == request.args['category'])
    order = case((SafetyReport.status == 'open', 0), (SafetyReport.status == 'reviewing', 1), else_=2)
    page, per = _page()
    return _paged(q.order_by(order, SafetyReport.id.desc()), page, per, _report_dict)


@admin_safety_bp.route('/api/admin/safety/reports/<int:rid>', methods=['GET'])
@admin_role_required(*SAFETY_ROLES)
def report(admin, rid):
    r = db.session.get(SafetyReport, rid)
    if not r:
        return _nf('Report not found.')
    if r.attachments:
        audit('safety.report_attachments_accessed', admin, 'safety_report', r.id,
              meta={'count': len(r.attachments)})
        db.session.commit()
    return success_response('Success', _report_dict(r, signed_for=admin))


@admin_safety_bp.route('/api/admin/safety/reports/<int:rid>/review', methods=['POST'])
@admin_role_required(*SAFETY_ROLES)
def review_report(admin, rid):
    r = db.session.get(SafetyReport, rid)
    if not r:
        return _nf('Report not found.')
    data = _body()
    st = (data.get('status') or '').lower()
    if st not in ('reviewing', 'resolved', 'dismissed'):
        return error_response('status must be reviewing, resolved or dismissed.',
                              data={'error_code': 'bad_status'}, status_code=422)
    before = r.to_dict()
    r.status, r.reviewed_by, r.reviewed_at = st, admin.id, datetime.utcnow()
    if data.get('resolution'):
        r.resolution = str(data['resolution'])[:5000]
    audit('safety.report_reviewed', admin, 'safety_report', r.id, before=before, after=r.to_dict())
    db.session.commit()
    return success_response('Report updated.', _report_dict(r))


# ── recordings (safety_reviewer only) ───────────────────────────────────────

@admin_safety_bp.route('/api/admin/safety/recordings', methods=['GET'])
@admin_role_required(*RECORDING_ROLES)
def recordings(admin):
    q = Recording.query
    for k in ('ride_type', 'status'):
        if request.args.get(k):
            q = q.filter(getattr(Recording, k) == request.args[k])
    for k in ('ride_id', 'incident_id', 'user_id'):
        if request.args.get(k, '').isdigit():
            q = q.filter(getattr(Recording, k) == int(request.args[k]))
    page, per = _page()
    return _paged(q.order_by(Recording.id.desc()), page, per, lambda r: r.to_dict())


@admin_safety_bp.route('/api/admin/safety/recordings/<int:rid>', methods=['GET'])
@admin_role_required(*RECORDING_ROLES)
def recording(admin, rid):
    rec = db.session.get(Recording, rid)
    if not rec:
        return _nf('Recording not found.')
    out = rec.to_dict()
    out['chunks'] = RS.chunk_urls(rec, admin.id, ttl_s=SIGNED_TTL_S,
                                  stream_base=f'/api/admin/safety/recordings/{rec.id}/chunks') \
        if rec.status != 'deleted' else []
    out['url_ttl_s'] = SIGNED_TTL_S
    if rec.ride_type and rec.ride_id:
        out['trip_events'] = [e.to_dict() for e in TripEvent.query.filter_by(
            ride_type=rec.ride_type, ride_id=rec.ride_id).order_by(TripEvent.id).all()]
    audit('recording.access', admin, 'recording', rec.id,
          meta={'chunks': len(out['chunks']), 'ride_type': rec.ride_type, 'ride_id': rec.ride_id,
                'owner_id': rec.user_id})
    db.session.commit()
    return success_response('Success', out)


def _range(header, size):
    """(start, end) inclusive for a single `bytes=a-b` range, or None."""
    import re
    m = re.fullmatch(r'bytes=(\d*)-(\d*)', (header or '').strip())
    if not m or (not m.group(1) and not m.group(2)):
        return None
    if m.group(1):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
    else:
        start, end = max(0, size - int(m.group(2))), size - 1
    if start >= size or start > end:
        return 'invalid'
    return start, min(end, size - 1)


@admin_safety_bp.route('/api/admin/safety/recordings/<int:rid>/chunks/<int:seq>', methods=['GET'])
@admin_role_required(*RECORDING_ROLES)
def recording_chunk_stream(admin, rid, seq):
    """Streams one decrypted audio chunk through the API (S3 or local), so
    every play / seek / download is audited (`recording.chunk_streamed`)."""
    from backend.models.safety import RecordingChunk
    rec = db.session.get(Recording, rid)
    if not rec or rec.status == 'deleted':
        return _nf('Recording not found.')
    c = RecordingChunk.query.filter_by(recording_id=rec.id, seq=seq).first()
    if not c:
        return _nf('Chunk not found.')
    try:
        data = PS.get(c.storage_key)
    except PS.StorageError:
        return _nf('Chunk not found.')
    rng = _range(request.headers.get('Range'), len(data))
    audit('recording.chunk_streamed', admin, 'recording', rec.id,
          meta={'seq': seq, 'bytes': len(data), 'range': request.headers.get('Range'), 'owner_id': rec.user_id,
                'ride_type': rec.ride_type, 'ride_id': rec.ride_id})
    db.session.commit()
    if rng == 'invalid':
        resp = Response(status=416)
        resp.headers['Content-Range'] = f'bytes */{len(data)}'
    elif rng:
        a, b = rng
        resp = Response(data[a:b + 1], status=206, mimetype='audio/mp4')
        resp.headers['Content-Range'] = f'bytes {a}-{b}/{len(data)}'
    else:
        resp = Response(data, mimetype='audio/mp4')
    resp.headers['Accept-Ranges'] = 'bytes'
    resp.headers['Content-Disposition'] = f'inline; filename="recording-{rec.id}-{seq:05d}.m4a"'
    resp.headers['Cache-Control'] = 'private, no-store'
    resp.headers['X-Robots-Tag'] = 'noindex'
    return resp


@admin_safety_bp.route('/api/admin/safety/recordings/<int:rid>/hold', methods=['POST'])
@admin_role_required(*RECORDING_ROLES)
def recording_hold(admin, rid):
    rec = db.session.get(Recording, rid)
    if not rec:
        return _nf('Recording not found.')
    hold = str(_body().get('legal_hold', True)).lower() in ('1', 'true', 'yes', 'on')
    before = {'legal_hold': bool(rec.legal_hold)}
    rec.legal_hold = hold
    audit('recording.legal_hold', admin, 'recording', rec.id, before=before, after={'legal_hold': hold})
    db.session.commit()
    return success_response('Recording updated.', rec.to_dict())


# ── help contacts ───────────────────────────────────────────────────────────

HC_FIELDS = ('name', 'phone', 'email', 'url', 'category', 'province', 'description', 'is_emergency', 'sort_order',
             'is_active')


def _apply_hc(h, data):
    for k in HC_FIELDS:
        if k not in data:
            continue
        v = data[k]
        if k in ('is_emergency', 'is_active'):
            v = str(v).lower() in ('1', 'true', 'yes', 'on')
        elif k == 'sort_order':
            v = int(v or 100)
        elif k == 'province':
            v = (v or '').upper()[:2] or None
            if v and v not in SS.PROVINCES:
                raise SS.SafetyError('Unknown province code.', 'bad_province', 422)
        else:
            v = (str(v).strip() if v is not None else None) or None
        setattr(h, k, v)
    if not h.name or not h.category:
        raise SS.SafetyError('name and category are required.', 'missing_fields', 422)


@admin_safety_bp.route('/api/admin/safety/help-contacts', methods=['GET'])
@admin_role_required(*SAFETY_ROLES)
def hc_list(admin):
    rows = HelpContact.query.order_by(HelpContact.province, HelpContact.sort_order, HelpContact.id).all()
    return success_response('Success', [{**SS.help_contact_dict(h), 'is_active': bool(h.is_active)} for h in rows])


@admin_safety_bp.route('/api/admin/safety/help-contacts', methods=['POST'])
@admin_role_required(*SAFETY_ROLES)
def hc_create(admin):
    h = HelpContact(is_active=True, sort_order=100, is_emergency=False)
    try:
        _apply_hc(h, _body())
    except SS.SafetyError as e:
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    db.session.add(h)
    db.session.flush()
    audit('safety.help_contact_created', admin, 'help_contact', h.id, after=h.to_dict())
    db.session.commit()
    return success_response('Help contact created.', SS.help_contact_dict(h), status_code=201)


@admin_safety_bp.route('/api/admin/safety/help-contacts/<int:hid>', methods=['PUT', 'PATCH'])
@admin_role_required(*SAFETY_ROLES)
def hc_update(admin, hid):
    h = db.session.get(HelpContact, hid)
    if not h:
        return _nf()
    before = h.to_dict()
    try:
        _apply_hc(h, _body())
    except SS.SafetyError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    audit('safety.help_contact_updated', admin, 'help_contact', h.id, before=before, after=h.to_dict())
    db.session.commit()
    return success_response('Help contact updated.', SS.help_contact_dict(h))


@admin_safety_bp.route('/api/admin/safety/help-contacts/<int:hid>', methods=['DELETE'])
@admin_role_required(*SAFETY_ROLES)
def hc_delete(admin, hid):
    h = db.session.get(HelpContact, hid)
    if not h:
        return _nf()
    audit('safety.help_contact_deleted', admin, 'help_contact', h.id, before=h.to_dict())
    db.session.delete(h)
    db.session.commit()
    return success_response('Help contact deleted.', {'id': hid})


# ── live operations map ─────────────────────────────────────────────────────

EN_ROUTE = ('CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'BOARDING')
ON_TRIP = ('IN_PROGRESS', 'RIDING', 'CHECKED_IN')


def _active_rides_by_driver():
    out = {}
    moving = EN_ROUTE + ON_TRIP
    for rt, model in (('carhire', Negotiation), ('scheduled', ScheduledBooking), ('rideshare_trip', Trip)):
        for r in model.query.filter(model.trip_stage.in_(moving), model.driver_id.isnot(None)).limit(2000).all():
            prev = out.get(int(r.driver_id))
            rank = 0 if r.trip_stage in ON_TRIP else 1
            if prev is None or rank < prev[2]:
                out[int(r.driver_id)] = (rt, r, rank)
    return out


@admin_safety_bp.route('/api/admin/live/drivers', methods=['GET'])
@admin_role_required('ops', 'safety_reviewer', 'support', 'finance')
def live_drivers(admin):
    from backend.services import tracking
    active = _active_rides_by_driver()
    online = AdminUser.query.filter(AdminUser.ready_for_trip == 'Yes',
                                    AdminUser.user_type.in_(['Driver', 'Pending Driver'])).limit(3000).all()
    by_id = {u.id: u for u in online}
    # Drivers on an active ride are shown even when they toggled offline
    # (default); ?include_offline_active=0 shows online drivers only.
    include_offline = str(request.args.get('include_offline_active', '1')).lower() not in ('0', 'false', 'no')
    if not include_offline:
        active = {k: v for k, v in active.items() if k in by_id}
    missing = [d for d in active if d not in by_id]
    if missing:
        for u in AdminUser.query.filter(AdminUser.id.in_(missing)).all():
            by_id[u.id] = u
    sos_users = {i.user_id: i for i in SafetyIncident.query.filter(SafetyIncident.status.in_(SS.OPEN_STATUSES)).all()}
    sos_rides = {(i.ride_type, i.ride_id): i for i in sos_users.values() if i.ride_type}
    now = datetime.utcnow()
    items = []
    counts = {'idle': 0, 'en_route': 0, 'on_trip': 0, 'sos': 0}
    for uid, u in by_id.items():
        ride = active.get(uid)
        state = 'idle'
        ride_out = None
        if ride:
            rt, r, rank = ride
            state = 'on_trip' if rank == 0 else 'en_route'
            cids = R.customer_ids(rt, r)
            ride_out = {'ride_type': rt, 'ride_id': r.id, 'stage': r.trip_stage, 'customer_ids': cids,
                        'customer_first_names': [(R.user_card(c) or {}).get('first_name') for c in cids[:4]]}
        inc = sos_users.get(uid) or (sos_rides.get((ride[0], ride[1].id)) if ride else None)
        if inc:
            state = 'sos'
        latest = tracking.latest(uid)
        pos = None
        if latest:
            pos = {'lat': latest.get('lat'), 'lng': latest.get('lng'), 'heading': latest.get('heading'),
                   'speed': latest.get('speed'), 'at': latest.get('at')}
        elif u.current_latitude is not None:
            pos = {'lat': float(u.current_latitude), 'lng': float(u.current_longitude), 'heading': None,
                   'speed': None, 'at': SS.iso(u.last_location_update)}
        stale = not u.last_location_update or (now - u.last_location_update) > timedelta(minutes=10)
        counts[state] += 1
        items.append({'driver_id': uid, 'name': u.name, 'first_name': SS.first_name(u), 'state': state,
                      'online': u.ready_for_trip == 'Yes', 'position': pos, 'stale': stale, 'ride': ride_out,
                      'incident_id': inc.id if inc else None, 'rating': SS._f(u.rating)})
    return success_response('Success', {'drivers': items, 'counts': counts, 'generated_at': SS.iso(now)})


def _pos_of(uid):
    from backend.services import tracking
    lt = tracking.latest(uid) if uid else None
    if lt and lt.get('lat') is not None:
        return {'lat': lt.get('lat'), 'lng': lt.get('lng'), 'heading': lt.get('heading'), 'at': lt.get('at'),
                'source': 'live'}
    u = db.session.get(AdminUser, uid) if uid else None
    if u and u.current_latitude is not None and u.current_longitude is not None:
        try:
            return {'lat': float(u.current_latitude), 'lng': float(u.current_longitude), 'heading': None,
                    'at': SS.iso(u.last_location_update), 'source': 'last_known'}
        except (TypeError, ValueError):
            return None
    return None


def _pt(lat, lng, address=None):
    return {'lat': SS._f(lat) if lat not in (None, '') else None, 'lng': SS._f(lng) if lng not in (None, '') else None,
            'address': address}


REQUEST_OPEN = ('favourite', 'broadcasting')
TRIP_LIVE = ('BOARDING', 'IN_PROGRESS')


@admin_safety_bp.route('/api/admin/live/rides', methods=['GET'])
@admin_role_required('ops', 'safety_reviewer', 'support', 'finance')
def live_rides(admin):
    """Admin live map layers besides drivers: unassigned car-hire demand,
    running rideshare trips and every open SOS (customers / ride-less too)."""
    from backend.models.experience import RideRequest
    now = datetime.utcnow()
    first = lambda uid: (R.user_card(uid) or {}).get('first_name') if uid else None  # noqa: E731

    requests_out = []
    for rr in (RideRequest.query.filter(RideRequest.status.in_(REQUEST_OPEN))
               .filter((RideRequest.expires_at.is_(None)) | (RideRequest.expires_at > now))
               .order_by(RideRequest.id.desc()).limit(500).all()):
        requests_out.append({'kind': 'ride_request', 'id': rr.id, 'ride_type': 'carhire', 'status': rr.status,
                             'mode': rr.mode, 'service_type': rr.service_type,
                             'pickup': _pt(rr.pickup_lat, rr.pickup_lng, rr.pickup_address),
                             'dropoff': _pt(rr.dropoff_lat, rr.dropoff_lng, rr.dropoff_address),
                             'offer_cents': rr.offer_cents, 'customer': {'id': rr.customer_id,
                                                                         'first_name': first(rr.customer_id)},
                             'negotiation_id': rr.negotiation_id, 'created_at': SS.iso(rr.created_at),
                             'expires_at': SS.iso(rr.expires_at)})
    for n in (Negotiation.query.filter(Negotiation.trip_stage.in_(('REQUESTED', 'NEGOTIATING')),
                                       Negotiation.pickup_lat.isnot(None), Negotiation.pickup_lat != '',
                                       Negotiation.created_at >= now - timedelta(hours=24))
              .order_by(Negotiation.id.desc()).limit(500).all()):
        pp = _pt(n.pickup_lat, n.pickup_lng, n.pickup_address)
        if pp['lat'] is None:
            continue
        requests_out.append({'kind': 'negotiation', 'id': n.id, 'ride_type': 'carhire', 'status': n.trip_stage,
                             'service_type': n.service_type, 'pickup': pp,
                             'dropoff': _pt(n.dropoff_lat, n.dropoff_lng, n.dropoff_address),
                             'offer_cents': R.fare_cents('carhire', n) or None,
                             'customer': {'id': n.customer_id, 'first_name': first(n.customer_id)},
                             'driver_id': n.driver_id, 'created_at': SS.iso(n.created_at)})

    trips_out = []
    for t in (Trip.query.filter(Trip.trip_stage.in_(TRIP_LIVE), Trip.driver_id.isnot(None))
              .order_by(Trip.id.desc()).limit(500).all()):
        sp, ep = R.pickup_point('rideshare_trip', t), R.dropoff_point('rideshare_trip', t)
        cids = R.customer_ids('rideshare_trip', t)
        trips_out.append({'trip_id': t.id, 'ride_type': 'rideshare_trip', 'stage': t.trip_stage,
                          'driver': {'id': int(t.driver_id), 'first_name': first(t.driver_id)},
                          'position': _pos_of(int(t.driver_id)),
                          'start': {'lat': sp[0] if sp else None, 'lng': sp[1] if sp else None,
                                    'address': t.start_address or t.start_name},
                          'end': {'lat': ep[0] if ep else None, 'lng': ep[1] if ep else None,
                                  'address': t.end_address or t.end_name},
                          'passengers': len(cids), 'seats': t.slots,
                          'departure_at': SS.iso(t.departure_at), 'started_at': SS.iso(t.started_at)})

    sos_out = []
    for inc in (SafetyIncident.query.filter(SafetyIncident.status.in_(SS.OPEN_STATUSES))
                .order_by(SafetyIncident.id.desc()).limit(500).all()):
        lat = inc.last_lat if inc.last_lat is not None else inc.lat
        lng = inc.last_lng if inc.last_lng is not None else inc.lng
        pos = ({'lat': SS._f(lat), 'lng': SS._f(lng), 'at': SS.iso(inc.last_location_at or inc.created_at),
                'accuracy_m': inc.accuracy_m, 'source': 'incident'} if lat is not None else None)
        if pos is None:
            pos = _pos_of(inc.user_id)
        sos_out.append({'incident_id': inc.id, 'kind': inc.kind, 'status': inc.status, 'severity': inc.severity,
                        'silent': bool(inc.silent), 'user': {'id': inc.user_id, 'first_name': first(inc.user_id),
                                                             'role': inc.role},
                        'ride_type': inc.ride_type, 'ride_id': inc.ride_id, 'position': pos,
                        'battery_pct': inc.battery_pct, 'created_at': SS.iso(inc.created_at),
                        'acknowledged_at': SS.iso(inc.acknowledged_at), 'escalated_at': SS.iso(inc.escalated_at)})
    return success_response('Success', {
        'requests': requests_out, 'rideshare_trips': trips_out, 'sos': sos_out,
        'counts': {'requests': len(requests_out), 'rideshare_trips': len(trips_out), 'sos': len(sos_out)},
        'generated_at': SS.iso(now), 'refresh_s': 10,
    })


@admin_safety_bp.route('/api/admin/rides/<ride_type>/<int:ride_id>/route', methods=['GET'])
@admin_role_required('ops', 'safety_reviewer', 'support', 'finance')
def ride_route(admin, ride_type, ride_id):
    try:
        rt = R.normalize_type(ride_type)
        ride = R.load(rt, ride_id)
    except R.RideNotFound:
        return _nf('Ride not found.')
    drv = R.driver_id(rt, ride)
    who = request.args.get('user', 'driver')
    uid = drv if who == 'driver' else (int(who) if str(who).isdigit() else drv)
    types, ids = [rt], [ride.id]
    if rt == 'rideshare_booking':
        types.append('rideshare_trip')
        ids.append(ride.trip_id)
    q = RideLocation.query.filter(RideLocation.ride_type.in_(types), RideLocation.ride_id.in_(ids))
    if uid:
        q = q.filter(RideLocation.user_id == uid)
    rows = q.order_by(RideLocation.recorded_at, RideLocation.id).limit(20000).all()
    pts = [{'lat': float(r.lat), 'lng': float(r.lng), 'speed_mps': SS._f(r.speed_mps), 'heading': r.heading,
            'accuracy_m': r.accuracy_m, 'at': SS.iso(r.recorded_at), 'user_id': r.user_id} for r in rows]
    dist = 0.0
    for a, b in zip(pts, pts[1:]):
        dist += R.haversine_m((a['lat'], a['lng']), (b['lat'], b['lng'])) or 0
    pp, dp = R.pickup_point(rt, ride), R.dropoff_point(rt, ride)
    pa, da = R.addresses(rt, ride)
    snapped = None
    if request.args.get('snap') in ('1', 'true') and len(pts) > 1:
        from backend.services import geo_routes as G
        spts, ok = G.snap_path_cached(f'replay:{rt}:{ride.id}:{uid}:{len(pts)}:{pts[-1]["at"]}',
                                      [(p['lat'], p['lng']) for p in pts])
        snapped = {'snapped': ok, 'polyline': G.encode_polyline(spts) if ok else None,
                   'points': [[round(a, 6), round(b, 6)] for a, b in spts] if ok else None}
    from backend.services import safety_detection as SD
    planned = {t: SD.planned_route(rt, ride.id, t) for t in ('pickup', 'dropoff')} \
        if rt in ('carhire', 'scheduled') else {}
    events = TripEvent.query.filter_by(ride_type=rt, ride_id=ride.id).order_by(TripEvent.id).all()
    audit('ride.route_viewed', admin, 'ride', f'{rt}:{ride.id}', meta={'points': len(pts)})
    db.session.commit()
    return success_response('Success', {
        'ride_type': rt, 'ride_id': ride.id, 'stage': R.current_stage(rt, ride), 'driver_id': drv,
        'pickup': {'address': pa, 'lat': pp[0] if pp else None, 'lng': pp[1] if pp else None},
        'dropoff': {'address': da, 'lat': dp[0] if dp else None, 'lng': dp[1] if dp else None},
        'points': pts, 'polyline': live_share.encode_polyline([(p['lat'], p['lng']) for p in pts]) if pts else '',
        'distance_m': round(dist), 'started_at': pts[0]['at'] if pts else None,
        'ended_at': pts[-1]['at'] if pts else None,
        'events': [{'at': SS.iso(e.created_at), 'from_stage': e.from_stage, 'to_stage': e.to_stage,
                    'actor_type': e.actor_type, 'lat': SS._f(e.lat), 'lng': SS._f(e.lng)} for e in events],
        'incidents': [SS.incident_dict(i) for i in
                      SafetyIncident.query.filter_by(ride_type=rt, ride_id=ride.id).all()],
        'is_terminal': TSM.is_terminal(rt, R.current_stage(rt, ride)),
        'snapped': snapped,
        'planned_routes': [{'target': t, 'polyline': r.polyline, 'distance_m': r.distance_m,
                            'duration_s': r.duration_s, 'source': r.source, 'created_at': SS.iso(r.created_at)}
                           for t, r in planned.items() if r is not None],
    })
