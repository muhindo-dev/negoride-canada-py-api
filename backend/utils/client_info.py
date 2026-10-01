"""Request metadata helpers: client app version, IP, device id (spec §11, §12).

The mobile app sends `X-App-Version: 4.0.0` (v4 builds) and `X-Device-Id`.
v3 builds send neither, so every v4-only rule is keyed on `is_v4_client()`.

Setting `app.legacy_clients_allowed` (default true). When an admin turns it
off, EVERY client is treated as v4 (a missing / old X-App-Version no longer
bypasses consent-at-registration, phone-required sign-up, sensitive-action
re-verification, the legal re-acceptance gate …). `sends_v4_header()` still
reports what the client actually sent (used only for copy/wording choices).
"""
import re

from flask import has_request_context, request


def _parse(v):
    nums = [int(x) for x in re.findall(r'\d+', str(v or ''))[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def version_gte(v, minimum):
    return bool(v) and _parse(v) >= _parse(minimum)


def app_version(data=None):
    if not has_request_context():
        return None
    v = request.headers.get('X-App-Version')
    if not v and data is not None:
        try:
            v = data.get('app_version')
        except AttributeError:
            v = None
    return (str(v).strip()[:30] or None) if v else None


def legacy_clients_allowed():
    try:
        from backend.services import settings_service as S
        return bool(S.get('app.legacy_clients_allowed'))
    except Exception:
        return True


def is_v4_client(data=None, minimum=None):
    """True when the v4 rules apply to this request: the client sent
    X-App-Version >= legal.consent_min_app_version, OR legacy clients are no
    longer allowed (app.legacy_clients_allowed = false)."""
    if not legacy_clients_allowed():
        return True
    return sends_v4_header(data, minimum)


def sends_v4_header(data=None, minimum=None):
    """What the client actually sent, regardless of app.legacy_clients_allowed."""
    if minimum is None:
        try:
            from backend.services import settings_service as S
            minimum = S.get('legal.consent_min_app_version') or '4.0.0'
        except Exception:
            minimum = '4.0.0'
    return version_gte(app_version(data), minimum)


def client_ip():
    """Client IP for rate limiting / consent proof. app.py wraps the app in
    werkzeug ProxyFix (TRUSTED_PROXY_COUNT hops, default 1), so request.remote_addr
    is already the address the trusted proxy saw — client-supplied X-Forwarded-For
    entries cannot spoof it."""
    if not has_request_context():
        return None
    return (request.remote_addr or '')[:64] or None


def user_agent():
    if not has_request_context():
        return None
    return (request.headers.get('User-Agent') or '')[:500] or None


def device_id(data=None):
    if not has_request_context():
        return None
    d = request.headers.get('X-Device-Id')
    if not d and data is not None:
        try:
            d = data.get('device_id')
        except AttributeError:
            d = None
    return (str(d).strip()[:191] or None) if d else None
