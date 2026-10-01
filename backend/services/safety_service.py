"""Safety core (spec §8): SOS incidents, trusted contacts, safety settings,
help contacts, reports and the SMS path to people who are not NegoRide users
(trusted contacts, on-call phones).

Request-time work is limited to DB writes + realtime emits (cheap). SMS / push /
email go through jobs (`notify()` or `enqueue_after_commit`).
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from backend import jobs
from backend.models import db
from backend.models.notification import Notification, NotificationDelivery
from backend.models.safety import (HelpContact, Recording, SafetyIncident, SafetyIncidentLocation, SafetySettings,
                                   TrustedContact)
from backend.models.user import AdminUser
from backend.services import live_share
from backend.services import realtime
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services.audit import audit
from backend.services.notify import catalogue as C
from backend.services.notify.dispatcher import render

log = logging.getLogger('negoride.safety')

OPEN_STATUSES = ('open', 'acknowledged')
REPORT_CATEGORIES = ('unsafe_driving', 'harassment', 'vehicle_condition', 'other')
PASSENGER_FLAG = 'passenger_flag'
HIGH_FREQUENCY_INTERVAL_S = 3
RECORD_AUDIO_MODES = ('off', 'always', 'ask')

PROVINCE_TZ = {
    'ON': 'America/Toronto', 'QC': 'America/Toronto', 'BC': 'America/Vancouver', 'AB': 'America/Edmonton',
    'SK': 'America/Regina', 'MB': 'America/Winnipeg', 'NS': 'America/Halifax', 'NB': 'America/Halifax',
    'PE': 'America/Halifax', 'NL': 'America/St_Johns', 'YT': 'America/Whitehorse', 'NT': 'America/Yellowknife',
    'NU': 'America/Iqaluit',
}
PROVINCES = tuple(PROVINCE_TZ)
CALLS = []   # on-call voice alerts when Twilio is not configured (test/dev introspection)


class SafetyError(Exception):
    def __init__(self, message, code='bad_request', status=400, data=None):
        super().__init__(message)
        self.message, self.code, self.status, self.data = message, code, status, data or {}


def iso(v):
    return v.strftime('%Y-%m-%dT%H:%M:%SZ') if v else None


def _f(v):
    return float(v) if v is not None else None


def first_name(user):
    if not user:
        return ''
    return (user.first_name or (user.name or '').split(' ')[0] or 'A NegoRide user').strip()


def mask_phone(p):
    return (p[:-4].rstrip()[:3] + '•••' + p[-4:]) if p and len(p) > 6 else '•••'


# ── settings ────────────────────────────────────────────────────────────────

def get_settings(user_id):
    s = db.session.get(SafetySettings, int(user_id))
    if s is None:
        s = SafetySettings(user_id=int(user_id), record_audio='off', auto_record_on_sos=False,
                           auto_share_night=False, auto_share_all=False, night_start='21:00', night_end='05:00')
    return s


def settings_dict(s):
    return {'record_audio': s.record_audio or 'off', 'auto_record_on_sos': bool(s.auto_record_on_sos),
            'auto_share_night': bool(s.auto_share_night), 'auto_share_all': bool(s.auto_share_all),
            'night_start': s.night_start or '21:00', 'night_end': s.night_end or '05:00',
            'updated_at': iso(s.updated_at)}


def user_tz(user):
    tz = getattr(user, 'timezone', None)
    if not tz:
        tz = PROVINCE_TZ.get((getattr(user, 'province', None) or '').upper(), 'America/Toronto')
    return tz


def local_now(user, now_utc=None):
    from zoneinfo import ZoneInfo
    now_utc = now_utc or datetime.utcnow()
    try:
        zone = ZoneInfo(user_tz(user))
    except Exception:
        zone = ZoneInfo('America/Toronto')
    return now_utc.replace(tzinfo=ZoneInfo('UTC')).astimezone(zone).replace(tzinfo=None)


def is_night(user, settings, now_utc=None):
    cur = local_now(user, now_utc).strftime('%H:%M')
    s, e = settings.night_start or '21:00', settings.night_end or '05:00'
    return (s <= cur < e) if s < e else (cur >= s or cur < e)


def should_auto_share(user, settings, now_utc=None):
    return bool(settings.auto_share_all) or (bool(settings.auto_share_night) and is_night(user, settings, now_utc))


# ── recipients ──────────────────────────────────────────────────────────────

def admin_recipient_ids():
    """Admins who receive SOS alerts (ops / safety_reviewer / super_admin)."""
    rows = AdminUser.query.filter((AdminUser.admin_roles.isnot(None)) |
                                  (AdminUser.user_type.in_(['Admin', 'Super Admin']))).limit(500).all()
    return [u.id for u in rows if u.deleted_at is None and u.has_admin_role('ops', 'safety_reviewer')]


def oncall_phones():
    import os
    from backend.utils.phone import safe_normalize
    raw = S.get('safety.oncall_phones') or os.getenv('SAFETY_ONCALL_PHONES', '')
    out = []
    for p in str(raw).split(','):
        n = safe_normalize(p.strip()) if p.strip() else None
        if n and n not in out:
            out.append(n)
    return out


# ── cards ───────────────────────────────────────────────────────────────────

def ride_brief(ride_type, ride_id):
    if not ride_type or not ride_id or ride_type not in R.RIDE_TYPES:
        return None
    try:
        ride = R.load(ride_type, ride_id)
    except R.RideNotFound:
        return None
    pickup, dropoff = R.addresses(ride_type, ride)
    return {'ride_type': ride_type, 'ride_id': ride.id, 'stage': R.current_stage(ride_type, ride),
            'pickup_address': pickup, 'dropoff_address': dropoff,
            'driver_id': R.driver_id(ride_type, ride), 'customer_ids': R.customer_ids(ride_type, ride)}


def incident_dict(inc, for_admin=False):
    d = inc.to_dict()
    for k in ('lat', 'lng', 'last_lat', 'last_lng'):
        d[k] = _f(getattr(inc, k))
    d['is_open'] = inc.status in OPEN_STATUSES
    if for_admin:
        u = db.session.get(AdminUser, inc.user_id)
        d['user'] = {'id': inc.user_id, 'name': u.name if u else None, 'first_name': first_name(u),
                     'avatar': R.user_card(inc.user_id)['avatar'] if u else None, 'role': inc.role}
        d['ride'] = ride_brief(inc.ride_type, inc.ride_id)
    return d


def realtime_payload(inc):
    u = db.session.get(AdminUser, inc.user_id)
    return {
        'incident_id': inc.id, 'kind': inc.kind, 'status': inc.status, 'severity': inc.severity,
        'silent': bool(inc.silent), 'role': inc.role,
        'user': {'id': inc.user_id, 'name': u.name if u else None, 'first_name': first_name(u)},
        'ride_type': inc.ride_type, 'ride_id': inc.ride_id,
        'lat': _f(inc.last_lat if inc.last_lat is not None else inc.lat),
        'lng': _f(inc.last_lng if inc.last_lng is not None else inc.lng),
        'accuracy_m': inc.accuracy_m, 'battery_pct': inc.battery_pct,
        'created_at': iso(inc.created_at), 'acknowledged_at': iso(inc.acknowledged_at),
        'acknowledged_by': inc.acknowledged_by, 'escalated_at': iso(inc.escalated_at),
        'resolved_at': iso(inc.resolved_at), 'last_location_at': iso(inc.last_location_at),
    }


def emit_incident(event, inc, extra=None):
    payload = {**realtime_payload(inc), **(extra or {})}
    realtime.to_admins(event, payload, room='admin:sos')
    realtime.to_admins(event, payload, room='admin:ops')
    realtime.to_user(inc.user_id, event, {k: payload[k] for k in ('incident_id', 'status', 'acknowledged_at',
                                                                  'resolved_at', 'escalated_at')})
    return payload


# ── SOS ─────────────────────────────────────────────────────────────────────

def _num(v, lo, hi):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if lo <= f <= hi else None


def resolve_ride(user, ride_type, ride_id):
    """(ride_type, ride, role). Explicit ride → caller must be a party (ended rides
    are fine). No ride → the caller's current active ride, if any."""
    if ride_type and ride_id:
        try:
            rt = R.normalize_type(ride_type)
            ride = R.load(rt, ride_id)
        except R.RideNotFound:
            raise SafetyError('Ride not found.', 'not_found', 404)
        role = R.role_of(user, rt, ride)
        if role not in ('customer', 'driver'):
            raise SafetyError('You are not part of this ride.', 'forbidden', 403)
        return rt, ride, role
    from backend.services.ride_actions import find_active_for
    rt, ride = find_active_for(user)
    if ride is None:
        return None, None, None
    return rt, ride, R.role_of(user, rt, ride)


