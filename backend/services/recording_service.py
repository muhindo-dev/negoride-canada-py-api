"""Optional in-trip audio recording (spec §10).

Rules implemented here:
  • opt-in: 'manual' (the user pressed Record = consent), 'always' (safety
    setting record_audio=always), 'sos' (auto_record_on_sos pre-consent)
  • transparency: every start/stop emits `recording.status` to the ride room and
    to the other parties; GET /api/rides/{type}/{id}/recording-status shows it
  • storage: 1-min AAC/M4A chunks, sha256-verified, in private encrypted storage
  • access: owner may fetch their own audio; other parties never; admins only
    with safety_reviewer (routes/admin_safety.py), every access audited
  • retention: safety_jobs.retention_cleanup
"""
from datetime import datetime, timedelta

from backend.models import db
from backend.models.safety import Recording, RecordingChunk
from backend.services import private_storage as PS
from backend.services import realtime
from backend.services import rides as R
from backend.services import settings_service as S

ALLOWED_AUDIO = ('audio/mp4', 'audio/m4a', 'audio/x-m4a', 'audio/aac', 'audio/aacp', 'audio/mpeg',
                 'application/octet-stream')
ALLOWED_EXT = ('m4a', 'aac', 'mp4')
BANNER = '🔴 Audio recording is on for safety'
LATE_UPLOAD_GRACE_H = 24


def iso(v):
    return v.strftime('%Y-%m-%dT%H:%M:%SZ') if v else None


def storage_key(rec, seq):
    return f'recordings/{rec.user_id}/{rec.id}/{int(seq):05d}.m4a'


def upload_info(rec):
    return {'method': 'POST', 'url': f'/api/recordings/{rec.id}/chunks', 'content_type': 'multipart/form-data',
            'fields': {'file': 'AAC/M4A chunk', 'seq': 'int, 0-based', 'sha256': 'hex digest of the file',
                       'duration_ms': 'optional', 'started_at': 'optional ISO-8601'},
            'chunk_seconds': S.get_int('recording.chunk_seconds'),
            'max_chunk_bytes': S.get_int('recording.max_chunk_bytes', 5_000_000) or 5_000_000,
            'stop_url': f'/api/recordings/{rec.id}/stop'}


def to_dict(rec, viewer_id=None):
    d = rec.to_dict()
    d['is_mine'] = viewer_id is not None and int(viewer_id) == rec.user_id
    return d


def active_for_ride(ride_type, ride_id):
    return Recording.query.filter_by(ride_type=ride_type, ride_id=int(ride_id), status='recording').all()


def create(user, ride_type, ride, role, trigger='manual', incident_id=None):
    """Create (or return the running) recording. Caller commits."""
    q = Recording.query.filter_by(user_id=user.id, status='recording')
    if ride is not None:
        q = q.filter_by(ride_type=ride_type, ride_id=ride.id)
    else:
        q = q.filter(Recording.ride_id.is_(None))
    existing = q.first()
    if existing:
        if incident_id and not existing.incident_id:
            existing.incident_id = incident_id
        return existing
    now = datetime.utcnow()
    rec = Recording(user_id=user.id, role=role or 'customer', ride_type=ride_type if ride is not None else None,
                    ride_id=ride.id if ride is not None else None, incident_id=incident_id, status='recording',
                    trigger_source=trigger, started_at=now, created_at=now,
                    retain_until=now + timedelta(days=S.get_int('recording.retention_days')))
    db.session.add(rec)
    db.session.flush()
    from backend.services.audit import audit
    audit('recording.started', user, 'recording', rec.id,
          meta={'ride_type': rec.ride_type, 'ride_id': rec.ride_id, 'trigger': trigger, 'incident_id': incident_id},
          actor_type='user')
    return rec


def status_payload(ride_type, ride_id, viewer_id=None):
    """Transparency payload for any party. `recording_active` / `banner` are about
    running recordings; `ever_recorded` + `recordings` list EVERY non-deleted
    recording of the ride (running or stopped) so the other party still sees
    that audio was recorded after it stopped or the ride ended. Never URLs."""
    recs = (Recording.query.filter(Recording.ride_type == ride_type, Recording.ride_id == int(ride_id),
                                   Recording.status != 'deleted')
            .order_by(Recording.started_at, Recording.id).all())
    active = [r for r in recs if r.status == 'recording']
    vid = int(viewer_id) if viewer_id is not None else None
    others = [r for r in active if vid is None or r.user_id != vid]
    mine = [r for r in active if vid is not None and r.user_id == vid]
    return {'ride_type': ride_type, 'ride_id': int(ride_id), 'recording_active': bool(active),
            'other_party_recording': bool(others), 'i_am_recording': bool(mine),
            'by_roles': sorted({r.role for r in active}),
            'banner': BANNER if others else None,
            'ever_recorded': bool(recs),
            'other_party_ever_recorded': any(vid is None or r.user_id != vid for r in recs),
            'recordings': [{'id': r.id, 'role': r.role, 'status': r.status,
                            'is_mine': vid is not None and r.user_id == vid,
                            'started_at': iso(r.started_at), 'stopped_at': iso(r.stopped_at)} for r in recs]}


