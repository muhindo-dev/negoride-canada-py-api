"""Live trip sharing (spec §9.1, §22): share links + the public tracking payload.

A link is a random 32-char token on `ride_share_links`. Two kinds:
  • ride links   ride_type ∈ rides.RIDE_TYPES — the trip (driver position, ETA …)
  • SOS links    ride_type == 'incident', ride_id = safety_incidents.id — the
                 person in distress (their high-frequency SOS positions, plus the
                 ride details when the SOS was raised during a ride)

Expiry: ride links expire `tracking.share_expiry_after_end_min` after the trip
ends (set by the after-hook in safety_detection), capped at
`tracking.share_max_hours` while the trip is running. SOS links expire 30 min
after the incident is closed (capped at `safety.incident_share_hours`).

The public payload NEVER contains phone numbers, emails, payment or fare data.
"""
import math
import os
import secrets
from datetime import datetime, timedelta

from backend.models import db
from backend.models.safety import RideLocation, RideShareLink, SafetyIncident, SafetyIncidentLocation
from backend.models.user import AdminUser
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services import trip_state_machine as TSM

INCIDENT = 'incident'

# Stages during which a party may share the trip ("CONFIRMED → COMPLETED").
SHAREABLE_STAGES = {
    'carhire': ('CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS'),
    'scheduled': ('CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS'),
    'rideshare_trip': ('PUBLISHED', 'BOARDING', 'IN_PROGRESS'),
    'rideshare_booking': ('CONFIRMED', 'DRIVER_ARRIVED', 'CHECKED_IN', 'RIDING'),
}
ENDED_STAGES = ('COMPLETED', 'CLOSED', 'DROPPED_OFF')
PRE_PICKUP = ('CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'PUBLISHED', 'BOARDING')


def base_url():
    return (os.getenv('PUBLIC_WEB_BASE_URL') or S.get('company.website') or 'https://negoride.ca').rstrip('/')


def url_for_token(token):
    return f'{base_url()}/t/{token}'


def new_token():
    return secrets.token_urlsafe(24)[:32]  # 32 url-safe chars (~190 bits)


def ride_ended(ride_type, stage):
    return stage in ENDED_STAGES or TSM.is_terminal(ride_type, stage)


def link_is_live(link, now=None):
    now = now or datetime.utcnow()
    return link is not None and link.revoked_at is None and (link.expires_at is None or link.expires_at > now)


def link_dict(link):
    return {'token': link.token, 'url': url_for_token(link.token), 'ride_type': link.ride_type,
            'ride_id': link.ride_id, 'expires_at': _iso(link.expires_at), 'created_at': _iso(link.created_at),
            'revoked_at': _iso(link.revoked_at), 'view_count': link.view_count or 0,
            'shared_with': link.shared_with or []}


def _iso(v):
    return v.strftime('%Y-%m-%dT%H:%M:%SZ') if v else None


def can_share(ride_type, ride):
    return R.current_stage(ride_type, ride) in SHAREABLE_STAGES.get(ride_type, ())


def get_or_create(ride_type, ride_id, user_id, shared_with=None):
    """Reuse the user's live link for this ride or create one (caller commits)."""
    now = datetime.utcnow()
    link = (RideShareLink.query.filter_by(ride_type=ride_type, ride_id=int(ride_id), user_id=int(user_id))
            .filter(RideShareLink.revoked_at.is_(None))
            .filter((RideShareLink.expires_at.is_(None)) | (RideShareLink.expires_at > now))
            .order_by(RideShareLink.id.desc()).first())
    if link is None:
        if ride_type == INCIDENT:
            cap = now + timedelta(hours=S.get_int('safety.incident_share_hours', 24) or 24)
        else:
            cap = now + timedelta(hours=S.get_int('tracking.share_max_hours', 12) or 12)
        link = RideShareLink(token=new_token(), ride_type=ride_type, ride_id=int(ride_id), user_id=int(user_id),
                             shared_with=[], created_at=now, expires_at=cap)
        db.session.add(link)
        db.session.flush()
    if shared_with:
        existing = list(link.shared_with or [])
        seen = {(e.get('contact_id'), e.get('channel')) for e in existing if isinstance(e, dict)}
        for entry in shared_with:
            if (entry.get('contact_id'), entry.get('channel')) not in seen:
                existing.append(entry)
        link.shared_with = existing
    return link


def expire_for_ride(ride_type, ride_id, ended_at=None):
    """Trip ended: every live link for it expires N minutes later."""
    ended_at = ended_at or datetime.utcnow()
    until = ended_at + timedelta(minutes=S.get_int('tracking.share_expiry_after_end_min'))
    n = 0
    for link in RideShareLink.query.filter_by(ride_type=ride_type, ride_id=int(ride_id)).filter(
            RideShareLink.revoked_at.is_(None)).all():
        if link.expires_at is None or link.expires_at > until:
            link.expires_at = until
            n += 1
    return n


def expire_for_incident(incident_id, closed_at=None):
    closed_at = closed_at or datetime.utcnow()
    return expire_for_ride(INCIDENT, incident_id, closed_at)


# ── public payload ──────────────────────────────────────────────────────────

def _f(v):
    return float(v) if v is not None else None


def _latest_driver_point(ride_type, ride, driver_id):
    if not driver_id:
        return None
    ids = [ride.id]
    types = [ride_type]
    if ride_type == 'rideshare_booking':      # the driver streams against the trip
        types.append('rideshare_trip')
        ids.append(ride.trip_id)
    row = (RideLocation.query.filter(RideLocation.user_id == driver_id, RideLocation.ride_type.in_(types),
                                     RideLocation.ride_id.in_(ids))
           .order_by(RideLocation.recorded_at.desc(), RideLocation.id.desc()).first())
    if row:
        return {'lat': _f(row.lat), 'lng': _f(row.lng), 'heading': row.heading,
                'speed_mps': _f(row.speed_mps), 'at': _iso(row.recorded_at)}
    d = db.session.get(AdminUser, driver_id)
    if d and d.current_latitude is not None and d.current_longitude is not None:
        return {'lat': _f(d.current_latitude), 'lng': _f(d.current_longitude), 'heading': None,
                'speed_mps': None, 'at': _iso(d.last_location_update)}
    return None


def breadcrumbs(ride_type, ride, user_id, limit=300, since=None):
    types, ids = [ride_type], [ride.id]
    if ride_type == 'rideshare_booking':
        types.append('rideshare_trip')
        ids.append(ride.trip_id)
    q = RideLocation.query.filter(RideLocation.user_id == user_id, RideLocation.ride_type.in_(types),
                                  RideLocation.ride_id.in_(ids))
    if since:
        q = q.filter(RideLocation.recorded_at >= since)
    rows = q.order_by(RideLocation.recorded_at.desc(), RideLocation.id.desc()).limit(limit).all()
    rows.reverse()
    return rows


def encode_polyline(points):
    """Google encoded polyline (precision 5)."""
    out, plat, plng = [], 0, 0
    for lat, lng in points:
        ilat, ilng = int(round(lat * 1e5)), int(round(lng * 1e5))
        for v in (ilat - plat, ilng - plng):
            v = ~(v << 1) if v < 0 else (v << 1)
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plng = ilat, ilng
    return ''.join(out)


def eta_for(ride_type, ride, stage, driver_pt):
    now = datetime.utcnow()
    secs = getattr(ride, 'eta_seconds', None)
    upd = getattr(ride, 'eta_updated_at', None)
    if secs and upd:
        arrives = upd + timedelta(seconds=int(secs))
        remaining = max(0, (arrives - now).total_seconds())
        return {'minutes': int(math.ceil(remaining / 60)), 'arrives_at': _iso(arrives),
                'target': getattr(ride, 'eta_target', None) or ('pickup' if stage in PRE_PICKUP else 'dropoff'),
                'source': 'live'}
    if not driver_pt:
        return None
    target = 'pickup' if stage in PRE_PICKUP else 'dropoff'
    dest = R.pickup_point(ride_type, ride) if target == 'pickup' else R.dropoff_point(ride_type, ride)
    if not dest:
        return None
    dist = R.haversine_m((driver_pt['lat'], driver_pt['lng']), dest) or 0
    seconds = dist * 1.35 / 8.33          # road factor, ~30 km/h city average
    return {'minutes': int(math.ceil(seconds / 60)), 'arrives_at': _iso(now + timedelta(seconds=seconds)),
            'target': target, 'source': 'estimate'}


def _public_driver(driver_id):
    card = R.user_card(driver_id) if driver_id else None
    if not card:
        return None
    return {'first_name': card['first_name'], 'avatar': card['avatar'], 'rating': card['rating']}


def _public_vehicle(driver_id):
    d = db.session.get(AdminUser, driver_id) if driver_id else None
    v = R.vehicle_card(d) if d else None
    if not v:
        return None
    return {'make': v.get('make'), 'model': v.get('model'), 'color': v.get('color'), 'plate': v.get('plate')}


def ride_public(ride_type, ride):
    stage = R.current_stage(ride_type, ride)
    drv = R.driver_id(ride_type, ride)
    pickup_addr, drop_addr = R.addresses(ride_type, ride)
    pp, dp = R.pickup_point(ride_type, ride), R.dropoff_point(ride_type, ride)
    driver_pt = _latest_driver_point(ride_type, ride, drv)
    ended = ride_ended(ride_type, stage)
    crumbs = breadcrumbs(ride_type, ride, drv, limit=300) if drv else []
    pts = [(float(c.lat), float(c.lng)) for c in crumbs]
    return {
        'status': _status_label(stage), 'stage': stage,
        'driver': _public_driver(drv), 'vehicle': _public_vehicle(drv),
        'pickup': {'address': pickup_addr, 'lat': pp[0] if pp else None, 'lng': pp[1] if pp else None},
        'dropoff': {'address': drop_addr, 'lat': dp[0] if dp else None, 'lng': dp[1] if dp else None},
        'driver_location': driver_pt,
        'breadcrumbs': [[round(a, 6), round(b, 6)] for a, b in pts],
        'polyline': encode_polyline(pts) if pts else '',
        'eta': None if ended else eta_for(ride_type, ride, stage, driver_pt),
        'trip_ended': ended,
    }


def _status_label(stage):
    return {
        'CONFIRMED': 'Ride confirmed', 'DRIVER_EN_ROUTE': 'Driver on the way', 'DRIVER_ARRIVING': 'Driver arriving',
        'DRIVER_ARRIVED': 'Driver has arrived', 'IN_PROGRESS': 'On trip', 'RIDING': 'On trip',
        'CHECKED_IN': 'Boarded', 'BOARDING': 'Boarding', 'PUBLISHED': 'Scheduled',
        'COMPLETED': 'Trip completed', 'DROPPED_OFF': 'Trip completed', 'CLOSED': 'Trip completed',
    }.get(stage, 'Trip ended' if stage else 'Unknown')


_STATUS_FR = {
    'Ride confirmed': 'Course confirmée', 'Driver on the way': 'Chauffeur en route',
    'Driver arriving': 'Chauffeur presque arrivé', 'Driver has arrived': 'Le chauffeur est arrivé',
    'On trip': 'En trajet', 'Boarded': 'À bord', 'Boarding': 'Embarquement', 'Scheduled': 'Prévu',
    'Trip completed': 'Trajet terminé', 'Trip ended': 'Trajet terminé', 'Unknown': 'Inconnu',
    'SOS active': 'SOS actif', 'SOS closed': 'SOS fermé',
}


def _with_status_text(out):
    """`status_text` in the viewer's language (?lang=fr) for the public page."""
    if out is None:
        return None
    lang = 'en'
    try:
        from flask import has_request_context, request
        if has_request_context():
            lang = (request.args.get('lang') or 'en')[:2].lower()
    except Exception:
        pass
    label = out.get('status') or ''
    out['status_text'] = _STATUS_FR.get(label, label) if lang == 'fr' else label
    return out


def public_payload(link):
    return _with_status_text(_public_payload(link))


def _public_payload(link):
    """Everything the public tracking page may show. No phones, no payments."""
    out = {'kind': 'sos' if link.ride_type == INCIDENT else 'trip', 'expires_at': _iso(link.expires_at),
           'generated_at': _iso(datetime.utcnow()), 'refresh_s': 5}
    if link.ride_type == INCIDENT:
        inc = db.session.get(SafetyIncident, link.ride_id)
        if not inc:
            return None
        owner = R.user_card(inc.user_id)
        locs = (SafetyIncidentLocation.query.filter_by(incident_id=inc.id)
                .order_by(SafetyIncidentLocation.recorded_at.desc(), SafetyIncidentLocation.id.desc())
                .limit(300).all())
        locs.reverse()
        pts = [(float(x.lat), float(x.lng)) for x in locs]
        last = locs[-1] if locs else None
        out.update({
            'status': 'SOS active' if inc.status in ('open', 'acknowledged') else 'SOS closed',
            'stage': 'SOS', 'sos_active': inc.status in ('open', 'acknowledged'),
            'person': {'first_name': owner['first_name'] if owner else None},
            'person_location': ({'lat': float(last.lat), 'lng': float(last.lng), 'heading': last.heading,
                                 'at': _iso(last.recorded_at)} if last else
                                ({'lat': _f(inc.lat), 'lng': _f(inc.lng), 'heading': None, 'at': _iso(inc.created_at)}
                                 if inc.lat is not None else None)),
            'breadcrumbs': [[round(a, 6), round(b, 6)] for a, b in pts],
            'polyline': encode_polyline(pts) if pts else '',
            'trip_ended': inc.status not in ('open', 'acknowledged'),
            'ride': None,
        })
        if inc.ride_type in R.RIDE_TYPES and inc.ride_id:
            try:
                ride = R.load(inc.ride_type, inc.ride_id)
                rp = ride_public(inc.ride_type, ride)
                rp.pop('eta', None)
                out['ride'] = rp
            except R.RideNotFound:
                pass
        return out
    try:
        ride = R.load(link.ride_type, link.ride_id)
    except R.RideNotFound:
        return None
    out.update(ride_public(link.ride_type, ride))
    return out
