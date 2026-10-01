"""Payment gateway abstraction (spec §6).

StripeGateway  — Checkout Sessions with `payment_intent_data.capture_method`
                 (manual = authorization hold), PaymentIntent capture / partial
                 capture (`amount_to_capture`, remainder auto-released), cancel
                 (instant release) and Refunds. Every mutating call carries an
                 idempotency key.
FakeGateway    — in-memory simulation for tests and local QA. Refused when
                 FLASK_ENV=production.

PAYMENTS_GATEWAY=stripe (default) | fake
"""
import os
import threading
import uuid
from datetime import datetime


class GatewayError(Exception):
    pass


class StripeGateway:
    name = 'stripe'

    def __init__(self):
        import stripe
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')
        self.stripe = stripe

    def create_checkout(self, *, amount_cents, currency, capture_method, metadata, description,
                        customer_email=None, idempotency_key=None, success_url=None, cancel_url=None,
                        save_payment_method=False):
        base = os.getenv('APP_URL', 'https://negoride.ugnews24.info').rstrip('/')
        pi_data = {'capture_method': capture_method, 'metadata': metadata, 'description': description}
        if save_payment_method:
            pi_data['setup_future_usage'] = 'off_session'
        params = {
            'mode': 'payment',
            'payment_method_types': ['card'],
            'line_items': [{'price_data': {'currency': currency, 'unit_amount': int(amount_cents),
                                           'product_data': {'name': description}}, 'quantity': 1}],
            'payment_intent_data': pi_data,
            'metadata': metadata,
            'success_url': success_url or f'{base}/api/payment-success?session_id={{CHECKOUT_SESSION_ID}}',
            'cancel_url': cancel_url or f'{base}/api/payment-cancel',
        }
        if customer_email:
            params['customer_email'] = customer_email
        try:
            s = self.stripe.checkout.Session.create(**params, idempotency_key=idempotency_key)
        except self.stripe.error.StripeError as e:
            raise GatewayError(getattr(e, 'user_message', None) or str(e))
        return {'session_id': s.id, 'url': s.url, 'intent_id': s.get('payment_intent')}

    def get_session(self, session_id):
        try:
            s = self.stripe.checkout.Session.retrieve(session_id)
        except self.stripe.error.StripeError as e:
            raise GatewayError(str(e))
        return {'id': s.id, 'status': s.status, 'payment_status': s.payment_status,
                'intent_id': s.get('payment_intent'), 'amount_total': s.amount_total,
                'metadata': dict(s.get('metadata') or {})}

    def expire_session(self, session_id):
        try:
            self.stripe.checkout.Session.expire(session_id)
        except self.stripe.error.StripeError:
            pass

    def get_intent(self, intent_id):
        try:
            pi = self.stripe.PaymentIntent.retrieve(intent_id, expand=['latest_charge'])
        except self.stripe.error.StripeError as e:
            raise GatewayError(str(e))
        return _intent_dict(pi)

    def capture(self, intent_id, amount_cents, idempotency_key):
        try:
            pi = self.stripe.PaymentIntent.capture(intent_id, amount_to_capture=int(amount_cents),
                                                   idempotency_key=idempotency_key, expand=['latest_charge'])
        except self.stripe.error.StripeError as e:
            raise GatewayError(str(e))
        return _intent_dict(pi)

    def cancel(self, intent_id, idempotency_key):
        try:
            pi = self.stripe.PaymentIntent.cancel(intent_id, idempotency_key=idempotency_key)
        except self.stripe.error.StripeError as e:
            raise GatewayError(str(e))
        return _intent_dict(pi)

    def refund(self, intent_id, amount_cents, idempotency_key, reason=None):
        params = {'payment_intent': intent_id, 'amount': int(amount_cents)}
        if reason in ('duplicate', 'fraudulent', 'requested_by_customer'):
            params['reason'] = reason
        try:
            r = self.stripe.Refund.create(**params, idempotency_key=idempotency_key)
        except self.stripe.error.StripeError as e:
            raise GatewayError(str(e))
        return {'id': r.id, 'status': r.status, 'amount': r.amount}

    def retrieve_payment_totals(self, intent_id):
        """Reconciliation (read-only): what the provider holds for an intent."""
        try:
            pi = self.stripe.PaymentIntent.retrieve(intent_id, expand=['latest_charge'])
        except self.stripe.error.StripeError as e:
            raise GatewayError(str(e))
        charge = pi.get('latest_charge')
        refunded = int(charge.get('amount_refunded') or 0) if charge and not isinstance(charge, str) else 0
        return {'id': pi.id, 'status': pi.status, 'currency': pi.get('currency'),
                'amount_received': int(pi.get('amount_received') or 0), 'amount_refunded': refunded}