def emit_status(rec):
    if not rec.ride_type or not rec.ride_id:
        return
    payload = {'ride_type': rec.ride_type, 'ride_id': rec.ride_id, 'recording_id': rec.id,
               'active': rec.status == 'recording', 'role': rec.role, 'user_id': rec.user_id,
               'banner': BANNER if rec.status == 'recording' else None,
               'at': iso(rec.stopped_at if rec.status != 'recording' else rec.started_at)}
    realtime.to_ride(rec.ride_type, rec.ride_id, 'recording.status', payload)
    try:
        ride = R.load(rec.ride_type, rec.ride_id)
        others = [uid for uid in R.all_party_ids(rec.ride_type, ride) if uid != rec.user_id]
        for uid in others:
            realtime.to_user(uid, 'recording.status', payload)
        # Transparency (spec §10.1): the other party is also told by push/inbox,
        # so they know even if their app is closed or offline.
        if others and rec.status == 'recording':
            from backend.services.notify import notify
            notify('safety.recording_started', others,
                   {'ride_type': rec.ride_type, 'ride_id': rec.ride_id, 'recording_id': rec.id},
                   dedupe_key=f'rec-{rec.id}')
    except R.RideNotFound:
        pass


def stop(rec, reason='user'):
    if rec.status != 'recording':
        return rec
    now = datetime.utcnow()
    rec.status, rec.stopped_at = 'stopped', now
    base = now + timedelta(days=S.get_int('recording.retention_days'))
    rec.retain_until = max(rec.retain_until or base, base)
    from backend.services.audit import audit
    audit('recording.stopped', rec.user_id if reason == 'user' else None, 'recording', rec.id,
          meta={'reason': reason, 'chunks': rec.chunk_count}, actor_type='user' if reason == 'user' else 'system')
    return rec


class ChunkError(Exception):
    def __init__(self, message, code, status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def add_chunk(rec, seq, data, sha256, content_type=None, filename=None, duration_ms=None, started_at=None):
    if rec.status == 'deleted':
        raise ChunkError('This recording no longer exists.', 'recording_deleted', 410)
    if rec.status == 'stopped' and rec.stopped_at and \
            datetime.utcnow() - rec.stopped_at > timedelta(hours=LATE_UPLOAD_GRACE_H):
        raise ChunkError('Upload window closed for this recording.', 'upload_window_closed', 409)
    try:
        seq = int(seq)
        assert 0 <= seq <= 100000
    except (TypeError, ValueError, AssertionError):
        raise ChunkError('seq must be a non-negative integer.', 'bad_seq')
    if not data:
        raise ChunkError('Empty chunk.', 'empty_chunk')
    limit = S.get_int('recording.max_chunk_bytes', 5_000_000) or 5_000_000
    if len(data) > limit:
        raise ChunkError(f'Chunk too large (max {limit} bytes).', 'chunk_too_large', 413)
    ext = (filename or '').rsplit('.', 1)[-1].lower() if filename and '.' in filename else None
    ct = (content_type or '').split(';')[0].strip().lower()
    if ct and ct not in ALLOWED_AUDIO and (ext not in ALLOWED_EXT):
        raise ChunkError('Only AAC/M4A audio chunks are accepted.', 'bad_type', 415)
    actual = PS.sha256_hex(data)
    if not sha256 or actual != str(sha256).strip().lower():
        raise ChunkError('Checksum mismatch — re-upload this chunk.', 'checksum_mismatch', 422)
    existing = RecordingChunk.query.filter_by(recording_id=rec.id, seq=seq).first()
    if existing:
        if existing.sha256 == actual:
            return existing, True
        raise ChunkError('A different chunk with this seq was already uploaded.', 'seq_conflict', 409)
    key = storage_key(rec, seq)
    PS.put(key, data, 'audio/mp4')
    st = None
    if started_at:
        try:
            st = datetime.strptime(str(started_at)[:19], '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            st = None
    chunk = RecordingChunk(recording_id=rec.id, seq=seq, storage_key=key, bytes=len(data), sha256=actual,
                           duration_ms=int(duration_ms) if str(duration_ms or '').isdigit() else None,
                           started_at=st, uploaded_at=datetime.utcnow())
    db.session.add(chunk)
    rec.chunk_count = (rec.chunk_count or 0) + 1
    rec.total_bytes = (rec.total_bytes or 0) + len(data)
    return chunk, False


def chunk_urls(rec, actor_id, ttl_s=300, stream_base=None):
    """Chunk list with short-lived signed URLs. `stream_base` (admin) adds
    `stream_url` = the authenticated, per-fetch audited streaming proxy, which
    admin players should prefer over the signed `url`."""
    out = []
    for c in RecordingChunk.query.filter_by(recording_id=rec.id).order_by(RecordingChunk.seq).all():
        item = {'seq': c.seq, 'bytes': c.bytes, 'sha256': c.sha256, 'duration_ms': c.duration_ms,
                'started_at': iso(c.started_at), 'uploaded_at': iso(c.uploaded_at),
                'url': PS.signed_url(c.storage_key, ttl_s=ttl_s, content_type='audio/mp4',
                                     filename=f'recording-{rec.id}-{c.seq:05d}.m4a', actor_id=actor_id)}
        if stream_base:
            item['stream_url'] = f'{stream_base}/{c.seq}'
        out.append(item)
    return out


def purge(rec):
    """Delete audio from storage + chunk rows; keep the metadata row (deleted)."""
    for c in RecordingChunk.query.filter_by(recording_id=rec.id).all():
        PS.delete(c.storage_key)
        db.session.delete(c)
    rec.status, rec.deleted_at = 'deleted', datetime.utcnow()
