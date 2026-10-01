"""Server-side Google Maps helpers (spec §16, §21.2) — Routes API + Roads API.

Only the server key `GOOGLE_MAPS_SERVER_KEY` is used (never a client key), and
these functions are called from background jobs, never inside an HTTP request.
When no key is configured (dev / tests) a haversine × road-factor estimate at
an average city speed is returned instead.

Routes API (verified against developers.google.com/maps/documentation/routes,
Sept 2026):
    POST https://routes.googleapis.com/directions/v2:computeRoutes
    headers: X-Goog-Api-Key, X-Goog-FieldMask: routes.duration,routes.distanceMeters
    body: {origin:{location:{latLng:{latitude,longitude}}}, destination:{…},
           travelMode:"DRIVE", routingPreference:"TRAFFIC_AWARE"}
    response: {"routes":[{"distanceMeters": 1234, "duration": "165s"}]}
    (departureTime is omitted → "now"; a past departureTime is rejected.)

Roads API:
    GET https://roads.googleapis.com/v1/snapToRoads?path=lat,lng|lat,lng&interpolate=true&key=…
    response: {"snappedPoints":[{"location":{"latitude","longitude"},"originalIndex":0,"placeId":…}]}
    ≤ 100 points per request.
"""
import json
import logging
import math
import os
import threading
import time
from collections import OrderedDict

log = logging.getLogger('negoride.geo')

ROUTES_URL = 'https://routes.googleapis.com/directions/v2:computeRoutes'
ROADS_URL = 'https://roads.googleapis.com/v1/snapToRoads'
FIELD_MASK = 'routes.duration,routes.distanceMeters'
TIMEOUT_S = 5

CALLS = []   # test introspection: every (origin, destination) sent to Google


def server_key():
    return (os.getenv('GOOGLE_MAPS_SERVER_KEY') or '').strip()


def haversine_m(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(min(1.0, h)))


def estimate(origin, destination):
    """Fallback: straight line × road factor at an average city speed."""
    from backend.services import settings_service as S
    dist = haversine_m(origin, destination) * S.get_float('eta.road_factor', 1.3)
    speed_mps = max(5.0, S.get_int('eta.avg_speed_kmh', 32)) / 3.6
    return {'seconds': int(round(dist / speed_mps)), 'distance_m': int(round(dist)), 'source': 'estimate'}


def _parse_duration(text):
    if text is None:
        return None
    s = str(text).strip()
    if s.endswith('s'):
        s = s[:-1]
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def google_compute_route(origin, destination):
    """One traffic-aware Routes API call. Returns {'seconds','distance_m','source'} or None."""
    key = server_key()
    if not key:
        return None
    import requests
    CALLS.append((tuple(origin), tuple(destination)))
    body = {
        'origin': {'location': {'latLng': {'latitude': origin[0], 'longitude': origin[1]}}},
        'destination': {'location': {'latLng': {'latitude': destination[0], 'longitude': destination[1]}}},
        'travelMode': 'DRIVE',
        'routingPreference': 'TRAFFIC_AWARE',
    }
    try:
        r = requests.post(ROUTES_URL, data=json.dumps(body), timeout=TIMEOUT_S, headers={
            'Content-Type': 'application/json', 'X-Goog-Api-Key': key, 'X-Goog-FieldMask': FIELD_MASK})
        if r.status_code != 200:
            log.warning('Routes API %s: %s', r.status_code, r.text[:300])
            return None
        routes = (r.json() or {}).get('routes') or []
        if not routes:
            return None
        secs = _parse_duration(routes[0].get('duration'))
        dist = routes[0].get('distanceMeters')
        if secs is None:
            return None
        return {'seconds': secs, 'distance_m': int(dist or 0), 'source': 'google_routes'}
    except Exception as exc:  # network / JSON
        log.warning('Routes API call failed: %s', exc)
        return None


def compute_route(origin, destination):
    """Google when a server key is configured, otherwise (or on failure) the estimate."""
    res = google_compute_route(origin, destination)
    return res or estimate(origin, destination)


# ── encoded polylines (Google format, precision 5) ─────────────────────────

def encode_polyline(points):
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


def decode_polyline(text):
    pts, i, lat, lng = [], 0, 0, 0
    text = text or ''
    n = len(text)
    while i < n:
        vals = []
        for _ in range(2):
            shift = result = 0
            while True:
                if i >= n:
                    return pts
                b = ord(text[i]) - 63
                i += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            vals.append(~(result >> 1) if result & 1 else result >> 1)
        lat += vals[0]
        lng += vals[1]
        pts.append((lat / 1e5, lng / 1e5))
    return pts


