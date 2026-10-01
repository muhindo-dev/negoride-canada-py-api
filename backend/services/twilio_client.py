"""Thin Twilio REST client (Messaging + Verify + Lookup) over `requests`.

Credentials come from env only (spec §2.7, §24). The app never talks to
Twilio directly (§11.1). When credentials are missing, `is_configured()` is
False and callers fall back (test numbers in non-production, logged SMS).
"""
import logging
import os

import requests

log = logging.getLogger('negoride.twilio')
API = 'https://api.twilio.com/2010-04-01'
VERIFY = 'https://verify.twilio.com/v2'
LOOKUP = 'https://lookups.twilio.com/v2'
SENT = []  # test/dev introspection


class TwilioError(Exception):
    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


def _creds():
    return os.getenv('TWILIO_ACCOUNT_SID', ''), os.getenv('TWILIO_AUTH_TOKEN', '')


def is_configured():
    sid, tok = _creds()
    return bool(sid and tok)


def _req(method, url, data=None, params=None):
    sid, tok = _creds()
    r = requests.request(method, url, data=data, params=params, auth=(sid, tok), timeout=15)
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        raise TwilioError(body.get('message') or f'Twilio HTTP {r.status_code}', r.status_code, body.get('code'))
    return body


def send_sms(to_e164, body):
    """Transactional SMS through the Messaging Service (STOP/HELP handled by
    Twilio Advanced Opt-Out on the service). Returns the message SID."""
    if not is_configured():
        log.warning('[sms:not-configured] to=%s body=%s', to_e164, body)
        SENT.append({'to': to_e164, 'body': body, 'simulated': True})
        raise TwilioError('Twilio is not configured', code='not_configured')
    sid, _ = _creds()
    data = {'To': to_e164, 'Body': body[:1500]}
    mss = os.getenv('TWILIO_MESSAGING_SERVICE_SID', '')
    if mss:
        data['MessagingServiceSid'] = mss
    else:
        data['From'] = os.getenv('TWILIO_FROM_NUMBER', '')
    status_cb = os.getenv('TWILIO_STATUS_CALLBACK_URL', '')
    if status_cb:
        data['StatusCallback'] = status_cb
    res = _req('POST', f'{API}/Accounts/{sid}/Messages.json', data=data)
    SENT.append({'to': to_e164, 'body': body, 'sid': res.get('sid')})
    return res.get('sid')


def verify_start(to_e164, channel='sms', locale=None, app_hash=None):
    """Twilio Verify v2 Create Verification. `AppHash` (SMS only) appends the
    Android SMS Retriever hash to the message so the app can read the code."""
    svc = os.getenv('TWILIO_VERIFY_SERVICE_SID', '')
    data = {'To': to_e164, 'Channel': channel}
    if locale:
        data['Locale'] = locale
    if app_hash and channel == 'sms':
        data['AppHash'] = app_hash
    return _req('POST', f'{VERIFY}/Services/{svc}/Verifications', data=data)


def verify_check(to_e164, code):
    svc = os.getenv('TWILIO_VERIFY_SERVICE_SID', '')
    return _req('POST', f'{VERIFY}/Services/{svc}/VerificationCheck', data={'To': to_e164, 'Code': code})


def lookup_line_type(e164):
    """Returns e.g. 'mobile', 'landline', 'nonFixedVoip', 'fixedVoip', or None."""
    res = _req('GET', f'{LOOKUP}/PhoneNumbers/{e164}', params={'Fields': 'line_type_intelligence'})
    lti = res.get('line_type_intelligence') or {}
    return lti.get('type')
