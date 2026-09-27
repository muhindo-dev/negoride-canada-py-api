"""Unit tests — refund policy engine: one test per row of spec §7.1 / §7.2."""
from datetime import datetime, timedelta

import pytest

from backend.services.refund_policy import CancelContext, evaluate, waiting_fee_cents, DEFAULT_CONFIG

NOW = datetime(2026, 9, 27, 12, 0, 0)
FARE = 2000   # $20.00


def ctx(stage, reason='customer_cancel', paid=FARE, **kw):
    return CancelContext(ride_type=kw.pop('ride_type', 'carhire'), stage=stage, reason=reason,
                         fare_cents=kw.pop('fare', FARE), paid_cents=paid, **kw)


# ── §7.1 Car hire ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('stage', ['REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT'])
def test_cancel_before_payment_is_free(stage):
    d = evaluate(ctx(stage, paid=0), NOW)
    assert d.allowed and d.rule_id == 'before_payment' and d.fee_cents == 0 and d.refund_cents == 0


def test_cancel_confirmed_before_driver_en_route_is_free():
    d = evaluate(ctx('CONFIRMED', confirmed_at=NOW - timedelta(minutes=10)), NOW)
    assert d.rule_id == 'before_en_route' and d.fee_cents == 0 and d.refund_cents == FARE


def test_cancel_within_2_min_of_confirmation_is_free_even_en_route():
    d = evaluate(ctx('DRIVER_EN_ROUTE', confirmed_at=NOW - timedelta(seconds=119),
                     en_route_at=NOW - timedelta(seconds=60)), NOW)
    assert d.rule_id == 'free_window' and d.fee_cents == 0 and d.refund_cents == FARE


def test_cancel_after_2_min_en_route_fee_is_lower_of_5_or_10_percent():
    # $20 fare → 10 % = $2.00 < $5.00
    d = evaluate(ctx('DRIVER_EN_ROUTE', confirmed_at=NOW - timedelta(minutes=5),
                     en_route_at=NOW - timedelta(minutes=4)), NOW)
    assert d.rule_id == 'en_route_fee' and d.fee_cents == 200 and d.refund_cents == FARE - 200
    assert 'driving for 4 min' in d.explanation
    # $80 fare → 10 % = $8.00 > $5.00 → $5.00
    d = evaluate(ctx('DRIVER_ARRIVING', fare=8000, paid=8000, confirmed_at=NOW - timedelta(minutes=5),
                     en_route_at=NOW - timedelta(minutes=4)), NOW)
    assert d.fee_cents == 500 and d.refund_cents == 7500
    # driver share = fee minus 10 % commission
    assert d.driver_share_cents == 450


def test_cancel_after_arrival_fee_plus_waiting_time():
    # arrived 5 min ago: 2 min free, 3 min billed at 35¢ → 500 + 105
    d = evaluate(ctx('DRIVER_ARRIVED', arrived_at=NOW - timedelta(minutes=5)), NOW)
    assert d.rule_id == 'after_arrival' and d.fee_cents == 605
    assert d.breakdown['waiting_minutes'] == 3 and d.breakdown['waiting_fee_cents'] == 105
    # within free waiting → only the base fee
    d = evaluate(ctx('DRIVER_ARRIVED', arrived_at=NOW - timedelta(seconds=90)), NOW)
    assert d.fee_cents == 500


def test_customer_no_show_fee():
    d = evaluate(ctx('DRIVER_ARRIVED', reason='customer_no_show'), NOW)
    assert d.rule_id == 'customer_no_show' and d.fee_cents == 700 and d.refund_cents == FARE - 700
    assert d.driver_share_cents == 630


def test_customer_no_show_only_after_arrival():
    d = evaluate(ctx('DRIVER_EN_ROUTE', reason='customer_no_show'), NOW)
    assert not d.allowed


def test_driver_cancels_after_confirmation_full_release_and_strike():
    d = evaluate(ctx('DRIVER_EN_ROUTE', reason='driver_cancel'), NOW)
    assert d.rule_id == 'driver_cancelled' and d.fee_cents == 0 and d.refund_cents == FARE and d.strike


def test_driver_cancel_before_payment_no_strike():
    d = evaluate(ctx('NEGOTIATING', reason='driver_cancel', paid=0), NOW)
    assert d.fee_cents == 0 and not d.strike