def google_route_polyline(origin, destination):
    """Routes API call that also returns the encoded polyline (planned route for
    route-deviation checks). Returns {'polyline','seconds','distance_m','source'} or None."""
    key = server_key()
    if not key:
        return None
    import requests
    CALLS.append((tuple(origin), tuple(destination)))
    body = {
        'origin': {'location': {'latLng': {'latitude': origin[0], 'longitude': origin[1]}}},
        'destination': {'location': {'latLng': {'latitude': destination[0], 'longitude': destination[1]}}},
        'travelMode': 'DRIVE', 'routingPreference': 'TRAFFIC_AWARE', 'polylineQuality': 'OVERVIEW',
    }
    try:
        r = requests.post(ROUTES_URL, data=json.dumps(body), timeout=TIMEOUT_S, headers={
            'Content-Type': 'application/json', 'X-Goog-Api-Key': key,
            'X-Goog-FieldMask': FIELD_MASK + ',routes.polyline.encodedPolyline'})
        if r.status_code != 200:
            log.warning('Routes API (polyline) %s: %s', r.status_code, r.text[:300])
            return None
        routes = (r.json() or {}).get('routes') or []
        poly = ((routes[0].get('polyline') or {}).get('encodedPolyline')) if routes else None
        if not poly:
            return None
        return {'polyline': poly, 'seconds': _parse_duration(routes[0].get('duration')),
                'distance_m': int(routes[0].get('distanceMeters') or 0), 'source': 'google_routes'}
    except Exception as exc:
        log.warning('Routes API (polyline) failed: %s', exc)
        return None


def planned_route(origin, destination):
    """Google route polyline when a server key is set, else a straight line."""
    res = google_route_polyline(origin, destination)
    if res:
        return res
    est = estimate(origin, destination)
    return {'polyline': encode_polyline([tuple(origin), tuple(destination)]), 'seconds': est['seconds'],
            'distance_m': est['distance_m'], 'source': 'straight_line'}


def snap_path_cached(cache_key, points, ttl_s=7 * 24 * 3600):
    """Snap a recorded path (any length) to roads in ≤100-point requests, cached
    (Redis or in-process) under `cache_key`. Returns (points, snapped: bool).
    Without GOOGLE_MAPS_SERVER_KEY the input is returned unchanged."""
    pts = [(float(a), float(b)) for a, b in points]
    if not server_key() or len(pts) < 2:
        return pts, False
    from backend import jobs
    rkey = 'negoride:snap:' + cache_key
    r = jobs.get_redis()
    if r is not None:
        try:
            raw = r.get(rkey)
            if raw:
                return [tuple(p) for p in json.loads(raw)], True
        except Exception:
            pass
    with _cache_lock:
        hit = _cache.get(rkey)
        if hit and time.monotonic() - hit[0] < ttl_s:
            return hit[1], True
    out = []
    for i in range(0, len(pts) - 1, 99):               # windows of 100 sharing 1 point (continuous path)
        snapped = snap_to_roads(pts[i:i + 100])
        out.extend(snapped[1:] if i and snapped else snapped)
    if r is not None:
        try:
            r.set(rkey, json.dumps(out), ex=ttl_s)
        except Exception:
            pass
    with _cache_lock:
        _cache[rkey] = (time.monotonic(), out)
    return out, True


def snap_to_roads(points, interpolate=False):
    """Snap GPS points [(lat, lng), …] (≤ 100) to roads. Returns the input on failure / no key."""
    key = server_key()
    pts = list(points)[:100]
    if not key or not pts:
        return pts
    import requests
    try:
        r = requests.get(ROADS_URL, timeout=TIMEOUT_S, params={
            'path': '|'.join(f'{p[0]:.6f},{p[1]:.6f}' for p in pts),
            'interpolate': 'true' if interpolate else 'false', 'key': key})
        if r.status_code != 200:
            return pts
        snapped = (r.json() or {}).get('snappedPoints') or []
        out = [(s['location']['latitude'], s['location']['longitude']) for s in snapped if s.get('location')]
        return out or pts
    except Exception as exc:
        log.warning('Roads API call failed: %s', exc)
        return pts


# ── small route cache (fair-price hint) ─────────────────────────────────────
_cache = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_MAX = 2000
_CACHE_TTL = 6 * 3600


def cache_key(origin, destination):
    """~1 km grid so nearby requests share one Google call."""
    return f'{origin[0]:.2f},{origin[1]:.2f}>{destination[0]:.2f},{destination[1]:.2f}'


def cached_route(origin, destination):
    key = cache_key(origin, destination)
    from backend import jobs
    r = jobs.get_redis()
    if r is not None:
        try:
            raw = r.get('negoride:route:' + key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < _CACHE_TTL:
            return hit[1]
    return None


def store_route(origin, destination, value):
    key = cache_key(origin, destination)
    from backend import jobs
    r = jobs.get_redis()
    if r is not None:
        try:
            r.set('negoride:route:' + key, json.dumps(value), ex=_CACHE_TTL)
        except Exception:
            pass
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


def warm_route_job(o_lat, o_lng, d_lat, d_lng):
    """Job: fetch a traffic-aware route from Google and cache it (fair-price hint)."""
    origin, dest = (float(o_lat), float(o_lng)), (float(d_lat), float(d_lng))
    if cached_route(origin, dest):
        return None
    res = google_compute_route(origin, dest)
    if res:
        store_route(origin, dest, res)
    return res