def resolve_ride_for_sos(user, ride_type, ride_id):
    """SOS must never fail (spec §8.2, §8.5). Like resolve_ride(), but an
    unknown / foreign / malformed ride falls back to the caller's active ride
    (or no ride). Returns (ride_type, ride, role, rejected_note|None); the note
    is stored on the incident so the safety team sees what the app sent."""
    rejected = None
    if ride_type or ride_id:
        try:
            if not ride_type or not ride_id:
                raise SafetyError('Incomplete ride reference.', 'bad_ride')
            return (*resolve_ride(user, ride_type, int(ride_id)), None)
        except (SafetyError, R.RideNotFound, ValueError, TypeError) as e:
            reason = getattr(e, 'code', None) or 'invalid'
            rejected = (f'app sent ride {str(ride_type)[:30]}#{str(ride_id)[:20]} which was rejected '
                        f'({reason}); using the caller\'s active ride instead')
            log.warning('SOS by user %s: %s', user.id, rejected)
    try:
        rt, ride, role = resolve_ride(user, None, None)
    except Exception:   # never let ride lookup break an SOS
        log.exception('SOS active-ride lookup failed for user %s', user.id)
        db.session.rollback()
        rt = ride = role = None
    return rt, ride, role, rejected


def default_role(user):
    return 'driver' if user.user_type in ('Driver', 'Pending Driver') else 'customer'


