"""Integer-cents money helpers (spec §2.3). Never do float math on money.

All v4 amounts are int cents, CAD. Percentages are applied with integer
arithmetic and ROUND_HALF_UP, so results are deterministic to the cent.
"""
from decimal import Decimal, ROUND_HALF_UP


def to_cents(value):
    """Parse dollars ("12.50", 12.5, Decimal) → 1250. Ints are treated as dollars."""
    if value is None or value == '':
        return 0
    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def pct_of(cents, pct):
    """pct (e.g. 10 or Decimal('9.975')) percent of `cents`, rounded half-up."""
    return int((Decimal(int(cents)) * Decimal(str(pct)) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def bp_of(cents, basis_points):
    """basis points (1300 = 13 %) of `cents`, rounded half-up."""
    return int((Decimal(int(cents)) * Decimal(int(basis_points)) / 10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def fmt(cents, symbol='$'):
    """1250 → "$12.50"; -300 → "-$3.00"."""
    cents = int(cents or 0)
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f"{sign}{symbol}{cents // 100:,}.{cents % 100:02d}"


def dollars(cents):
    """For display/JSON only (e.g. legacy fields). Returns a Decimal with 2dp."""
    return (Decimal(int(cents or 0)) / 100).quantize(Decimal('0.01'))


def legacy_price_to_cents(value):
    """Negotiation.agreed_price is a DECIMAL column that the legacy code fills
    with CENTS (see negotiations.accept). Normalize it to an int."""
    if value is None:
        return None
    return int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
