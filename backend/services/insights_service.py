"""Fair-price hint, demand heatmaps, client analytics and admin reports
(spec §21.2, §21.3, §19.1.9, §19.1.13).

All reports read real tables with aggregate SQL (no row-by-row Python over
large tables) and take a UTC date range.
"""
import json
import math
import re
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import text

from backend import jobs
from backend.models import db
from backend.models.platform import AnalyticsEvent
from backend.services import geo_routes as G
from backend.services import settings_service as S

FAIR_SERVICE_RATE_KEYS = {
    'car': 'pricing.fair_car_pct', 'special car': 'pricing.fair_special_car_pct',
    'special car hire': 'pricing.fair_special_car_pct', 'carhire': 'pricing.fair_car_pct',
    'car hire': 'pricing.fair_car_pct', 'courier': 'pricing.fair_courier_pct',
    'movers': 'pricing.fair_movers_pct', 'airport': 'pricing.fair_airport_pct',
    'airport pickup': 'pricing.fair_airport_pct',
}


class InsightError(Exception):
    def __init__(self, message, code='bad_request', status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def _q(sql, **params):
    return db.session.execute(text(sql), params).fetchall()


def _round_down(c, step=100):
    return int(c // step * step)


def _round_up(c, step=100):
    return int(math.ceil(c / step) * step)


def _pct(sorted_vals, p):
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(math.ceil(p * len(sorted_vals))) - 1))
    return sorted_vals[k]


def _service_filter(st, col='n.service_type'):
    st = (st or 'car').strip().lower().replace('_', ' ')
    if st in ('car', 'car hire', 'carhire'):
        # Null service_type is a legacy car-hire record. Premium cars should
        # use their own history so standard-car fares do not flatten the uplift.
        return f"({col} IS NULL OR {col} IN ('car','carhire','Car'))", {}
    if st in ('special car', 'special car hire'):
        return f"{col} IN ('special car','special car hire','Special Car')", {}
    return f"{col} = :st", {'st': st}


# ── fair-price hint (§21.2) ─────────────────────────────────────────────────

_HAV_SQL = ("6371000*2*ASIN(SQRT(POW(SIN(RADIANS({b_lat}-{a_lat})/2),2)"
            "+COS(RADIANS({a_lat}))*COS(RADIANS({b_lat}))*POW(SIN(RADIANS({b_lng}-{a_lng})/2),2)))")


def _dec(col):
    return f"CAST({col} AS DECIMAL(10,7))"


def history_prices(service_type, straight_m, days=180, limit=2000):
    """Agreed prices (cents) of similar completed car-hire rides: same service
    type, straight-line distance within ±20 %."""
    where_st, params = _service_filter(service_type)
    hav = _HAV_SQL.format(a_lat=_dec('n.pickup_lat'), a_lng=_dec('n.pickup_lng'),
                          b_lat=_dec('n.dropoff_lat'), b_lng=_dec('n.dropoff_lng'))
    sql = f"""
        SELECT price FROM (
            SELECT COALESCE(n.agreed_price_cents, ROUND(n.agreed_price)) AS price, {hav} AS dist
            FROM negotiations n
            WHERE (n.trip_stage IN ('COMPLETED','CLOSED') OR n.status = 'Completed')
              AND n.created_at >= :since AND {where_st}
              AND n.pickup_lat IS NOT NULL AND n.pickup_lat <> '' AND n.dropoff_lat IS NOT NULL
              AND n.dropoff_lat <> '' AND n.pickup_lng <> '' AND n.dropoff_lng <> ''
        ) x
        WHERE x.dist BETWEEN :lo AND :hi AND x.price >= 50
        LIMIT {int(limit)}"""
    rows = _q(sql, since=datetime.utcnow() - timedelta(days=days), lo=straight_m * 0.8, hi=straight_m * 1.2,
              **params)
    return sorted(int(r[0]) for r in rows if r[0] is not None)