def trigger_sos(user, data, idem_key=None, kind='sos', severity='critical'):
    """Create (or replay) an SOS incident. Returns (incident, link, recording, replayed)."""
    idem_key = (idem_key or '').strip()[:120] or None
    if idem_key:
        prior = SafetyIncident.query.filter_by(user_id=user.id, idempotency_key=idem_key).first()
        if prior:
            link = live_share.get_or_create(live_share.INCIDENT, prior.id, user.id)
            rec = Recording.query.filter_by(incident_id=prior.id, user_id=user.id).first()
            db.session.commit()
            return prior, link, rec, True

    rt, ride, role, rejected = resolve_ride_for_sos(user, data.get('ride_type'), data.get('ride_id'))
    lat = _num(data.get('lat', data.get('latitude')), -90, 90)
    lng = _num(data.get('lng', data.get('longitude')), -180, 180)
    if lat is None or lng is None:
        # Fall back to the last known position — never refuse an SOS for missing GPS.
        if user.current_latitude is not None and user.current_longitude is not None:
            lat, lng = float(user.current_latitude), float(user.current_longitude)
        else:
            lat = lng = None
    acc = _num(data.get('accuracy', data.get('accuracy_m')), 0, 100000)
    bat = _num(data.get('battery', data.get('battery_pct')), 0, 100)
    silent = str(data.get('silent', '')).lower() in ('1', 'true', 'yes', 'on')
    now = datetime.utcnow()
    inc = SafetyIncident(user_id=user.id, role=role or default_role(user), ride_type=rt,
                         ride_id=ride.id if ride is not None else None, kind=kind, status='open',
                         severity=severity, silent=silent, lat=lat, lng=lng, last_lat=lat, last_lng=lng,
                         last_location_at=now if lat is not None else None,
                         accuracy_m=int(acc) if acc is not None else None,
                         battery_pct=int(bat) if bat is not None else None,
                         idempotency_key=idem_key, created_at=now)
    if rejected:
        inc.notes = f'[{iso(now)}] system: {rejected}'
    db.session.add(inc)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        prior = SafetyIncident.query.filter_by(user_id=user.id, idempotency_key=idem_key).first()
        link = live_share.get_or_create(live_share.INCIDENT, prior.id, user.id)
        db.session.commit()
        return prior, link, None, True
    if lat is not None:
        db.session.add(SafetyIncidentLocation(incident_id=inc.id, lat=lat, lng=lng, accuracy_m=inc.accuracy_m,
                                              battery_pct=inc.battery_pct, recorded_at=now))
    link = live_share.get_or_create(live_share.INCIDENT, inc.id, user.id)
    audit('safety.sos_triggered', user, 'safety_incident', inc.id, after=inc.to_dict(),
          meta={'silent': silent, 'ride_type': rt, 'ride_id': inc.ride_id, 'kind': kind,
                'rejected_ride': rejected})

    rec = None
    st = get_settings(user.id)
    if st.auto_record_on_sos and S.flag('audio_recording'):
        from backend.services import recording_service
        rec = recording_service.create(user, rt if ride is not None else None, ride, inc.role,
                                       trigger='sos', incident_id=inc.id)

    ctx = {'name': first_name(user), 'link': live_share.url_for_token(link.token), 'incident_id': inc.id,
           'id': inc.id, 'ride_type': rt, 'ride_id': inc.ride_id, 'role': inc.role, 'silent': silent}
    contacts = TrustedContact.query.filter_by(user_id=user.id).all()
    if contacts:
        link.shared_with = [{'contact_id': c.id, 'name': c.name, 'channel': 'sms', 'reason': 'sos'}
                            for c in contacts]
        jobs.enqueue_after_commit('backend.services.safety_service.sms_contacts', user.id, 'safety.sos_triggered',
                                  [c.id for c in contacts], ctx)
    admins = admin_recipient_ids()
    if admins:
        from backend.services.notify import notify
        notify('safety.sos_triggered', admins, ctx, dedupe_key=f'sos-{inc.id}')
    ack = S.get_int('safety.sos_ack_timeout_s')
    jobs.enqueue_after_commit('backend.services.safety_jobs.escalate_incident', inc.id, delay_s=max(1, ack))
    db.session.commit()

    emit_incident('safety.sos', inc, {'share_url': live_share.url_for_token(link.token)})
    if rec is not None:
        from backend.services import recording_service
        recording_service.emit_status(rec)
    return inc, link, rec, False


