"""In-trip audio recording API (spec §10) + signed private-file downloads.

    POST /api/recordings                               start {ride_type?, ride_id?, trigger?: manual|always}
    POST /api/recordings/<id>/chunks                   multipart: file, seq, sha256, duration_ms?, started_at?
    POST /api/recordings/<id>/stop
    GET  /api/recordings/<id>                          OWNER only (metadata + own audio signed URLs)
    GET  /api/rides/<type>/<id>/recording-status       any party (sees that a recording exists, never the audio)
    GET  /api/private-files/<token>                    HMAC-signed, short-lived (local storage backend)
"""
from flask import Blueprint, Response, request

from backend.models import db
from backend.models.safety import Recording, SafetyIncident
from backend.models.user import AdminUser
from backend.services import private_storage as PS
from backend.services import recording_service as RS
from backend.services import rides as R
from backend.services import safety_service as SS
from backend.services import settings_service as S
from backend.services import trip_state_machine as TSM
from backend.services.audit import audit
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import error_response, success_response

recordings_bp = Blueprint('recordings', __name__)


def _body():
    return request.get_json(silent=True) or request.form.to_dict() or {}


@recordings_bp.route('/api/recordings', methods=['POST'])
@jwt_required_with_user
def start(user):
    if not S.flag('audio_recording'):
        return error_response('Audio recording is currently unavailable.', data={'error_code': 'feature_disabled'},
                              status_code=403)
    data = _body()
    trigger = (data.get('trigger') or 'manual').lower()
    if trigger not in ('manual', 'always'):
        return error_response('trigger must be manual or always.', data={'error_code': 'bad_trigger'},
                              status_code=422)
    settings = SS.get_settings(user.id)
    if trigger == 'always' and settings.record_audio != 'always':
        return error_response('Turn on "Record audio on my trips" in Safety settings first.',
                              data={'error_code': 'not_opted_in'}, status_code=403)
    try:
        rt, ride, role = SS.resolve_ride(user, data.get('ride_type'), data.get('ride_id'))
    except SS.SafetyError as e:
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    if ride is None and data.get('ride_type'):
        return error_response('Ride not found.', data={'error_code': 'not_found'}, status_code=404)
    if ride is not None:
        stage = R.current_stage(rt, ride)
        has_open_inc = SafetyIncident.query.filter_by(user_id=user.id).filter(
            SafetyIncident.status.in_(SS.OPEN_STATUSES)).first()
        if (TSM.is_terminal(rt, stage) or stage in ('COMPLETED', 'DROPPED_OFF')) and not has_open_inc:
            return error_response('This ride has ended.', data={'error_code': 'ride_ended'}, status_code=409)
    elif trigger != 'manual':
        return error_response('No active ride to record.', data={'error_code': 'no_ride'}, status_code=409)
    rec = RS.create(user, rt if ride is not None else None, ride, role or SS.default_role(user), trigger=trigger)
    db.session.commit()
    RS.emit_status(rec)
    return success_response('Recording started. The other party will see that audio recording is on.',
                            {'recording': RS.to_dict(rec, user.id), 'upload': RS.upload_info(rec)},
                            status_code=201)


def _own(user, rec_id):
    rec = db.session.get(Recording, rec_id)
    if not rec or rec.user_id != user.id:
        return None
    return rec


@recordings_bp.route('/api/recordings/<int:rec_id>/chunks', methods=['POST'])
@jwt_required_with_user
def upload_chunk(user, rec_id):
    rec = _own(user, rec_id)
    if not rec:
        return error_response('Recording not found.', data={'error_code': 'not_found'}, status_code=404)
    f = request.files.get('file') or request.files.get('chunk')
    if f is None:
        return error_response('file is required (multipart).', data={'error_code': 'file_required'},
                              status_code=422)
    data = f.read()
    try:
        chunk, dup = RS.add_chunk(rec, request.form.get('seq'), data, request.form.get('sha256'),
                                  content_type=f.mimetype, filename=f.filename,
                                  duration_ms=request.form.get('duration_ms'),
                                  started_at=request.form.get('started_at'))
    except RS.ChunkError as e:
        db.session.rollback()
        return error_response(e.message, data={'error_code': e.code}, status_code=e.status)
    db.session.commit()
    return success_response('Chunk stored' if not dup else 'Chunk already stored',
                            {'recording_id': rec.id, 'seq': chunk.seq, 'bytes': chunk.bytes, 'sha256': chunk.sha256,
                             'duplicate': dup, 'chunk_count': rec.chunk_count},
                            status_code=200 if dup else 201)


@recordings_bp.route('/api/recordings/<int:rec_id>/stop', methods=['POST'])
@jwt_required_with_user
def stop(user, rec_id):
    rec = _own(user, rec_id)
    if not rec:
        return error_response('Recording not found.', data={'error_code': 'not_found'}, status_code=404)
    was = rec.status
    RS.stop(rec, reason='user')
    db.session.commit()
    if was == 'recording':
        RS.emit_status(rec)
    return success_response('Recording stopped.', RS.to_dict(rec, user.id))


@recordings_bp.route('/api/recordings/<int:rec_id>', methods=['GET'])
@jwt_required_with_user
def get_recording(user, rec_id):
    rec = db.session.get(Recording, rec_id)
    if not rec:
        return error_response('Recording not found.', data={'error_code': 'not_found'}, status_code=404)
    if rec.user_id != user.id:
        # Other parties can see that a recording exists (recording-status) but
        # never its audio; access is through support / the safety team.
        return error_response("You can't access another person's recording. Contact support if you need it.",
                              data={'error_code': 'forbidden'}, status_code=403)
    out = RS.to_dict(rec, user.id)
    out['chunks'] = RS.chunk_urls(rec, user.id, ttl_s=300) if rec.status != 'deleted' else []
    return success_response('Success', out)


@recordings_bp.route('/api/rides/<ride_type>/<int:ride_id>/recording-status', methods=['GET'])
@jwt_required_with_user
def recording_status(user, ride_type, ride_id):
    try:
        rt = R.normalize_type(ride_type)
        ride = R.load(rt, ride_id)
    except R.RideNotFound:
        return error_response('Ride not found.', data={'error_code': 'not_found'}, status_code=404)
    if R.role_of(user, rt, ride) not in ('customer', 'driver', 'admin'):
        return error_response('You are not part of this ride.', data={'error_code': 'forbidden'}, status_code=403)
    return success_response('Success', RS.status_payload(rt, ride.id, user.id))


@recordings_bp.route('/api/private-files/<token>', methods=['GET'])
def private_file(token):
    payload = PS.verify_token(token)
    if not payload:
        return error_response('Link expired or invalid.', data={'error_code': 'link_expired'}, status_code=403)
    try:
        data = PS.get(payload['k'])
    except PS.StorageError:
        return error_response('File not found.', data={'error_code': 'not_found'}, status_code=404)
    actor = db.session.get(AdminUser, payload['u']) if payload.get('u') else None
    audit('private_file.download', actor, 'private_file', payload['k'][:180], meta={'bytes': len(data)})
    db.session.commit()
    resp = Response(data, mimetype=payload.get('ct') or 'application/octet-stream')
    if payload.get('fn'):
        resp.headers['Content-Disposition'] = f'inline; filename="{payload["fn"]}"'
    resp.headers['Cache-Control'] = 'private, no-store'
    resp.headers['X-Robots-Tag'] = 'noindex'
    return resp
