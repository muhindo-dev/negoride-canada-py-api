"""Weekly driver earnings statements (spec §13.3 "Drivers").

`weekly_driver_statements()` is registered in jobs/scheduler.PERIODIC (weekly).
For the last complete ISO week (Mon 00:00 → Mon 00:00 UTC) every driver with
activity gets one statement row (unique per driver-week → idempotent), a PDF in
private storage and an email.

Figures (integer cents, CAD):
  gross_fares   fares of the rides receipted that week (the amount the driver
                was credited on, before commission — receipt snapshot)
  commission    platform commission on those fares (rate frozen on the receipt)
  tips, cancellation_fees, bonuses   wallet-ledger credits in the week
  fees          wallet-ledger debits other than payouts (clawbacks, penalties,
                background-check fees)
  gross = gross_fares + tips + cancellation_fees + bonuses
  net   = gross − commission − fees
  payouts       payout requests completed in the week (+ pending shown apart)
"""
import logging
from datetime import date, datetime, timedelta


from backend.models import db
from backend.models.money import Receipt
from backend.models.payout_request import PayoutRequest
from backend.models.statements import DriverStatement
from backend.models.transaction import Transaction
from backend.models.user import AdminUser
from backend.services import receipts as RC
from backend.services import settings_service as S
from backend.utils.money import fmt, to_cents

log = logging.getLogger('negoride.statements')

CREDIT_CATEGORIES = {'tip': 'tips', 'cancellation_fee': 'cancellation_fees',
                     'bonus': 'bonuses', 'referral_bonus': 'bonuses'}
DEBIT_FEE_CATEGORIES = ('clawback', 'penalty', 'background_check_fee', 'service_fee', 'rideshare_fee')


def last_week_start(today=None):
    today = today or datetime.utcnow().date()
    return today - timedelta(days=today.weekday() + 7)


def _window(week_start):
    start = datetime.combine(week_start, datetime.min.time())
    return start, start + timedelta(days=7)


def active_driver_ids(week_start):
    start, end = _window(week_start)
    ids = {r[0] for r in db.session.query(Receipt.driver_id)
           .filter(Receipt.issued_at >= start, Receipt.issued_at < end, Receipt.driver_id.isnot(None),
                   Receipt.voided_at.is_(None)).distinct()}
    cats = list(CREDIT_CATEGORIES) + list(DEBIT_FEE_CATEGORIES) + ['ride_earning', 'rideshare_earning']
    ids |= {int(r[0]) for r in db.session.query(Transaction.user_id)
            .filter(Transaction.created_at >= start, Transaction.created_at < end,
                    Transaction.user_type == 'driver', Transaction.category.in_(cats)).distinct()}
    ids |= {int(r[0]) for r in db.session.query(PayoutRequest.user_id)
            .filter(PayoutRequest.processed_at >= start, PayoutRequest.processed_at < end,
                    PayoutRequest.status == 'completed').distinct()}
    return sorted(i for i in ids if i)


