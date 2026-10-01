"""Receipts, credit notes and the "Thank you for riding" email (spec §13).

Entry points (called by the foundation):
    issue_and_send(ride_type, ride_id)        job after the completion capture
    issue_credit_note_for_refund(refund_id)   job after a provider refund
    resend(receipt_id, actor=None)            admin / support re-email (same number)

Rules
  • Every amount is INTEGER CENTS, CAD. Taxes use basis points from `tax_rates`
    and integer arithmetic; every column of the receipt adds up exactly.
  • Numbers are sequential per year and never reused: NR-2026-000123 and
    NR-CN-2026-000045, allocated from `document_sequences` under
    SELECT … FOR UPDATE in the same transaction that inserts the document, so
    a rolled-back issue never burns a number (no gaps, no duplicates).
  • An issued receipt is immutable: the totals JSON is a snapshot. Refunds
    produce credit notes; resend re-renders from the snapshot.
  • PDFs are stored privately (PRIVATE_STORAGE_DIR, default
    backend/storage/private) and only streamed through authorised endpoints.
"""
import base64
import hashlib
import hmac
import logging
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from backend import jobs
from backend.models import db
from backend.models.money import (CAPTURED_STATES, CreditNote, DocumentSequence, Receipt, Refund, RidePayment,
                                  TaxRate, TipReceipt)
from backend.models.notification import Notification, NotificationDelivery
from backend.models.user import AdminUser
from backend.services import rides as R
from backend.services import settings_service as S
from backend.utils.money import bp_of, fmt, pct_of

log = logging.getLogger('negoride.receipts')

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_TEMPLATE_DIR = os.path.join(BACKEND_DIR, 'templates', 'pdf')
RECEIPT_RIDE_TYPES = ('carhire', 'scheduled', 'rideshare_booking')
MAX_EMAIL_ATTEMPTS = 3

PROVINCES = {
    'AB': 'Alberta', 'BC': 'British Columbia', 'MB': 'Manitoba', 'NB': 'New Brunswick',
    'NL': 'Newfoundland and Labrador', 'NS': 'Nova Scotia', 'NT': 'Northwest Territories',
    'NU': 'Nunavut', 'ON': 'Ontario', 'PE': 'Prince Edward Island', 'QC': 'Quebec',
    'SK': 'Saskatchewan', 'YT': 'Yukon',
}
PROVINCE_TZ = {
    'AB': 'America/Edmonton', 'BC': 'America/Vancouver', 'MB': 'America/Winnipeg', 'NB': 'America/Moncton',
    'NL': 'America/St_Johns', 'NS': 'America/Halifax', 'NT': 'America/Yellowknife', 'NU': 'America/Iqaluit',
    'ON': 'America/Toronto', 'PE': 'America/Halifax', 'QC': 'America/Toronto', 'SK': 'America/Regina',
    'YT': 'America/Whitehorse',
}
CARD_BRANDS = {'visa': 'Visa', 'mastercard': 'Mastercard', 'amex': 'American Express', 'discover': 'Discover',
               'interac': 'Interac', 'jcb': 'JCB', 'unionpay': 'UnionPay', 'diners': 'Diners Club'}


class ReceiptError(Exception):
    pass


# ═══════════════════════════════════════════════════════════════════════════
# Private storage
# ═══════════════════════════════════════════════════════════════════════════

def save_private(key, blob):
    """Store in the shared private store (Fernet-encrypted locally, SSE on S3;
    never web-served). Returns the key saved in `pdf_path`."""
    from backend.services import private_storage as PSTORE
    PSTORE.put(key, blob, 'application/pdf')
    return key


def read_private(key):
    if not key:
        return None
    from backend.services import private_storage as PSTORE
    try:
        return PSTORE.get(key)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Tax (pure functions — unit tested)
# ═══════════════════════════════════════════════════════════════════════════

def _div_half_up(num, den):
    """Integer division rounded half-up (num, den ≥ 0)."""
    q, r = divmod(int(num), int(den))
    return q + (1 if 2 * r >= den else 0)


def tax_components(rate):
    """TaxRate row → ordered [(code, label, bp)] with non-zero rates."""
    if rate is None:
        return []
    out = []
    for code, bp in (('HST', rate.hst_bp), ('GST', rate.gst_bp), ('PST', rate.pst_bp), ('QST', rate.qst_bp)):
        if bp:
            out.append((code, f'{code} {_pct_label(bp)}', int(bp)))
    return out


def _pct_label(bp):
    whole, frac = divmod(int(bp), 100)
    return f'{whole}%' if frac == 0 else f'{whole}.{frac:02d}'.rstrip('0') + '%'


def split_tax(amount_cents, components, inclusive=True):
    """Split `amount_cents` into (pre_tax_cents, [tax lines], tax_total).

    inclusive=True : the amount already contains the tax. pre_tax = amount /
                     (1 + Σrates) rounded half-up; tax_total = amount − pre_tax;
                     each component = pre_tax × rate, and the rounding
                     remainder is put on the largest component so the lines
                     add up to the cent: pre_tax + Σtax == amount.
    inclusive=False: tax is added on top: each component = amount × rate.
    """
    amount_cents = int(amount_cents)
    total_bp = sum(c[2] for c in components)
    if not components or amount_cents == 0:
        return amount_cents, [], 0
    sign = -1 if amount_cents < 0 else 1
    amt = abs(amount_cents)
    if inclusive:
        pre = _div_half_up(amt * 10000, 10000 + total_bp)
        tax_total = amt - pre
        parts = [bp_of(pre, bp) for _, _, bp in components]
        diff = tax_total - sum(parts)
        biggest = max(range(len(components)), key=lambda i: components[i][2])
        parts[biggest] += diff
    else:
        pre = amt
        parts = [bp_of(pre, bp) for _, _, bp in components]
        tax_total = sum(parts)
    lines = [{'code': code, 'label': label, 'rate_bp': bp, 'amount_cents': sign * p}
             for (code, label, bp), p in zip(components, parts)]
    return sign * pre, lines, sign * tax_total


def allocate(total, weights):
    """Split integer `total` proportionally to integer `weights` (largest
    remainder), so the parts add up exactly. Weights may be negative
    (discounts); the remainder lands on the largest weight."""
    wsum = sum(weights)
    if not weights:
        return []
    if wsum == 0:
        return [0] * len(weights)
    parts = []
    for w in weights:
        num = total * w
        q, r = divmod(abs(num), abs(wsum))
        v = q + (1 if 2 * r >= abs(wsum) else 0)
        parts.append(v if (num >= 0) == (wsum > 0) else -v)
    big = max(range(len(weights)), key=lambda i: abs(weights[i]))
    parts[big] += total - sum(parts)
    return parts


def rate_for(province, on_date=None):
    on_date = on_date or datetime.utcnow().date()
    q = (TaxRate.query.filter(TaxRate.province == province, TaxRate.effective_from <= on_date)
         .filter((TaxRate.effective_to.is_(None)) | (TaxRate.effective_to >= on_date))
         .order_by(TaxRate.effective_from.desc()))
    return q.first()