def test_driver_no_show_full_refund_credit_and_strike():
    d = evaluate(ctx('DRIVER_EN_ROUTE', reason='driver_no_show'), NOW)
    assert d.rule_id == 'driver_no_show' and d.fee_cents == 0 and d.refund_cents == FARE
    assert d.credit_cents == 500 and d.strike


def test_safety_end_is_free_and_needs_review():
    d = evaluate(ctx('IN_PROGRESS', reason='safety'), NOW)
    assert d.rule_id == 'safety_review' and d.fee_cents == 0 and d.needs_admin_review


def test_customer_cannot_cancel_trip_in_progress():
    d = evaluate(ctx('IN_PROGRESS'), NOW)
    assert not d.allowed and d.rule_id == 'in_progress'


def test_driver_ending_trip_in_progress_is_reviewed():
    d = evaluate(ctx('IN_PROGRESS', reason='driver_cancel'), NOW)
    assert d.allowed and d.fee_cents == 0 and d.strike and d.needs_admin_review


def test_terminal_rides_cannot_be_cancelled():
    for st in ('COMPLETED', 'CLOSED', 'CANCELLED_BY_CUSTOMER', 'EXPIRED', 'CUSTOMER_NO_SHOW'):
        assert not evaluate(ctx(st), NOW).allowed


def test_fee_never_exceeds_what_was_secured():
    d = evaluate(ctx('DRIVER_ARRIVED', paid=300, arrived_at=NOW - timedelta(minutes=30)), NOW)
    assert d.fee_cents == 300 and d.refund_cents == 0


def test_fees_disabled_by_flag():
    d = evaluate(ctx('DRIVER_ARRIVED', arrived_at=NOW), NOW, {'ff.cancellation_fees': False})
    assert d.fee_cents == 0 and d.refund_cents == FARE


def test_waiting_fee_rounds_up_per_started_minute():
    fee, mins = waiting_fee_cents(NOW - timedelta(seconds=121), NOW, DEFAULT_CONFIG)
    assert (fee, mins) == (35, 1)


# ── §7.2 Rideshare seats ────────────────────────────────────────────────────

def rs(stage='CONFIRMED', hours=48, reason='customer_cancel', paid=5000):
    return CancelContext(ride_type='rideshare_booking', stage=stage, reason=reason, fare_cents=paid,
                         paid_cents=paid, departure_at=NOW + timedelta(hours=hours))


def test_rideshare_more_than_24h_full_refund():
    d = evaluate(rs(hours=24.5), NOW)
    assert d.rule_id == 'rideshare_over_24h' and d.refund_cents == 5000 and d.fee_cents == 0


def test_rideshare_2_to_24h_half_refund():
    d = evaluate(rs(hours=10), NOW)
    assert d.rule_id == 'rideshare_2_to_24h' and d.refund_cents == 2500 and d.fee_cents == 2500
    d = evaluate(rs(hours=2), NOW)          # boundary: exactly 2 h → 50 %
    assert d.rule_id == 'rideshare_2_to_24h'


def test_rideshare_half_refund_odd_cents():
    d = evaluate(rs(hours=5, paid=1001), NOW)
    assert d.refund_cents + d.fee_cents == 1001 and d.refund_cents == 501


def test_rideshare_under_2h_no_refund():
    d = evaluate(rs(hours=1.9), NOW)
    assert d.rule_id == 'rideshare_under_2h' and d.refund_cents == 0 and d.fee_cents == 5000


def test_rideshare_no_show_no_refund():
    d = evaluate(rs(reason='customer_no_show'), NOW)
    assert d.rule_id == 'rideshare_no_show' and d.refund_cents == 0


def test_rideshare_driver_cancels_full_refund_and_strike():
    d = evaluate(rs(hours=0.5, reason='driver_cancel'), NOW)
    assert d.rule_id == 'rideshare_driver_cancelled' and d.refund_cents == 5000 and d.strike


def test_rideshare_before_payment_free():
    d = evaluate(rs(stage='PENDING_PAYMENT', paid=0), NOW)
    assert d.rule_id == 'rideshare_before_payment' and d.fee_cents == 0
