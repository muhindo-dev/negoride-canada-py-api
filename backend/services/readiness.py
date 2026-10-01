"""Launch readiness (admin GET /api/admin/readiness) and startup warnings.

Each check returns {key, severity: blocker|warning, ok, message, fix}. A
"blocker" must be fixed before going live; a "warning" degrades a feature.
Nothing here calls a vendor — it only inspects configuration.
"""
import logging
import os
from datetime import datetime

log = logging.getLogger('negoride.readiness')

PLACEHOLDER_ADDRESSES = ('', 'toronto, on, canada', 'canada', 'tbd', 'address')


def is_production():
    return os.getenv('FLASK_ENV', '').strip().lower() not in ('development', 'dev', 'testing', 'test', 'local')


def _env(name):
    return (os.getenv(name) or '').strip()


def redis_status():
    """(configured, importable, reachable, detail)."""
    url = _env('REDIS_URL')
    if not url:
        return False, None, False, 'REDIS_URL is not set'
    try:
        import redis  # noqa: F401
        import rq  # noqa: F401
    except ImportError as exc:
        return True, False, False, f'REDIS_URL is set but the redis/rq packages are missing ({exc})'
    from backend import jobs
    ok = jobs.get_redis() is not None
    return True, True, ok, 'reachable' if ok else 'REDIS_URL is set but Redis does not answer'


