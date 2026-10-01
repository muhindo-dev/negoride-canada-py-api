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
    if not phones:
        # Never skip silently: nobody can be phoned. Readiness shows this as
        # critical (safety_service.readiness_checks) and every admin is alerted.
        log.error('SOS #%s escalation: NO on-call phones configured (safety.oncall_phones / '
                  'SAFETY_ONCALL_PHONES) — only dashboard/push alerts were sent', inc.id)
        audit('safety.oncall_missing', None, 'safety_incident', inc.id,
              meta={'message': 'SOS escalated with an empty on-call list'})
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
    if not phones:
        for room in ('admin:ops', 'admin:sos'):
            realtime.to_admins('alert', {'kind': 'oncall_not_configured', 'incident_id': inc.id, 'level': 'critical',
                                         'message': f'SOS #{inc.id} could not be escalated by phone: no on-call '
                                                    f'numbers are configured (Settings → safety.oncall_phones).'},
                               room=room)
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
    user = db.session.get(AdminUser, chk.user_id)
    role = 'customer'
    try:
        role = R.role_of(user, chk.ride_type, R.load(chk.ride_type, chk.ride_id)) or 'customer'
    except R.RideNotFound:
        pass
    if role not in ('customer', 'driver'):
        role = 'customer'
    inc = SafetyIncident(user_id=chk.user_id, role=role, ride_type=chk.ride_type, ride_id=chk.ride_id,
                         kind='check_in_timeout', status='open', severity='high', silent=False,
                         lat=chk.lat, lng=chk.lng, last_lat=chk.lat, last_lng=chk.lng,
                         last_location_at=chk.created_at, created_at=now,
                         notes=f'[{SS.iso(now)}] system: no answer to "{chk.kind}" check #{chk.id}')
    db.session.add(inc)
    db.session.flush()
    chk.incident_id = inc.id
    audit('safety.check_escalated', None, 'safety_check', chk.id, meta={'incident_id': inc.id, 'kind': chk.kind})
    # Incident live link: the on-call escalation SMS carries the live location URL.
    link = live_share.get_or_create(live_share.INCIDENT, inc.id, chk.user_id)
    admins = SS.admin_recipient_ids()
    if admins:
        from backend.services.notify import notify
        notify('safety.check_unanswered', admins, {'incident_id': inc.id, 'id': inc.id, 'check_id': chk.id,
                                                   'name': SS.first_name(user), 'kind': chk.kind,
                                                   'ride_type': chk.ride_type, 'ride_id': chk.ride_id,
                                                   'link': live_share.url_for_token(link.token)})
    from backend import jobs
    jobs.enqueue_after_commit('backend.services.safety_jobs.escalate_incident', inc.id,
                              delay_s=max(1, S.get_int('safety.sos_ack_timeout_s')))
    db.session.commit()
    SS.emit_incident('safety.sos', inc, {'check_id': chk.id, 'check_kind': chk.kind,
                                         'share_url': live_share.url_for_token(link.token)})
    return inc.id


# ── retention ───────────────────────────────────────────────────────────────
#
# A ride is PROTECTED while it has an open case: a safety incident, a safety
# report, a ride dispute (`disputed_at` without `dispute_resolved_at`) or a
# support ticket of type `dispute`. Once every case is closed, its evidence
# (recordings, breadcrumbs) is kept `recording.hold_after_case_days` (90) more
# days, then purged like everything else. Scans are cursor-paged, so protected
# rows can never starve deletions.

PAGE = 500
MAX_PAGES = 200


def _dispute_state(ride_type, ride_id):
    """(linked, closed_at|None) for ride disputes + dispute support tickets."""
    closes, linked = [], False
    try:
        ride = R.load(ride_type, ride_id)
    except Exception:
        ride = None
    if ride is not None and getattr(ride, 'disputed_at', None) is not None:
        linked = True
        closes.append(getattr(ride, 'dispute_resolved_at', None))
    try:
        from backend.models.identity import SupportTicket
        for t in SupportTicket.query.filter_by(type='dispute', ride_type=ride_type, ride_id=int(ride_id)).all():
            linked = True
            closes.append((t.resolved_at or t.updated_at or datetime.utcnow())
                          if t.status in ('resolved', 'closed') else None)
    except Exception:
        db.session.rollback()
    return linked, closes


def ride_case_state(ride_type, ride_id):
    """(linked, closed_at). linked + closed_at None → a case is still open."""
    closes, linked = [], False
    for i in SafetyIncident.query.filter_by(ride_type=ride_type, ride_id=ride_id).all():
        linked = True
        closes.append(i.resolved_at if i.status in ('resolved', 'false_alarm') else None)
    for r in SafetyReport.query.filter_by(ride_type=ride_type, ride_id=ride_id).all():
        linked = True
        closes.append(r.reviewed_at if r.status in ('resolved', 'dismissed') else None)
    d_linked, d_closes = _dispute_state(ride_type, ride_id)
    if d_linked:
        linked = True
        closes += d_closes
    if not linked:
        return False, None
    if any(c is None for c in closes):
        return True, None
    return True, max(closes)