def add_location(inc, data):
    lat = _num(data.get('lat', data.get('latitude')), -90, 90)
    lng = _num(data.get('lng', data.get('longitude')), -180, 180)
    if lat is None or lng is None:
        raise SafetyError('lat and lng are required.', 'bad_location')
    acc = _num(data.get('accuracy', data.get('accuracy_m')), 0, 100000)
    spd = _num(data.get('speed', data.get('speed_mps')), 0, 150)
    hdg = _num(data.get('heading'), 0, 360)
    bat = _num(data.get('battery', data.get('battery_pct')), 0, 100)
    now = datetime.utcnow()
    db.session.add(SafetyIncidentLocation(incident_id=inc.id, lat=lat, lng=lng,
                                          accuracy_m=int(acc) if acc is not None else None, speed_mps=spd,
                                          heading=int(hdg) if hdg is not None else None,
                                          battery_pct=int(bat) if bat is not None else None, recorded_at=now))
    inc.last_lat, inc.last_lng, inc.last_location_at = lat, lng, now
    if inc.lat is None:
        inc.lat, inc.lng = lat, lng
    if bat is not None:
        inc.battery_pct = int(bat)
    db.session.commit()
    payload = {'incident_id': inc.id, 'status': inc.status, 'lat': lat, 'lng': lng,
               'accuracy_m': int(acc) if acc is not None else None, 'heading': int(hdg) if hdg is not None else None,
               'speed_mps': spd, 'battery_pct': inc.battery_pct, 'at': iso(now), 'type': 'location'}
    realtime.to_admins('safety.sos_updated', payload, room='admin:sos')
    # Admin live map (GET /api/admin/live/rides → `sos`): cheap position push.
    realtime.to_admins('live.sos_location', {**payload, 'user_id': inc.user_id, 'role': inc.role,
                                             'ride_type': inc.ride_type, 'ride_id': inc.ride_id})
    return payload


