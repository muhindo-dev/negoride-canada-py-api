"""Safety periodic jobs (scheduler.PERIODIC):

  tick()               every 30 s — SOS escalation, "Are you OK?" timeouts
  retention_cleanup()  daily      — recordings, breadcrumbs, share links
"""
import logging
from datetime import datetime, timedelta

from backend.models import db
from backend.models.safety import (Recording, RideLocation, RideShareLink, SafetyCheck, SafetyIncident,
                                   SafetyReport)
from backend.models.user import AdminUser
from backend.services import live_share
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services.audit import audit

log = logging.getLogger('negoride.safety.jobs')


def tick():
    now = datetime.utcnow()
    n = 0
    ack = S.get_int('safety.sos_ack_timeout_s')
    for inc in (SafetyIncident.query.filter(SafetyIncident.status == 'open', SafetyIncident.escalated_at.is_(None),
                                            SafetyIncident.created_at <= now - timedelta(seconds=ack))
                .limit(50).all()):
        if escalate_incident(inc.id):
            n += 1
    wait = S.get_int('safety.check_response_s')
    for chk in (SafetyCheck.query.filter(SafetyCheck.status == 'pending',
                                         SafetyCheck.created_at <= now - timedelta(seconds=wait))
                .limit(50).all()):
        if check_timeout(chk.id):
            n += 1
    return n


def escalate_incident(incident_id):
    """No admin acknowledged in time → SMS + voice call to on-call phones,
    admin alert. Idempotent."""
    from backend.services import realtime
    from backend.services import safety_service as SS
    inc = SafetyIncident.query.filter_by(id=incident_id).with_for_update().first()
    if not inc or inc.status != 'open' or inc.escalated_at is not None:
        db.session.rollback()
        return False
    inc.escalated_at = datetime.utcnow()
    phones = SS.oncall_phones()
    audit('safety.sos_escalated', None, 'safety_incident', inc.id, meta={'oncall_count': len(phones)})
    db.session.commit()

    user = db.session.get(AdminUser, inc.user_id)
    link = RideShareLink.query.filter_by(ride_type=live_share.INCIDENT, ride_id=inc.id).order_by(
        RideShareLink.id.desc()).first()
    where = f' Live location: {live_share.url_for_token(link.token)}' if link else ''
    sms = (f'NegoRide SOS #{inc.id} NOT ACKNOWLEDGED: {SS.first_name(user)} ({inc.role}) needs help.{where} '
           f'Open the Safety Center now.')
    voice = (f'NegoRide safety alert. S O S number {inc.id} has not been acknowledged. '
             f'Please open the Safety Center immediately.')
    for p in phones:
        SS.sms_raw(p, sms)
        SS.call_alert(p, voice)
    SS.emit_incident('safety.sos_updated', inc, {'type': 'escalated', 'oncall_notified': len(phones)})
    realtime.to_admins('alert', {'kind': 'sos_unacknowledged', 'incident_id': inc.id,
                                 'message': f'SOS #{inc.id} not acknowledged — on-call escalated'})
    admins = SS.admin_recipient_ids()
    if admins:
        from backend.services.notify import notify
        notify('safety.sos_escalated', admins, {'incident_id': inc.id, 'id': inc.id, 'name': SS.first_name(user)},
               dedupe_key=f'sos-esc-{inc.id}')
        db.session.commit()
    return True


def check_timeout(check_id):
    """Unanswered "Are you OK?" → escalated to admins as an incident."""
    from backend.services import safety_service as SS
    chk = SafetyCheck.query.filter_by(id=check_id).with_for_update().first()
    if not chk or chk.status != 'pending':
        db.session.rollback()
        return False
    if (datetime.utcnow() - chk.created_at).total_seconds() < S.get_int('safety.check_response_s') - 1:
        db.session.rollback()
        return False
    now = datetime.utcnow()
    chk.status, chk.responded_at = 'escalated', None
    inc = SafetyIncident(user_id=chk.user_id, role='customer', ride_type=chk.ride_type, ride_id=chk.ride_id,
                         kind='check_in_timeout', status='open', severity='high', silent=False,
                         lat=chk.lat, lng=chk.lng, last_lat=chk.lat, last_lng=chk.lng,
                         last_location_at=chk.created_at, created_at=now,
                         notes=f'[{SS.iso(now)}] system: no answer to "{chk.kind}" check #{chk.id}')
    db.session.add(inc)
    db.session.flush()
    chk.incident_id = inc.id
    audit('safety.check_escalated', None, 'safety_check', chk.id, meta={'incident_id': inc.id, 'kind': chk.kind})
    user = db.session.get(AdminUser, chk.user_id)
    admins = SS.admin_recipient_ids()
    if admins:
        from backend.services.notify import notify
        notify('safety.check_unanswered', admins, {'incident_id': inc.id, 'id': inc.id, 'check_id': chk.id,
                                                   'name': SS.first_name(user), 'kind': chk.kind,
                                                   'ride_type': chk.ride_type, 'ride_id': chk.ride_id})
    db.session.commit()
    SS.emit_incident('safety.sos', inc, {'check_id': chk.id, 'check_kind': chk.kind})
    return inc.id


# ── retention ───────────────────────────────────────────────────────────────