def _case_state(rec):
    """(linked, closed_at) for a recording: its incident + its ride's cases."""
    closes, linked = [], False
    if rec.incident_id:
        inc = db.session.get(SafetyIncident, rec.incident_id)
        if inc:
            linked = True
            closes.append(inc.resolved_at if inc.status in ('resolved', 'false_alarm') else None)
    if rec.ride_type and rec.ride_id:
        r_linked, r_closed = ride_case_state(rec.ride_type, rec.ride_id)
        if r_linked:
            linked = True
            closes.append(r_closed)
    if not linked:
        return False, None
    if any(c is None for c in closes):
        return True, None
    return True, max(closes)


def _held(linked, closed_at, now, hold_days):
    return linked and (closed_at is None or closed_at + timedelta(days=hold_days) > now)


def ride_protected(ride_type, ride_id, now=None):
    now = now or datetime.utcnow()
    linked, closed_at = ride_case_state(ride_type, ride_id)
    return _held(linked, closed_at, now, S.get_int('recording.hold_after_case_days'))


def retention_cleanup(now=None, scope_user_ids=None):
    """scope_user_ids: limit to these owners (tests / targeted maintenance)."""
    from backend.services import recording_service
    now = now or datetime.utcnow()
    stats = {'recordings_deleted': 0, 'recordings_kept_for_case': 0, 'ride_locations_deleted': 0,
             'ride_locations_kept_for_case': 0, 'share_links_deleted': 0}
    keep_days = S.get_int('recording.retention_days')
    hold_days = S.get_int('recording.hold_after_case_days')
    cutoff = now - timedelta(days=keep_days)

    last_id = 0
    for _ in range(MAX_PAGES):
        rq = Recording.query.filter(Recording.status != 'deleted', Recording.legal_hold.is_(False),
                                    Recording.started_at < cutoff, Recording.id > last_id)
        if scope_user_ids:
            rq = rq.filter(Recording.user_id.in_(scope_user_ids))
        page = rq.order_by(Recording.id).limit(PAGE).all()
        if not page:
            break
        last_id = page[-1].id
        for rec in page:
            linked, closed_at = _case_state(rec)
            if _held(linked, closed_at, now, hold_days):
                stats['recordings_kept_for_case'] += 1
                continue
            if rec.status == 'recording':
                recording_service.stop(rec, reason='retention')
            recording_service.purge(rec)
            audit('recording.retention_deleted', None, 'recording', rec.id,
                  meta={'ride_type': rec.ride_type, 'ride_id': rec.ride_id, 'linked_case': linked,
                        'case_closed_at': closed_at.strftime('%Y-%m-%dT%H:%M:%SZ') if closed_at else None})
            stats['recordings_deleted'] += 1
        db.session.commit()

    loc_cut = now - timedelta(days=S.get_int('tracking.retention_days'))
    cursor = ('', 0)
    for _ in range(MAX_PAGES):
        lq = (db.session.query(RideLocation.ride_type, RideLocation.ride_id)
              .filter(RideLocation.recorded_at < loc_cut, RideLocation.ride_type.isnot(None),
                      RideLocation.ride_id.isnot(None))
              .filter((RideLocation.ride_type > cursor[0]) |
                      ((RideLocation.ride_type == cursor[0]) & (RideLocation.ride_id > cursor[1]))))
        if scope_user_ids:
            lq = lq.filter(RideLocation.user_id.in_(scope_user_ids))
        rides = lq.distinct().order_by(RideLocation.ride_type, RideLocation.ride_id).limit(PAGE).all()
        if not rides:
            break
        cursor = (rides[-1][0], int(rides[-1][1]))
        for rt, rid in rides:
            if ride_protected(rt, rid, now):
                stats['ride_locations_kept_for_case'] += 1
                continue
            q = RideLocation.query.filter(RideLocation.recorded_at < loc_cut, RideLocation.ride_type == rt,
                                          RideLocation.ride_id == rid)
            if scope_user_ids:
                q = q.filter(RideLocation.user_id.in_(scope_user_ids))
            stats['ride_locations_deleted'] += q.delete(synchronize_session=False)
        db.session.commit()
    # Ride-less breadcrumbs (no case can reference them).
    nq = RideLocation.query.filter(RideLocation.recorded_at < loc_cut,
                                   (RideLocation.ride_type.is_(None)) | (RideLocation.ride_id.is_(None)))
    if scope_user_ids:
        nq = nq.filter(RideLocation.user_id.in_(scope_user_ids))
    stats['ride_locations_deleted'] += nq.delete(synchronize_session=False)
    db.session.commit()

    # Share links: make sure ended rides' links expire, purge long-dead links.
    sq = RideShareLink.query
    dq = RideShareLink.query
    if scope_user_ids:
        sq = sq.filter(RideShareLink.user_id.in_(scope_user_ids))
        dq = dq.filter(RideShareLink.user_id.in_(scope_user_ids))
    for link in (sq.filter(RideShareLink.revoked_at.is_(None),
                           (RideShareLink.expires_at.is_(None)) | (RideShareLink.expires_at > now))
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
