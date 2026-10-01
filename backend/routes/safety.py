"""Safety toolkit API (spec §8) — customers AND drivers.

    POST   /api/safety/sos                              trigger SOS (Idempotency-Key)
    GET    /api/safety/incidents                        my incidents (?status=open)
    GET    /api/safety/incidents/<id>                   owner
    POST   /api/safety/incidents/<id>/location          3 s cadence while open
    POST   /api/safety/incidents/<id>/cancel            false alarm (owner)
    GET    /api/safety/trusted-contacts                 list
    POST   /api/safety/trusted-contacts                 {name, phone, relationship?, auto_share?}
    PUT    /api/safety/trusted-contacts/<id>
    DELETE /api/safety/trusted-contacts/<id>
    GET    /api/safety/settings | PUT /api/safety/settings
    POST   /api/safety/reports                          JSON or multipart (attachments[])
    GET    /api/safety/reports                          my reports
    POST   /api/safety/flag-passenger                   driver only
    GET    /api/safety/help-contacts?province=ON
    GET    /api/safety/checks/pending
    POST   /api/safety/checks/<id>/respond              {response: ok|help}
    GET    /api/safety/toolkit?ride_type=&ride_id=      everything the Safety Toolkit sheet needs

SOS-critical endpoints work for suspended accounts too (safety first).
"""
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from backend.models import db
from backend.models.safety import (Recording, RideShareLink, SafetyCheck, SafetyIncident, SafetyReport,
                                   TrustedContact)
from backend.services import live_share
from backend.services import private_storage as PS
from backend.services import realtime
from backend.services import recording_service as RS
from backend.services import rides as R
from backend.services import safety_detection  # noqa: F401  (registers location + after hooks)
from backend.services import safety_service as SS
from backend.services import settings_service as S
from backend.services.audit import audit
from backend.utils.auth import get_current_user, jwt_required_with_user
from backend.utils.response import error_response, success_response

safety_bp = Blueprint('safety', __name__)

MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/heic': 'heic',
               'image/heif': 'heif'}