def checks():
    from backend.services import settings_service as S
    prod = is_production()
    out = []

    def add(key, ok, severity, message, fix):
        out.append({'key': key, 'ok': bool(ok), 'severity': severity, 'message': message, 'fix': fix})

    # ── tax / company (receipts §13) ─────────────────────────────────────────
    add('company.gst_number', not (S.get('pricing.tax_inclusive') and not (S.get('company.gst_number') or '').strip()),
        'blocker', 'Fares are tax-inclusive but the GST/HST registration number is empty — receipts are not valid '
                   'tax documents.', 'Admin → Settings → company.gst_number')
    addr = (S.get('company.address') or '').strip().lower()
    add('company.address', addr not in PLACEHOLDER_ADDRESSES and len(addr) > 20, 'blocker',
        'The company address on receipts is a placeholder.', 'Admin → Settings → company.address (full postal address)')
    add('company.legal_name', bool((S.get('company.legal_name') or '').strip()), 'blocker',
        'The legal name on receipts is empty.', 'Admin → Settings → company.legal_name')

    # ── safety / support contacts ────────────────────────────────────────────
    add('safety.oncall_phones', bool((S.get('safety.oncall_phones') or '').strip()), 'blocker',
        'No on-call phones: an unacknowledged SOS cannot be escalated by SMS/voice.',
        'Admin → Settings → safety.oncall_phones (comma-separated E.164)')
    add('safety.support_phone', bool((S.get('safety.support_phone') or '').strip()), 'blocker',
        'The support phone shown in apps, emails and receipts is empty.', 'Admin → Settings → safety.support_phone')

    # ── vendor keys ──────────────────────────────────────────────────────────
    add('twilio', bool(_env('TWILIO_ACCOUNT_SID') and _env('TWILIO_AUTH_TOKEN')), 'blocker',
        'Twilio is not configured: no phone verification, no SMS fallback, no SOS SMS.',
        'Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VERIFY_SERVICE_SID, TWILIO_MESSAGING_SERVICE_SID')
    provider = (_env('EMAIL_PROVIDER') or 'smtp').lower()
    email_ok = bool(_env('POSTMARK_SERVER_TOKEN')) if provider == 'postmark' else (
        provider == 'smtp' and bool(_env('MAIL_USERNAME') and _env('MAIL_PASSWORD')))
    add('email', email_ok and provider == 'postmark', 'blocker' if not email_ok else 'warning',
        'Transactional email is not on Postmark (receipts, bounces tracking).' if email_ok else
        'No working email provider: receipts and onboarding emails are not sent.',
        'EMAIL_PROVIDER=postmark + POSTMARK_SERVER_TOKEN (+ POSTMARK_WEBHOOK_USER/PASSWORD for bounces)')
    add('postmark.webhook', bool(_env('POSTMARK_WEBHOOK_USER') and _env('POSTMARK_WEBHOOK_PASSWORD')), 'warning',
        'Postmark webhooks are not protected/configured: bounces will not suppress bad addresses.',
        'Set POSTMARK_WEBHOOK_USER / POSTMARK_WEBHOOK_PASSWORD and point Postmark to /api/webhooks/postmark')
    add('certn', bool(_env('CERTN_API_KEY')), 'blocker', 'Certn is not configured: background checks cannot run.',
        'Set CERTN_API_KEY and CERTN_WEBHOOK_SECRET')
    add('google_maps', bool(_env('GOOGLE_MAPS_SERVER_KEY')), 'blocker',
        'No Google Maps server key: ETAs fall back to straight-line estimates and receipts have no map.',
        'Set GOOGLE_MAPS_SERVER_KEY (and GOOGLE_MAPS_STATIC_KEY + signing secret for receipt maps)')
    add('stripe', bool(_env('STRIPE_SECRET_KEY') and _env('STRIPE_WEBHOOK_SECRET')), 'blocker',
        'Stripe secret key or webhook signing secret missing: payments cannot be confirmed.',
        'Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET')
    add('payments.fake_gateway', (_env('PAYMENTS_GATEWAY') or 'stripe').lower() != 'fake' or not prod, 'blocker',
        'PAYMENTS_GATEWAY=fake in production.', 'Unset PAYMENTS_GATEWAY')
    add('onesignal', bool(_env('ONESIGNAL_REST_API_KEY')), 'blocker',
        'No OneSignal REST key: push notifications and Live Activities are not delivered.',
        'Set ONESIGNAL_REST_API_KEY')

    # ── infrastructure ───────────────────────────────────────────────────────
    configured, importable, reachable, detail = redis_status()
    add('redis', reachable or not prod, 'blocker' if prod else 'warning',
        f'Redis: {detail}. Without it jobs run in-process threads and Socket.IO cannot scale beyond one worker.',
        'Set REDIS_URL, install redis+rq, run worker.py (systemd negoride-worker)')
    add('public_web_base_url', bool(_env('PUBLIC_WEB_BASE_URL')), 'blocker',
        'PUBLIC_WEB_BASE_URL is unset: email links (rate, tip, receipts, share) point to a default domain.',
        'Set PUBLIC_WEB_BASE_URL (e.g. https://negoride.ca)')
    add('app_url', bool(_env('APP_URL')), 'warning',
        'APP_URL is unset: Stripe return URLs and the email logo use defaults.', 'Set APP_URL to the public API origin')
    add('storage', bool(_env('PRIVATE_STORAGE_KEY') or _env('S3_BUCKET')), 'warning' if not prod else 'blocker',
        'No PRIVATE_STORAGE_KEY / S3 bucket: receipts, documents and recordings use a development key.',
        'Set PRIVATE_STORAGE_KEY (Fernet) or S3_*')

    # Module-provided checks (safety_service.readiness_checks — level ok|warning|critical).
    have = {c['key'] for c in out}
    try:
        from backend.services import safety_service
        for item in safety_service.readiness_checks() if hasattr(safety_service, 'readiness_checks') else []:
            if item.get('key') in have:
                continue
            add(item.get('key'), item.get('level') == 'ok',
                'blocker' if item.get('level') == 'critical' else 'warning', item.get('message') or '',
                'See docs/SAFETY.md')
    except Exception:
        log.exception('safety readiness checks failed')
    return out


def report():
    items = checks()
    blockers = [c for c in items if not c['ok'] and c['severity'] == 'blocker']
    warnings = [c for c in items if not c['ok'] and c['severity'] == 'warning']
    return {'ready': not blockers, 'production': is_production(), 'blockers': blockers, 'warnings': warnings,
            'checks': items, 'checked_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}


def log_startup_warnings():
    """Called once at app start: Redis problems are the ones that silently
    degrade production (jobs in threads, no cross-process Socket.IO)."""
    configured, importable, reachable, detail = redis_status()
    if configured and importable is False:
        log.error('REDIS_URL is set but redis/rq cannot be imported — background jobs run in-process. %s', detail)
        print(f'\n⚠️  WARNING: {detail}. Install requirements (redis, rq).\n')
    if is_production() and not reachable:
        msg = (f'PRODUCTION WITHOUT REDIS ({detail}): jobs run in API threads, the scheduler must run with '
               'RUN_SCHEDULER=1, Socket.IO events do not reach other processes. See GET /api/admin/readiness.')
        log.critical(msg)
        print('\n' + '!' * 78 + f'\n!!  {msg}\n' + '!' * 78 + '\n')