def compute_statement(driver_id, week_start):
    start, end = _window(week_start)
    pct_default = S.get_int('pricing.commission_pct')
    trips = []
    for rc in (Receipt.query.filter(Receipt.driver_id == driver_id, Receipt.issued_at >= start,
                                    Receipt.issued_at < end, Receipt.voided_at.is_(None))
               .order_by(Receipt.issued_at.asc())):
        internal = (rc.totals or {}).get('internal') or {}
        fare = int(internal.get('driver_fare_cents') or 0)
        commission = int(internal.get('commission_cents') or 0)
        trips.append({'receipt_number': rc.number, 'ride_ref': ((rc.totals or {}).get('ride') or {}).get('ride_ref'),
                      'date': rc.issued_at.strftime('%Y-%m-%d'), 'fare_cents': fare, 'commission_cents': commission})
    credits = {'tips': 0, 'cancellation_fees': 0, 'bonuses': 0}
    fees = 0
    adjustments = []
    for tx in (Transaction.query.filter(Transaction.user_id == driver_id, Transaction.created_at >= start,
                                        Transaction.created_at < end)
               .order_by(Transaction.created_at.asc())):
        cents = to_cents(tx.amount)
        if tx.type == 'credit' and tx.category in CREDIT_CATEGORIES:
            credits[CREDIT_CATEGORIES[tx.category]] += cents
            adjustments.append({'date': tx.created_at.strftime('%Y-%m-%d'), 'description': tx.description,
                                'amount_cents': cents})
        elif tx.type == 'debit' and tx.category in DEBIT_FEE_CATEGORIES:
            fees += cents
            adjustments.append({'date': tx.created_at.strftime('%Y-%m-%d'), 'description': tx.description,
                                'amount_cents': -cents})
    payouts = sum(to_cents(p.net_amount) for p in PayoutRequest.query.filter(
        PayoutRequest.user_id == driver_id, PayoutRequest.status == 'completed',
        PayoutRequest.processed_at >= start, PayoutRequest.processed_at < end))
    pending = sum(to_cents(p.amount) for p in PayoutRequest.query.filter(
        PayoutRequest.user_id == driver_id, PayoutRequest.status.in_(('pending', 'processing')),
        PayoutRequest.requested_at >= start, PayoutRequest.requested_at < end))
    gross_fares = sum(t['fare_cents'] for t in trips)
    commission = sum(t['commission_cents'] for t in trips)
    gross = gross_fares + sum(credits.values())
    return {
        'version': 1, 'currency': 'cad',
        'period_start': week_start.isoformat(), 'period_end': (week_start + timedelta(days=7)).isoformat(),
        'period_end_inclusive': (week_start + timedelta(days=6)).isoformat(),
        'trip_count': len(trips), 'trips': trips, 'adjustments': adjustments,
        'gross_fares_cents': gross_fares, 'commission_pct': pct_default, 'commission_cents': commission,
        'tips_cents': credits['tips'], 'cancellation_fees_cents': credits['cancellation_fees'],
        'bonuses_cents': credits['bonuses'], 'fees_cents': fees,
        'gross_cents': gross, 'net_cents': gross - commission - fees,
        'payouts_cents': payouts, 'payouts_pending_cents': pending,
        'company': {'legal_name': S.get('company.legal_name'), 'address': S.get('company.address'),
                    'support_email': S.get('safety.support_email'), 'support_phone': S.get('safety.support_phone')},
        'registration': {'gst_hst': S.get('company.gst_number') or '', 'qst': ''},
    }


def statement_number(driver_id, week_start):
    y, w, _ = week_start.isocalendar()
    return f'NR-ST-{y}-W{w:02d}-{driver_id}'


def period_label(st):
    s, e = st.period_start, st.period_start + timedelta(days=6)
    return f"{s.strftime('%b %d')} – {e.strftime('%b %d, %Y')}"


def render_statement_pdf(st):
    driver = db.session.get(AdminUser, st.driver_id)
    return RC.render_pdf('statement.html', {'number': st.number, 't': st.totals, 'r': {}, 'driver_id': st.driver_id,
                                            'driver_name': RC._full_name(driver), 'period_label': period_label(st),
                                            'web_base': RC._web_base(), 'policy_url': None})


def ensure_statement_pdf(st):
    blob = RC.read_private(st.pdf_path)
    if blob:
        return blob
    blob = render_statement_pdf(st)
    st.pdf_path = RC.save_private(f'statements/{st.period_start.year}/{st.number}.pdf', blob)
    db.session.commit()
    return blob


def _email(st):
    from backend.services.notify.templates import render
    driver = db.session.get(AdminUser, st.driver_id)
    results = []
    if driver is not None and getattr(driver, 'email_bounced_at', None):
        results.append((False, None, f'suppressed: {driver.email_bounce_reason or "email bounced"}'))
    elif driver and driver.email:
        pdf = ensure_statement_pdf(st)
        subject = f'Your NegoRide earnings statement · {period_label(st)}'
        html, txt = render('driver_statement', {'title': subject, 'first_name': RC._first_name(driver) or 'there',
                                                'number': st.number, 't': st.totals, 'period_label': period_label(st),
                                                'preheader': f'Net earnings {fmt(st.net_cents)}', 'money': fmt})
        results.append(RC._send(driver.email, subject, html, txt,
                                [(f'NegoRide-statement-{st.number}.pdf', pdf, 'application/pdf')], 'driver.statement'))
    else:
        results.append((False, None, 'no email address'))
    RC._log_email(st.driver_id, 'driver.statement', f'statement-{st.id}', 'Your weekly statement',
                  f'Week of {period_label(st)}: net earnings {fmt(st.net_cents)}.',
                  {'statement_id': st.id, 'number': st.number, 'net': fmt(st.net_cents)},
                  'negoride://wallet', results)
    ok = all(r[0] for r in results)
    if ok:
        st.emailed_at = datetime.utcnow()
    db.session.commit()
    return ok