_PROV_RE = re.compile(r'(?:,|\s)\s*(AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\b(?:\s+[A-Z]\d[A-Z]|\s*,|\s*$)')


def province_of(ride_type, ride):
    """(province_code, source). Source: ride (stored pickup_province) | geo (pickup
    lat/lng lookup) | address (", QC H2X") | default (setting tax.default_province)."""
    candidates = [getattr(ride, 'pickup_province', None)]
    if ride_type == 'rideshare_booking':
        trip = R.load('rideshare_trip', ride.trip_id)
        candidates.append(getattr(trip, 'pickup_province', None))
    for c in candidates:
        c = (c or '').strip().upper()[:2]
        if c in PROVINCES:
            return c, 'ride'
    # Rides created before the province was stamped: look the pickup point up.
    try:
        from backend.utils.province import province_at
        pt = R.pickup_point(ride_type, ride)
        code = province_at(pt[0], pt[1]) if pt else None
        if code in PROVINCES:
            return code, 'geo'
    except Exception:
        pass
    pickup, _ = R.addresses(ride_type, ride)
    if pickup:
        m = _PROV_RE.search(pickup.upper())
        if m:
            return m.group(1), 'address'
        low = pickup.lower()
        for code, name in PROVINCES.items():
            if name.lower() in low or (code == 'QC' and 'québec' in low):
                return code, 'address'
    default = (S.get('tax.default_province') or 'ON').strip().upper()[:2]
    return (default if default in PROVINCES else 'ON'), 'default'


# ═══════════════════════════════════════════════════════════════════════════
# Totals
# ═══════════════════════════════════════════════════════════════════════════

def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def _first_name(u):
    if not u:
        return ''
    return (u.first_name or (u.name or '').split(' ')[0] or '').strip()


def _display_name(u):
    if not u:
        return ''
    first = _first_name(u)
    last = (u.last_name or '').strip()
    if not last and u.name and ' ' in u.name.strip():
        last = u.name.strip().split(' ')[-1]
    return f'{first} {last[0]}.' if last else first


def _full_name(u):
    if not u:
        return ''
    if u.first_name or u.last_name:
        return ' '.join(x for x in ((u.first_name or '').strip(), (u.last_name or '').strip()) if x)
    return (u.name or '').strip()


def payment_method_label(rp):
    if not rp or not rp.payment_method_last4:
        return 'Card'
    brand = CARD_BRANDS.get((rp.payment_method_brand or '').lower(), (rp.payment_method_brand or 'Card').title())
    return f'{brand} •••• {rp.payment_method_last4}'


def ride_payment_for(ride_type, ride_id):
    """Latest ride payment that actually took money."""
    return (RidePayment.query.filter_by(ride_type=ride_type, ride_id=ride_id, purpose='ride')
            .filter(RidePayment.capture_status.in_(CAPTURED_STATES))
            .order_by(RidePayment.id.desc()).first())


def _legacy_paid(ride_type, ride):
    paid = str(getattr(ride, 'stripe_paid', '') or '').lower() in ('yes', 'true', '1')
    return paid or (getattr(ride, 'payment_status', '') or '').lower() == 'paid'


def _times(ride_type, ride):
    if ride_type == 'rideshare_booking':
        trip = R.load('rideshare_trip', ride.trip_id)
        start = ride.checked_in_at or trip.started_at
        end = ride.dropped_off_at or trip.completed_at
    else:
        start, end = ride.started_at, ride.completed_at
    return start, end


def _breadcrumbs(ride_type, ride, limit=2000):
    try:
        from backend.models.safety import RideLocation
    except ImportError:
        return []
    drv = R.driver_id(ride_type, ride)
    rt, rid = ride_type, ride.id
    if ride_type == 'rideshare_booking':      # the driver streams on the trip
        rt, rid = 'rideshare_trip', ride.trip_id
    q = RideLocation.query.filter(RideLocation.ride_id == rid, RideLocation.ride_type.in_((rt, ride_type)))
    if drv:
        q = q.filter(RideLocation.user_id == drv)
    start, end = _times(ride_type, ride)
    if start:
        q = q.filter(RideLocation.recorded_at >= start)
    if end:
        q = q.filter(RideLocation.recorded_at <= end)
    return [(float(p.lat), float(p.lng)) for p in q.order_by(RideLocation.recorded_at.asc()).limit(limit)]


def _path_distance_m(points):
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += R.haversine_m(a, b) or 0
    return int(round(total))


def _initial_ask_cents(ride_type, ride, fare):
    """What was asked before negotiating: the driver's first counter-offer
    (car hire) or the posted seat price (rideshare)."""
    if ride_type == 'carhire':
        try:
            from backend.models.negotiation_record import NegotiationRecord
            first_driver = (NegotiationRecord.query.filter_by(negotiation_id=ride.id)
                            .filter(NegotiationRecord.last_negotiator_id == ride.driver_id)
                            .order_by(NegotiationRecord.id.asc()).first())
            if first_driver and first_driver.price:
                return int(first_driver.price)
        except Exception:
            db.session.rollback()
        return int(ride.initial_price or 0)
    if ride_type == 'scheduled':
        return int(ride.driver_proposed_price or 0)
    if ride_type == 'rideshare_booking':
        trip = R.load('rideshare_trip', ride.trip_id)
        if trip.price_per_seat_cents:
            return int(trip.price_per_seat_cents) * int(ride.slot_count or 1)
    return 0


def ride_info(ride_type, ride, province):
    customer_id = (R.customer_ids(ride_type, ride) or [None])[0]
    driver_id = R.driver_id(ride_type, ride)
    customer = db.session.get(AdminUser, customer_id) if customer_id else None
    driver = db.session.get(AdminUser, driver_id) if driver_id else None
    veh = R.vehicle_card(driver) if driver else None
    vehicle = ''
    plate = ''
    if veh:
        vehicle = ' '.join(str(x) for x in (veh.get('color'), veh.get('year'), veh.get('make'), veh.get('model')) if x)
        plate = veh.get('plate') or ''
    pickup, dropoff = R.addresses(ride_type, ride)
    start, end = _times(ride_type, ride)
    crumbs = _breadcrumbs(ride_type, ride)
    distance_m = getattr(ride, 'distance_m', None)
    estimated = False
    if not distance_m and len(crumbs) >= 2:
        distance_m = _path_distance_m(crumbs)
    if not distance_m:
        d = R.haversine_m(R.pickup_point(ride_type, ride), R.dropoff_point(ride_type, ride))
        if d:
            distance_m, estimated = int(round(d)), True
    duration_s = getattr(ride, 'duration_s', None)
    if not duration_s and start and end and end >= start:
        duration_s = int((end - start).total_seconds())
    photo = None
    if driver and driver.avatar:
        try:
            from backend.models.user import resolve_media_url
            photo = resolve_media_url(driver.avatar)
        except Exception:
            photo = None
    seats = int(getattr(ride, 'slot_count', 0) or 0) if ride_type == 'rideshare_booking' else None
    return {
        'ride_type': ride_type, 'ride_id': ride.id,
        'ride_ref': f'{ride_type.upper().replace("_", "-")}-{ride.id}',
        'trip_id': getattr(ride, 'trip_id', None),
        'rider_name': _full_name(customer), 'rider_first': _first_name(customer),
        'driver_name': _display_name(driver), 'driver_first': _first_name(driver), 'driver_photo': photo,
        'vehicle': vehicle, 'plate': plate, 'seats': seats,
        'pickup_address': pickup or '', 'dropoff_address': dropoff or '',
        'pickup_at': _iso(start), 'dropoff_at': _iso(end),
        'distance_m': int(distance_m) if distance_m else None, 'distance_estimated': estimated,
        'duration_s': int(duration_s) if duration_s else None,
        'province': province, 'timezone': PROVINCE_TZ.get(province, 'UTC'),
    }


