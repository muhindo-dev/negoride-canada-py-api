"""Request metadata helpers: client app version, IP, device id (spec §11, §12).

The mobile app sends `X-App-Version: 4.0.0` (v4 builds) and `X-Device-Id`.
v3 builds send neither, so every v4-only rule is keyed on `is_v4_client()`.
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


def is_v4_client(data=None, minimum=None):
    if minimum is None:
        try:
            from backend.services import settings_service as S
            minimum = S.get('legal.consent_min_app_version') or '4.0.0'
        except Exception:
            minimum = '4.0.0'
    return version_gte(app_version(data), minimum)


def client_ip():
    """Client IP for rate limiting. Behind nginx (`proxy_add_x_forwarded_for`) the
    RIGHT-most X-Forwarded-For entry is the address nginx saw, which a client
    cannot spoof; left-most entries are client-supplied."""
    if not has_request_context():
        return None
    xff = [p.strip() for p in (request.headers.get('X-Forwarded-For') or '').split(',') if p.strip()]
    return ((xff[-1] if xff else request.remote_addr) or '')[:64] or None


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
