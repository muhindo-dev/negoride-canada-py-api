"""Shared helpers for the identity / onboarding / account tests."""
import random

import pytest

from backend.models import db
from backend.services import settings_service as S


def rand_phone():
    return f'+1416{random.randint(200, 999)}{random.randint(0, 9999):04d}'


def rand_ip():
    return f'10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}'


def v4(ip=None, **extra):
    h = {'X-App-Version': '4.0.0', 'X-Forwarded-For': ip or rand_ip()}
    h.update(extra)
    return h


def setting(monkeypatch, key, value):
    """Override a setting for one test without touching app_settings rows."""
    spec = S.DEFAULTS[key]
    monkeypatch.setitem(S.DEFAULTS, key, (value,) + tuple(spec[1:]))
    S.invalidate()
    assert key not in S._load(), f'{key} is overridden in app_settings; the test cannot patch it'


class Phones:
    """Registers test numbers in TWILIO_TEST_NUMBERS and cleans their rows."""

    def __init__(self, monkeypatch):
        self.mp = monkeypatch
        self.codes = {}
        self.voip = set()

    def new(self, code='123456', voip=False):
        p = rand_phone()
        self.codes[p] = code
        if voip:
            self.voip.add(p)
        self.mp.setenv('TWILIO_TEST_NUMBERS', ','.join(f'{k}:{v}' for k, v in self.codes.items()))
        self.mp.setenv('TWILIO_TEST_VOIP_NUMBERS', ','.join(self.voip))
        return p

    def cleanup(self):
        if not self.codes:
            return
        db.session.rollback()
        from backend.models.identity import PhoneVerification
        PhoneVerification.query.filter(PhoneVerification.phone.in_(list(self.codes))).delete(synchronize_session=False)
        db.session.commit()


@pytest.fixture()
def phones(monkeypatch):
    p = Phones(monkeypatch)
    yield p
    p.cleanup()


def verify(client, phone, purpose, headers=None, code='123456', **extra):
    """start + check → verification_token (asserts success)."""
    h = headers or v4()
    r = client.post('/api/verify/phone/start', json={'phone': phone, 'purpose': purpose, **extra}, headers=h)
    assert r.get_json()['code'] == 1, r.get_json()
    r = client.post('/api/verify/phone/check', json={'phone': phone, 'purpose': purpose, 'code': code, **extra},
                    headers=h)
    body = r.get_json()
    assert body['code'] == 1, body
    return body['data']


def give_verified_phone(user, phone):
    from datetime import datetime
    user.phone_e164 = phone
    user.phone_number = phone
    user.phone_verified_at = datetime.utcnow()
    db.session.commit()
