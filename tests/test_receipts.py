"""Receipts, credit notes, weekly statements and the finance admin API (spec §13, §19.1.7).

Acceptance §13.4: totals on the email, the PDF, the app API and the captured
Stripe amount match to the cent — compared automatically below.
"""
import io
import re
import threading
import uuid
from datetime import datetime, timedelta

import pytest
from pypdf import PdfReader

from backend.models import db
from backend.models.money import CreditNote, Receipt, RidePayment, TaxRate
from backend.models.negotiation import Negotiation
from backend.models.notification import Notification, NotificationDelivery
from backend.models.platform import AuditLog
from backend.models.statements import DriverStatement
from backend.models.trip_booking import TripBooking
from backend.services import private_storage as PSTORE
from backend.services import receipt_jobs
from backend.services import receipts as RC
from backend.services import settings_service as S
from backend.services.notify import email_provider
from backend.services.payments import payment_service as PS
from backend.services.payments.gateway import get_gateway
from backend.utils.money import fmt
from tests.conftest import body
from tests.test_carhire_flow import DROPOFF, PICKUP, agree, create_negotiation, deliver_webhook, pay
from tests.test_lifecycles_admin import _book_and_pay, _publish_trip


# ── fixtures / helpers ──────────────────────────────────────────────────────

@pytest.fixture(scope='module', autouse=True)
def _private_store(tmp_path_factory):
    prev = PSTORE._backend
    PSTORE.configure(root=str(tmp_path_factory.mktemp('private')), key='test-receipts-key')
    yield
    PSTORE._backend = prev


@pytest.fixture(scope='module', autouse=True)
def _cleanup_statements(_created_users):
    yield
    db.session.rollback()
    if _created_users:
        ids = ','.join(str(int(i)) for i in _created_users)
        db.session.connection().exec_driver_sql(f'DELETE FROM driver_statements WHERE driver_id IN ({ids})')
        db.session.commit()


@pytest.fixture(autouse=True)
def _outbox():
    email_provider.OUTBOX.clear()
    yield


def pdf_text(blob):
    return '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(blob)).pages)


def _seq(number):
    return int(number.rsplit('-', 1)[1])


def paid_carhire(make_user, fare=2200, province='ON', customer=None, driver=None, capture=True, **ride_kw):
    """A COMPLETED car-hire ride paid through the fake gateway (authorize → capture)."""
    customer = customer or make_user('customer')
    driver = driver or make_user('driver')
    now = datetime.utcnow()
    neg = Negotiation(customer_id=customer.id, driver_id=driver.id, status='Completed', is_active='No',
                      pickup_lat=str(PICKUP[0]), pickup_lng=str(PICKUP[1]), pickup_address='100 Queen St W, Toronto',
                      dropoff_lat=str(DROPOFF[0]), dropoff_lng=str(DROPOFF[1]), dropoff_address='290 Bremner Blvd',
                      initial_price=fare, agreed_price_cents=fare, trip_stage='COMPLETED', pickup_province=province,
                      started_at=now - timedelta(minutes=18), completed_at=now, stripe_paid='Yes',
                      payment_status='paid', **ride_kw)
    db.session.add(neg)
    db.session.commit()
    gw = get_gateway()
    co = gw.create_checkout(amount_cents=fare, currency='cad', capture_method='manual', metadata={},
                            description='test', idempotency_key=f'test-{uuid.uuid4().hex}')
    gw.simulate_customer_pays(co['session_id'])
    intent_id = gw.sessions[co['session_id']]['intent_id']
    rp = RidePayment(ride_type='carhire', ride_id=neg.id, customer_id=customer.id, driver_id=driver.id,
                     purpose='ride', checkout_session_id=co['session_id'], intent_id=intent_id, fare_cents=fare,
                     amount_authorized_cents=fare, capture_status='authorized', payment_method_brand='visa',
                     payment_method_last4='4242', authorized_at=now - timedelta(minutes=25))
    if capture:
        gw.capture(intent_id, fare, idempotency_key=f'test-cap-{intent_id}')
        rp.amount_captured_cents, rp.capture_status, rp.captured_at = fare, 'captured', now
    db.session.add(rp)
    db.session.commit()
    return customer, driver, neg, rp


def _admin(make_user, roles='finance'):
    return make_user('admin', admin_roles=roles)


# ── tax math (unit) ─────────────────────────────────────────────────────────