def fair_range(origin, destination, service_type='car'):
    straight = G.haversine_m(origin, destination)
    route = G.cached_route(origin, destination)
    if route is None:
        route = G.estimate(origin, destination)
        if G.server_key():
            # Never call Google inside the request: warm the cache for next time.
            jobs.enqueue('backend.services.geo_routes.warm_route_job', origin[0], origin[1],
                         destination[0], destination[1])
    km, minutes = route['distance_m'] / 1000.0, route['seconds'] / 60.0
    base = S.get_int('pricing.fair_base_cents', 425)
    distance_rate = S.get_int('pricing.fair_per_km_cents', 175)
    time_rate = S.get_int('pricing.fair_per_min_cents', 15)
    normalized_service = (service_type or 'car').strip().lower().replace('_', ' ')
    rate_key = FAIR_SERVICE_RATE_KEYS.get(normalized_service, 'pricing.fair_car_pct')
    service_pct = max(50, min(300, S.get_int(rate_key, 100)))
    model = round((base + distance_rate * km + time_rate * minutes) * service_pct / 100)
    model = max(model, S.get_int('pricing.min_fare_cents', 500))
    spread = S.get_int('pricing.fair_spread_pct', 13) / 100.0
    low_m, high_m = model * (1 - spread), model * (1 + spread)

    hist = history_prices(service_type, straight) if straight > 200 else []
    n = len(hist)
    w = min(0.7, n / 20.0) if n >= 3 else 0.0
    if w:
        p25, p50, p75 = _pct(hist, 0.25), _pct(hist, 0.5), _pct(hist, 0.75)
        typical = w * p50 + (1 - w) * model
        low = w * p25 + (1 - w) * low_m
        high = w * p75 + (1 - w) * high_m
    else:
        typical, low, high = model, low_m, high_m
    floor = S.get_int('pricing.min_fare_cents', 500)
    low = max(floor, _round_down(min(low, typical)))
    high = max(low + 100, _round_up(max(high, typical)))
    typical = int(round(min(max(typical, low), high) / 50.0) * 50)
    return {
        'low_cents': low, 'high_cents': high, 'typical_cents': typical, 'currency': 'cad',
        'distance_m': int(route['distance_m']), 'duration_s': int(route['seconds']),
        'basis': {'distance_source': route.get('source', 'estimate'), 'history_count': n,
                  'history_weight': round(w, 2), 'service_type': service_type,
                  'service_multiplier_pct': service_pct, 'time_minutes': round(minutes, 1)},
        'text': f"Typical fare for this route: ${low // 100}–${high // 100}",
    }


# ── demand heatmaps ─────────────────────────────────────────────────────────

def demand_cells(since, until, cell_deg, bbox=None, min_count=1):
    """Request pickup points aggregated into a grid. No personal data: only
    cell centres and counts. Counts ride_requests plus negotiations that did
    not come from a ride_request (legacy / direct creates)."""
    params = {'since': since, 'until': until, 'c': cell_deg}
    box_rr = box_n = ''
    if bbox:
        params.update({'la1': bbox[0], 'la2': bbox[1], 'lo1': bbox[2], 'lo2': bbox[3]})
        box_rr = ' AND rr.pickup_lat BETWEEN :la1 AND :la2 AND rr.pickup_lng BETWEEN :lo1 AND :lo2'
        box_n = (f" AND {_dec('n.pickup_lat')} BETWEEN :la1 AND :la2 "
                 f"AND {_dec('n.pickup_lng')} BETWEEN :lo1 AND :lo2")
    sql = f"""
        SELECT ROUND(lat / :c) * :c AS clat, ROUND(lng / :c) * :c AS clng, COUNT(*) AS cnt FROM (
            SELECT rr.pickup_lat AS lat, rr.pickup_lng AS lng FROM ride_requests rr
             WHERE rr.created_at >= :since AND rr.created_at < :until {box_rr}
            UNION ALL
            SELECT {_dec('n.pickup_lat')} AS lat, {_dec('n.pickup_lng')} AS lng FROM negotiations n
             WHERE n.created_at >= :since AND n.created_at < :until
               AND n.pickup_lat IS NOT NULL AND n.pickup_lat <> '' AND n.pickup_lng <> '' {box_n}
               AND NOT EXISTS (SELECT 1 FROM ride_requests r2 WHERE r2.negotiation_id = n.id)
        ) p
        GROUP BY clat, clng HAVING cnt >= :k ORDER BY cnt DESC LIMIT 2000"""
    params['k'] = min_count
    rows = _q(sql, **params)
    peak = max((int(r[2]) for r in rows), default=0)
    return [{'lat': round(float(r[0]), 5), 'lng': round(float(r[1]), 5), 'count': int(r[2]),
             'intensity': round(int(r[2]) / peak, 3) if peak else 0} for r in rows]


