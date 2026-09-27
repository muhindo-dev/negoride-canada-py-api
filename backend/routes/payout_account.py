from datetime import datetime
from flask import Blueprint, request, render_template_string
from backend.models import db
from backend.models.payout_account import PayoutAccount
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response
import os

payout_account_bp = Blueprint('payout_account', __name__)

STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')


def _sensitive_guard(user, data):
    """v4 clients must re-verify their phone (purpose=sensitive_action) before
    changing the payout account (spec §11.2 #7). v3 clients are unaffected."""
    from backend.services import phone_verification as PV
    return PV.require_sensitive_action(user, (data or {}).get('verification_token')
                                       or request.headers.get('X-Verification-Token'), data)



@payout_account_bp.route('/api/payout-account', methods=['GET'])
@jwt_required_with_user
def get_account(user):
    """Get or create driver's payout account."""
    account = PayoutAccount.query.filter_by(user_id=user.id).first()
    if not account:
        account = PayoutAccount(user_id=user.id, status='pending')
        db.session.add(account)
        db.session.commit()

    return success_response("Success", account.to_dict())


@payout_account_bp.route('/api/payout-account/create-stripe', methods=['POST'])
@jwt_required_with_user
def create_stripe(user):
    """Create a Stripe Connect Express account (Canada)."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    data = request.get_json(silent=True) or request.form
    email = data.get('email')
    if not email:
        return error_response("Email is required")
    blocked = _sensitive_guard(user, data)
    if blocked is not None:
        return blocked

    account = PayoutAccount.query.filter_by(user_id=user.id).first()

    # Create if no existing Stripe account
    if account and account.stripe_account_id:
        return success_response("Stripe account already exists", account.to_dict())

    try:
        stripe_account = stripe.Account.create(
            type='express',
            country='CA',
            email=email,
            capabilities={
                'card_payments': {'requested': True},
                'transfers': {'requested': True},
            },
            business_type=data.get('business_type', 'individual'),
        )
    except stripe.error.StripeError as e:
        msg = str(e)
        # Friendlier message while the platform hasn't finished enabling Connect.
        if 'connect' in msg.lower() or 'signed up for Connect' in msg:
            return error_response(
                "Driver payouts aren't switched on yet. The NegoRide team is "
                "finalising payout setup — please try again shortly."
            )
        return error_response(msg)

    if not account:
        account = PayoutAccount(user_id=user.id)
        db.session.add(account)

    account.stripe_account_id = stripe_account.id
    account.account_type = 'express'
    account.status = 'restricted'  # created on Stripe, not yet onboarded/verified
    db.session.commit()

    return success_response("Stripe account created", {
        'account': account.to_dict(),
        'stripe_account_id': stripe_account.id,
    })


@payout_account_bp.route('/api/payout-account/onboarding-link', methods=['POST'])
@jwt_required_with_user
def onboarding_link(user):
    """Get Stripe onboarding URL."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    account = PayoutAccount.query.filter_by(user_id=user.id).first()
    if not account or not account.stripe_account_id:
        return error_response("No Stripe account found. Create one first.")

    data = request.get_json(silent=True) or request.form
    base_url = request.host_url.rstrip('/')
    return_url = data.get('return_url', f'{base_url}/api/payout-complete')
    refresh_url = data.get('refresh_url', f'{base_url}/api/payout-refresh')

    try:
        link = stripe.AccountLink.create(
            account=account.stripe_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type='account_onboarding',
        )
    except stripe.error.StripeError as e:
        return error_response(str(e))

    return success_response("Onboarding link generated", {
        'onboarding_url': link.url,
        'expires_at': link.expires_at,
    })