def close_incident(inc, status, actor, note=None, by_user=False):
    """acknowledged | resolved | false_alarm (admin) or user cancel (false_alarm)."""
    before = inc.to_dict()
    now = datetime.utcnow()
    if status == 'acknowledged':
        if inc.status != 'open':
            raise SafetyError('Only open incidents can be acknowledged.', 'invalid_status', 409)
        inc.status, inc.acknowledged_by, inc.acknowledged_at = 'acknowledged', getattr(actor, 'id', None), now
    elif status in ('resolved', 'false_alarm'):
        if inc.status not in OPEN_STATUSES:
            raise SafetyError('This incident is already closed.', 'invalid_status', 409)
        inc.status, inc.resolved_by, inc.resolved_at = status, getattr(actor, 'id', None), now
        if not inc.acknowledged_at and not by_user:
            inc.acknowledged_by, inc.acknowledged_at = getattr(actor, 'id', None), now
        live_share.expire_for_incident(inc.id, now)
        hold = S.get_int('recording.hold_after_case_days')
        for rec in Recording.query.filter_by(incident_id=inc.id).all():
            rec.retain_until = max(rec.retain_until or now, now + timedelta(days=hold))
    else:
        raise SafetyError('Unknown status.', 'bad_status')
    if note:
        append_note(inc, actor, note)
    action = {'acknowledged': 'safety.sos_acknowledged', 'resolved': 'safety.sos_resolved',
              'false_alarm': 'safety.sos_cancelled_by_user' if by_user else 'safety.sos_false_alarm'}[status]
    audit(action, actor, 'safety_incident', inc.id, before=before, after=inc.to_dict(), meta={'note': note},
          actor_type='user' if by_user else None)
    db.session.commit()
    emit_incident('safety.sos_updated', inc, {'type': 'status', 'by_user': by_user})
    return inc


def append_note(inc, actor, note):
    who = getattr(actor, 'name', None) or f'user {getattr(actor, "id", "system")}'
    line = f"[{iso(datetime.utcnow())}] {who}: {str(note).strip()[:2000]}"
    inc.notes = f'{inc.notes}\n{line}' if inc.notes else line


# ── SMS to non-users (trusted contacts / on-call) ───────────────────────────

def _render_sms(event_key, ctx, lang='en'):
    spec = C.get(event_key)
    text = render(spec['body'][lang], ctx) or render(spec['body']['en'], ctx)
    return text if text.lower().startswith('negoride') else f'NegoRide: {text}'