def _intent_dict(pi):
    charge = pi.get('latest_charge') if hasattr(pi, 'get') else None
    brand = last4 = capture_before = None
    if charge and not isinstance(charge, str):
        card = ((charge.get('payment_method_details') or {}).get('card') or {})
        brand, last4 = card.get('brand'), card.get('last4')
        cb = card.get('capture_before')
        capture_before = datetime.utcfromtimestamp(cb) if cb else None
    err = pi.get('last_payment_error') if hasattr(pi, 'get') else None
    return {'id': pi.id, 'status': pi.status, 'amount': pi.amount,
            'amount_capturable': pi.get('amount_capturable') or 0,
            'amount_received': pi.get('amount_received') or 0,
            'brand': brand, 'last4': last4, 'capture_before': capture_before,
            'last_payment_error': (err or {}).get('message') if err else None,
            'decline_code': ((err or {}).get('decline_code') or (err or {}).get('code')) if err else None,
            'metadata': dict(pi.get('metadata') or {})}


class FakeGateway:
    """Deterministic in-memory gateway. `simulate_customer_pays()` plays the
    customer completing Checkout; the resulting PaymentIntent is
    requires_capture (manual) or succeeded (automatic)."""
    name = 'fake'
    _lock = threading.Lock()
    sessions = {}
    intents = {}
    refunds = {}
    idem = {}
    calls = []

    @classmethod
    def reset(cls):
        with cls._lock:
            cls.sessions.clear(), cls.intents.clear(), cls.refunds.clear(), cls.idem.clear(), cls.calls.clear()

    def _once(self, key, fn):
        if key and key in self.idem:
            return self.idem[key]
        res = fn()
        if key:
            self.idem[key] = res
        return res

    def create_checkout(self, *, amount_cents, currency, capture_method, metadata, description,
                        customer_email=None, idempotency_key=None, success_url=None, cancel_url=None,
                        save_payment_method=False):
        def make():
            sid = f'cs_fake_{uuid.uuid4().hex[:16]}'
            from flask import has_request_context, request as _rq
            base = (_rq.host_url if has_request_context() else os.getenv('APP_URL', 'http://localhost:5001')).rstrip('/')
            self.sessions[sid] = {'id': sid, 'status': 'open', 'payment_status': 'unpaid', 'intent_id': None,
                                  'amount_total': int(amount_cents), 'capture_method': capture_method,
                                  'currency': currency, 'metadata': dict(metadata)}
            self.calls.append(('create_checkout', sid, amount_cents, capture_method))
            return {'session_id': sid, 'url': f'{base}/api/dev/fake-checkout/{sid}', 'intent_id': None}
        return self._once(idempotency_key, make)

    DECLINES = {
        'card_declined': 'Your card was declined.',
        'insufficient_funds': 'Your card has insufficient funds.',
        'expired_card': 'Your card has expired.',
    }

    def simulate_customer_pays(self, session_id, decline=False, requires_action=False):
        """decline: False | True (card_declined) | 'insufficient_funds' | 'expired_card'.
        requires_action: 3-D Secure still pending (status requires_action)."""
        s = self.sessions[session_id]
        pid = f'pi_fake_{uuid.uuid4().hex[:16]}'
        manual = s['capture_method'] == 'manual'
        code = ('card_declined' if decline is True else decline) if decline else None
        blocked = bool(code) or requires_action
        if requires_action:
            status = 'requires_action'
        elif code:
            status = 'requires_payment_method'
        else:
            status = 'requires_capture' if manual else 'succeeded'
        self.intents[pid] = {'id': pid, 'status': status, 'amount': s['amount_total'],
                             'amount_capturable': s['amount_total'] if (manual and not blocked) else 0,
                             'amount_received': 0 if (manual or blocked) else s['amount_total'],
                             'brand': 'visa', 'last4': '4242',
                             'capture_before': datetime.utcfromtimestamp(datetime.utcnow().timestamp() + 7 * 86400),
                             'last_payment_error': self.DECLINES.get(code) if code else None,
                             'decline_code': code,
                             'metadata': dict(s['metadata'])}
        decline = blocked
        s.update(status='complete', payment_status='unpaid' if manual or decline else 'paid', intent_id=pid)
        return {'id': f'evt_fake_{uuid.uuid4().hex[:12]}', 'type': 'checkout.session.completed',
                'data': {'object': {'id': session_id, 'object': 'checkout.session',
                                    'payment_intent': pid, 'payment_status': s['payment_status'],
                                    'amount_total': s['amount_total'], 'metadata': dict(s['metadata'])}}}

    def get_session(self, session_id):
        s = self.sessions.get(session_id)
        if not s:
            raise GatewayError('No such session')
        return {k: s[k] for k in ('id', 'status', 'payment_status', 'intent_id', 'amount_total', 'metadata')}

    def expire_session(self, session_id):
        if session_id in self.sessions and self.sessions[session_id]['status'] == 'open':
            self.sessions[session_id]['status'] = 'expired'

    def get_intent(self, intent_id):
        if intent_id not in self.intents:
            raise GatewayError('No such payment_intent')
        return dict(self.intents[intent_id])

    def capture(self, intent_id, amount_cents, idempotency_key):
        def do():
            pi = self.intents[intent_id]
            if pi['status'] != 'requires_capture':
                raise GatewayError(f"PaymentIntent is {pi['status']}, cannot capture")
            if amount_cents > pi['amount_capturable']:
                raise GatewayError('amount_to_capture exceeds amount_capturable')
            pi.update(status='succeeded', amount_received=int(amount_cents), amount_capturable=0)
            self.calls.append(('capture', intent_id, amount_cents))
            return dict(pi)
        return self._once(idempotency_key, do)

    def cancel(self, intent_id, idempotency_key):
        def do():
            pi = self.intents[intent_id]
            if pi['status'] == 'succeeded':
                raise GatewayError('Cannot cancel a succeeded PaymentIntent')
            pi.update(status='canceled', amount_capturable=0)
            self.calls.append(('cancel', intent_id))
            return dict(pi)
        return self._once(idempotency_key, do)

    def refund(self, intent_id, amount_cents, idempotency_key, reason=None):
        def do():
            pi = self.intents[intent_id]
            already = sum(r['amount'] for r in self.refunds.values() if r['intent'] == intent_id)
            if amount_cents + already > pi['amount_received']:
                raise GatewayError('Refund exceeds captured amount')
            rid = f're_fake_{uuid.uuid4().hex[:12]}'
            self.refunds[rid] = {'id': rid, 'intent': intent_id, 'amount': int(amount_cents), 'status': 'succeeded'}
            self.calls.append(('refund', intent_id, amount_cents))
            return {'id': rid, 'status': 'succeeded', 'amount': int(amount_cents)}
        return self._once(idempotency_key, do)

    def retrieve_payment_totals(self, intent_id):
        if intent_id not in self.intents:
            raise GatewayError('No such payment_intent')
        pi = self.intents[intent_id]
        refunded = sum(r['amount'] for r in self.refunds.values() if r['intent'] == intent_id)
        return {'id': intent_id, 'status': pi['status'], 'currency': 'cad',
                'amount_received': int(pi['amount_received']), 'amount_refunded': int(refunded)}


_gateway = None
_forced = False


def get_gateway():
    global _gateway
    if _forced and _gateway is not None:
        return _gateway
    want = (os.getenv('PAYMENTS_GATEWAY') or 'stripe').strip().lower()
    if want == 'fake':
        if (os.getenv('FLASK_ENV') or '').lower() == 'production':
            raise GatewayError('The fake payment gateway is disabled in production.')
        if not isinstance(_gateway, FakeGateway):
            _gateway = FakeGateway()
        return _gateway
    if not isinstance(_gateway, StripeGateway):
        _gateway = StripeGateway()
    return _gateway


def set_gateway(gw):
    """Tests: force a gateway instance (None to reset)."""
    global _gateway, _forced
    _gateway = gw
    _forced = gw is not None
