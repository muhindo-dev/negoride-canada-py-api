"""Checkout landing pages + the dev-only fake checkout.

The app's WebView closes itself as soon as the URL contains `payment-success`
or `payment-cancel`; these pages exist so a browser user also sees a clear
result. `/api/dev/fake-checkout/<session>` is only served when
PAYMENTS_GATEWAY=fake and FLASK_ENV != production (local QA without Stripe).
"""
import os

from flask import Blueprint, Response, abort, redirect, request

payment_pages_bp = Blueprint('payment_pages', __name__)

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · NegoRide</title>
<style>:root{{--bg:#f3f4f6;--card:#fff;--ink:#111827;--muted:#6b7280;--brand:#EF9B11}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b0f17;--card:#151d2b;--ink:#e5e7eb;--muted:#9ca3af}}}}
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--bg);
font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);padding:16px}}
.c{{background:var(--card);border-radius:18px;padding:32px;max-width:420px;width:100%;text-align:center}}
.i{{font-size:44px}}h1{{font-size:22px;margin:12px 0 8px}}p{{color:var(--muted);line-height:1.5}}
a,button{{display:inline-block;margin-top:14px;background:var(--brand);color:#111;border:0;border-radius:10px;
padding:12px 18px;font-weight:700;text-decoration:none;font-size:15px;cursor:pointer}}</style></head>
<body><div class="c"><div class="i">{icon}</div><h1>{title}</h1><p>{body}</p>{extra}</div></body></html>"""


def _page(title, body, icon, extra=''):
    return Response(_PAGE.format(title=title, body=body, icon=icon, extra=extra), mimetype='text/html')


@payment_pages_bp.route('/api/payment-success', methods=['GET'])
def payment_success():
    return _page('Payment authorized', 'Your ride is being confirmed. You can return to the NegoRide app — '
                 'the amount is held on your card and only charged when your trip ends.', '✅')


@payment_pages_bp.route('/api/payment-cancel', methods=['GET'])
def payment_cancel():
    return _page('Payment not completed', 'No money was taken. Return to the NegoRide app to try again.', '↩️')


def _fake_enabled():
    return (os.getenv('PAYMENTS_GATEWAY') or '').lower() == 'fake' and \
        (os.getenv('FLASK_ENV') or '').lower() != 'production'


@payment_pages_bp.route('/api/dev/fake-checkout/<session_id>', methods=['GET', 'POST'])
def fake_checkout(session_id):
    if not _fake_enabled():
        abort(404)
    from backend.services.payments.gateway import get_gateway
    from backend.services.payments import payment_service as PS
    gw = get_gateway()
    if session_id not in gw.sessions:
        abort(404)
    if request.method == 'POST':
        decline = request.form.get('decline') == '1'
        event = gw.simulate_customer_pays(session_id, decline=decline)
        PS.handle_stripe_event(event)
        return redirect(f'/api/payment-{"cancel" if decline else "success"}?session_id={session_id}')
    s = gw.sessions[session_id]
    amount = s['amount_total']
    form = (f'<form method="post"><button>Authorize ${amount / 100:.2f} CAD (test)</button></form>'
            f'<form method="post"><input type="hidden" name="decline" value="1">'
            f'<button style="background:#e5e7eb">Decline card</button></form>')
    return _page('Test checkout', f'Fake gateway — {s["capture_method"]} capture. No real card is used.', '🧪', form)