def sms_contacts(owner_id, event_key, contact_ids, ctx, attempt=1):
    """Job: SMS the owner's trusted contacts. Each message is logged as a
    notification in the OWNER's inbox ("SMS sent to Mom") with one `sms`
    delivery row (status sent|failed), so support can see what went out."""
    from backend.services import twilio_client
    owner = db.session.get(AdminUser, owner_id)
    lang = 'fr' if (getattr(owner, 'preferred_language', '') or '').lower().startswith('fr') else 'en'
    text = _render_sms(event_key, ctx, lang)
    retry = []
    for cid in contact_ids:
        c = db.session.get(TrustedContact, cid)
        if not c or c.user_id != owner_id:
            continue
        n = Notification(user_id=owner_id, event_key=event_key, event_group='safety',
                         title=f'SMS sent to {c.name}' if lang == 'en' else f'SMS envoyé à {c.name}', body=text,
                         data={'recipient': 'trusted_contact', 'contact_id': c.id, 'contact_name': c.name,
                               'to': mask_phone(c.phone_e164), 'incident_id': ctx.get('incident_id'),
                               'ride_type': ctx.get('ride_type'), 'ride_id': ctx.get('ride_id'),
                               'event': event_key, 'outbound': True},
                         is_critical=event_key == 'safety.sos_triggered')
        db.session.add(n)
        db.session.flush()
        d = NotificationDelivery(notification_id=n.id, channel='sms', attempts=attempt)
        try:
            d.provider_message_id = twilio_client.send_sms(c.phone_e164, text)
            d.status, d.sent_at = 'sent', datetime.utcnow()
        except twilio_client.TwilioError as exc:
            d.status, d.error, d.failed_at = 'failed', str(exc)[:1000], datetime.utcnow()
            transient = exc.code != 'not_configured' and not (exc.status and 400 <= exc.status < 500)
            if transient:
                retry.append(cid)
        except Exception as exc:  # network
            d.status, d.error, d.failed_at = 'failed', str(exc)[:1000], datetime.utcnow()
            retry.append(cid)
        # Never leave these queued/retrying: the generic dispatcher would resend
        # them to the OWNER's phone. Retries are scheduled here instead.
        db.session.add(d)
        db.session.commit()
    if retry and attempt < 3:
        jobs.enqueue_in(30 * attempt, 'backend.services.safety_service.sms_contacts', owner_id, event_key, retry,
                        ctx, attempt + 1)
    return len(contact_ids)


def sms_raw(phone, text):
    from backend.services import twilio_client
    try:
        return twilio_client.send_sms(phone, text)
    except Exception as exc:
        log.warning('on-call SMS to %s failed: %s', mask_phone(phone), exc)
        return None


def call_alert(phone, text):
    """Voice call that reads the alert (Twilio Calls API). Simulated when Twilio
    is not configured."""
    from backend.services import twilio_client
    if not twilio_client.is_configured():
        CALLS.append({'to': phone, 'text': text, 'simulated': True})
        log.warning('[call:not-configured] to=%s text=%s', mask_phone(phone), text)
        return None
    import os
    from xml.sax.saxutils import escape
    sid, _ = twilio_client._creds()
    frm = os.getenv('TWILIO_VOICE_FROM') or os.getenv('TWILIO_FROM_NUMBER', '')
    twiml = f'<Response><Say voice="alice">{escape(text)}</Say><Pause length="1"/><Say>{escape(text)}</Say></Response>'
    try:
        res = twilio_client._req('POST', f'{twilio_client.API}/Accounts/{sid}/Calls.json',
                                 data={'To': phone, 'From': frm, 'Twiml': twiml})
        CALLS.append({'to': phone, 'sid': res.get('sid')})
        return res.get('sid')
    except Exception as exc:
        log.warning('on-call voice alert to %s failed: %s', mask_phone(phone), exc)
        return None


# ── help contacts ───────────────────────────────────────────────────────────

def help_contact_dict(h):
    return {'id': h.id, 'name': h.name, 'phone': h.phone or None, 'email': h.email, 'url': h.url,
            'category': h.category, 'province': h.province, 'description': h.description,
            'is_emergency': bool(h.is_emergency), 'sort_order': h.sort_order}


def support_contact():
    return {'name': 'NegoRide Safety & Support', 'phone': S.get('safety.support_phone') or None,
            'email': S.get('safety.support_email') or None, 'chat_route': 'support_chat', 'category': 'support'}


