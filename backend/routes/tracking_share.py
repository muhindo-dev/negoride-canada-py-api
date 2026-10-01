"""Live trip sharing + public tracking (spec §9, §22).

    GET    /api/rides/<type>/<id>/share                my live links for the ride
    POST   /api/rides/<type>/<id>/share                parties, CONFIRMED → before COMPLETED
                                                       {contact_ids?: [..]} → SMS to those trusted contacts
    DELETE /api/rides/<type>/<id>/share/<token>        revoke (link owner)
    GET    /api/public/track/<token>                   NO auth, rate-limited (per IP + per token), no-store
    GET    /t/<token>                                  302 → PUBLIC_WEB_BASE_URL/t/<token> when that is another
                                                       host; otherwise the minimal fallback page (noindex)

Client IP: `request.remote_addr` only. Behind nginx, backend/app.py wraps the
app in werkzeug ProxyFix (TRUSTED_PROXY_COUNT, default 1) so remote_addr is the
real client and a spoofed X-Forwarded-For can't dodge the limit.
"""
import json
import os
import threading
import time
from datetime import datetime

from flask import Blueprint, Response, redirect, request

from backend import jobs
from backend.models import db
from backend.models.safety import RideShareLink, TrustedContact
from backend.services import live_share
from backend.services import rides as R
from backend.services import settings_service as S
from backend.services.audit import audit
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import error_response, success_response

tracking_share_bp = Blueprint('tracking_share', __name__)

_rl_lock = threading.Lock()
_rl = {}