@payout_account_bp.route('/api/payout-account/dashboard-link', methods=['GET'])
@jwt_required_with_user
def dashboard_link(user):
    """Get Stripe Express Dashboard login link."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    account = PayoutAccount.query.filter_by(user_id=user.id).first()
    if not account or not account.stripe_account_id:
        return error_response("No Stripe account found")

    try:
        link = stripe.Account.create_login_link(account.stripe_account_id)
    except stripe.error.StripeError as e:
        return error_response(str(e))

    return success_response("Dashboard link generated", {
        'dashboard_url': link.url,
    })


@payout_account_bp.route('/api/payout-account/sync', methods=['POST'])
@jwt_required_with_user
def sync(user):
    """Sync local account with Stripe (banking info, status)."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    account = PayoutAccount.query.filter_by(user_id=user.id).first()
    if not account or not account.stripe_account_id:
        return error_response("No Stripe account found")

    try:
        stripe_acct = stripe.Account.retrieve(account.stripe_account_id)
    except stripe.error.StripeError as e:
        return error_response(str(e))

    account.charges_enabled = stripe_acct.charges_enabled
    account.payouts_enabled = stripe_acct.payouts_enabled
    account.onboarding_completed = stripe_acct.details_submitted

    if stripe_acct.external_accounts and stripe_acct.external_accounts.data:
        ext = stripe_acct.external_accounts.data[0]
        if ext.object == 'bank_account':
            account.bank_account_last4 = ext.last4
            account.bank_name = ext.bank_name
        elif ext.object == 'card':
            account.card_last4 = ext.last4
            account.card_brand = ext.brand

    if stripe_acct.requirements:
        account.requirements_currently_due = str(stripe_acct.requirements.currently_due) if stripe_acct.requirements.currently_due else None
        account.requirements_past_due = str(stripe_acct.requirements.past_due) if stripe_acct.requirements.past_due else None

    if stripe_acct.details_submitted and stripe_acct.charges_enabled:
        account.status = 'active'
        account.verification_status = 'verified'
    else:
        account.status = 'restricted'

    db.session.commit()
    return success_response("Account synced", {'account': account.to_dict()})


@payout_account_bp.route('/api/payout-account/preferences', methods=['POST'])
@jwt_required_with_user
def preferences(user):
    """Update payout preferences."""
    data = request.get_json(silent=True) or request.form
    blocked = _sensitive_guard(user, data)
    if blocked is not None:
        return blocked
    account = PayoutAccount.query.filter_by(user_id=user.id).first()
    if not account:
        return error_response("No payout account found")

    method = data.get('default_payout_method')
    if method and method in ('standard', 'instant'):
        account.default_payout_method = method

    min_amount = data.get('minimum_payout_amount')
    if min_amount is not None:
        try:
            min_amount = float(min_amount)  # dollars
        except (TypeError, ValueError):
            return error_response("Invalid minimum payout amount")
        if min_amount < 1:
            return error_response("Minimum payout amount must be at least $1.00")
        account.minimum_payout_amount = round(min_amount, 2)

    db.session.commit()
    return success_response("Preferences updated", {'account': account.to_dict()})


@payout_account_bp.route('/api/payout-account/deactivate', methods=['POST'])
@jwt_required_with_user
def deactivate(user):
    """Deactivate payout account."""
    data = request.get_json(silent=True) or request.form
    blocked = _sensitive_guard(user, data)
    if blocked is not None:
        return blocked
    account = PayoutAccount.query.filter_by(user_id=user.id).first()
    if not account:
        return error_response("No payout account found")

    account.status = 'disabled'
    account.disabled_at = datetime.utcnow()
    db.session.commit()

    return success_response("Account deactivated", {'account': account.to_dict()})


@payout_account_bp.route('/api/payout-account/reactivate', methods=['POST'])
@jwt_required_with_user
def reactivate(user):
    """Reactivate payout account (checks Stripe good standing)."""
    import stripe
    blocked = _sensitive_guard(user, request.get_json(silent=True) or request.form)
    if blocked is not None:
        return blocked
    stripe.api_key = STRIPE_SECRET_KEY

    account = PayoutAccount.query.filter_by(user_id=user.id).first()
    if not account:
        return error_response("No payout account found")

    if account.stripe_account_id:
        try:
            stripe_acct = stripe.Account.retrieve(account.stripe_account_id)
            if not stripe_acct.charges_enabled:
                return error_response("Stripe account is not in good standing")
        except stripe.error.StripeError as e:
            return error_response(str(e))

    account.status = 'active'
    account.activated_at = datetime.utcnow()
    db.session.commit()

    return success_response("Account reactivated", {'account': account.to_dict()})


# ---------------------------------------------------------------------------
# Public Stripe onboarding callbacks (no auth — render HTML)
# ---------------------------------------------------------------------------

CALLBACK_HTML = """
<!DOCTYPE html>
<html>
<head><title>{{ title }}</title>
<style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f8f9fa}
.card{text-align:center;padding:2rem;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.1);background:#fff}
h2{color:#333}p{color:#666}</style></head>
<body><div class="card"><h2>{{ title }}</h2><p>{{ message }}</p></div></body>
</html>
"""


@payout_account_bp.route('/api/payout-complete', methods=['GET'])
def payout_complete():
    """Stripe onboarding return callback."""
    return render_template_string(
        CALLBACK_HTML,
        title="Setup Complete",
        message="Your payout account has been set up. You can close this page and return to the app.",
    )


@payout_account_bp.route('/api/payout-refresh', methods=['GET'])
def payout_refresh():
    """Stripe onboarding refresh callback."""
    return render_template_string(
        CALLBACK_HTML,
        title="Session Expired",
        message="Your onboarding session expired. Please go back to the app and try again.",
    )