def help_contacts(province=None):
    province = (province or '').upper()[:2] or None
    q = HelpContact.query.filter_by(is_active=True)
    if province:
        q = q.filter((HelpContact.province.is_(None)) | (HelpContact.province == province))
    else:
        q = q.filter(HelpContact.province.is_(None))
    out = []
    sup = support_contact()
    for h in q.order_by(HelpContact.sort_order, HelpContact.id).all():
        d = help_contact_dict(h)
        if h.category == 'support':
            d['phone'] = d['phone'] or sup['phone']
            d['email'] = d['email'] or sup['email']
            d['chat_route'] = sup['chat_route']
        out.append(d)
    return out


def province_for(user, ride_type=None, ride=None):
    p = getattr(ride, 'pickup_province', None) if ride is not None else None
    return (p or getattr(user, 'province', None) or '').upper()[:2] or None


# ── ride PIN brute-force lock (spec §8.4) ───────────────────────────────────
#
# Called from trip_state_machine._check_guards. Failures are written on an
# INDEPENDENT connection: the failing transition raises and its transaction is
# rolled back, but the attempt must still count.

def _pin_window():
    return (max(1, S.get_int('safety.pin_max_attempts', 5) or 5),
            max(60, S.get_int('safety.pin_lock_window_s', 600) or 600))


def _pin_failures(conn, ride_type, ride_id, since):
    from sqlalchemy import text
    rows = conn.execute(text('SELECT created_at FROM ride_pin_failures WHERE ride_type=:t AND ride_id=:i '
                             'AND created_at >= :s ORDER BY created_at DESC, id DESC'),
                        {'t': ride_type, 'i': int(ride_id), 's': since}).fetchall()
    return [r[0] for r in rows]


def _pin_state(times, now, max_attempts, window):
    if len(times) < max_attempts:
        return False, 0
    # Locked until the max_attempts-th most recent failure leaves the window.
    unlock = times[max_attempts - 1] + timedelta(seconds=window)
    retry = int((unlock - now).total_seconds()) + 1
    return retry > 0, max(0, retry)


def pin_lock_status(ride_type, ride_id, now=None):
    """(locked, retry_after_s, recent_failures)."""
    now = now or datetime.utcnow()
    max_attempts, window = _pin_window()
    with db.engine.connect() as conn:
        times = _pin_failures(conn, ride_type, ride_id, now - timedelta(seconds=window))
    locked, retry = _pin_state(times, now, max_attempts, window)
    return locked, retry, len(times)


def record_pin_failure(ride_type, ride, actor_id=None, now=None):
    """Count a wrong PIN. Returns (failures_in_window, locked, retry_after_s,
    attempts_left). The attempt that reaches the limit triggers the audit +
    admin alert job (runs outside the rolled-back transition)."""
    from sqlalchemy import text
    now = now or datetime.utcnow()
    max_attempts, window = _pin_window()
    actor_id = actor_id or R.driver_id(ride_type, ride)
    with db.engine.begin() as conn:
        conn.execute(text('INSERT INTO ride_pin_failures (ride_type, ride_id, actor_id, created_at) '
                          'VALUES (:t, :i, :a, :c)'), {'t': ride_type, 'i': int(ride.id), 'a': actor_id, 'c': now})
        times = _pin_failures(conn, ride_type, ride.id, now - timedelta(seconds=window))
    locked, retry = _pin_state(times, now, max_attempts, window)
    if len(times) == max_attempts:
        jobs.enqueue('backend.services.safety_service.pin_locked_job', ride_type, int(ride.id), actor_id,
                     len(times), retry)
    return len(times), locked, retry, max(0, max_attempts - len(times))