def safety_auth(fn):
    """JWT required, but suspended/deactivated accounts may still use SOS."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'code': 0, 'message': 'Unauthorized'}), 401
        return fn(user, *args, **kwargs)
    return wrapper


def _body():
    return request.get_json(silent=True) or request.form.to_dict() or {}


def _err(e):
    db.session.rollback()
    return error_response(e.message, data={'error_code': e.code, **e.data}, status_code=e.status)


def _flag_off(name):
    return error_response('This feature is currently unavailable.', data={'error_code': 'feature_disabled',
                                                                          'feature': name}, status_code=403)


def _bool(v):
    return str(v).strip().lower() in ('1', 'true', 'yes', 'on')


# ── SOS ─────────────────────────────────────────────────────────────────────

@safety_bp.route('/api/safety/sos', methods=['POST'])
@safety_auth
def sos(user):
    if not S.flag('sos'):
        return _flag_off('sos')
    data = _body()
    key = request.headers.get('Idempotency-Key') or data.get('idempotency_key')
    try:
        inc, link, rec, replayed = SS.trigger_sos(user, data, idem_key=key)
    except SS.SafetyError as e:
        return _err(e)
    out = {
        'incident': SS.incident_dict(inc),
        'share_url': live_share.url_for_token(link.token) if link else None,
        'share_token': link.token if link else None,
        'high_frequency_interval_s': S.get_int('safety.sos_location_interval_s', 3) or 3,
        'location_url': f'/api/safety/incidents/{inc.id}/location',
        'recording': None,
        'replayed': replayed,
    }
    if rec is not None:
        out['recording'] = {**RS.to_dict(rec, user.id), 'upload': RS.upload_info(rec)}
    resp, status = success_response('SOS sent. Our safety team has been alerted.', out,
                                    status_code=200 if replayed else 201)
    if replayed:
        resp.headers['Idempotent-Replayed'] = 'true'
    return resp, status


def _own_incident(user, incident_id):
    inc = db.session.get(SafetyIncident, incident_id)
    if not inc or inc.user_id != user.id:
        return None
    return inc


@safety_bp.route('/api/safety/incidents', methods=['GET'])
@safety_auth
def my_incidents(user):
    q = SafetyIncident.query.filter_by(user_id=user.id)
    if request.args.get('status') == 'open':
        q = q.filter(SafetyIncident.status.in_(SS.OPEN_STATUSES))
    rows = q.order_by(SafetyIncident.id.desc()).limit(50).all()
    return success_response('Success', [SS.incident_dict(i) for i in rows])


@safety_bp.route('/api/safety/incidents/<int:incident_id>', methods=['GET'])
@safety_auth
def get_incident(user, incident_id):
    inc = _own_incident(user, incident_id)
    if not inc:
        return error_response('Incident not found.', data={'error_code': 'not_found'}, status_code=404)
    link = (RideShareLink.query.filter_by(ride_type=live_share.INCIDENT, ride_id=inc.id, user_id=user.id)
            .order_by(RideShareLink.id.desc()).first())
    d = SS.incident_dict(inc)
    d.pop('notes', None)   # admin working notes stay internal
    d['share_url'] = live_share.url_for_token(link.token) if link else None
    d['keep_sending_location'] = inc.status in SS.OPEN_STATUSES
    d['high_frequency_interval_s'] = S.get_int('safety.sos_location_interval_s', 3) or 3
    return success_response('Success', d)


@safety_bp.route('/api/safety/incidents/<int:incident_id>/location', methods=['POST'])
@safety_auth
def incident_location(user, incident_id):
    inc = _own_incident(user, incident_id)
    if not inc:
        return error_response('Incident not found.', data={'error_code': 'not_found'}, status_code=404)
    if inc.status not in SS.OPEN_STATUSES:
        return success_response('Incident closed', {'incident_id': inc.id, 'status': inc.status,
                                                    'keep_sending_location': False})
    try:
        p = SS.add_location(inc, _body())
    except SS.SafetyError as e:
        return _err(e)
    return success_response('Location received', {**p, 'keep_sending_location': True,
                                                  'interval_s': S.get_int('safety.sos_location_interval_s', 3) or 3})


@safety_bp.route('/api/safety/incidents/<int:incident_id>/cancel', methods=['POST'])
@safety_auth
def cancel_incident(user, incident_id):
    inc = _own_incident(user, incident_id)
    if not inc:
        return error_response('Incident not found.', data={'error_code': 'not_found'}, status_code=404)
    try:
        SS.close_incident(inc, 'false_alarm', user, note=(_body().get('reason') or 'Cancelled by user (false alarm)'),
                          by_user=True)
    except SS.SafetyError as e:
        return _err(e)
    return success_response('SOS cancelled. Glad you are safe.', SS.incident_dict(inc))


# ── trusted contacts ────────────────────────────────────────────────────────

def _contact_dict(c):
    return {'id': c.id, 'name': c.name, 'phone': c.phone_e164, 'relationship': c.relationship,
            'auto_share': bool(c.auto_share), 'created_at': SS.iso(c.created_at)}


def _phone(raw):
    from backend.utils.phone import PhoneError, normalize
    try:
        return normalize(raw), None
    except PhoneError as e:
        return None, str(e)


@safety_bp.route('/api/safety/trusted-contacts', methods=['GET'])
@safety_auth
def list_contacts(user):
    rows = TrustedContact.query.filter_by(user_id=user.id).order_by(TrustedContact.id).all()
    return success_response('Success', {'contacts': [_contact_dict(c) for c in rows],
                                        'max': S.get_int('safety.max_trusted_contacts')})


@safety_bp.route('/api/safety/trusted-contacts', methods=['POST'])
@jwt_required_with_user
def add_contact(user):
    data = _body()
    name = (data.get('name') or '').strip()[:120]
    if not name:
        return error_response('Name is required.', data={'error_code': 'name_required'}, status_code=422)
    e164, err = _phone(data.get('phone') or data.get('phone_number'))
    if err:
        return error_response(err, data={'error_code': 'invalid_phone'}, status_code=422)
    if (user.phone_e164 and user.phone_e164 == e164):
        return error_response("You can't add your own number.", data={'error_code': 'own_number'}, status_code=422)
    # Lock the owner's user row so two concurrent adds can't both pass the
    # 5-contact limit (count + insert are serialised per user).
    from backend.models.user import AdminUser
    # (The count is a LOCKING read too: under REPEATABLE READ a plain read would
    # use the snapshot taken before we waited for the lock.)
    db.session.query(AdminUser.id).filter(AdminUser.id == user.id).with_for_update().first()
    count = len(db.session.query(TrustedContact.id).filter(TrustedContact.user_id == user.id)
                .with_for_update().all())
    limit = S.get_int('safety.max_trusted_contacts')
    if count >= limit:
        db.session.rollback()
        return error_response(f'You can save up to {limit} trusted contacts.',
                              data={'error_code': 'limit_reached', 'max': limit}, status_code=422)
    if TrustedContact.query.filter_by(user_id=user.id, phone_e164=e164).first():
        db.session.rollback()
        return error_response('This contact is already saved.', data={'error_code': 'duplicate'}, status_code=409)
    # New contacts receive auto-shared trips by default (editable per contact).
    c = TrustedContact(user_id=user.id, name=name, phone_e164=e164,
                       relationship=(data.get('relationship') or '')[:40] or None,
                       auto_share=_bool(data.get('auto_share', True)), created_at=datetime.utcnow())
    db.session.add(c)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error_response('This contact is already saved.', data={'error_code': 'duplicate'}, status_code=409)
    return success_response('Trusted contact saved.', _contact_dict(c), status_code=201)


@safety_bp.route('/api/safety/trusted-contacts/<int:cid>', methods=['PUT', 'PATCH'])
@jwt_required_with_user
def update_contact(user, cid):
    c = TrustedContact.query.filter_by(id=cid, user_id=user.id).first()
    if not c:
        return error_response('Contact not found.', data={'error_code': 'not_found'}, status_code=404)
    data = _body()
    if 'name' in data:
        name = (data.get('name') or '').strip()[:120]
        if not name:
            return error_response('Name is required.', data={'error_code': 'name_required'}, status_code=422)
        c.name = name
    if 'phone' in data or 'phone_number' in data:
        e164, err = _phone(data.get('phone') or data.get('phone_number'))
        if err:
            return error_response(err, data={'error_code': 'invalid_phone'}, status_code=422)
        dup = TrustedContact.query.filter_by(user_id=user.id, phone_e164=e164).first()
        if dup and dup.id != c.id:
            return error_response('This contact is already saved.', data={'error_code': 'duplicate'},
                                  status_code=409)
        c.phone_e164 = e164
    if 'relationship' in data:
        c.relationship = (data.get('relationship') or '')[:40] or None
    if 'auto_share' in data:
        c.auto_share = _bool(data.get('auto_share'))
    db.session.commit()
    return success_response('Trusted contact updated.', _contact_dict(c))


@safety_bp.route('/api/safety/trusted-contacts/<int:cid>', methods=['DELETE'])
@jwt_required_with_user
def delete_contact(user, cid):
    c = TrustedContact.query.filter_by(id=cid, user_id=user.id).first()
    if not c:
        return error_response('Contact not found.', data={'error_code': 'not_found'}, status_code=404)
    db.session.delete(c)
    db.session.commit()
    return success_response('Trusted contact removed.', {'id': cid})


# ── settings ────────────────────────────────────────────────────────────────

@safety_bp.route('/api/safety/settings', methods=['GET'])
@safety_auth
def get_settings(user):
    return success_response('Success', SS.settings_dict(SS.get_settings(user.id)))


@safety_bp.route('/api/safety/settings', methods=['PUT', 'PATCH', 'POST'])
@jwt_required_with_user
def put_settings(user):
    import re
    data = _body()
    s = SS.get_settings(user.id)
    if 'record_audio' in data:
        v = str(data.get('record_audio') or '').lower()
        if v not in SS.RECORD_AUDIO_MODES:
            return error_response('record_audio must be off, always or ask.', data={'error_code': 'bad_value'},
                                  status_code=422)
        s.record_audio = v
    for k in ('auto_record_on_sos', 'auto_share_night', 'auto_share_all'):
        if k in data:
            setattr(s, k, _bool(data.get(k)))
    for k in ('night_start', 'night_end'):
        if k in data:
            v = str(data.get(k) or '')
            if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', v):
                return error_response(f'{k} must be HH:MM.', data={'error_code': 'bad_value'}, status_code=422)
            setattr(s, k, v)
    s.updated_at = datetime.utcnow()
    db.session.merge(s)
    db.session.commit()
    return success_response('Safety settings saved.', SS.settings_dict(SS.get_settings(user.id)))


# ── reports ─────────────────────────────────────────────────────────────────

def _report_dict(r, admin=False):
    d = r.to_dict()
    atts = r.attachments or []
    d['attachments'] = [{'name': a.get('name'), 'content_type': a.get('content_type'), 'bytes': a.get('bytes')}
                        for a in atts] if not admin else atts
    return d


def _store_attachments(report, files):
    out = []
    for i, f in enumerate(files[:MAX_ATTACHMENTS]):
        data = f.read()
        ct = (f.mimetype or '').lower()
        if ct not in IMAGE_TYPES:
            raise SS.SafetyError('Attachments must be images (JPEG, PNG, WebP, HEIC).', 'bad_attachment', 415)
        if not data or len(data) > MAX_ATTACHMENT_BYTES:
            raise SS.SafetyError('Each attachment must be under 8 MB.', 'attachment_too_large', 413)
        key = f'safety_reports/{report.id}/{i + 1}-{uuid.uuid4().hex[:8]}.{IMAGE_TYPES[ct]}'
        PS.put(key, data, ct)
        out.append({'key': key, 'content_type': ct, 'bytes': len(data), 'name': (f.filename or '')[:120],
                    'sha256': PS.sha256_hex(data)})
    return out


def _create_report(user, data, files, category, reported_user_id=None, ride_type=None, ride=None):
    r = SafetyReport(reporter_id=user.id, reported_user_id=reported_user_id,
                     ride_type=ride_type if ride is not None else None, ride_id=ride.id if ride is not None else None,
                     category=category, description=(data.get('description') or '').strip()[:5000] or None,
                     status='open', created_at=datetime.utcnow())
    db.session.add(r)
    db.session.flush()
    if files:
        r.attachments = _store_attachments(r, files)
    audit('safety.report_created', user, 'safety_report', r.id, after={'category': category,
                                                                       'ride_type': r.ride_type,
                                                                       'ride_id': r.ride_id,
                                                                       'reported_user_id': reported_user_id},
          actor_type='user')
    db.session.commit()
    realtime.to_admins('safety.report_created', {'report_id': r.id, 'category': category, 'reporter_id': user.id,
                                                 'reported_user_id': reported_user_id, 'ride_type': r.ride_type,
                                                 'ride_id': r.ride_id, 'created_at': SS.iso(r.created_at)})
    return r


def _ride_from(user, data, required=False):
    rt, rid = data.get('ride_type'), data.get('ride_id')
    if not rt or not rid:
        if required:
            raise SS.SafetyError('ride_type and ride_id are required.', 'ride_required', 422)
        return None, None, None
    return SS.resolve_ride(user, rt, rid)


@safety_bp.route('/api/safety/reports', methods=['POST'])
@jwt_required_with_user
def create_report(user):
    data = _body()
    cat = (data.get('category') or '').strip().lower()
    if cat not in SS.REPORT_CATEGORIES:
        return error_response('Choose a category.', data={'error_code': 'bad_category',
                                                          'categories': list(SS.REPORT_CATEGORIES)},
                              status_code=422)
    try:
        rt, ride, role = _ride_from(user, data)
        other = None
        if ride is not None:
            if data.get('reported_user_id'):
                other = int(data['reported_user_id'])
                if other not in R.all_party_ids(rt, ride) or other == user.id:
                    raise SS.SafetyError('That person was not part of this ride.', 'bad_reported_user', 422)
            elif role == 'customer':
                other = R.driver_id(rt, ride)
            else:
                ids = R.customer_ids(rt, ride)
                other = ids[0] if len(ids) == 1 else None
        files = request.files.getlist('attachments') or request.files.getlist('attachments[]') or []
        r = _create_report(user, data, files, cat, other, rt, ride)
    except SS.SafetyError as e:
        return _err(e)
    return success_response('Thanks — our safety team will review your report.', _report_dict(r), status_code=201)


@safety_bp.route('/api/safety/reports', methods=['GET'])
@jwt_required_with_user
def my_reports(user):
    rows = SafetyReport.query.filter_by(reporter_id=user.id).order_by(SafetyReport.id.desc()).limit(50).all()
    return success_response('Success', [_report_dict(r) for r in rows])


@safety_bp.route('/api/safety/flag-passenger', methods=['POST'])
@jwt_required_with_user
def flag_passenger(user):
    data = _body()
    try:
        rt, ride, role = _ride_from(user, data, required=True)
        if role != 'driver':
            raise SS.SafetyError('Only the driver of this ride can flag a passenger.', 'forbidden', 403)
        pax = data.get('passenger_id') or data.get('reported_user_id')
        ids = R.customer_ids(rt, ride)
        if pax:
            pax = int(pax)
            if pax not in ids:
                raise SS.SafetyError('That passenger was not on this ride.', 'bad_reported_user', 422)
        elif len(ids) == 1:
            pax = ids[0]
        else:
            raise SS.SafetyError('passenger_id is required.', 'passenger_required', 422)
        reason = (data.get('reason') or data.get('category') or 'other').strip().lower()[:40]
        data = dict(data)
        data['description'] = f"[{reason}] {data.get('description') or ''}".strip()
        files = request.files.getlist('attachments') or []
        r = _create_report(user, data, files, SS.PASSENGER_FLAG, pax, rt, ride)
    except SS.SafetyError as e:
        return _err(e)
    return success_response('Passenger flagged. Our safety team will review it.', _report_dict(r), status_code=201)


# ── help contacts ───────────────────────────────────────────────────────────

@safety_bp.route('/api/safety/help-contacts', methods=['GET'])
@safety_auth
def help_contacts(user):
    prov = (request.args.get('province') or SS.province_for(user) or '').upper()[:2] or None
    return success_response('Success', {'province': prov, 'emergency_number': '911',
                                        'contacts': SS.help_contacts(prov), 'support': SS.support_contact()})


# ── "Are you OK?" checks ────────────────────────────────────────────────────

def _check_dict(c):
    d = c.to_dict()
    d['lat'], d['lng'] = SS._f(c.lat), SS._f(c.lng)
    return d


@safety_bp.route('/api/safety/checks/pending', methods=['GET'])
@safety_auth
def pending_checks(user):
    rows = SafetyCheck.query.filter_by(user_id=user.id, status='pending').order_by(SafetyCheck.id.desc()).all()
    return success_response('Success', [_check_dict(c) for c in rows])


@safety_bp.route('/api/safety/checks/<int:check_id>/respond', methods=['POST'])
@safety_auth
def respond_check(user, check_id):
    data = _body()
    resp = (data.get('response') or '').strip().lower()
    if resp not in ('ok', 'help'):
        return error_response('response must be ok or help.', data={'error_code': 'bad_response'}, status_code=422)
    chk = SafetyCheck.query.filter_by(id=check_id, user_id=user.id).with_for_update().first()
    if not chk:
        db.session.rollback()
        return error_response('Check not found.', data={'error_code': 'not_found'}, status_code=404)
    if chk.status not in ('pending', 'escalated'):
        db.session.rollback()
        return success_response('Already answered', _check_dict(chk))
    was_escalated = chk.status == 'escalated'
    chk.status, chk.responded_at = resp, datetime.utcnow()
    audit(f'safety.check_{resp}', user, 'safety_check', chk.id, meta={'kind': chk.kind}, actor_type='user')
    db.session.commit()
    out = {'check': _check_dict(chk), 'incident': None, 'share_url': None}
    if resp == 'help':
        payload = {'ride_type': chk.ride_type, 'ride_id': chk.ride_id,
                   'lat': data.get('lat', SS._f(chk.lat)), 'lng': data.get('lng', SS._f(chk.lng))}
        try:
            inc, link, rec, _ = SS.trigger_sos(user, payload, idem_key=f'check-{chk.id}', kind='sos')
        except SS.SafetyError as e:
            return _err(e)
        chk.incident_id = inc.id
        db.session.commit()
        out.update({'incident': SS.incident_dict(inc), 'share_url': live_share.url_for_token(link.token),
                    'high_frequency_interval_s': S.get_int('safety.sos_location_interval_s', 3) or 3})
        return success_response('Help is on the way. Our safety team has been alerted.', out)
    if was_escalated and chk.incident_id:
        inc = db.session.get(SafetyIncident, chk.incident_id)
        if inc and inc.status in SS.OPEN_STATUSES:
            SS.append_note(inc, user, 'Rider answered "I\'m OK" after escalation.')
            db.session.commit()
            SS.emit_incident('safety.sos_updated', inc, {'type': 'rider_ok', 'check_id': chk.id})
    realtime.to_admins('safety.check_answered', {'check_id': chk.id, 'response': resp, 'ride_type': chk.ride_type,
                                                 'ride_id': chk.ride_id, 'user_id': user.id})
    return success_response('Thanks for letting us know.', out)


# ── toolkit ─────────────────────────────────────────────────────────────────

@safety_bp.route('/api/safety/toolkit', methods=['GET'])
@safety_auth
def toolkit(user):
    try:
        rt, ride, role = SS.resolve_ride(user, request.args.get('ride_type'), request.args.get('ride_id'))
    except SS.SafetyError as e:
        return _err(e)
    ride_out = share = None
    rec_out = {'mine': None, 'other_party_recording': False, 'banner': None, 'ever_recorded': False,
               'recordings': []}
    if ride is not None:
        pickup, dropoff = R.addresses(rt, ride)
        pp, dp = R.pickup_point(rt, ride), R.dropoff_point(rt, ride)
        drv = R.driver_id(rt, ride)
        driver_card = R.user_card(drv) if drv else None
        from backend.models.user import AdminUser
        veh = R.vehicle_card(db.session.get(AdminUser, drv), ride_type=rt, ride=ride, viewer=user) if drv else None
        cids = R.customer_ids(rt, ride)
        ride_out = {
            'ride_type': rt, 'ride_id': ride.id, 'stage': R.current_stage(rt, ride), 'my_role': role,
            'pickup': {'address': pickup, 'lat': pp[0] if pp else None, 'lng': pp[1] if pp else None},
            'dropoff': {'address': dropoff, 'lat': dp[0] if dp else None, 'lng': dp[1] if dp else None},
            'driver': ({'id': driver_card['id'], 'first_name': driver_card['first_name'],
                        'name': driver_card['first_name'], 'avatar': driver_card['avatar'],
                        'rating': driver_card['rating']} if driver_card else None),
            'vehicle': veh,
            'customers': [{'id': c['id'], 'first_name': c['first_name']} for c in
                          (R.user_card(x) for x in cids) if c] if role == 'driver' else None,
        }
        link = (RideShareLink.query.filter_by(ride_type=rt, ride_id=ride.id, user_id=user.id)
                .order_by(RideShareLink.id.desc()).first())
        share = {'can_share': live_share.can_share(rt, ride) and S.flag('live_share'),
                 'active': live_share.link_dict(link) if live_share.link_is_live(link) else None}
        st = RS.status_payload(rt, ride.id, user.id)
        mine = Recording.query.filter_by(user_id=user.id, ride_type=rt, ride_id=ride.id,
                                         status='recording').first()
        rec_out = {'mine': ({**RS.to_dict(mine, user.id), 'upload': RS.upload_info(mine)} if mine else None),
                   'other_party_recording': st['other_party_recording'], 'banner': st['banner'],
                   'ever_recorded': st['ever_recorded'], 'recordings': st['recordings']}
    prov = (request.args.get('province') or SS.province_for(user, rt, ride) or '').upper()[:2] or None
    open_inc = (SafetyIncident.query.filter_by(user_id=user.id).filter(SafetyIncident.status.in_(SS.OPEN_STATUSES))
                .order_by(SafetyIncident.id.desc()).first())
    contacts = TrustedContact.query.filter_by(user_id=user.id).order_by(TrustedContact.id).all()
    return success_response('Success', {
        'ride': ride_out,
        'my_location': {'lat': SS._f(user.current_latitude), 'lng': SS._f(user.current_longitude),
                        'at': SS.iso(user.last_location_update)},
        'emergency_number': '911',
        'province': prov,
        'help_contacts': SS.help_contacts(prov),
        'support': SS.support_contact(),
        'trusted_contacts': [_contact_dict(c) for c in contacts],
        'max_trusted_contacts': S.get_int('safety.max_trusted_contacts'),
        'settings': SS.settings_dict(SS.get_settings(user.id)),
        'recording': rec_out,
        'share': share,
        'open_incident': SS.incident_dict(open_inc) if open_inc else None,
        'pending_checks': [_check_dict(c) for c in
                           SafetyCheck.query.filter_by(user_id=user.id, status='pending').all()],
        'report_categories': list(SS.REPORT_CATEGORIES),
        'flags': {'sos': S.flag('sos'), 'live_share': S.flag('live_share'),
                  'audio_recording': S.flag('audio_recording'), 'route_deviation': S.flag('route_deviation')},
        'high_frequency_interval_s': S.get_int('safety.sos_location_interval_s', 3) or 3,
    })
