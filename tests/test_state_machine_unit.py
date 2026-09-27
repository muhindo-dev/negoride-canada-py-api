"""Unit tests — trip state machine graph, legacy mapping, money helpers."""
import itertools

import pytest

from backend.services import trip_state_machine as TSM
from backend.utils import money
from backend.utils.phone import PhoneError, normalize


ALL_CARHIRE = sorted(set(TSM.CARHIRE_GRAPH) | {s for v in TSM.CARHIRE_GRAPH.values() for s in v})


def test_every_carhire_stage_maps_to_a_legacy_status():
    for st in ALL_CARHIRE:
        assert TSM.legacy_status('carhire', st) in ('Active', 'Accepted', 'Started', 'Completed', 'Cancelled')


@pytest.mark.parametrize('stage,legacy', [
    ('REQUESTED', 'Active'), ('NEGOTIATING', 'Active'), ('PRICE_AGREED', 'Accepted'),
    ('AWAITING_PAYMENT', 'Accepted'), ('CONFIRMED', 'Accepted'), ('DRIVER_EN_ROUTE', 'Started'),
    ('DRIVER_ARRIVING', 'Started'), ('DRIVER_ARRIVED', 'Started'), ('IN_PROGRESS', 'Started'),
    ('COMPLETED', 'Completed'), ('CLOSED', 'Completed'), ('EXPIRED', 'Cancelled'),
    ('CANCELLED_BY_CUSTOMER', 'Cancelled'), ('CANCELLED_BY_DRIVER', 'Cancelled'),
    ('CUSTOMER_NO_SHOW', 'Cancelled'), ('DRIVER_NO_SHOW', 'Cancelled'),
])
def test_carhire_legacy_mapping(stage, legacy):
    assert TSM.legacy_status('carhire', stage) == legacy


@pytest.mark.parametrize('stage,legacy', [
    ('REQUESTED', 'Pending'), ('PENDING_PAYMENT', 'Pending'), ('CONFIRMED', 'Reserved'),
    ('CHECKED_IN', 'Reserved'), ('RIDING', 'Reserved'), ('DROPPED_OFF', 'Completed'), ('NO_SHOW', 'Canceled'),
    ('CANCELLED_BY_CUSTOMER', 'Canceled'), ('DECLINED', 'Canceled'),
])
def test_rideshare_booking_legacy_mapping(stage, legacy):
    assert TSM.legacy_status('rideshare_booking', stage) == legacy


def test_terminal_stages_have_no_outgoing_transitions():
    for rt, graph in TSM.GRAPHS.items():
        for st in TSM.TERMINAL[rt]:
            assert st not in graph or graph[st] == (), (rt, st)


def test_forbidden_pairs_are_absent():
    g = TSM.CARHIRE_GRAPH
    assert 'IN_PROGRESS' not in g['COMPLETED']
    assert 'DRIVER_EN_ROUTE' not in g['AWAITING_PAYMENT']     # payment first
    assert 'IN_PROGRESS' not in g['CONFIRMED']                # must arrive first
    assert 'CUSTOMER_NO_SHOW' not in g['DRIVER_EN_ROUTE']     # only after arrival
    # every pair NOT listed is forbidden
    listed = {(a, b) for a, bs in g.items() for b in bs}
    for a, b in itertools.product(ALL_CARHIRE, ALL_CARHIRE):
        assert ((a, b) in listed) == (b in TSM.allowed_next('carhire', a))


def test_shortest_path_for_legacy_start():
    assert TSM.shortest_path('carhire', 'CONFIRMED', 'IN_PROGRESS') == ['DRIVER_EN_ROUTE', 'DRIVER_ARRIVED', 'IN_PROGRESS']
    assert TSM.shortest_path('carhire', 'PRICE_AGREED', 'IN_PROGRESS') == \
        ['CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVED', 'IN_PROGRESS']
    assert TSM.shortest_path('carhire', 'COMPLETED', 'IN_PROGRESS') is None
    assert TSM.shortest_path('rideshare_booking', 'CONFIRMED', 'DROPPED_OFF') == ['CHECKED_IN', 'DROPPED_OFF']


def test_every_stage_has_actor_rules():
    for rt, graph in TSM.GRAPHS.items():
        targets = {s for v in graph.values() for s in v}
        for t in targets:
            assert t in TSM.ACTORS[rt], (rt, t)


# ── money ───────────────────────────────────────────────────────────────────

def test_money_helpers():
    assert money.to_cents('12.50') == 1250
    assert money.to_cents(0.1 + 0.2) == 30
    assert money.pct_of(2005, 10) == 201           # 200.5 → half-up
    assert money.bp_of(10000, 1300) == 1300
    assert money.bp_of(1999, 998) == 200           # QST 9.975 % ≈ 199.5 → 200
    assert money.fmt(123456) == '$1,234.56'
    assert money.fmt(-300) == '-$3.00'
    assert money.legacy_price_to_cents('2500.00') == 2500


# ── phone ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('raw,e164', [
    ('(416) 555-0199', '+14165550199'), ('416-555-0199', '+14165550199'), ('+1 604 555 0100', '+16045550100'),
    ('1-514-555-0000', '+15145550000'), ('0014165550199', '+14165550199'),
])
def test_phone_normalize(raw, e164):
    assert normalize(raw) == e164


@pytest.mark.parametrize('raw', ['', '123', '(016) 555-0199', '+1 416 055 0199', 'abc'])
def test_phone_rejects_invalid(raw):
    with pytest.raises(PhoneError):
        normalize(raw)
