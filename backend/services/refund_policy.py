"""Cancellation & refund policy engine (spec §7.3).

`evaluate(ctx, now, cfg)` is a PURE function: no DB, no Stripe. Every row of the
policy tables in §7.1 / §7.2 maps to one `rule_id` and is covered by unit tests
(tests/test_refund_policy.py). Numbers come from app_settings via `config()`,
so admins can change them without a deploy.

Terminology
  paid_cents          what the customer has secured (authorized or captured)
  fee_cents           what the customer is finally charged
  refund_cents        paid_cents - fee_cents (released hold or refunded money)
  driver_share_cents  fee_cents minus platform commission
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
import math

from backend.utils.money import fmt, pct_of

PRE_PAYMENT = ('REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT')
EN_ROUTE = ('DRIVER_EN_ROUTE', 'DRIVER_ARRIVING')
BOOKING_PRE_PAYMENT = ('REQUESTED', 'PENDING_PAYMENT')


@dataclass
class CancelContext:
    ride_type: str                 # carhire | scheduled | rideshare_booking
    stage: str
    reason: str                    # customer_cancel | driver_cancel | customer_no_show |
                                   # driver_no_show | safety | expired | admin
    fare_cents: int = 0
    paid_cents: int = 0
    confirmed_at: datetime = None
    en_route_at: datetime = None
    arrived_at: datetime = None
    departure_at: datetime = None


@dataclass
class Decision:
    allowed: bool
    rule_id: str
    fee_cents: int = 0
    refund_cents: int = 0
    driver_share_cents: int = 0
    credit_cents: int = 0          # apology ride credit to the customer
    strike: bool = False           # driver reliability strike
    needs_admin_review: bool = False
    explanation: str = ''
    breakdown: dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d['fee'] = fmt(self.fee_cents)
        d['refund'] = fmt(self.refund_cents)
        return d


DEFAULT_CONFIG = {
    'cancel.free_window_s': 120,
    'cancel.fee_cents': 500,
    'cancel.fee_pct_cap': 10,
    'cancel.after_arrival_fee_cents': 500,
    'wait.free_s': 120,
    'wait.rate_cents_per_min': 35,
    'noshow.customer_fee_cents': 700,
    'noshow.driver_credit_cents': 500,
    'rideshare.refund_full_h': 24,
    'rideshare.refund_half_h': 2,
    'rideshare.refund_half_pct': 50,
    'pricing.commission_pct': 10,
    'ff.cancellation_fees': True,
    'ff.driver_no_show_credit': True,
}


def config():
    """Live values from app_settings (falls back to defaults)."""
    from backend.services import settings_service as S
    return {k: S.get(k, v) for k, v in DEFAULT_CONFIG.items()}


def _minutes(seconds):
    return max(0, int(round(seconds / 60)))


def waiting_fee_cents(arrived_at, now, cfg):
    """Waiting time accrued after the free period, billed per started minute."""
    if not arrived_at:
        return 0, 0
    waited = max(0, (now - arrived_at).total_seconds() - int(cfg['wait.free_s']))
    minutes = math.ceil(waited / 60) if waited > 0 else 0
    return minutes * int(cfg['wait.rate_cents_per_min']), minutes


def _finish(d, ctx, cfg):
    """Clamp the fee to what was secured and derive refund / driver share."""
    paid = max(0, int(ctx.paid_cents or 0))
    if not cfg.get('ff.cancellation_fees', True) and d.rule_id not in ('rideshare_under_2h', 'rideshare_no_show', 'rideshare_2_to_24h'):
        d.fee_cents = 0
    d.fee_cents = max(0, min(int(d.fee_cents), paid))
    d.refund_cents = paid - d.fee_cents
    commission = pct_of(d.fee_cents, cfg['pricing.commission_pct'])
    d.driver_share_cents = d.fee_cents - commission
    d.breakdown.setdefault('paid_cents', paid)
    d.breakdown['commission_cents'] = commission
    return d


def evaluate(ctx: CancelContext, now: datetime = None, cfg: dict = None) -> Decision:
    now = now or datetime.utcnow()
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}
    if ctx.ride_type == 'rideshare_booking':
        return _evaluate_rideshare(ctx, now, cfg)
    return _evaluate_carhire(ctx, now, cfg)


def _evaluate_carhire(ctx, now, cfg):
    stage, reason = ctx.stage, ctx.reason

    if stage in ('COMPLETED', 'CLOSED') or stage.startswith('CANCELLED') or stage.endswith('NO_SHOW') or stage == 'EXPIRED':
        return Decision(False, 'not_cancellable', explanation='This ride has already ended.')

    if reason == 'expired':
        return _finish(Decision(True, 'expired', explanation='The ride expired — nothing is charged.'), ctx, cfg)

    if reason == 'safety':
        return _finish(Decision(True, 'safety_review', needs_admin_review=True,
                                explanation='Trip ended for safety. Nothing is charged; our safety team will review it.'),
                       ctx, cfg)

    if reason == 'driver_cancel':
        confirmed = stage not in PRE_PAYMENT
        if stage == 'IN_PROGRESS':
            return _finish(Decision(True, 'driver_ended_trip', strike=True, needs_admin_review=True,
                                    explanation='The driver ended the trip early. You are not charged; '
                                                'our team will review what happened.'), ctx, cfg)
        return _finish(Decision(True, 'driver_cancelled', strike=confirmed,
                                explanation='Your driver cancelled. Any payment hold is released in full.'),
                       ctx, cfg)

    if reason == 'driver_no_show':
        credit = int(cfg['noshow.driver_credit_cents']) if cfg.get('ff.driver_no_show_credit', True) else 0
        return _finish(Decision(True, 'driver_no_show', strike=True, credit_cents=credit,
                                explanation="Your driver didn't show up. You're not charged"
                                            + (f" and we added a {fmt(credit)} ride credit." if credit else '.')),
                       ctx, cfg)

    if reason == 'customer_no_show':
        if stage != 'DRIVER_ARRIVED':
            return Decision(False, 'no_show_not_allowed',
                            explanation='A no-show can only be recorded after the driver has arrived.')
        fee = int(cfg['noshow.customer_fee_cents'])
        return _finish(Decision(True, 'customer_no_show', fee_cents=fee,
                                explanation=f'No-show fee of {fmt(fee)} — the driver waited the full window.'),
                       ctx, cfg)

    # ── customer cancels ────────────────────────────────────────────────────
    if stage == 'IN_PROGRESS':
        return Decision(False, 'in_progress', explanation='A trip in progress cannot be cancelled. '
                                                          'Use the Safety toolkit if you need to end it early.')
    if stage in PRE_PAYMENT:
        return _finish(Decision(True, 'before_payment', explanation='Free cancellation — nothing has been charged.'),
                       ctx, cfg)
    if stage == 'CONFIRMED':
        return _finish(Decision(True, 'before_en_route',
                                explanation='Free cancellation — your driver has not started driving yet. '
                                            'Your payment hold is released.'), ctx, cfg)
    if stage in EN_ROUTE:
        since_confirm = (now - ctx.confirmed_at).total_seconds() if ctx.confirmed_at else 1e9
        if since_confirm <= int(cfg['cancel.free_window_s']):
            return _finish(Decision(True, 'free_window',
                                    explanation=f"Free cancellation within {int(cfg['cancel.free_window_s']) // 60} "
                                                'minutes of confirming. Your payment hold is released.'), ctx, cfg)
        flat = int(cfg['cancel.fee_cents'])
        cap = pct_of(ctx.fare_cents, cfg['cancel.fee_pct_cap']) if ctx.fare_cents else flat
        fee = min(flat, cap)
        driving_min = _minutes((now - ctx.en_route_at).total_seconds()) if ctx.en_route_at else 0
        return _finish(Decision(True, 'en_route_fee', fee_cents=fee,
                                explanation=f'Cancelling now costs {fmt(fee)} because your driver has been driving '
                                            f"for {driving_min} min.",
                                breakdown={'flat_fee_cents': flat, 'pct_cap_cents': cap}), ctx, cfg)
    if stage == 'DRIVER_ARRIVED':
        base = int(cfg['cancel.after_arrival_fee_cents'])
        wait_fee, wait_min = waiting_fee_cents(ctx.arrived_at, now, cfg)
        fee = base + wait_fee
        extra = f' plus {fmt(wait_fee)} for {wait_min} min of waiting' if wait_fee else ''
        return _finish(Decision(True, 'after_arrival', fee_cents=fee,
                                explanation=f'Your driver has arrived. Cancelling now costs {fmt(base)}{extra}.',
                                breakdown={'base_fee_cents': base, 'waiting_fee_cents': wait_fee,
                                           'waiting_minutes': wait_min}), ctx, cfg)
    return Decision(False, 'unknown_stage', explanation=f'Cannot cancel a ride in stage {stage}.')


def _evaluate_rideshare(ctx, now, cfg):
    stage, reason = ctx.stage, ctx.reason
    if stage in ('DROPPED_OFF', 'CLOSED', 'RIDING', 'CHECKED_IN') or stage.startswith('CANCELLED') \
            or stage in ('NO_SHOW', 'EXPIRED', 'DECLINED'):
        return Decision(False, 'not_cancellable', explanation='This seat booking can no longer be cancelled.')

    if reason in ('driver_cancel',):
        return _finish(Decision(True, 'rideshare_driver_cancelled', strike=stage not in BOOKING_PRE_PAYMENT,
                                explanation='The driver cancelled this trip. You get a 100 % refund.'), ctx, cfg)
    if reason in ('expired', 'declined'):
        return _finish(Decision(True, 'rideshare_' + reason,
                                explanation='The booking was not confirmed — nothing is charged.'), ctx, cfg)
    if reason == 'safety':
        return _finish(Decision(True, 'safety_review', needs_admin_review=True,
                                explanation='Nothing is charged; our safety team will review it.'), ctx, cfg)
    if stage in BOOKING_PRE_PAYMENT:
        return _finish(Decision(True, 'rideshare_before_payment', explanation='Free cancellation — nothing was charged.'),
                       ctx, cfg)

    paid = int(ctx.paid_cents or 0)
    if reason == 'customer_no_show':
        return _finish(Decision(True, 'rideshare_no_show', fee_cents=paid,
                                explanation='No-show — the seat is not refundable.'), ctx, cfg)

    hours = ((ctx.departure_at - now).total_seconds() / 3600) if ctx.departure_at else 1e9
    full_h, half_h = int(cfg['rideshare.refund_full_h']), int(cfg['rideshare.refund_half_h'])
    if hours > full_h:
        return _finish(Decision(True, 'rideshare_over_24h',
                                explanation=f'Cancelled more than {full_h} h before departure — 100 % refund.'),
                       ctx, cfg)
    if hours >= half_h:
        pct = int(cfg['rideshare.refund_half_pct'])
        refund = pct_of(paid, pct)
        return _finish(Decision(True, 'rideshare_2_to_24h', fee_cents=paid - refund,
                                explanation=f'Cancelled {half_h}–{full_h} h before departure — {pct} % refund '
                                            f'({fmt(refund)}).'), ctx, cfg)
    return _finish(Decision(True, 'rideshare_under_2h', fee_cents=paid,
                            explanation=f'Cancelled less than {half_h} h before departure — no refund.'), ctx, cfg)