def _comps(prov):
    return RC.tax_components(RC.rate_for(prov))


def test_tax_rates_seeded():
    assert _comps('ON') == [('HST', 'HST 13%', 1300)]
    assert _comps('QC') == [('GST', 'GST 5%', 500), ('QST', 'QST 9.975%', 998)] or \
        [c[0] for c in _comps('QC')] == ['GST', 'QST']
    assert [c[0] for c in _comps('AB')] == ['GST']


@pytest.mark.parametrize('prov,amount,expected_pre,expected', [
    ('ON', 2200, 1947, {'HST': 253}),
    ('QC', 2200, 1913, {'GST': 96, 'QST': 191}),
    ('AB', 2200, 2095, {'GST': 105}),
    ('ON', 1, 1, {'HST': 0}),
    ('QC', 12345, 10737, None),
])
def test_tax_inclusive_extraction(prov, amount, expected_pre, expected):
    pre, lines, tax = RC.split_tax(amount, _comps(prov), inclusive=True)
    assert pre == expected_pre
    assert pre + tax == amount
    assert sum(x['amount_cents'] for x in lines) == tax
    if expected:
        assert {x['code']: x['amount_cents'] for x in lines} == expected


@pytest.mark.parametrize('prov', ['ON', 'QC', 'AB', 'BC', 'NS'])
def test_tax_lines_always_sum_exactly(prov):
    comps = _comps(prov)
    for amount in list(range(0, 3000, 7)) + [99999, 123457, 1000000]:
        pre, lines, tax = RC.split_tax(amount, comps, inclusive=True)
        assert pre + tax == amount and sum(x['amount_cents'] for x in lines) == tax and tax >= 0
        # allocation of the pre-tax subtotal over line items is exact too
        parts = RC.allocate(pre, [amount - 150, 150, -40] if amount > 400 else [amount])
        assert sum(parts) == pre


def test_tax_exclusive_adds_on_top():
    pre, lines, tax = RC.split_tax(2000, _comps('QC'), inclusive=False)
    assert pre == 2000 and {x['code']: x['amount_cents'] for x in lines} == {'GST': 100, 'QST': 200} and tax == 300
    pre, lines, tax = RC.split_tax(2000, _comps('ON'), inclusive=False)
    assert tax == 260


def test_province_detection(make_user):
    _, _, neg, _ = paid_carhire(make_user, province=None, capture=False)
    neg.pickup_address = '1 Rue Sainte-Catherine, Montréal, QC H2X 1Z4'
    assert RC.province_of('carhire', neg) == ('QC', 'address')
    neg.pickup_address = 'Somewhere'
    assert RC.province_of('carhire', neg)[1] == 'default'
    neg.pickup_province = 'ab'
    assert RC.province_of('carhire', neg) == ('AB', 'ride')
    db.session.rollback()


# ── end to end (§13.4) ──────────────────────────────────────────────────────

def _drive_to_completion(client, auth, customer, driver, neg_id, sign_stripe):
    rp, event = pay(client, auth, customer, neg_id)
    assert deliver_webhook(client, sign_stripe, event).status_code == 200
    db.session.rollback()
    pin = db.session.get(Negotiation, neg_id).ride_pin
    for path, payload in (('en-route', {}), ('arrived', {'lat': PICKUP[0], 'lng': PICKUP[1]}), ('start', {'pin': pin}),
                          ('complete', {'lat': DROPOFF[0], 'lng': DROPOFF[1]})):
        r = client.post(f'/api/rides/carhire/{neg_id}/{path}', headers=auth(driver), json=payload)
        assert body(r)['code'] == 1, (path, r.get_json())
    db.session.rollback()
    return db.session.get(RidePayment, rp.id)