def pin_locked_job(ride_type, ride_id, actor_id, attempts, retry_after_s):
    """Job: audit + admin alert (socket `alert` + safety notification to ops)."""
    actor = db.session.get(AdminUser, actor_id) if actor_id else None
    audit('ride.pin_locked', actor, ride_type, ride_id,
          meta={'attempts': attempts, 'retry_after_s': retry_after_s, 'actor_id': actor_id},
          actor_type='driver' if actor else 'system')
    ctx = {'ride_type': ride_type, 'ride_id': ride_id, 'id': ride_id, 'attempts': attempts,
           'name': first_name(actor) if actor else 'unknown', 'driver_id': actor_id,
           'retry_after_s': retry_after_s}
    admins = admin_recipient_ids()
    if admins:
        from backend.services.notify import notify
        notify('safety.pin_locked', admins, ctx, dedupe_key=f'pinlock-{ride_type}-{ride_id}-{attempts}')
    db.session.commit()
    realtime.to_admins('alert', {'kind': 'pin_locked', 'ride_type': ride_type, 'ride_id': ride_id,
                                 'driver_id': actor_id, 'attempts': attempts, 'retry_after_s': retry_after_s,
                                 'message': f'Ride PIN locked on {ride_type} #{ride_id} after {attempts} wrong attempts'})
    realtime.to_admins('alert', {'kind': 'pin_locked', 'ride_type': ride_type, 'ride_id': ride_id,
                                 'driver_id': actor_id, 'attempts': attempts}, room='admin:sos')
    return True


# ── disputes (retention of evidence, spec §10.1) ────────────────────────────

def mark_dispute_resolved(ride_type, ride_id, at=None, actor=None):
    """Mark a ride dispute resolved (sets `dispute_resolved_at`). Evidence
    (recordings, breadcrumbs) is then kept `recording.hold_after_case_days`
    more days and purged by retention_cleanup. Caller commits.

    Call it when an admin resolves/closes a support ticket of type `dispute`
    (routes/support.py, admin resolution path). Returns True when changed."""
    try:
        ride = R.load(ride_type, ride_id)
    except (R.RideNotFound, Exception):
        return False
    if not hasattr(ride, 'dispute_resolved_at') or getattr(ride, 'disputed_at', None) is None:
        return False
    if ride.dispute_resolved_at is not None:
        return False
    ride.dispute_resolved_at = at or datetime.utcnow()
    audit('ride.dispute_resolved', actor, R.normalize_type(ride_type), ride.id,
          meta={'dispute_resolved_at': iso(ride.dispute_resolved_at)})
    return True


# ── production readiness (consumed by GET /api/admin/readiness) ─────────────

def readiness_checks():
    """Safety items for the admin readiness page. Each item:
    {key, area:'safety', level: ok|warning|critical, message}."""
    import os
    from backend.services import twilio_client
    prod = os.getenv('FLASK_ENV', '').lower() == 'production'
    items = []

    def add(key, level, message):
        items.append({'key': key, 'area': 'safety', 'level': level, 'message': message})

    phones = oncall_phones()
    add('safety.oncall_phones', 'ok' if phones else 'critical',
        f'{len(phones)} on-call phone(s) configured for SOS escalation.' if phones else
        'No on-call phones: an unacknowledged SOS cannot be escalated by SMS/voice. '
        'Set Settings → safety.oncall_phones (E.164, comma-separated).')
    add('safety.support_phone', 'ok' if S.get('safety.support_phone') else 'warning',
        'Support phone configured.' if S.get('safety.support_phone') else
        'Support phone empty: the Safety Toolkit cannot offer a call to NegoRide support.')
    tw = twilio_client.is_configured()
    add('safety.twilio', 'ok' if tw else ('critical' if prod else 'warning'),
        'Twilio configured (SOS SMS to trusted contacts / on-call).' if tw else
        'Twilio is not configured: SOS SMS and voice escalation are only simulated.')
    from backend import jobs
    red = jobs.get_redis() is not None
    add('safety.redis', 'ok' if red else ('critical' if prod else 'warning'),
        'Redis available (latest positions, rate limits, breadcrumb buffer).' if red else
        'REDIS_URL absent/unreachable: latest driver positions, public-tracking rate limits and ETA throttles '
        'fall back to per-process memory (wrong with several workers).')
    return items
