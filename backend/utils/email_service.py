"""
Email Service — NegoRide Canada (account emails: verification, password reset).

* Links point to the public website landing pages, which call the API:
    {PUBLIC_WEB_BASE_URL}/verify-email?token=…&email=…    → POST /api/email/verify
    {PUBLIC_WEB_BASE_URL}/reset-password?token=…&email=…  → POST /api/auth/reset-password
  (PUBLIC_WEB_BASE_URL falls back to company.website, then APP_URL.)
* Copy is localised EN / FR from the user's preferred_language.
* Delivery goes through services/notify/email_provider (EMAIL_PROVIDER =
  smtp | postmark | console | memory) in a background job — never inline in
  the request (V4 developer guide).
"""
import logging
import os
from urllib.parse import quote

from flask import current_app

logger = logging.getLogger(__name__)

COPY = {
    'verify': {
        'en': {'subject': 'Verify your NegoRide Canada account', 'title': 'Welcome to NegoRide!',
               'greeting': 'Hi {name},',
               'body': 'Thanks for creating an account. Please confirm your email address to finish setting up.',
               'cta': 'Verify my email', 'fallback': 'Or copy this link into your browser:',
               'footnote': 'This link expires in 24 hours. If you did not create this account, you can ignore this email.'},
        'fr': {'subject': 'Confirmez votre compte NegoRide Canada', 'title': 'Bienvenue sur NegoRide!',
               'greeting': 'Bonjour {name},',
               'body': 'Merci d’avoir créé un compte. Veuillez confirmer votre adresse courriel pour terminer la configuration.',
               'cta': 'Confirmer mon courriel', 'fallback': 'Ou copiez ce lien dans votre navigateur :',
               'footnote': 'Ce lien expire dans 24 heures. Si vous n’avez pas créé ce compte, ignorez ce courriel.'},
    },
    'reset': {
        'en': {'subject': 'Reset your NegoRide Canada password', 'title': 'Password reset request',
               'greeting': 'Hi {name},',
               'body': 'We received a request to reset your NegoRide password. Tap the button below to choose a new one.',
               'cta': 'Reset my password', 'fallback': 'Or copy this link into your browser:',
               'footnote': 'This link expires in 1 hour. If you did not request a reset, ignore this email — '
                           'your password will not change.'},
        'fr': {'subject': 'Réinitialisez votre mot de passe NegoRide Canada',
               'title': 'Demande de réinitialisation du mot de passe', 'greeting': 'Bonjour {name},',
               'body': 'Nous avons reçu une demande de réinitialisation de votre mot de passe NegoRide. '
                       'Touchez le bouton ci-dessous pour en choisir un nouveau.',
               'cta': 'Réinitialiser mon mot de passe', 'fallback': 'Ou copiez ce lien dans votre navigateur :',
               'footnote': 'Ce lien expire dans 1 heure. Si vous n’avez rien demandé, ignorez ce courriel — '
                           'votre mot de passe ne changera pas.'},
    },
}


def web_base():
    """Public website base URL for landing pages."""
    try:
        from backend.services import settings_service as S
        site = S.get('company.website')
    except Exception:
        site = None
    return (os.getenv('PUBLIC_WEB_BASE_URL') or site or current_app.config.get('APP_URL')
            or 'https://negoride.ca').rstrip('/')


def verification_url(token, email):
    return f'{web_base()}/verify-email?token={quote(token or "", safe="")}&email={quote(email or "", safe="")}'


def reset_url(token, email):
    return f'{web_base()}/reset-password?token={quote(token or "", safe="")}&email={quote(email or "", safe="")}'


def _lang(lang):
    return 'fr' if str(lang or '').lower().startswith('fr') else 'en'


def _render(kind, name, url, lang):
    from backend.services.notify import templates
    c = COPY[kind][_lang(lang)]
    html, text = templates.render('auth_link', {
        'lang': _lang(lang), 'title': c['title'], 'preheader': c['body'],
        'greeting': c['greeting'].format(name=(name or '').strip() or ('there' if _lang(lang) == 'en' else '')).replace(' ,', ','),
        'body': c['body'], 'cta_url': url, 'cta_label': c['cta'], 'fallback_label': c['fallback'],
        'footnote': c['footnote']})
    return c['subject'], html, text


def deliver(to_address, subject, html, text=None, tag=None):
    """Job: send through the configured email provider."""
    from backend.services.notify import email_provider
    try:
        email_provider.send(to_address, subject, html, text=text, tag=tag)
        return True
    except Exception as exc:
        logger.error('[EmailService] Failed to send email to %s: %s', to_address, exc)
        return False


def _send(to_address, subject, html, text=None, tag=None):
    from backend import jobs
    try:
        jobs.enqueue('backend.utils.email_service.deliver', to_address, subject, html, text, tag)
        return True
    except Exception as exc:   # queue unavailable → best-effort inline send
        logger.warning('[EmailService] queue unavailable (%s) — sending inline', exc)
        return deliver(to_address, subject, html, text, tag)


def send_verification_email(to_address: str, name: str, token: str, lang=None) -> bool:
    """Account verification email → website /verify-email landing page."""
    subject, html, text = _render('verify', name, verification_url(token, to_address), lang)
    return _send(to_address, subject, html, text, tag='email-verification')


def send_password_reset_email(to_address: str, name: str, token: str, lang=None) -> bool:
    """Password reset email → website /reset-password landing page (full token only)."""
    subject, html, text = _render('reset', name, reset_url(token, to_address), lang)
    return _send(to_address, subject, html, text, tag='password-reset')