def test_receipt_totals_match_everywhere(client, auth, make_user, sign_stripe):
    customer, driver = make_user('customer'), make_user('driver')
    neg_id = create_negotiation(client, auth, customer, driver)
    agree(client, auth, customer, driver, neg_id)
    rp = _drive_to_completion(client, auth, customer, driver, neg_id, sign_stripe)
    neg = db.session.get(Negotiation, neg_id)

    receipt = Receipt.query.filter_by(ride_type='carhire', ride_id=neg_id).one()
    t = receipt.totals
    assert re.fullmatch(r'NR-\d{4}-\d{6}', receipt.number)
    # sent within 60 s of COMPLETED, exactly once
    assert receipt.emailed_at and (receipt.emailed_at - neg.completed_at).total_seconds() < 60
    assert receipt.email_count == 1

    # internal consistency
    assert sum(line['amount_cents'] for line in t['lines']) == t['subtotal_cents']
    assert t['subtotal_cents'] + t['tax_cents'] == t['ride_total_cents']
    assert t['ride_total_cents'] + t['tip_cents'] == t['total_cents'] == receipt.total_cents
    assert t['payment_method'] == 'Visa •••• 4242' and t['authorized_at'] and t['captured_at']

    # Stripe (fake gateway) captured amount
    stripe_amount = get_gateway().get_intent(rp.intent_id)['amount_received']
    assert stripe_amount == rp.amount_captured_cents == receipt.total_cents == 2200

    # email
    mails = [m for m in email_provider.OUTBOX if m['to'] == customer.email and m['tag'] == 'ride.receipt']
    assert len(mails) == 1
    mail = mails[0]
    assert mail['subject'] == f'Thanks for riding with NegoRide, {customer.first_name} 🚗'
    assert mail['attachments'][0][0] == f'NegoRide-receipt-{receipt.number}.pdf'
    assert mail['attachments'][0][2] == 'application/pdf'
    for part in (mail['html'], mail['text']):
        assert receipt.number in part
        for cents in (t['total_cents'], t['subtotal_cents'], t['tax_cents']):
            assert fmt(cents) in part
    assert f'negoride%3A%2F%2Frate%2Fcarhire%2F{neg_id}%3Fstars%3D5' in mail['html']
    assert 'Add a tip' in mail['html'] and 'Lost an item?' in mail['html'] and 'Report an issue' in mail['html']

    # PDF
    text = pdf_text(RC.read_private(receipt.pdf_path))
    assert receipt.number in text and 'Total charged' in text
    for cents in (t['total_cents'], t['subtotal_cents'], t['tax_cents']):
        assert fmt(cents) in text
    assert 'HST 13%' in text and 'CARHIRE-' in text

    # app API (JSON + PDF) — the rider and the driver, nobody else
    j = body(client.get(f'/api/rides/carhire/{neg_id}/receipt', headers=auth(customer)))
    assert j['code'] == 1
    d = j['data']
    assert d['number'] == receipt.number and d['total_cents'] == stripe_amount
    assert d['totals']['subtotal_cents'] + d['totals']['tax_cents'] == d['total_cents']
    assert 'internal' not in d['totals']
    r = client.get(f'/api/rides/carhire/{neg_id}/receipt.pdf', headers=auth(customer))
    assert r.status_code == 200 and r.mimetype == 'application/pdf' and fmt(stripe_amount) in pdf_text(r.data)
    dj = body(client.get(f'/api/rides/carhire/{neg_id}/receipt', headers=auth(driver)))['data']
    assert dj['total_cents'] == stripe_amount and 'payment_method' not in dj['totals']

    # notification log shows it
    n = Notification.query.filter_by(user_id=customer.id, event_key='ride.receipt').one()
    chans = {(x.channel, x.status) for x in NotificationDelivery.query.filter_by(notification_id=n.id)}
    assert ('inbox', 'delivered') in chans and ('email', 'sent') in chans

    # re-running the job is a no-op (same receipt, no second email)
    again = RC.issue_and_send('carhire', neg_id)
    assert again.id == receipt.id
    assert len([m for m in email_provider.OUTBOX if m['tag'] == 'ride.receipt' and m['to'] == customer.email]) == 1

    # my receipts list
    lst = body(client.get('/api/receipts', headers=auth(customer)))['data']
    assert lst['total'] == 1 and lst['data'][0]['number'] == receipt.number


def test_strangers_get_403(client, auth, make_user):
    customer, driver, neg, rp = paid_carhire(make_user)
    RC.issue_and_send('carhire', neg.id)
    stranger = make_user('customer')
    for path in (f'/api/rides/carhire/{neg.id}/receipt', f'/api/rides/carhire/{neg.id}/receipt.pdf'):
        assert client.get(path, headers=auth(stranger)).status_code == 403
        assert client.get(path).status_code == 401
    receipt = RC.find_receipt('carhire', neg.id)
    # stranger's receipt list is empty; admin finance endpoints refuse non-finance users
    assert body(client.get('/api/receipts', headers=auth(stranger)))['data']['total'] == 0
    assert client.get(f'/api/admin/finance/receipts/{receipt.id}', headers=auth(stranger)).status_code == 403
    ops = _admin(make_user, 'safety_reviewer')
    assert client.get('/api/admin/finance/receipts', headers=auth(ops)).status_code == 403
    assert client.post(f'/api/admin/receipts/{receipt.id}/resend', headers=auth(stranger)).status_code == 403