def rate_ok(ip, limit=None, scope='ip'):
    limit = limit or S.get_int('tracking.public_rate_limit_per_min', 60) or 60
    minute = int(time.time() // 60)
    ip = f'{scope}:{ip}'
    r = jobs.get_redis()
    if r is not None:
        try:
            key = f'negoride:rl:track:{ip}:{minute}'
            n = r.incr(key)
            if n == 1:
                r.expire(key, 70)
            return n <= limit
        except Exception:
            pass
    with _rl_lock:
        for k in [k for k in _rl if k[1] < minute]:
            _rl.pop(k, None)
        n = _rl.get((ip, minute), 0) + 1
        _rl[(ip, minute)] = n
    return n <= limit


def _client_ip():
    # ProxyFix (app.py) already resolved the trusted X-Forwarded-For hop.
    return (request.remote_addr or '').strip() or '?'


def _limited(token):
    """None when allowed, else the 429 response. Per IP and per token (a
    leaked link hammered from many IPs is capped too)."""
    ok = rate_ok(_client_ip())
    if ok:
        per_token = S.get_int('tracking.public_rate_limit_per_token_per_min', 120) or 120
        ok = rate_ok((token or '')[:64], limit=per_token, scope='tok')
    if ok:
        return None
    resp, status = error_response('Too many requests. Try again in a minute.',
                                  data={'error_code': 'rate_limited', 'retry_after': 60}, status_code=429)
    resp.headers['Retry-After'] = '60'
    return _nocache(resp), status


def _load_party(user, ride_type, ride_id):
    try:
        rt = R.normalize_type(ride_type)
        ride = R.load(rt, ride_id)
    except R.RideNotFound:
        return None, None, None, error_response('Ride not found.', data={'error_code': 'not_found'},
                                                status_code=404)
    role = R.role_of(user, rt, ride)
    if role not in ('customer', 'driver'):
        return None, None, None, error_response('You are not part of this ride.', data={'error_code': 'forbidden'},
                                                status_code=403)
    return rt, ride, role, None


@tracking_share_bp.route('/api/rides/<ride_type>/<int:ride_id>/share', methods=['GET'])
@jwt_required_with_user
def list_links(user, ride_type, ride_id):
    rt, ride, role, err = _load_party(user, ride_type, ride_id)
    if err:
        return err
    links = RideShareLink.query.filter_by(ride_type=rt, ride_id=ride.id, user_id=user.id).all()
    return success_response('Success', [live_share.link_dict(l) for l in links if live_share.link_is_live(l)])


@tracking_share_bp.route('/api/rides/<ride_type>/<int:ride_id>/share', methods=['POST'])
@jwt_required_with_user
def create_link(user, ride_type, ride_id):
    if not S.flag('live_share'):
        return error_response('Trip sharing is currently unavailable.', data={'error_code': 'feature_disabled'},
                              status_code=403)
    rt, ride, role, err = _load_party(user, ride_type, ride_id)
    if err:
        return err
    if not live_share.can_share(rt, ride):
        return error_response('You can share a trip once it is confirmed and until it ends.',
                              data={'error_code': 'share_not_available', 'stage': R.current_stage(rt, ride)},
                              status_code=409)
    data = request.get_json(silent=True) or {}
    ids = [int(x) for x in (data.get('contact_ids') or []) if str(x).isdigit()]
    contacts = TrustedContact.query.filter(TrustedContact.user_id == user.id,
                                           TrustedContact.id.in_(ids)).all() if ids else []
    if ids and len(contacts) != len(set(ids)):
        return error_response('Unknown trusted contact.', data={'error_code': 'bad_contact'}, status_code=422)
    link = live_share.get_or_create(rt, ride.id, user.id,
                                    shared_with=[{'contact_id': c.id, 'name': c.name, 'channel': 'sms',
                                                  'reason': 'manual'} for c in contacts])
    url = live_share.url_for_token(link.token)
    if contacts:
        from backend.services import safety_service as SS
        jobs.enqueue_after_commit('backend.services.safety_service.sms_contacts', user.id, 'safety.trip_shared',
                                  [c.id for c in contacts],
                                  {'name': SS.first_name(user), 'link': url, 'ride_type': rt, 'ride_id': ride.id})
    audit('safety.trip_shared', user, 'ride_share_link', link.id,
          meta={'ride_type': rt, 'ride_id': ride.id, 'contacts': len(contacts)}, actor_type='user')
    db.session.commit()
    return success_response('Share link ready.', {**live_share.link_dict(link), 'token': link.token, 'url': url,
                                                  'expires_at': live_share._iso(link.expires_at),
                                                  'sms_sent_to': [c.id for c in contacts]}, status_code=201)


@tracking_share_bp.route('/api/rides/<ride_type>/<int:ride_id>/share/<token>', methods=['DELETE'])
@jwt_required_with_user
def revoke_link(user, ride_type, ride_id, token):
    try:
        rt = R.normalize_type(ride_type)
    except R.RideNotFound:
        return error_response('Ride not found.', data={'error_code': 'not_found'}, status_code=404)
    link = RideShareLink.query.filter_by(token=token, ride_type=rt, ride_id=ride_id, user_id=user.id).first()
    if not link:
        return error_response('Share link not found.', data={'error_code': 'not_found'}, status_code=404)
    if link.revoked_at is None:
        link.revoked_at = datetime.utcnow()
        audit('safety.trip_share_revoked', user, 'ride_share_link', link.id, actor_type='user')
        db.session.commit()
    return success_response('Sharing stopped.', live_share.link_dict(link))


def _find_live(token):
    if not token or len(token) > 64:
        return None
    link = RideShareLink.query.filter_by(token=token).first()
    return link if live_share.link_is_live(link) else None


def _nocache(resp):
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    return resp


@tracking_share_bp.route('/api/public/track/<token>', methods=['GET'])
def public_track(token):
    limited = _limited(token)
    if limited:
        return limited
    link = _find_live(token)
    payload = live_share.public_payload(link) if link else None
    if not payload:
        resp, status = error_response('This tracking link has expired or was turned off.',
                                      data={'error_code': 'link_expired'}, status_code=404)
        return _nocache(resp), status
    try:
        RideShareLink.query.filter_by(id=link.id).update(
            {RideShareLink.view_count: RideShareLink.view_count + 1, RideShareLink.last_viewed_at: datetime.utcnow()},
            synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
    resp, status = success_response('Success', payload)
    return _nocache(resp), status


# ── public HTML page ────────────────────────────────────────────────────────

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<title>NegoRide live trip</title>
__MAPHEAD__
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171f;--muted:#5b6475;--brand:#0b7a53;--sos:#c62828}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b22;--ink:#eef0f4;--muted:#9aa3b2}}
*{box-sizing:border-box}html,body{margin:0;height:100%;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
#map{position:fixed;inset:0 0 auto 0;height:58vh}
.sheet{position:fixed;left:0;right:0;bottom:0;min-height:42vh;background:var(--card);border-radius:16px 16px 0 0;padding:16px;box-shadow:0 -4px 20px rgba(0,0,0,.12);overflow:auto}
.status{font-size:20px;font-weight:700;margin:0 0 4px}.eta{color:var(--brand);font-weight:600}
.row{display:flex;gap:12px;align-items:center;margin:12px 0}.av{width:48px;height:48px;border-radius:50%;background:#ccd;object-fit:cover}
.plate{display:inline-block;border:2px solid var(--ink);border-radius:6px;padding:2px 8px;font-weight:800;letter-spacing:1px}
.muted{color:var(--muted);font-size:14px}.addr{margin:6px 0;font-size:14px}.sos{background:var(--sos);color:#fff;padding:8px 12px;border-radius:8px;font-weight:700}
.center{display:flex;align-items:center;justify-content:center;height:100%;padding:24px;text-align:center}
</style></head><body>
<div id="map"></div>
<div class="sheet" id="sheet"><p class="muted">Loading live trip…</p></div>
<script>
const TOKEN = __TOKEN__;
const LANG = (new URLSearchParams(location.search).get('lang') || (navigator.language||'en')).slice(0,2);
const API = '/api/public/track/' + encodeURIComponent(TOKEN) + '?lang=' + encodeURIComponent(LANG);
const GMAPS = __GMAPS__;
let map, car, line, pickupM, dropM, fitted = false;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function initMap(lat,lng){
  if(GMAPS){map=new google.maps.Map(document.getElementById('map'),{center:{lat,lng},zoom:14,disableDefaultUI:true});}
  else{map=L.map('map',{zoomControl:false}).setView([lat,lng],14);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map);}
}
function marker(m,lat,lng,color){
  if(GMAPS){if(!m)m=new google.maps.Marker({map,position:{lat,lng},icon:{path:google.maps.SymbolPath.CIRCLE,scale:8,fillColor:color,fillOpacity:1,strokeColor:'#fff',strokeWeight:2}});else m.setPosition({lat,lng});return m;}
  if(!m)m=L.circleMarker([lat,lng],{radius:8,color:'#fff',weight:2,fillColor:color,fillOpacity:1}).addTo(map);else m.setLatLng([lat,lng]);return m;
}
function path(pts){
  if(!pts.length)return;
  if(GMAPS){const p=pts.map(x=>({lat:x[0],lng:x[1]}));if(!line)line=new google.maps.Polyline({map,path:p,strokeColor:'#0b7a53',strokeWeight:4});else line.setPath(p);}
  else{if(!line)line=L.polyline(pts,{color:'#0b7a53',weight:4}).addTo(map);else line.setLatLngs(pts);}
}
function render(d){
  const loc = d.driver_location || d.person_location;
  const anchor = loc || (d.pickup && d.pickup.lat!=null ? d.pickup : null);
  if(anchor && !map) initMap(anchor.lat, anchor.lng);
  if(map){
    if(d.pickup && d.pickup.lat!=null) pickupM = marker(pickupM,d.pickup.lat,d.pickup.lng,'#1565c0');
    if(d.dropoff && d.dropoff.lat!=null) dropM = marker(dropM,d.dropoff.lat,d.dropoff.lng,'#6a1b9a');
    if(loc){ car = marker(car,loc.lat,loc.lng,d.kind==='sos'?'#c62828':'#0b7a53');
      if(!fitted){ GMAPS?map.setCenter({lat:loc.lat,lng:loc.lng}):map.setView([loc.lat,loc.lng],15); fitted=true; } }
    path(d.breadcrumbs||[]);
  }
  const r = d.kind==='sos' ? (d.ride||{}) : d;
  const drv = r.driver||{}, v = r.vehicle||{};
  let h = '';
  if(d.kind==='sos') h += '<p class="sos">'+(d.sos_active?'SOS active':'SOS closed')+' · '+esc((d.person||{}).first_name||'')+'</p>';
  h += '<p class="status">'+esc(d.kind==='sos'?(r.status_text||r.status||''):(d.status_text||d.status))+'</p>';
  if(d.eta && !d.trip_ended) h += '<p class="eta">'+esc(d.eta.text || (d.eta.minutes+' min'))+(d.eta.arrives_at?' · '+esc(new Date(d.eta.arrives_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})):'')+'</p>';
  if(d.trip_ended) h += '<p class="muted">This trip has ended.</p>';
  if(drv.first_name) h += '<div class="row">'+(drv.avatar?'<img class="av" src="'+esc(drv.avatar)+'" alt="">':'<div class="av"></div>')+
     '<div><div><b>'+esc(drv.first_name)+'</b>'+(drv.rating?' · ★ '+esc(Number(drv.rating).toFixed(1)):'')+'</div>'+
     '<div class="muted">'+esc([v.color,v.make,v.model].filter(Boolean).join(' '))+'</div></div>'+
     (v.plate?'<span class="plate" style="margin-left:auto">'+esc(v.plate)+'</span>':'')+'</div>';
  if(r.pickup && r.pickup.address) h += '<p class="addr"><span class="muted">From</span> '+esc(r.pickup.address)+'</p>';
  if(r.dropoff && r.dropoff.address) h += '<p class="addr"><span class="muted">To</span> '+esc(r.dropoff.address)+'</p>';
  if(loc && loc.at) h += '<p class="muted">Updated '+esc(new Date(loc.at).toLocaleTimeString())+'</p>';
  h += '<p class="muted">In an emergency call 911.</p>';
  document.getElementById('sheet').innerHTML = h;
}
function expired(){document.body.innerHTML='<div class="center"><div><h2>Link expired</h2><p class="muted">This live trip link has expired or was turned off.</p></div></div>';}
async function poll(){
  try{const r=await fetch(API,{cache:'no-store'});
    if(r.status===404){expired();return;}
    const j=await r.json(); if(j.code===1) render(j.data);
  }catch(e){}
  setTimeout(poll,5000);
}
poll();
</script></body></html>"""


def _external_page_url(token):
    """PUBLIC_WEB_BASE_URL/t/<token> when the landing site lives on another host."""
    from urllib.parse import urlencode, urlparse
    base = (os.getenv('PUBLIC_WEB_BASE_URL') or '').strip().rstrip('/')
    if not base:
        return None
    host = (urlparse(base).netloc or '').lower()
    if not host or host == (request.host or '').lower():
        return None
    q = {k: v for k, v in request.args.items() if k in ('lang',)}
    return f'{base}/t/{token[:64]}' + (f'?{urlencode(q)}' if q else '')


@tracking_share_bp.route('/t/<token>', methods=['GET'])
def public_page(token):
    limited = _limited(token)
    if limited:
        return limited
    ext = _external_page_url(token)
    if ext:
        return _nocache(redirect(ext, code=302))
    key = os.getenv('GOOGLE_MAPS_BROWSER_KEY', '').strip()
    if key:
        head = f'<script src="https://maps.googleapis.com/maps/api/js?key={key}"></script>'
    else:
        head = ('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">'
                '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>')
    html = (PAGE.replace('__MAPHEAD__', head).replace('__TOKEN__', json.dumps(token[:64]).replace('<', '\\u003c').replace('>', '\\u003e'))
            .replace('__GMAPS__', 'true' if key else 'false'))
    status = 200 if _find_live(token) else 404
    return _nocache(Response(html, status=status, mimetype='text/html'))