def driver_heatmap(lat, lng, radius_km=10, hours=2):
    radius_km = max(1.0, min(50.0, float(radius_km)))
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    now = datetime.utcnow()
    cells = demand_cells(now - timedelta(hours=hours), now + timedelta(minutes=1), 0.01,
                         bbox=(lat - dlat, lat + dlat, lng - dlng, lng + dlng))
    return {'cell_size_deg': 0.01, 'cell_size_m': 1100, 'window_hours': hours, 'radius_km': radius_km,
            'generated_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'cells': cells}


# ── client analytics (§21.3 item 8) ─────────────────────────────────────────

NAME_RE = re.compile(r'^[a-z][a-z0-9_.]{0,79}$')
MAX_BATCH = 50
_rate = {}
_rate_lock = threading.Lock()


def _rate_ok(key, n):
    limit = S.get_int('analytics.max_events_per_min', 120)
    minute = int(time.time() // 60)
    r = jobs.get_redis()
    if r is not None:
        try:
            k = f'negoride:analytics:{key}:{minute}'
            used = r.incrby(k, n)
            r.expire(k, 120)
            return used <= limit
        except Exception:
            pass
    with _rate_lock:
        cur = _rate.get(key)
        if not cur or cur[0] != minute:
            cur = [minute, 0]
        cur[1] += n
        _rate[key] = cur
        if len(_rate) > 50000:
            _rate.clear()
        return cur[1] <= limit


def reset_rate_limits():
    with _rate_lock:
        _rate.clear()


def ingest_events(user, ip, events):
    if not isinstance(events, list) or not events:
        raise InsightError('events must be a non-empty list.', code='bad_events')
    if len(events) > MAX_BATCH:
        raise InsightError(f'At most {MAX_BATCH} events per batch.', code='batch_too_large')
    key = f'u{user.id}' if user else f'ip{ip or "-"}'
    if not _rate_ok(key, len(events)):
        raise InsightError('Too many analytics events — slow down.', code='rate_limited', status=429)
    accepted = dropped = 0
    for ev in events:
        if not isinstance(ev, dict):
            dropped += 1
            continue
        name = str(ev.get('name') or '').strip().lower()
        if not NAME_RE.match(name):
            dropped += 1
            continue
        val = ev.get('value_num', ev.get('value'))
        try:
            val = None if val in (None, '') else float(val)
            if val is not None and (math.isnan(val) or abs(val) >= 1e11):
                raise ValueError
        except (TypeError, ValueError):
            dropped += 1
            continue
        props = ev.get('props')
        if props is not None:
            if not isinstance(props, dict) or len(json.dumps(props, default=str)) > 2000:
                props = None
        db.session.add(AnalyticsEvent(user_id=user.id if user else None, name=name, value_num=val, props=props))
        accepted += 1
    db.session.commit()
    return {'accepted': accepted, 'dropped': dropped}


def latency_stats(name, days=7):
    since = datetime.utcnow() - timedelta(days=days)
    base = "FROM analytics_events WHERE name = :n AND created_at >= :s AND value_num IS NOT NULL"
    row = _q(f"SELECT COUNT(*), AVG(value_num), MIN(value_num), MAX(value_num) {base}", n=name, s=since)[0]
    count = int(row[0] or 0)
    out = {'name': name, 'days': days, 'count': count, 'avg': round(float(row[1]), 1) if count else None,
           'min': float(row[2]) if count else None, 'max': float(row[3]) if count else None,
           'p50': None, 'p95': None, 'p99': None, 'target_p95_ms': 400}
    for label, p in (('p50', 0.5), ('p95', 0.95), ('p99', 0.99)):
        if count:
            k = max(0, int(math.ceil(p * count)) - 1)
            v = _q(f"SELECT value_num {base} ORDER BY value_num LIMIT 1 OFFSET {k}", n=name, s=since)
            out[label] = float(v[0][0]) if v else None
    out['daily'] = [{'date': str(r[0]), 'count': int(r[1]), 'avg': round(float(r[2]), 1)} for r in _q(
        f"SELECT DATE(created_at) d, COUNT(*), AVG(value_num) {base} GROUP BY d ORDER BY d", n=name, s=since)]
    return out


# ── admin: ratings (§19.1.9) ────────────────────────────────────────────────

def lowest_rated_drivers(min_count=10, limit=50):
    rows = _q("""
        SELECT r.ratee_id, AVG(r.stars) avg_stars, COUNT(*) n, u.first_name, u.name, u.rating, u.rating_count
        FROM ride_ratings r JOIN admin_users u ON u.id = r.ratee_id
        WHERE r.role = 'customer' AND r.hidden_by_admin = 0
        GROUP BY r.ratee_id, u.first_name, u.name, u.rating, u.rating_count
        HAVING n >= :m ORDER BY avg_stars ASC, n DESC LIMIT :l""", m=min_count, l=limit)
    return [{'driver_id': r[0], 'avg_stars': round(float(r[1]), 2), 'ratings': int(r[2]),
             'name': r[4] or r[3], 'score': float(r[5]) if r[5] is not None else None,
             'rating_count': int(r[6] or 0)} for r in rows]


def rating_trend_alerts(drop=None, min_recent=3, now=None):
    """Drivers whose last-7-day average fell by more than `drop` versus the 28 days before."""
    drop = S.get_float('rating.trend_drop', 0.3) if drop is None else drop
    now = now or datetime.utcnow()
    d7, d35 = now - timedelta(days=7), now - timedelta(days=35)
    rows = _q("""
        SELECT * FROM (
            SELECT r.ratee_id,
                   AVG(CASE WHEN r.created_at >= :d7 THEN r.stars END) recent,
                   SUM(CASE WHEN r.created_at >= :d7 THEN 1 ELSE 0 END) recent_n,
                   AVG(CASE WHEN r.created_at < :d7 THEN r.stars END) prior,
                   SUM(CASE WHEN r.created_at < :d7 THEN 1 ELSE 0 END) prior_n,
                   u.name, u.first_name
            FROM ride_ratings r JOIN admin_users u ON u.id = r.ratee_id
            WHERE r.role = 'customer' AND r.hidden_by_admin = 0 AND r.created_at >= :d35
            GROUP BY r.ratee_id, u.name, u.first_name
        ) t
        WHERE t.recent_n >= :mr AND t.prior_n >= :mr AND t.prior - t.recent > :drop
        ORDER BY (t.prior - t.recent) DESC LIMIT 200""", d7=d7, d35=d35, mr=min_recent, drop=drop)
    return [{'driver_id': r[0], 'name': r[5] or r[6], 'recent_avg': round(float(r[1]), 2),
             'recent_count': int(r[2]), 'prior_avg': round(float(r[3]), 2), 'prior_count': int(r[4]),
             'drop': round(float(r[3]) - float(r[1]), 2)} for r in rows]


# ── admin: reports & analytics (§19.1.13) ───────────────────────────────────

def supply_vs_demand(since, until, tz='UTC'):
    from zoneinfo import ZoneInfo
    demand = {str(r[0]): int(r[1]) for r in _q("""
        SELECT DATE_FORMAT(created_at, '%Y-%m-%d %H:00:00') h, COUNT(*) FROM (
            SELECT created_at FROM ride_requests WHERE created_at >= :s AND created_at < :u
            UNION ALL
            SELECT n.created_at FROM negotiations n WHERE n.created_at >= :s AND n.created_at < :u
               AND NOT EXISTS (SELECT 1 FROM ride_requests r2 WHERE r2.negotiation_id = n.id)
        ) x GROUP BY h""", s=since, u=until)}
    supply = {str(r[0]): float(r[1]) for r in _q("""
        SELECT DATE_FORMAT(bucket_at, '%Y-%m-%d %H:00:00') h, AVG(online_drivers)
        FROM driver_supply_snapshots WHERE bucket_at >= :s AND bucket_at < :u GROUP BY h""", s=since, u=until)}
    engaged = {str(r[0]): int(r[1]) for r in _q("""
        SELECT DATE_FORMAT(created_at, '%Y-%m-%d %H:00:00') h, COUNT(DISTINCT driver_id)
        FROM negotiations WHERE created_at >= :s AND created_at < :u AND driver_id IS NOT NULL GROUP BY h""",
                                                 s=since, u=until)}
    try:
        zone = ZoneInfo(tz or 'UTC')
    except Exception:
        zone = ZoneInfo('UTC')
    utc = ZoneInfo('UTC')
    series, profile = [], {h: {'requests': 0, 'online_sum': 0.0, 'online_n': 0, 'hours': 0} for h in range(24)}
    t = since.replace(minute=0, second=0, microsecond=0)
    while t < until and len(series) < 24 * 400:
        key = t.strftime('%Y-%m-%d %H:00:00')
        req, onl = demand.get(key, 0), supply.get(key)
        series.append({'hour': t.strftime('%Y-%m-%dT%H:00:00Z'), 'requests': req,
                       'online_drivers': round(onl, 1) if onl is not None else None,
                       'engaged_drivers': engaged.get(key, 0),
                       'requests_per_online_driver': round(req / onl, 2) if onl else None})
        lh = t.replace(tzinfo=utc).astimezone(zone).hour
        p = profile[lh]
        p['requests'] += req
        p['hours'] += 1
        if onl is not None:
            p['online_sum'] += onl
            p['online_n'] += 1
        t += timedelta(hours=1)
    by_hour = [{'hour_of_day': h, 'avg_requests': round(p['requests'] / p['hours'], 2) if p['hours'] else 0,
                'avg_online_drivers': round(p['online_sum'] / p['online_n'], 1) if p['online_n'] else None}
               for h, p in profile.items()]
    return {'timezone': str(zone), 'series': series, 'by_hour_of_day': by_hour,
            'totals': {'requests': sum(demand.values())}}


AGREED_STAGES = "('PRICE_AGREED','AWAITING_PAYMENT','CONFIRMED','DRIVER_EN_ROUTE','DRIVER_ARRIVING'," \
                "'DRIVER_ARRIVED','IN_PROGRESS','COMPLETED','CLOSED')"


def negotiation_analytics(since, until):
    rows = _q(f"""
        SELECT COUNT(*) total,
               SUM(CASE WHEN agreed = 1 THEN 1 ELSE 0 END) agreed_n,
               AVG(CASE WHEN agreed = 1 AND initial_price > 0 AND agreed_c IS NOT NULL
                        THEN (agreed_c - initial_price) / initial_price * 100 END) change_vs_offer,
               AVG(CASE WHEN agreed = 1 AND ask > 0 AND agreed_c IS NOT NULL
                        THEN (ask - agreed_c) / ask * 100 END) discount_vs_ask,
               AVG(rounds) rounds,
               AVG(CASE WHEN agreed = 1 THEN rounds END) rounds_agreed,
               SUM(CASE WHEN agreed = 1 AND ask > 0 THEN 1 ELSE 0 END) with_ask
        FROM (
            SELECT n.id, n.initial_price,
                   COALESCE(n.agreed_price_cents, ROUND(n.agreed_price)) agreed_c,
                   CASE WHEN n.trip_stage IN {AGREED_STAGES}
                          OR (n.trip_stage IS NULL AND n.status IN ('Accepted','Accept','Started','Ongoing','Completed'))
                        THEN 1 ELSE 0 END agreed,
                   (SELECT COUNT(*) FROM negotiation_records r WHERE r.negotiation_id = n.id AND r.price > 0) rounds,
                   (SELECT r.price FROM negotiation_records r
                     WHERE r.negotiation_id = n.id AND r.price > 0 AND r.last_negotiator_id = n.driver_id
                     ORDER BY r.id ASC LIMIT 1) ask
            FROM negotiations n WHERE n.created_at >= :s AND n.created_at < :u
        ) x""", s=since, u=until)
    r = rows[0]
    total, agreed = int(r[0] or 0), int(r[1] or 0)
    by_outcome = {str(x[0] or 'UNKNOWN'): int(x[1]) for x in _q("""
        SELECT COALESCE(trip_stage, status), COUNT(*) FROM negotiations
        WHERE created_at >= :s AND created_at < :u GROUP BY COALESCE(trip_stage, status)""", s=since, u=until)}
    return {
        'negotiations': total, 'agreed': agreed,
        'acceptance_rate_pct': round(agreed * 100.0 / total, 1) if total else None,
        'avg_change_vs_customer_offer_pct': round(float(r[2]), 1) if r[2] is not None else None,
        'avg_discount_from_driver_initial_ask_pct': round(float(r[3]), 1) if r[3] is not None else None,
        'agreed_with_driver_ask': int(r[6] or 0),
        'avg_rounds': round(float(r[4]), 2) if r[4] is not None else None,
        'avg_rounds_when_agreed': round(float(r[5]), 2) if r[5] is not None else None,
        'by_stage': by_outcome,
    }


def _completed_rides_sql():
    return """
        SELECT customer_id cid, created_at at FROM negotiations
         WHERE customer_id IS NOT NULL AND (trip_stage IN ('COMPLETED','CLOSED') OR status = 'Completed')
        UNION ALL
        SELECT customer_id, created_at FROM trip_bookings
         WHERE trip_stage IN ('DROPPED_OFF','CLOSED') OR status = 'Completed'
        UNION ALL
        SELECT customer_id, created_at FROM scheduled_bookings
         WHERE trip_stage IN ('COMPLETED','CLOSED') OR status = 'completed'"""


def cohort_retention(since, until, weeks=8):
    weeks = max(1, min(26, int(weeks)))
    wk = "DATE_SUB(DATE(u.created_at), INTERVAL WEEKDAY(u.created_at) DAY)"
    sizes = {str(r[0]): int(r[1]) for r in _q(f"""
        SELECT {wk} c, COUNT(*) FROM admin_users u
        WHERE u.created_at >= :s AND u.created_at < :u GROUP BY c""", s=since, u=until)}
    active = _q(f"""
        SELECT {wk} c, FLOOR(DATEDIFF(r.at, u.created_at) / 7) w, COUNT(DISTINCT u.id)
        FROM admin_users u JOIN ({_completed_rides_sql()}) r ON r.cid = u.id
        WHERE u.created_at >= :s AND u.created_at < :u AND r.at >= u.created_at
          AND DATEDIFF(r.at, u.created_at) < :days
        GROUP BY c, w""", s=since, u=until, days=weeks * 7)
    grid = {}
    for c, w, n in active:
        grid.setdefault(str(c), {})[int(w)] = int(n)
    out = []
    for c in sorted(sizes):
        size = sizes[c]
        row = grid.get(c, {})
        out.append({'cohort_week': c, 'users': size,
                    'weeks': [{'week': i, 'active_users': row.get(i, 0),
                               'pct': round(row.get(i, 0) * 100.0 / size, 1) if size else 0.0}
                              for i in range(weeks)]})
    return {'weeks': weeks, 'cohorts': out}


def earnings_distribution(since, until, bucket_cents=None):
    rows = _q("""
        SELECT t.user_id, SUM(t.amount) FROM transactions t
        WHERE t.type = 'credit' AND t.category IN ('ride_earning','rideshare_earning','tip','cancellation_fee')
          AND t.status = 'completed' AND t.created_at >= :s AND t.created_at < :u
        GROUP BY t.user_id""", s=since, u=until)
    vals = sorted(int(round(float(r[1]) * 100)) for r in rows if r[1] is not None)
    if not vals:
        return {'drivers': 0, 'bucket_cents': bucket_cents or 5000, 'histogram': [], 'total_cents': 0,
                'mean_cents': None, 'p50_cents': None, 'p90_cents': None}
    if not bucket_cents:
        raw = max(1000, vals[-1] // 20)
        bucket_cents = int(_round_up(raw, 1000))
    counts = {}
    for v in vals:
        b = v // bucket_cents
        counts[b] = counts.get(b, 0) + 1
    hist = [{'from_cents': b * bucket_cents, 'to_cents': (b + 1) * bucket_cents, 'drivers': counts.get(b, 0)}
            for b in range(0, max(counts) + 1)]
    return {'drivers': len(vals), 'bucket_cents': bucket_cents, 'histogram': hist, 'total_cents': sum(vals),
            'mean_cents': int(sum(vals) / len(vals)), 'p50_cents': _pct(vals, 0.5), 'p90_cents': _pct(vals, 0.9)}


def snapshot_supply(now=None):
    """Record the online-driver count once per 10-minute bucket (supply report)."""
    now = now or datetime.utcnow()
    bucket = now.replace(minute=now.minute - now.minute % 10, second=0, microsecond=0)
    stale = now - timedelta(minutes=15)
    n = _q("""SELECT COUNT(*) FROM admin_users WHERE ready_for_trip = 'Yes' AND status = 1
              AND (account_status IS NULL OR account_status = 'active')
              AND last_location_update >= :st""", st=stale)[0][0]
    db.session.execute(text("INSERT IGNORE INTO driver_supply_snapshots (bucket_at, online_drivers, created_at) "
                            "VALUES (:b, :n, :c)"), {'b': bucket, 'n': int(n or 0), 'c': now})
    db.session.commit()
    return int(n or 0)