def build_statement(driver_id, week_start, send=True):
    """Idempotent per (driver, week)."""
    st = DriverStatement.query.filter_by(driver_id=driver_id, period_start=week_start).first()
    if st is None:
        totals = compute_statement(driver_id, week_start)
        st = DriverStatement(number=statement_number(driver_id, week_start), driver_id=driver_id,
                             period_start=week_start, period_end=week_start + timedelta(days=7),
                             gross_cents=totals['gross_cents'], commission_cents=totals['commission_cents'],
                             fees_cents=totals['fees_cents'], net_cents=totals['net_cents'],
                             payouts_cents=totals['payouts_cents'], totals=totals)
        db.session.add(st)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            st = DriverStatement.query.filter_by(driver_id=driver_id, period_start=week_start).first()
            if st is None:
                raise
            return st
        try:
            ensure_statement_pdf(st)
        except Exception:
            db.session.rollback()
            log.exception('Statement PDF failed for %s', st.number)
    if send and st.emailed_at is None:
        from sqlalchemy import text
        claimed = db.session.execute(text('UPDATE driver_statements SET emailed_at=:n WHERE id=:id AND emailed_at IS NULL'),
                                     {'n': datetime.utcnow(), 'id': st.id}).rowcount == 1
        db.session.commit()
        if claimed:
            db.session.refresh(st)
            st.emailed_at = None
            if not _email(st):
                db.session.execute(text('UPDATE driver_statements SET emailed_at=NULL WHERE id=:id'), {'id': st.id})
                db.session.commit()
    return st


def weekly_driver_statements(week_start=None):
    """Periodic (weekly). Returns the number of statements touched."""
    if not S.flag('driver_statements'):
        return 0
    if isinstance(week_start, str):
        week_start = date.fromisoformat(week_start)
    week_start = week_start or last_week_start()
    week_start = week_start - timedelta(days=week_start.weekday())
    n = 0
    for driver_id in active_driver_ids(week_start):
        try:
            build_statement(driver_id, week_start)
            n += 1
        except Exception:
            db.session.rollback()
            log.exception('Statement failed for driver %s week %s', driver_id, week_start)
    return n


# ── receipt sweeper (§13.4: the receipt must never be forgotten) ────────────

def sweep_missing_receipts(now=None, limit=100):
    """Periodic: rides that ended (COMPLETED / DROPPED_OFF / CLOSED) with a
    captured ride payment but no receipt `receipts.sweep_after_s` (2 min) after
    the capture get one now (e.g. the worker died between capture and receipt).
    Cancelled rides with a fee capture are not receipted here."""
    from backend.models.money import CAPTURED_STATES, RidePayment
    from backend.services import rides as R
    from backend.services import trip_effects
    if not S.flag('receipts_email'):
        return 0
    now = now or datetime.utcnow()
    cutoff = now - timedelta(seconds=S.get_int('receipts.sweep_after_s', 120))
    since = now - timedelta(days=14)
    rows = (db.session.query(RidePayment)
            .outerjoin(Receipt, (Receipt.ride_type == RidePayment.ride_type) & (Receipt.ride_id == RidePayment.ride_id))
            .filter(RidePayment.purpose == 'ride', RidePayment.capture_status.in_(CAPTURED_STATES),
                    RidePayment.ride_type.in_(RC.RECEIPT_RIDE_TYPES),
                    RidePayment.captured_at <= cutoff, RidePayment.captured_at >= since,
                    Receipt.id.is_(None))
            .order_by(RidePayment.captured_at.asc()).limit(limit).all())
    n = 0
    seen = set()
    for rp in rows:
        key = (rp.ride_type, rp.ride_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            ride = R.load(rp.ride_type, rp.ride_id)
            if R.current_stage(rp.ride_type, ride) not in ('COMPLETED', 'DROPPED_OFF', 'CLOSED'):
                continue
            if trip_effects.issue_receipt_safe(rp.ride_type, rp.ride_id) is not None or \
                    RC.find_receipt(rp.ride_type, rp.ride_id) is not None:
                n += 1
                log.warning('Receipt sweeper issued the missing receipt for %s/%s', rp.ride_type, rp.ride_id)
        except Exception:
            db.session.rollback()
            log.exception('Receipt sweeper failed for %s/%s', rp.ride_type, rp.ride_id)
    return n