def compute_totals(ride_type, ride, rp=None, *, at=None):
    """Snapshot of every number on the receipt (integer cents)."""
    at = at or datetime.utcnow()
    inclusive = bool(S.get('pricing.tax_inclusive'))
    province, source = province_of(ride_type, ride)
    rate = rate_for(province, at.date())
    comps = tax_components(rate)
    meta = (rp.meta or {}) if rp else {}

    if rp is not None:
        fare = int(rp.fare_cents or 0)
        fees = int(rp.fees_cents or 0)
        charged = int(rp.amount_captured_cents or 0)
    else:
        fare = int(R.fare_cents(ride_type, ride) or 0)
        fees = 0
        charged = fare
    waiting = int(meta.get('waiting_fee_cents') or 0)
    tolls = int(meta.get('tolls_cents') or 0)
    discount = abs(int(meta.get('discount_cents') or 0))
    if not waiting and getattr(ride, 'waiting_fee_cents', None):
        wf = int(ride.waiting_fee_cents)
        if fare + wf + fees + tolls - discount == charged:   # only when it was actually charged
            waiting = wf

    seats = int(getattr(ride, 'slot_count', 0) or 1) if ride_type == 'rideshare_booking' else None
    if ride_type == 'rideshare_booking':
        per = fare // seats if seats else fare
        fare_label = f'Seat fare ({seats} × {fmt(per)})' if seats and seats > 1 else 'Seat fare'
    else:
        fare_label = 'Negotiated fare'
    items = [('fare', fare_label, fare)]
    if waiting:
        items.append(('waiting', 'Waiting time', waiting))
    if fees:
        items.append(('booking_fee', 'Booking / service fee', fees))
    if tolls:
        items.append(('tolls', 'Tolls / airport fee', tolls))
    if discount:
        items.append(('discount', 'Discounts / credits', -discount))
    items_total = sum(a for _, _, a in items)
    if rp is not None and items_total != charged:
        # e.g. capture limited to the authorized amount — show it, never hide it
        items.append(('adjustment', 'Adjustment', charged - items_total))
        items_total = charged

    if inclusive:
        subtotal, taxes, tax_total = split_tax(items_total, comps, inclusive=True)
        pre = allocate(subtotal, [a for _, _, a in items])
        lines = [{'code': c, 'label': lbl, 'amount_cents': p, 'amount_incl_tax_cents': a}
                 for (c, lbl, a), p in zip(items, pre)]
        ride_total = items_total
    else:
        subtotal = items_total
        _, taxes, tax_total = split_tax(subtotal, comps, inclusive=False)
        lines = [{'code': c, 'label': lbl, 'amount_cents': a, 'amount_incl_tax_cents': None} for c, lbl, a in items]
        ride_total = subtotal + tax_total

    tips = (RidePayment.query.filter_by(ride_type=ride_type, ride_id=ride.id, purpose='tip')
            .filter(RidePayment.capture_status.in_(CAPTURED_STATES)).all())
    tip = sum(int(t.amount_captured_cents or 0) for t in tips)
    total = ride_total + tip

    refunds = []
    if rp is not None:
        for r in (Refund.query.filter_by(ride_payment_id=rp.id, kind='refund', status='succeeded')
                  .order_by(Refund.id.asc())):
            refunds.append({'id': r.id, 'amount_cents': int(r.amount_cents), 'reason': r.reason or '',
                            'at': _iso(r.processed_at or r.created_at)})
    refunded = sum(r['amount_cents'] for r in refunds)

    ask = _initial_ask_cents(ride_type, ride, fare)
    commission_pct = S.get_int('pricing.commission_pct')
    driver_fare = min(fare, charged) if rp is not None else fare
    warnings = []
    if not inclusive and rp is not None and ride_total != charged:
        warnings.append('tax_exclusive_total_differs_from_captured_amount')
    return {
        'version': 1,
        'currency': 'cad',
        'tax_inclusive': inclusive,
        'province': province, 'province_name': PROVINCES.get(province, province), 'province_source': source,
        'lines': lines,
        'items_total_cents': items_total,
        'subtotal_cents': subtotal,
        'taxes': taxes,
        'tax_cents': tax_total,
        'ride_total_cents': ride_total,
        'tip_cents': tip,
        'total_cents': total,
        'charged_cents': charged + tip,
        'payment_method': payment_method_label(rp) if rp is not None else 'Card',
        'authorized_at': _iso(rp.authorized_at) if rp is not None else None,
        'captured_at': _iso(rp.captured_at) if rp is not None else _iso(getattr(ride, 'payment_completed_at', None)),
        'refunds': refunds,
        'refunded_cents': refunded,
        'net_total_cents': total - refunded,
        'registration': {'gst_hst': S.get('company.gst_number') or '', 'qst': S.get('company.qst_number') or ''},
        'company': {'legal_name': S.get('company.legal_name'), 'address': S.get('company.address'),
                    'website': S.get('company.website'), 'support_email': S.get('safety.support_email'),
                    'support_phone': S.get('safety.support_phone')},
        'negotiation': {'initial_ask_cents': ask, 'saved_cents': max(0, ask - fare) if ask else 0},
        'ride': ride_info(ride_type, ride, province),
        'internal': {'ride_payment_id': rp.id if rp is not None else None,
                     'intent_id': rp.intent_id if rp is not None else None,
                     'tip_intent_ids': [t.intent_id for t in tips if t.intent_id],
                     'commission_pct': commission_pct, 'driver_fare_cents': driver_fare,
                     'commission_cents': pct_of(driver_fare, commission_pct),
                     'legacy_payment': rp is None},
        'warnings': warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Document numbers
# ═══════════════════════════════════════════════════════════════════════════

DOC_PREFIX = {'receipt': 'NR', 'credit_note': 'NR-CN', 'tip': 'NR-TIP'}


def _ensure_sequence_row(doc_type, year):
    """Create the (doc_type, year) row in its own short transaction so the
    later SELECT … FOR UPDATE always locks an existing row (no gap locks)."""
    with db.engine.connect() as conn:
        exists = conn.execute(text('SELECT id FROM document_sequences WHERE doc_type=:t AND year=:y'),
                              {'t': doc_type, 'y': year}).first()
        if not exists:
            try:
                conn.execute(text('INSERT INTO document_sequences (doc_type, year, last_value) VALUES (:t, :y, 0)'),
                             {'t': doc_type, 'y': year})
                conn.commit()
            except IntegrityError:
                conn.rollback()


def _allocate_number(doc_type, year):
    """Call inside the transaction that inserts the document."""
    seq = (DocumentSequence.query.filter_by(doc_type=doc_type, year=year)
           .with_for_update().populate_existing().one())
    seq.last_value = int(seq.last_value or 0) + 1
    return f'{DOC_PREFIX[doc_type]}-{year}-{seq.last_value:06d}'


def _is_retryable(exc):
    s = str(getattr(exc, 'orig', exc))
    return '1213' in s or '1205' in s or 'Deadlock' in s or 'Lock wait timeout' in s


def _insert_numbered(doc_type, build, find_existing):
    """Allocate a number and insert the document atomically. `build(number)`
    returns the new row; `find_existing()` returns a row issued meanwhile."""
    year = datetime.utcnow().year
    _ensure_sequence_row(doc_type, year)
    for attempt in range(6):
        try:
            db.session.rollback()               # fresh snapshot
            number = _allocate_number(doc_type, year)
            dup = find_existing(lock=True)
            if dup is not None:
                db.session.rollback()           # give the number back
                return find_existing(lock=False), False
            row = build(number)
            db.session.add(row)
            db.session.commit()
            return row, True
        except IntegrityError:
            db.session.rollback()
            row = find_existing(lock=False)
            if row is not None:
                return row, False
            raise
        except OperationalError as e:
            db.session.rollback()
            if not _is_retryable(e) or attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise ReceiptError('Could not allocate a document number')


# ═══════════════════════════════════════════════════════════════════════════
# Rendering
# ═══════════════════════════════════════════════════════════════════════════

_pdf_env = Environment(loader=FileSystemLoader(PDF_TEMPLATE_DIR), autoescape=select_autoescape(['html']))


def local_time(iso_value, tz_name, with_date=True):
    if not iso_value:
        return ''
    try:
        dt = datetime.strptime(iso_value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return str(iso_value)
    try:
        from zoneinfo import ZoneInfo
        dt = dt.astimezone(ZoneInfo(tz_name or 'UTC'))
    except Exception:
        pass
    fmt_s = '%a %b %d, %Y · %I:%M %p %Z' if with_date else '%I:%M %p %Z'
    return dt.strftime(fmt_s).replace(' 0', ' ')


def human_duration(seconds):
    if not seconds:
        return ''
    m = max(1, int(round(seconds / 60)))
    return f'{m // 60} h {m % 60} min' if m >= 60 else f'{m} min'


def human_distance(meters, estimated=False):
    if not meters:
        return ''
    km = meters / 1000
    s = f'{km:.1f} km' if km < 100 else f'{int(round(km))} km'
    return f'≈ {s}' if estimated else s


_LOGO_URI = None


def logo_data_uri():
    """The brand logo embedded as a data URI (the PDF renderer never fetches
    remote resources). backend/static/brand/logo.png — replace with the final
    artwork (same name); '' falls back to the text wordmark."""
    global _LOGO_URI
    if _LOGO_URI is None:
        path = os.path.join(BACKEND_DIR, 'static', 'brand', 'logo.png')
        try:
            with open(path, 'rb') as f:
                _LOGO_URI = 'data:image/png;base64,' + base64.b64encode(f.read()).decode()
        except OSError:
            _LOGO_URI = ''
    return _LOGO_URI


def _helpers():
    return {'money': fmt, 'local_time': local_time, 'human_duration': human_duration,
            'human_distance': human_distance, 'logo_data_uri': logo_data_uri()}


def _pdf_fetcher():
    """Never touch the network or the disk while rendering (fast + private):
    only data: URIs (the embedded logo) are allowed."""
    try:
        from weasyprint.urls import URLFetcher
        return URLFetcher(allowed_protocols=('data',), timeout=2)
    except ImportError:   # older WeasyPrint: function-style fetcher
        def fetch(url, *args, **kwargs):
            if url.startswith('data:'):
                from weasyprint import default_url_fetcher
                return default_url_fetcher(url, *args, **kwargs)
            raise ValueError(f'External resource blocked in PDF: {url[:60]}')
        return fetch


def render_pdf(template, context):
    html = _pdf_env.get_template(template).render(**_helpers(), **context)
    from weasyprint import HTML
    return HTML(string=html, url_fetcher=_pdf_fetcher(), base_url=PDF_TEMPLATE_DIR).write_pdf()


def _web_base():
    return (os.getenv('PUBLIC_WEB_BASE_URL') or S.get('company.website') or 'https://negoride.ca').rstrip('/')


def open_link(deep_link):
    return f"{_web_base()}/open?link={quote(deep_link, safe='')}"


def rating_links(ride_type, ride_id):
    return [{'stars': n, 'url': open_link(f'negoride://rate/{ride_type}/{ride_id}?stars={n}')} for n in range(1, 6)]


def _receipt_pdf_context(receipt, totals, driver_copy=False):
    return {'doc': 'receipt', 'number': receipt.number, 'issued_at': _iso(receipt.issued_at), 't': totals,
            'r': totals.get('ride') or {}, 'policy_url': f'{_web_base()}/cancellation-policy',
            'web_base': _web_base(), 'driver_copy': driver_copy}


def render_receipt_pdf(receipt, viewer='customer'):
    """The stored PDF is the customer's. `viewer='driver'` renders the driver
    copy on the fly: rider first name only, no payment method."""
    if viewer == 'driver':
        return render_pdf('receipt.html', _receipt_pdf_context(receipt, public_totals(receipt.totals, 'driver'),
                                                               driver_copy=True))
    return render_pdf('receipt.html', _receipt_pdf_context(receipt, receipt.totals))


def ensure_pdf(receipt):
    """Bytes of the receipt PDF; re-renders from the immutable snapshot if the
    file is missing (same number, same totals)."""
    blob = read_private(receipt.pdf_path)
    if blob:
        return blob
    blob = render_receipt_pdf(receipt)
    rel = receipt.pdf_path or f'receipts/{receipt.issued_at.year}/{receipt.number}.pdf'
    save_private(rel, blob)
    if receipt.pdf_path != rel:
        receipt.pdf_path = rel
        db.session.commit()
    return blob


# ── Static map ─────────────────────────────────────────────────────────────

def encode_polyline(points):
    """Google encoded polyline algorithm."""
    out, prev_lat, prev_lng = [], 0, 0
    for lat, lng in points:
        ilat, ilng = int(round(lat * 1e5)), int(round(lng * 1e5))
        for v in (ilat - prev_lat, ilng - prev_lng):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev_lat, prev_lng = ilat, ilng
    return ''.join(out)


def _downsample(points, max_points=90):
    if len(points) <= max_points:
        return points
    step = (len(points) - 1) / (max_points - 1)
    return [points[int(round(i * step))] for i in range(max_points)]


def _sign_url(url, secret):
    parsed = urlparse(url)
    to_sign = f'{parsed.path}?{parsed.query}'
    key = base64.urlsafe_b64decode(secret + '=' * (-len(secret) % 4))
    sig = base64.urlsafe_b64encode(hmac.new(key, to_sign.encode(), hashlib.sha1).digest()).decode()
    return f'{url}&signature={sig}'


def static_map_url(ride_type, ride):
    """Google Static Maps image of the route (breadcrumb polyline). None when
    no key is configured. Use a key restricted to the Static Maps API (and a
    URL-signing secret) because the URL is visible in the email."""
    key = (os.getenv('GOOGLE_MAPS_STATIC_KEY') or os.getenv('GOOGLE_MAPS_SERVER_KEY') or '').strip()
    if not key:
        return None
    pts = _breadcrumbs(ride_type, ride)
    a, b = R.pickup_point(ride_type, ride), R.dropoff_point(ride_type, ride)
    if len(pts) < 2:
        pts = [p for p in (a, b) if p]
    if not pts:
        return None
    params = [('size', '600x300'), ('scale', '2'), ('maptype', 'roadmap')]
    if len(pts) >= 2:
        params.append(('path', f'color:0xEF9B11ff|weight:5|enc:{encode_polyline(_downsample(pts))}'))
    if a:
        params.append(('markers', f'color:0x16a34a|label:A|{a[0]:.6f},{a[1]:.6f}'))
    if b:
        params.append(('markers', f'color:0xdc2626|label:B|{b[0]:.6f},{b[1]:.6f}'))
    params.append(('key', key))
    url = 'https://maps.googleapis.com/maps/api/staticmap?' + urlencode(params)
    secret = (os.getenv('GOOGLE_MAPS_URL_SIGNING_SECRET') or '').strip()
    return _sign_url(url, secret) if secret else url


# ═══════════════════════════════════════════════════════════════════════════
# Email + delivery log
# ═══════════════════════════════════════════════════════════════════════════

def _email_context(receipt, ride_type, ride):
    t = receipt.totals
    rt, rid = receipt.ride_type, receipt.ride_id
    info = t.get('ride') or {}
    return {
        'number': receipt.number, 't': t, 'r': info, 'lang': 'en',
        'first_name': info.get('rider_first') or 'there',
        'map_url': static_map_url(ride_type, ride) if ride is not None else None,
        'ratings': rating_links(rt, rid),
        'tip_url': open_link(f'negoride://tip/{rt}/{rid}'),
        'receipt_url': open_link(f'negoride://receipt/{rt}/{rid}'),
        'lost_item_url': open_link(f'negoride://support/new?category=lost_item&ride_type={rt}&ride_id={rid}'),
        'report_url': open_link(f'negoride://support/new?category=ride_issue&ride_type={rt}&ride_id={rid}'),
        'policy_url': f'{_web_base()}/cancellation-policy',
        **_helpers(),
    }


def _find_notification(user_id, event_key, dedupe):
    return (Notification.query.filter_by(user_id=user_id, event_key=event_key)
            .filter(Notification.data['dedupe_key'].as_string() == dedupe).first())


def _log_email(user_id, event_key, dedupe, title, body, data, deep_link, results):
    """Inbox row (once) + one email delivery row per send, so the admin
    notification log shows every receipt email and its provider id."""
    n = _find_notification(user_id, event_key, dedupe)
    now = datetime.utcnow()
    if n is None:
        n = Notification(user_id=user_id, event_key=event_key, event_group='payment' if event_key != 'driver.statement'
                         else 'payouts', title=title[:255], body=body, deep_link=deep_link, is_critical=False,
                         data={**data, 'event': event_key, 'route': 'receipt', 'dedupe_key': dedupe})
        db.session.add(n)
        db.session.flush()
        n.data = {**n.data, 'notification_id': n.id}
        db.session.add(NotificationDelivery(notification_id=n.id, channel='inbox', status='delivered', attempts=1,
                                            sent_at=now, delivered_at=now))
    for ok, provider_id, error in results:
        db.session.add(NotificationDelivery(
            notification_id=n.id, channel='email', status='sent' if ok else 'failed', attempts=1,
            provider_message_id=provider_id, error=(error or None) and str(error)[:1000],
            sent_at=now if ok else None, failed_at=None if ok else now))
    return n


def _send(to, subject, html, text, attachments, tag):
    from backend.services.notify import email_provider
    try:
        return True, email_provider.send(to, subject, html, text, attachments=attachments, tag=tag), None
    except Exception as exc:  # EmailError or transport failure
        log.warning('Email %s to %s failed: %s', tag, to, exc)
        return False, None, str(exc)


def thanks_subject(first_name):
    return f'Thanks for riding with NegoRide, {first_name or "there"} 🚗'


def _send_receipt_email(receipt, ride=None):
    """Returns True when every message went out."""
    from backend.services.notify.templates import render
    customer = db.session.get(AdminUser, receipt.customer_id)
    if customer is not None and getattr(customer, 'email_bounced_at', None):
        _log_suppressed(customer, 'ride.receipt', f'receipt-{receipt.id}', f'Your receipt {receipt.number}',
                        f'Total charged {fmt(receipt.total_cents)}', {'receipt_id': receipt.id, 'number': receipt.number},
                        f'negoride://receipt/{receipt.ride_type}/{receipt.ride_id}')
        return None
    if not customer or not customer.email:
        _log_email(receipt.customer_id, 'ride.receipt', f'receipt-{receipt.id}', f'Your receipt {receipt.number}',
                   f'Total charged {fmt(receipt.total_cents)}', {'receipt_id': receipt.id, 'number': receipt.number},
                   f'negoride://receipt/{receipt.ride_type}/{receipt.ride_id}', [(False, None, 'no email address')])
        db.session.commit()
        return False
    if ride is None:
        try:
            ride = R.load(receipt.ride_type, receipt.ride_id)
        except R.RideNotFound:
            ride = None
    pdf = ensure_pdf(receipt)
    attach = [(f'NegoRide-receipt-{receipt.number}.pdf', pdf, 'application/pdf')]
    ctx = _email_context(receipt, receipt.ride_type, ride)
    first = ctx['first_name']
    combined = S.flag('combined_receipt_email')
    results = []
    if combined:
        subject = thanks_subject(first)
        html, txt = render('ride_receipt', {**ctx, 'title': subject, 'show_thanks': True, 'show_receipt': True,
                                            'preheader': f'Receipt {receipt.number} · {fmt(receipt.total_cents)} · PDF attached'})
        results.append(_send(customer.email, subject, html, txt, attach, 'ride.receipt'))
    else:
        subject = thanks_subject(first)
        html, txt = render('ride_receipt', {**ctx, 'title': subject, 'show_thanks': True, 'show_receipt': False,
                                            'preheader': 'Thanks for riding with NegoRide'})
        results.append(_send(customer.email, subject, html, txt, [], 'ride.thanks'))
        rsub = f'Your NegoRide receipt {receipt.number}'
        html, txt = render('ride_receipt', {**ctx, 'title': rsub, 'show_thanks': False, 'show_receipt': True,
                                            'preheader': f'{fmt(receipt.total_cents)} · PDF attached'})
        results.append(_send(customer.email, rsub, html, txt, attach, 'ride.receipt'))
    _log_email(customer.id, 'ride.receipt', f'receipt-{receipt.id}', f'Your receipt {receipt.number}',
               f'Thanks for riding with NegoRide. Total charged {fmt(receipt.total_cents)}.',
               {'receipt_id': receipt.id, 'number': receipt.number, 'total': fmt(receipt.total_cents),
                'ride_type': receipt.ride_type, 'ride_id': receipt.ride_id},
               f'negoride://receipt/{receipt.ride_type}/{receipt.ride_id}', results)
    ok = all(r[0] for r in results)
    if ok:
        receipt.emailed_at = datetime.utcnow()
        receipt.email_count = int(receipt.email_count or 0) + 1
    db.session.commit()
    return ok


def _log_suppressed(user, event_key, dedupe, title, body, data, deep_link):
    """Email suppressed after a hard bounce / spam complaint: inbox row + a
    failed email delivery explaining why; no retries."""
    _log_email(user.id, event_key, dedupe, title, body, data, deep_link,
               [(False, None, f'suppressed: {user.email_bounce_reason or "email bounced"}')])
    db.session.commit()


def _claim_first_send(receipt_id):
    """Atomically mark a never-emailed receipt as being sent (one sender wins)."""
    res = db.session.execute(text('UPDATE receipts SET emailed_at=:now WHERE id=:id AND emailed_at IS NULL'),
                             {'now': datetime.utcnow(), 'id': receipt_id})
    db.session.commit()
    return res.rowcount == 1


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════

def find_receipt(ride_type, ride_id, lock=False):
    q = Receipt.query.filter_by(ride_type=ride_type, ride_id=int(ride_id))
    if lock:
        q = q.with_for_update()
    return q.first()


def issue(ride_type, ride_id):
    """Create the receipt row (numbered) + PDF. Idempotent. No email."""
    rt = R.normalize_type(ride_type)
    if rt not in RECEIPT_RIDE_TYPES:
        return None
    existing = find_receipt(rt, ride_id)
    if existing is not None:
        return existing
    ride = R.load(rt, ride_id)
    rp = ride_payment_for(rt, ride.id)
    if rp is None:
        has_any = RidePayment.query.filter_by(ride_type=rt, ride_id=ride.id, purpose='ride').first()
        if has_any is not None or not _legacy_paid(rt, ride):
            log.info('No captured payment for %s/%s — no receipt', rt, ride_id)
            return None
    totals = compute_totals(rt, ride, rp)
    if totals['total_cents'] <= 0:
        return None
    customer_id = rp.customer_id if rp is not None else (R.customer_ids(rt, ride) or [None])[0]
    if not customer_id:
        return None

    def build(number):
        return Receipt(number=number, ride_type=rt, ride_id=ride.id, ride_payment_id=rp.id if rp else None,
                       customer_id=customer_id, driver_id=R.driver_id(rt, ride), currency='cad',
                       total_cents=totals['total_cents'], totals=totals, issued_at=datetime.utcnow())

    receipt, created = _insert_numbered('receipt', build, lambda lock: find_receipt(rt, ride.id, lock=lock))
    if created:
        try:
            blob = render_receipt_pdf(receipt)
            receipt.pdf_path = save_private(f'receipts/{receipt.issued_at.year}/{receipt.number}.pdf', blob)
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception('PDF rendering failed for receipt %s (will retry on first download/send)', receipt.number)
    return receipt


def issue_and_send(ride_type, ride_id):
    """Job (spec §13): issue the receipt and send the thank-you + receipt email
    once. Safe to run any number of times."""
    receipt = issue(ride_type, ride_id)
    if receipt is None:
        return None
    if receipt.emailed_at is None and _claim_first_send(receipt.id):
        db.session.refresh(receipt)
        receipt.emailed_at = None           # set for real after a successful send
        ok = False
        try:
            ok = _send_receipt_email(receipt)
        finally:
            if ok is None:          # suppressed (bounced address): no email, no retry
                db.session.rollback()
                db.session.execute(text('UPDATE receipts SET emailed_at=NULL WHERE id=:id AND email_count=0'),
                                   {'id': receipt.id})
                db.session.commit()
            elif not ok:
                db.session.rollback()
                db.session.execute(text('UPDATE receipts SET emailed_at=NULL WHERE id=:id AND email_count=0'),
                                   {'id': receipt.id})
                db.session.commit()
                jobs.enqueue_in(120, retry_email, receipt.id, 2)
    return receipt


def retry_email(receipt_id, attempt=2):
    receipt = db.session.get(Receipt, receipt_id)
    if receipt is None or receipt.emailed_at is not None:
        return
    if _claim_first_send(receipt.id):
        db.session.refresh(receipt)
        receipt.emailed_at = None
        ok = _send_receipt_email(receipt)
        if not ok:
            db.session.execute(text('UPDATE receipts SET emailed_at=NULL WHERE id=:id AND email_count=0'),
                               {'id': receipt.id})
            db.session.commit()
            if ok is not None and attempt < MAX_EMAIL_ATTEMPTS:
                jobs.enqueue_in(120 * attempt, retry_email, receipt.id, attempt + 1)


def resend(receipt_id, actor=None):
    """Re-email the SAME receipt (same number, same totals). Audited when an
    admin (or any actor) triggers it."""
    receipt = db.session.get(Receipt, int(receipt_id))
    if receipt is None:
        raise ReceiptError('Receipt not found')
    ok = bool(_send_receipt_email(receipt))
    if actor is not None:
        from backend.services.audit import audit
        audit('receipt.resend', actor, 'receipt', receipt.id,
              meta={'number': receipt.number, 'ride_type': receipt.ride_type, 'ride_id': receipt.ride_id,
                    'sent': ok, 'email_count': receipt.email_count})
        db.session.commit()
    return ok


def resend_job(receipt_id, actor_id=None):
    """Job behind the admin 'Resend' button (the request returns 202)."""
    actor = db.session.get(AdminUser, actor_id) if actor_id else None
    try:
        return resend(receipt_id, actor=actor)
    except ReceiptError:
        return False


# ── Credit notes ────────────────────────────────────────────────────────────

def credit_note_totals(receipt, refund, previously_credited):
    t = receipt.totals or {}
    amount = int(refund.amount_cents)
    comps = [(x['code'], x['label'], int(x['rate_bp'])) for x in (t.get('taxes') or [])]
    pre, taxes, tax_total = split_tax(amount, comps, inclusive=True)
    net_before = int(receipt.total_cents) - previously_credited
    return {
        'version': 1, 'currency': 'cad',
        'receipt_number': receipt.number, 'receipt_id': receipt.id, 'refund_id': refund.id,
        'reason': refund.reason or '', 'rule_id': refund.rule_id,
        'refunded_at': _iso(refund.processed_at or refund.created_at),
        'amount_cents': amount, 'subtotal_cents': pre, 'taxes': taxes, 'tax_cents': tax_total,
        'original_total_cents': int(receipt.total_cents),
        'previously_credited_cents': previously_credited,
        'net_total_cents': net_before - amount,
        'payment_method': t.get('payment_method'),
        'province': t.get('province'), 'province_name': t.get('province_name'),
        'registration': {'gst_hst': S.get('company.gst_number') or '', 'qst': S.get('company.qst_number') or ''},
        'company': t.get('company') or {},
        'ride': t.get('ride') or {},
    }


def render_credit_note_pdf(cn, receipt):
    return render_pdf('credit_note.html', {'doc': 'credit_note', 'number': cn.number, 'issued_at': _iso(cn.issued_at),
                                           't': cn.totals, 'r': (cn.totals or {}).get('ride') or {},
                                           'receipt_number': receipt.number, 'web_base': _web_base(),
                                           'policy_url': f'{_web_base()}/cancellation-policy'})


def ensure_credit_note_pdf(cn):
    blob = read_private(cn.pdf_path)
    if blob:
        return blob
    receipt = db.session.get(Receipt, cn.receipt_id)
    blob = render_credit_note_pdf(cn, receipt)
    rel = cn.pdf_path or f'credit_notes/{cn.issued_at.year}/{cn.number}.pdf'
    save_private(rel, blob)
    if cn.pdf_path != rel:
        cn.pdf_path = rel
        db.session.commit()
    return blob


def _send_credit_note_email(cn, receipt):
    from backend.services.notify.templates import render
    customer = db.session.get(AdminUser, cn.customer_id)
    results = []
    if customer is not None and getattr(customer, 'email_bounced_at', None):
        results.append((False, None, f'suppressed: {customer.email_bounce_reason or "email bounced"}'))
    elif customer and customer.email:
        pdf = ensure_credit_note_pdf(cn)
        subject = f'Credit note {cn.number} for your NegoRide receipt {receipt.number}'
        t = cn.totals or {}
        html, txt = render('credit_note', {'title': subject, 'first_name': _first_name(customer) or 'there',
                                           'number': cn.number, 'receipt_number': receipt.number, 't': t,
                                           'r': t.get('ride') or {}, 'preheader': f'Refund of {fmt(cn.amount_cents)}',
                                           'receipt_url': open_link(f'negoride://receipt/{receipt.ride_type}/{receipt.ride_id}'),
                                           **_helpers()})
        results.append(_send(customer.email, subject, html, txt,
                             [(f'NegoRide-credit-note-{cn.number}.pdf', pdf, 'application/pdf')], 'refund.credit_note'))
    else:
        results.append((False, None, 'no email address'))
    _log_email(cn.customer_id, 'refund.credit_note', f'credit-note-{cn.id}', f'Credit note {cn.number}',
               f'We refunded {fmt(cn.amount_cents)} for ride #{receipt.ride_id}.',
               {'credit_note_id': cn.id, 'number': cn.number, 'receipt_id': receipt.id,
                'ride_type': receipt.ride_type, 'ride_id': receipt.ride_id, 'amount': fmt(cn.amount_cents)},
               f'negoride://receipt/{receipt.ride_type}/{receipt.ride_id}', results)
    ok = all(r[0] for r in results)
    if ok:
        cn.emailed_at = datetime.utcnow()
    db.session.commit()
    return ok


def issue_credit_note_for_refund(refund_id):
    """Job: credit note NR-CN-YYYY-NNNNNN for a money-back refund on a ride that
    has a receipt. Idempotent (unique per refund). Never edits the receipt."""
    refund = db.session.get(Refund, int(refund_id))
    if refund is None or refund.kind != 'refund' or refund.status != 'succeeded' or refund.amount_cents <= 0:
        return None
    receipt = find_receipt(refund.ride_type, refund.ride_id)
    if receipt is None:
        return None

    def find(lock=False):
        q = CreditNote.query.filter_by(refund_id=refund.id)
        return (q.with_for_update() if lock else q).first()

    existing = find()
    if existing is None:
        def build(number):
            prev = sum(int(c.amount_cents) for c in CreditNote.query.filter_by(receipt_id=receipt.id))
            totals = credit_note_totals(receipt, refund, prev)
            return CreditNote(number=number, receipt_id=receipt.id, refund_id=refund.id,
                              customer_id=receipt.customer_id, amount_cents=int(refund.amount_cents),
                              tax_cents=totals['tax_cents'], reason=refund.reason, totals=totals,
                              issued_at=datetime.utcnow())
        cn, created = _insert_numbered('credit_note', build, find)
        if created:
            r = db.session.get(Refund, refund.id)
            r.credit_note_id = cn.id
            db.session.commit()
            try:
                blob = render_credit_note_pdf(cn, receipt)
                cn.pdf_path = save_private(f'credit_notes/{cn.issued_at.year}/{cn.number}.pdf', blob)
                db.session.commit()
            except Exception:
                db.session.rollback()
                log.exception('Credit note PDF failed for %s', cn.number)
    else:
        cn = existing
    if cn.emailed_at is None:
        claimed = db.session.execute(text('UPDATE credit_notes SET emailed_at=:n WHERE id=:id AND emailed_at IS NULL'),
                                     {'n': datetime.utcnow(), 'id': cn.id}).rowcount == 1
        db.session.commit()
        if claimed:
            db.session.refresh(cn)
            cn.emailed_at = None
            if not _send_credit_note_email(cn, receipt):
                db.session.execute(text('UPDATE credit_notes SET emailed_at=NULL WHERE id=:id'), {'id': cn.id})
                db.session.commit()
    return cn


# ═══════════════════════════════════════════════════════════════════════════
# Serialization (API)
# ═══════════════════════════════════════════════════════════════════════════

def public_totals(totals, viewer='customer'):
    t = {k: v for k, v in (totals or {}).items() if k not in ('internal', 'warnings')}
    if viewer == 'driver':
        t.pop('payment_method', None)
        t['ride'] = {k: v for k, v in (t.get('ride') or {}).items() if k not in ('rider_name',)}
    return t


def receipt_payload(receipt, viewer='customer', base_path=None):
    cns = CreditNote.query.filter_by(receipt_id=receipt.id).order_by(CreditNote.id.asc()).all()
    credited = sum(int(c.amount_cents) for c in cns)
    rt, rid = receipt.ride_type, receipt.ride_id
    return {
        'id': receipt.id, 'number': receipt.number, 'ride_type': rt, 'ride_id': rid,
        'currency': receipt.currency, 'issued_at': _iso(receipt.issued_at), 'voided_at': _iso(receipt.voided_at),
        'total_cents': int(receipt.total_cents), 'total': fmt(receipt.total_cents),
        'credited_cents': credited, 'net_total_cents': int(receipt.total_cents) - credited,
        'emailed_at': _iso(receipt.emailed_at),
        'totals': public_totals(receipt.totals, viewer),
        'credit_notes': [{'id': c.id, 'number': c.number, 'amount_cents': int(c.amount_cents),
                          'tax_cents': int(c.tax_cents or 0), 'reason': c.reason, 'issued_at': _iso(c.issued_at)}
                         for c in cns],
        # Tips paid after the receipt was issued have their own documents
        # (NR-TIP-…); tips already on the receipt stay in totals.tip_cents.
        'tips': tips_section(rt, rid),
        'pdf_url': base_path or f'/api/rides/{rt}/{rid}/receipt.pdf',
    }


def tips_section(ride_type, ride_id):
    rows = (TipReceipt.query.filter_by(ride_type=ride_type, ride_id=int(ride_id))
            .order_by(TipReceipt.id.asc()).all())
    items = [{'id': t.id, 'number': t.number, 'amount_cents': int(t.amount_cents), 'currency': t.currency,
              'paid_at': (t.totals or {}).get('paid_at'), 'issued_at': _iso(t.issued_at),
              'pdf_url': f'/api/receipts/tips/{t.id}.pdf'} for t in rows]
    return {'items': items, 'total_cents': sum(i['amount_cents'] for i in items)}


# ═══════════════════════════════════════════════════════════════════════════
# Tip receipts (NR-TIP-YYYY-NNNNNN) — tips paid after the ride (§13, §17)
# ═══════════════════════════════════════════════════════════════════════════

def tip_totals(rp, ride_type, ride):
    info = {}
    province = None
    try:
        province, _ = province_of(ride_type, ride)
        info = ride_info(ride_type, ride, province)
    except Exception:
        db.session.rollback()
    return {
        'version': 1, 'currency': 'cad', 'amount_cents': int(rp.amount_captured_cents or rp.fare_cents or 0),
        'taxable': False, 'note': 'Tips are not subject to GST/HST and go 100 % to the driver.',
        'payment_method': payment_method_label(rp), 'paid_at': _iso(rp.captured_at or rp.authorized_at),
        'province': province, 'ride': info,
        'company': {'legal_name': S.get('company.legal_name'), 'address': S.get('company.address'),
                    'website': S.get('company.website'), 'support_email': S.get('safety.support_email'),
                    'support_phone': S.get('safety.support_phone')},
        'registration': {'gst_hst': S.get('company.gst_number') or '', 'qst': S.get('company.qst_number') or ''},
    }


def issue_tip_receipt(ride_payment_id):
    """Job after a tip is paid: numbered tip receipt + PDF + email. Idempotent
    (unique per ride payment)."""
    rp = db.session.get(RidePayment, int(ride_payment_id))
    if rp is None or rp.purpose != 'tip' or rp.capture_status not in CAPTURED_STATES:
        return None
    if rp.ride_type not in RECEIPT_RIDE_TYPES:
        return None
    ride = R.load(rp.ride_type, rp.ride_id)

    def find(lock=False):
        q = TipReceipt.query.filter_by(ride_payment_id=rp.id)
        return (q.with_for_update() if lock else q).first()

    tr = find()
    if tr is None:
        totals = tip_totals(rp, rp.ride_type, ride)
        base = find_receipt(rp.ride_type, rp.ride_id)

        def build(number):
            return TipReceipt(number=number, ride_payment_id=rp.id, ride_type=rp.ride_type, ride_id=rp.ride_id,
                              receipt_id=base.id if base else None, customer_id=rp.customer_id,
                              driver_id=rp.driver_id, amount_cents=totals['amount_cents'], totals=totals,
                              issued_at=datetime.utcnow())
        tr, created = _insert_numbered('tip', build, find)
        if created:
            try:
                tr.pdf_path = save_private(f'tip_receipts/{tr.issued_at.year}/{tr.number}.pdf', render_tip_pdf(tr))
                db.session.commit()
            except Exception:
                db.session.rollback()
                log.exception('Tip receipt PDF failed for %s', tr.number)
    if tr.emailed_at is None:
        claimed = db.session.execute(text('UPDATE tip_receipts SET emailed_at=:n WHERE id=:id AND emailed_at IS NULL'),
                                     {'n': datetime.utcnow(), 'id': tr.id}).rowcount == 1
        db.session.commit()
        if claimed:
            db.session.refresh(tr)
            if not _send_tip_email(tr):
                db.session.execute(text('UPDATE tip_receipts SET emailed_at=NULL WHERE id=:id'), {'id': tr.id})
                db.session.commit()
    return tr


def issue_tip_receipt_safe(ride_payment_id):
    if not S.flag('receipts_email'):
        return None
    try:
        return issue_tip_receipt(ride_payment_id)
    except Exception:
        db.session.rollback()
        log.exception('tip receipt failed for payment %s', ride_payment_id)
        return None


def render_tip_pdf(tr):
    t = tr.totals or {}
    return render_pdf('tip_receipt.html', {'doc': 'tip', 'number': tr.number, 'issued_at': _iso(tr.issued_at),
                                           't': t, 'r': t.get('ride') or {}, 'web_base': _web_base(),
                                           'policy_url': None})


def ensure_tip_pdf(tr):
    blob = read_private(tr.pdf_path)
    if blob:
        return blob
    blob = render_tip_pdf(tr)
    rel = tr.pdf_path or f'tip_receipts/{tr.issued_at.year}/{tr.number}.pdf'
    save_private(rel, blob)
    if tr.pdf_path != rel:
        tr.pdf_path = rel
        db.session.commit()
    return blob


def _send_tip_email(tr):
    from backend.services.notify.templates import render
    customer = db.session.get(AdminUser, tr.customer_id)
    t = tr.totals or {}
    info = t.get('ride') or {}
    results = []
    if customer is not None and getattr(customer, 'email_bounced_at', None):
        results.append((False, None, f'suppressed: {customer.email_bounce_reason or "email bounced"}'))
    elif customer and customer.email:
        subject = f'Your NegoRide tip receipt {tr.number}'
        html, txt = render('tip_receipt', {'title': subject, 'first_name': _first_name(customer) or 'there',
                                           'number': tr.number, 't': t, 'r': info,
                                           'preheader': f'{fmt(tr.amount_cents)} · 100 % to {info.get("driver_first") or "your driver"}',
                                           'receipt_url': open_link(f'negoride://receipt/{tr.ride_type}/{tr.ride_id}'),
                                           **_helpers()})
        results.append(_send(customer.email, subject, html, txt,
                             [(f'NegoRide-tip-{tr.number}.pdf', ensure_tip_pdf(tr), 'application/pdf')], 'tip.receipt'))
    else:
        results.append((False, None, 'no email address'))
    _log_email(tr.customer_id, 'tip.receipt', f'tip-receipt-{tr.id}', f'Tip receipt {tr.number}',
               f'Thanks! Your {fmt(tr.amount_cents)} tip went 100 % to {info.get("driver_first") or "your driver"}.',
               {'tip_receipt_id': tr.id, 'number': tr.number, 'ride_type': tr.ride_type, 'ride_id': tr.ride_id,
                'amount': fmt(tr.amount_cents)},
               f'negoride://receipt/{tr.ride_type}/{tr.ride_id}', results)
    ok = all(r[0] for r in results)
    if ok:
        tr.emailed_at = datetime.utcnow()
    db.session.commit()
    return ok