def test_receipt_not_ready_before_payment(client, auth, make_user):
    customer, driver, neg, rp = paid_carhire(make_user, capture=False)
    assert RC.issue_and_send('carhire', neg.id) is None
    r = client.get(f'/api/rides/carhire/{neg.id}/receipt', headers=auth(customer))
    assert r.status_code == 404 and body(r)['data']['error_code'] == 'receipt_not_ready'


@pytest.mark.parametrize('prov,expected', [('ON', {'HST': 253}), ('QC', {'GST': 96, 'QST': 191}), ('AB', {'GST': 105})])
def test_receipt_tax_by_province(make_user, prov, expected):
    customer, driver, neg, rp = paid_carhire(make_user, province=prov)
    receipt = RC.issue_and_send('carhire', neg.id)
    t = receipt.totals
    assert t['province'] == prov and t['province_source'] == 'ride'
    assert {x['code']: x['amount_cents'] for x in t['taxes']} == expected
    assert t['subtotal_cents'] + t['tax_cents'] == 2200 == receipt.total_cents
    text = pdf_text(RC.read_private(receipt.pdf_path))
    for x in t['taxes']:
        assert x['label'] in text and fmt(x['amount_cents']) in text


def test_booking_fee_waiting_and_negotiated_savings(make_user):
    customer, driver, neg, rp = paid_carhire(make_user, fare=2500, capture=False)
    from backend.models.negotiation_record import NegotiationRecord
    db.session.add(NegotiationRecord(negotiation_id=neg.id, customer_id=customer.id, driver_id=driver.id,
                                     last_negotiator_id=driver.id, first_negotiator_id=customer.id, price=3000))
    # fare 2500 + booking fee 199 + waiting 105 captured together
    gw = get_gateway()
    total = 2500 + 199 + 105
    gw.intents[rp.intent_id].update(amount_capturable=total, amount=total)
    gw.capture(rp.intent_id, total, idempotency_key=f'cap2-{rp.intent_id}')
    rp.fees_cents, rp.meta = 199, {'waiting_fee_cents': 105}
    rp.amount_captured_cents, rp.capture_status, rp.captured_at = total, 'captured', datetime.utcnow()
    db.session.commit()
    receipt = RC.issue_and_send('carhire', neg.id)
    t = receipt.totals
    assert [line['code'] for line in t['lines']] == ['fare', 'waiting', 'booking_fee']
    assert sum(line['amount_incl_tax_cents'] for line in t['lines']) == total == receipt.total_cents
    assert sum(line['amount_cents'] for line in t['lines']) == t['subtotal_cents']
    assert t['negotiation'] == {'initial_ask_cents': 3000, 'saved_cents': 500}
    mail = [m for m in email_provider.OUTBOX if m['tag'] == 'ride.receipt'][-1]
    assert 'You negotiated and saved $5.00' in mail['html']


def test_legacy_paid_ride_without_ride_payment(make_user):
    customer, driver = make_user('customer'), make_user('driver')
    neg = Negotiation(customer_id=customer.id, driver_id=driver.id, status='Completed', trip_stage='COMPLETED',
                      pickup_address='Calgary Tower, Calgary, AB T2G 0P3', dropoff_address='YYC',
                      agreed_price_cents=1575, initial_price=1575, stripe_paid='Yes', payment_status='paid',
                      completed_at=datetime.utcnow())
    db.session.add(neg)
    db.session.commit()
    receipt = RC.issue_and_send('carhire', neg.id)
    t = receipt.totals
    assert receipt.total_cents == 1575 and t['province'] == 'AB' and t['payment_method'] == 'Card'
    assert t['subtotal_cents'] + t['tax_cents'] == 1575 and t['internal']['legacy_payment'] is True


# ── numbering ───────────────────────────────────────────────────────────────