def _ride_disputed(ride_type, ride_id):
    try:
        ride = R.load(ride_type, ride_id)
    except (R.RideNotFound, Exception):
        return False
    return getattr(ride, 'disputed_at', None) is not None


def _case_state(rec):
    """(linked, closed_at). linked → keep until closed_at + hold days."""
    closes = []
    linked = False
    incs = []
    if rec.incident_id:
        incs = SafetyIncident.query.filter_by(id=rec.incident_id).all()
    if rec.ride_type and rec.ride_id:
        incs += SafetyIncident.query.filter_by(ride_type=rec.ride_type, ride_id=rec.ride_id).all()
        reports = SafetyReport.query.filter_by(ride_type=rec.ride_type, ride_id=rec.ride_id).all()
        for r in reports:
            linked = True
            closes.append(r.reviewed_at if r.status in ('resolved', 'dismissed') else None)
        if _ride_disputed(rec.ride_type, rec.ride_id):
            linked = True
            closes.append(None)   # disputes: kept until an admin releases (legal_hold off + no open dispute)
    for i in incs:
        linked = True
        closes.append(i.resolved_at if i.status in ('resolved', 'false_alarm') else None)
    if not linked:
        return False, None
    if any(c is None for c in closes):
        return True, None
    return True, max(closes)


def ride_protected(ride_type, ride_id):
    if SafetyIncident.query.filter_by(ride_type=ride_type, ride_id=ride_id).first():
        return True
    if SafetyReport.query.filter_by(ride_type=ride_type, ride_id=ride_id).first():
        return True
    return _ride_disputed(ride_type, ride_id)


def retention_cleanup(now=None, scope_user_ids=None):
    """scope_user_ids: limit to these owners (tests / targeted maintenance)."""
    from backend.services import recording_service
    now = now or datetime.utcnow()
    stats = {'recordings_deleted': 0, 'recordings_kept_for_case': 0, 'ride_locations_deleted': 0,
             'share_links_deleted': 0}
    keep_days = S.get_int('recording.retention_days')
    hold_days = S.get_int('recording.hold_after_case_days')
    cutoff = now - timedelta(days=keep_days)
    rq = Recording.query.filter(Recording.status != 'deleted', Recording.legal_hold.is_(False),
                                Recording.started_at < cutoff)
    if scope_user_ids:
        rq = rq.filter(Recording.user_id.in_(scope_user_ids))
    for rec in rq.limit(500).all():
        linked, closed_at = _case_state(rec)
        if linked:
            if closed_at is None or closed_at + timedelta(days=hold_days) > now:
                stats['recordings_kept_for_case'] += 1
                continue
        if rec.status == 'recording':
            recording_service.stop(rec, reason='retention')
        recording_service.purge(rec)
        audit('recording.retention_deleted', None, 'recording', rec.id,
              meta={'ride_type': rec.ride_type, 'ride_id': rec.ride_id, 'linked_case': linked})
        stats['recordings_deleted'] += 1
    db.session.commit()

    loc_cut = now - timedelta(days=S.get_int('tracking.retention_days'))
    lq = db.session.query(RideLocation.ride_type, RideLocation.ride_id).filter(RideLocation.recorded_at < loc_cut)
    if scope_user_ids:
        lq = lq.filter(RideLocation.user_id.in_(scope_user_ids))
    rides = lq.distinct().limit(1000).all()
    for rt, rid in rides:
        if rt and rid and ride_protected(rt, rid):
            continue
        q = RideLocation.query.filter(RideLocation.recorded_at < loc_cut)
        if scope_user_ids:
            q = q.filter(RideLocation.user_id.in_(scope_user_ids))
        q = q.filter(RideLocation.ride_type == rt, RideLocation.ride_id == rid) if rt else \
            q.filter(RideLocation.ride_type.is_(None))
        stats['ride_locations_deleted'] += q.delete(synchronize_session=False)
    db.session.commit()

    # Share links: make sure ended rides' links expire, purge long-dead links.
    sq = RideShareLink.query
    dq = RideShareLink.query
    if scope_user_ids:
        sq = sq.filter(RideShareLink.user_id.in_(scope_user_ids))
        dq = dq.filter(RideShareLink.user_id.in_(scope_user_ids))
    for link in (sq.filter(RideShareLink.revoked_at.is_(None),
                                            (RideShareLink.expires_at.is_(None)) |
                                            (RideShareLink.expires_at > now))
                 .filter(RideShareLink.ride_type != live_share.INCIDENT).limit(1000).all()):
        try:
            ride = R.load(link.ride_type, link.ride_id)
        except R.RideNotFound:
            link.expires_at = now
            continue
        if live_share.ride_ended(link.ride_type, R.current_stage(link.ride_type, ride)):
            ended = getattr(ride, 'completed_at', None) or getattr(ride, 'stage_changed_at', None) or now
            live_share.expire_for_ride(link.ride_type, link.ride_id, ended)
    dead = now - timedelta(days=30)
    stats['share_links_deleted'] = dq.filter(
        ((RideShareLink.expires_at.isnot(None)) & (RideShareLink.expires_at < dead)) |
        ((RideShareLink.revoked_at.isnot(None)) & (RideShareLink.revoked_at < dead))).delete(
        synchronize_session=False)
    db.session.commit()
    log.info('safety retention: %s', stats)
    return stats