def test_sequential_numbers_under_concurrency(app, make_user):
    rides = [paid_carhire(make_user)[2].id for _ in range(8)]
    rides_dup = rides[:3]          # the same rides issued twice at the same time
    results, errors = [], []

    def worker(ride_id):
        with app.app_context():
            try:
                r = RC.issue('carhire', ride_id)
                results.append((ride_id, r.number))
            except Exception as e:  # pragma: no cover
                errors.append(repr(e))
            finally:
                db.session.remove()

    threads = [threading.Thread(target=worker, args=(rid,)) for rid in rides + rides_dup]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    by_ride = {}
    for rid, num in results:
        by_ride.setdefault(rid, set()).add(num)
    assert all(len(v) == 1 for v in by_ride.values()), by_ride   # one number per ride
    nums = sorted(_seq(next(iter(v))) for v in by_ride.values())
    assert len(nums) == len(rides) == len(set(nums))
    assert nums == list(range(nums[0], nums[0] + len(nums)))       # no gaps
    db.session.rollback()
    assert Receipt.query.filter(Receipt.ride_type == 'carhire', Receipt.ride_id.in_(rides)).count() == len(rides)


# ── resend / credit notes ───────────────────────────────────────────────────

def test_admin_resend_reuses_number_and_is_audited(client, auth, make_user):
    customer, driver, neg, rp = paid_carhire(make_user)
    receipt = RC.issue_and_send('carhire', neg.id)
    number = receipt.number
    admin = _admin(make_user)
    r = client.post(f'/api/admin/receipts/{receipt.id}/resend', headers=auth(admin))
    assert body(r)['code'] == 1, r.get_json()
    assert body(r)['data']['number'] == number and body(r)['data']['email_count'] == 2
    mails = [m for m in email_provider.OUTBOX if m['to'] == customer.email and m['tag'] == 'ride.receipt']
    assert len(mails) == 2 and all(m['attachments'][0][0] == f'NegoRide-receipt-{number}.pdf' for m in mails)
    db.session.rollback()
    assert Receipt.query.filter_by(ride_type='carhire', ride_id=neg.id).count() == 1
    assert db.session.get(Receipt, receipt.id).number == number
    assert AuditLog.query.filter_by(action='receipt.resend', actor_id=admin.id, entity_id=str(receipt.id)).count() == 1
    n = Notification.query.filter_by(user_id=customer.id, event_key='ride.receipt').one()
    assert NotificationDelivery.query.filter_by(notification_id=n.id, channel='email', status='sent').count() == 2


def test_two_separate_emails_when_not_combined(make_user):
    S.set_value('ff.combined_receipt_email', False)
    db.session.commit()
    S.invalidate()
    try:
        customer, driver, neg, rp = paid_carhire(make_user)
        receipt = RC.issue_and_send('carhire', neg.id)
        mails = [m for m in email_provider.OUTBOX if m['to'] == customer.email and m['tag'] in ('ride.thanks', 'ride.receipt')]
        assert [m['subject'] for m in mails] == [RC.thanks_subject(customer.first_name),
                                                 f'Your NegoRide receipt {receipt.number}']
        assert mails[0]['attachments'] == [] and mails[1]['attachments'][0][2] == 'application/pdf'
    finally:
        S.set_value('ff.combined_receipt_email', True)
        db.session.commit()
        S.invalidate()


def test_credit_note_on_refund(client, auth, make_user):
    customer, driver, neg, rp = paid_carhire(make_user, province='QC')
    receipt = RC.issue_and_send('carhire', neg.id)
    before = dict(receipt.totals)
    admin = _admin(make_user)
    PS.manual_refund(db.session.get(RidePayment, rp.id), 500, 'Driver took a longer route', admin, 'cn-test')
    db.session.rollback()
    cn = CreditNote.query.filter_by(receipt_id=receipt.id).one()
    assert re.fullmatch(r'NR-CN-\d{4}-\d{6}', cn.number) and cn.amount_cents == 500
    t = cn.totals
    assert t['subtotal_cents'] + t['tax_cents'] == 500 and sum(x['amount_cents'] for x in t['taxes']) == cn.tax_cents
    assert {x['code'] for x in t['taxes']} == {'GST', 'QST'} and t['net_total_cents'] == 1700
    # the receipt is never edited
    assert db.session.get(Receipt, receipt.id).totals == before
    # emailed with the PDF, logged
    mail = [m for m in email_provider.OUTBOX if m['subject'].startswith(f'Credit note {cn.number}')][0]
    assert mail['attachments'][0][0] == f'NegoRide-credit-note-{cn.number}.pdf' and fmt(500) in mail['html']
    assert fmt(500) in pdf_text(RC.read_private(cn.pdf_path)) and cn.number in pdf_text(RC.read_private(cn.pdf_path))
    assert get_gateway().retrieve_payment_totals(rp.intent_id)['amount_refunded'] == 500
    # idempotent
    assert RC.issue_credit_note_for_refund(cn.refund_id).id == cn.id
    assert CreditNote.query.filter_by(receipt_id=receipt.id).count() == 1
    # the app shows the new net total
    d = body(client.get(f'/api/rides/carhire/{neg.id}/receipt', headers=auth(customer)))['data']
    assert d['credited_cents'] == 500 and d['net_total_cents'] == 1700 and d['credit_notes'][0]['number'] == cn.number
    r = client.get(f'/api/receipts/{receipt.id}/credit-notes/{cn.id}.pdf', headers=auth(customer))
    assert r.status_code == 200 and r.mimetype == 'application/pdf'
    assert client.get(f'/api/receipts/{receipt.id}/credit-notes/{cn.id}.pdf',
                      headers=auth(make_user('customer'))).status_code == 403


# ── rideshare seats ─────────────────────────────────────────────────────────

def test_rideshare_one_receipt_per_seat_booking(client, auth, make_user):
    driver, c1, c2 = make_user('driver'), make_user('customer'), make_user('customer')
    trip_id = _publish_trip(client, auth, driver)
    b1, rp1 = _book_and_pay(client, auth, c1, trip_id, seats=2)
    b2, rp2 = _book_and_pay(client, auth, c2, trip_id, seats=1)
    assert body(client.post(f'/api/rides/rideshare_trip/{trip_id}/boarding', headers=auth(driver)))['code'] == 1
    for b in (b1, b2):
        assert body(client.post(f'/api/rides/rideshare_booking/{b}/arrived', headers=auth(driver)))['code'] == 1
        assert body(client.post(f'/api/rides/rideshare_booking/{b}/start', headers=auth(driver)))['code'] == 1
    assert body(client.post(f'/api/rides/rideshare_trip/{trip_id}/start', headers=auth(driver)))['code'] == 1
    assert body(client.post(f'/api/rides/rideshare_trip/{trip_id}/complete', headers=auth(driver)))['code'] == 1
    db.session.rollback()
    r1 = RC.find_receipt('rideshare_booking', b1)
    r2 = RC.find_receipt('rideshare_booking', b2)
    assert r1 and r2 and r1.number != r2.number
    assert r1.total_cents == 5000 == db.session.get(RidePayment, rp1.id).amount_captured_cents
    assert r2.total_cents == 2500 and r1.customer_id == c1.id and r2.customer_id == c2.id
    assert r1.totals['lines'][0]['label'] == 'Seat fare (2 × $25.00)'
    assert RC.find_receipt('rideshare_trip', trip_id) is None
    d = body(client.get(f'/api/rides/rideshare_booking/{b1}/receipt', headers=auth(c1)))['data']
    assert d['number'] == r1.number
    # the other passenger cannot read it
    assert client.get(f'/api/rides/rideshare_booking/{b1}/receipt', headers=auth(c2)).status_code == 403
    assert len([m for m in email_provider.OUTBOX if m['to'] in (c1.email, c2.email) and m['tag'] == 'ride.receipt']) == 2


# ── weekly driver statements ────────────────────────────────────────────────

def test_weekly_statement_idempotent(client, auth, make_user):
    from backend.services import wallet_service
    driver = make_user('driver')
    week = receipt_jobs.last_week_start()
    when = datetime.combine(week, datetime.min.time()) + timedelta(days=2, hours=15)
    for fare in (2200, 1800):
        _, _, neg, _ = paid_carhire(make_user, fare=fare, driver=driver)
        rc = RC.issue('carhire', neg.id)
        rc.issued_at = when
    wallet_service.credit(driver.id, wallet_service.cents_to_dollars(300), 'tip', f'tip-test-{uuid.uuid4().hex}',
                          'Tip for ride')
    db.session.commit()
    from backend.models.transaction import Transaction
    Transaction.query.filter_by(user_id=driver.id, category='tip').update({'created_at': when})
    db.session.commit()

    assert receipt_jobs.weekly_driver_statements(week) >= 1
    receipt_jobs.weekly_driver_statements(week)                    # second run: no-op
    db.session.rollback()
    rows = DriverStatement.query.filter_by(driver_id=driver.id).all()
    assert len(rows) == 1
    st = rows[0]
    t = st.totals
    assert t['trip_count'] == 2 and t['gross_fares_cents'] == 4000 and t['commission_cents'] == 400
    assert t['tips_cents'] == 300 and st.gross_cents == 4300 and st.net_cents == 3900
    mails = [m for m in email_provider.OUTBOX if m['to'] == driver.email and m['tag'] == 'driver.statement']
    assert len(mails) == 1 and mails[0]['attachments'][0][0] == f'NegoRide-statement-{st.number}.pdf'
    text = pdf_text(RC.read_private(st.pdf_path))
    assert fmt(3900) in text and st.number in text
    lst = body(client.get('/api/driver/statements', headers=auth(driver)))['data']
    assert lst['total'] == 1 and lst['data'][0]['net_cents'] == 3900
    assert client.get(f'/api/driver/statements/{st.id}.pdf', headers=auth(driver)).status_code == 200
    assert client.get(f'/api/driver/statements/{st.id}.pdf', headers=auth(make_user('driver'))).status_code == 403


# ── finance admin ───────────────────────────────────────────────────────────

def test_finance_admin_reports_and_reconciliation(client, auth, make_user):
    customer, driver, neg, rp = paid_carhire(make_user, province='QC')
    receipt = RC.issue_and_send('carhire', neg.id)
    admin = _admin(make_user)
    PS.manual_refund(db.session.get(RidePayment, rp.id), 300, 'Partial refund for detour', admin, 'fin-test')
    db.session.rollback()
    h = auth(admin)
    today = datetime.utcnow().strftime('%Y-%m-%d')

    lst = body(client.get(f'/api/admin/finance/receipts?q={receipt.number}', headers=h))['data']
    assert lst['total'] == 1 and lst['data'][0]['credited_cents'] == 300 and lst['data'][0]['net_total_cents'] == 1900
    det = body(client.get(f'/api/admin/finance/receipts/{receipt.id}', headers=h))['data']
    assert det['number'] == receipt.number and det['payment']['intent_id'] == rp.intent_id
    assert client.get(f'/api/admin/finance/receipts/{receipt.id}/pdf', headers=h).mimetype == 'application/pdf'
    csv_r = client.get(f'/api/admin/finance/receipts?format=csv&from={today}&to={today}', headers=h)
    assert csv_r.mimetype == 'text/csv' and receipt.number in csv_r.get_data(as_text=True)
    assert body(client.get('/api/admin/finance/credit-notes', headers=h))['data']['total'] >= 1
    for path in ('payments', 'payments/summary', 'refunds', 'payouts', 'commission', 'tax', 'statements'):
        r = client.get(f'/api/admin/finance/{path}?from={today}&to={today}', headers=h)
        assert r.status_code == 200 and body(r)['code'] == 1, (path, r.get_json())
        assert client.get(f'/api/admin/finance/{path}?format=csv', headers=h).mimetype == 'text/csv', path
    tax = body(client.get(f'/api/admin/finance/tax?from={today}&to={today}', headers=h))['data']
    qc = [p for p in tax['provinces'] if p['province'] == 'QC'][0]
    assert qc['gst_cents'] + qc['qst_cents'] == qc['net_tax_cents'] and qc['credited_tax_cents'] > 0

    rec = body(client.get(f'/api/admin/finance/reconciliation?from={today}&to={today}&per_page=100', headers=h))['data']
    mine = [x for x in rec['data'] if x['ride_payment_id'] == rp.id][0]
    assert mine['status'] == 'ok' and mine['provider_captured_cents'] == 2200 and mine['provider_refunded_cents'] == 300
    # a DB/provider mismatch is flagged
    p = db.session.get(RidePayment, rp.id)
    p.amount_refunded_cents = 0
    db.session.commit()
    rec = body(client.get(f'/api/admin/finance/reconciliation?from={today}&to={today}&per_page=100&only=issues',
                          headers=h))['data']
    assert any(x['ride_payment_id'] == rp.id and 'refunded_mismatch' in x['issues'] for x in rec['data'])
    actions = {a.action for a in AuditLog.query.filter_by(actor_id=admin.id)}
    assert {'personal_data.view', 'finance.export', 'finance.reconciliation'} <= actions
