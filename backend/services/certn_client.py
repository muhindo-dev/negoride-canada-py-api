"""Certn background checks — CertnCentric API (spec §14.2).

Verified against the public CertnCentric docs (https://centric-api-docs.certn.co,
read 2026-09-27). The legacy API (api.certn.co/api/v1/hr/…) was deprecated on
2026-04-13 and returns 410 Gone since 2026-08-05, so it is NOT used.

  Auth       Authorization: Api-Key <CERTN_API_KEY>   (keys expire after 365 days)
  Base URL   CERTN_API_BASE_URL — https://api.ca.certn.co (Canada data residency),
             sandbox https://api.sandbox.certn.co
  Order      POST /api/public/cases/order/
             {email_address, send_invite_email:false, return_invite_link:true,
              check_types_with_arguments:{CHECK_TYPE: {}}, input_claims?, package?}
             → {id, invite_link}      (invite flow: the applicant completes identity
                                       + consent steps on Certn's hosted page — our WebView)
  Retrieve   GET  /api/public/cases/{id}/  → {overall_status, overall_score, checks[…]}
  Report     POST /api/public/cases/{id}/generate-report/  then GET /api/public/cases/report-files/{id}/
  Cancel     POST /api/public/cases/{id}/cancel/                      [path UNVERIFIED]
  Webhooks   X-Signature: hex HMAC-SHA256(raw body, CERTN_WEBHOOK_SECRET);
             GET ?challenge=… must echo the challenge (endpoint verification).
             Body: {created, event_id, event_type, object_id, object_type:'CASE', case_status}
             event_type ∈ CASE_STATUS_CHANGED | CHECK_STATUS_CHANGED | CASE_REPORT_READY |
                          CASE_INPUT_CLAIMS_AUTOMATICALLY_GENERATED

Case overall_status: CASE_ORDERED, APPLICANT_INVITED, APPLICANT_OPENED,
APPLICANT_STARTED, APPLICANT_SUBMITTED, IN_PROGRESS, CLIENT_ACTION_REQUIRED,
APPLICANT_ACTION_REQUIRED, COMPLETE, APPLICANT_EXPIRED, INVITE_UNDELIVERABLE,
CANCELLED. overall_score (null until closed): CLEAR | REVIEW | REJECT |
NOT_APPLICABLE | RESTRICTED.

Unverified details (confirm with Certn onboarding): exact check type keys for
the rideshare package (defaults in onboarding.certn_check_types), whether
`package` accepts our package id, the cancel path, and the report-files
response shape (we read `url`/`file_url`/`download_url`).

When CERTN_API_KEY is empty (dev, tests) `get_client()` returns FakeCertnClient —
clearly labelled, never used in production.
"""
import hashlib
import hmac
import logging
import os
import uuid

import requests

log = logging.getLogger('negoride.certn')

DEFAULT_BASE = 'https://api.ca.certn.co'
IN_PROGRESS_STATUSES = ('APPLICANT_SUBMITTED', 'IN_PROGRESS', 'CLIENT_ACTION_REQUIRED', 'APPLICANT_ACTION_REQUIRED')
INVITED_STATUSES = ('CASE_ORDERED', 'APPLICANT_INVITED', 'APPLICANT_OPENED', 'APPLICANT_STARTED', 'DRAFT')


class CertnError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def is_configured():
    return bool(os.getenv('CERTN_API_KEY', '').strip())


def webhook_secret():
    return os.getenv('CERTN_WEBHOOK_SECRET', '')


def sign(raw_body, secret=None):
    secret = secret if secret is not None else webhook_secret()
    if isinstance(raw_body, str):
        raw_body = raw_body.encode()
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def verify_signature(raw_body, signature, secret=None):
    secret = secret if secret is not None else webhook_secret()
    if not secret or not signature:
        return False
    return hmac.compare_digest(sign(raw_body, secret), signature.strip())


def map_case(case):
    """CertnCentric case → (our status, result). Our statuses:
    initiated (awaiting applicant) · pending (checks running) · clear · consider ·
    failed · expired · cancelled."""
    st = (case.get('overall_status') or case.get('case_status') or '').upper()
    score = (case.get('overall_score') or '').upper() or None
    if st == 'COMPLETE':
        if score == 'CLEAR':
            return 'clear', 'clear'
        if score == 'REJECT':
            return 'failed', 'reject'
        if score is None:
            return 'pending', None     # complete but score not computed yet
        return 'consider', score.lower()   # REVIEW / NOT_APPLICABLE / RESTRICTED → human review
    if st in ('APPLICANT_EXPIRED', 'INVITE_UNDELIVERABLE'):
        return 'expired', st.lower()
    if st == 'CANCELLED':
        return 'cancelled', None
    if st in IN_PROGRESS_STATUSES:
        return 'pending', None
    return 'initiated', None


class CertnClient:
    name = 'certn'

    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or os.getenv('CERTN_API_KEY', '')
        self.base = (base_url or os.getenv('CERTN_API_BASE_URL') or DEFAULT_BASE).rstrip('/')

    def _req(self, method, path, json=None):
        url = f'{self.base}{path}'
        r = requests.request(method, url, json=json, timeout=20,
                             headers={'Authorization': f'Api-Key {self.api_key}', 'Content-Type': 'application/json',
                                      'Accept': 'application/json'})
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            msg = body.get('detail') or body.get('message') or body.get('error') or f'Certn HTTP {r.status_code}'
            raise CertnError(str(msg)[:500], r.status_code)
        return body

    def order_case(self, email, check_types, input_claims=None, package=None, language='en-CA', tag_ids=None):
        payload = {'email_address': email, 'send_invite_email': False, 'return_invite_link': True,
                   'check_types_with_arguments': {c: {} for c in check_types}}
        if package:
            payload['package'] = package
        if input_claims:
            payload['input_claims'] = input_claims
        if tag_ids:
            payload['tag_ids'] = tag_ids
        # documented order fields: check_types_with_arguments, package, permissible_purpose,
        # email_address, send_invite_email, return_invite_link, group, ordered_by, tag_ids, input_claims
        group = os.getenv('CERTN_GROUP_ID', '').strip()
        if group:
            payload['group'] = group
        res = self._req('POST', '/api/public/cases/order/', payload)
        return {'id': res.get('id'), 'invite_link': res.get('invite_link'), 'raw': res}

    def get_case(self, case_id):
        return self._req('GET', f'/api/public/cases/{case_id}/')

    def cancel_case(self, case_id):
        return self._req('POST', f'/api/public/cases/{case_id}/cancel/')

    def report_url(self, case_id):
        res = self._req('POST', f'/api/public/cases/{case_id}/generate-report/')
        file_id = res.get('id') or res.get('report_file_id') or case_id
        f = self._req('GET', f'/api/public/cases/report-files/{file_id}/')
        return f.get('url') or f.get('file_url') or f.get('download_url')


class FakeCertnClient:
    """DEV/TEST ONLY — simulates CertnCentric in memory. Never used when
    CERTN_API_KEY is set; refuses to run with FLASK_ENV=production."""
    name = 'fake-certn'
    cases = {}

    def __init__(self):
        if os.getenv('FLASK_ENV', '').lower() == 'production':
            raise CertnError('Certn is not configured (CERTN_API_KEY missing) in production.')

    @classmethod
    def reset(cls):
        cls.cases.clear()

    def order_case(self, email, check_types, input_claims=None, package=None, language='en-CA', tag_ids=None):
        cid = f'fake-case-{uuid.uuid4().hex[:12]}'
        self.cases[cid] = {'id': cid, 'overall_status': 'APPLICANT_INVITED', 'overall_score': None,
                           'email_address': email, 'check_types_with_arguments': {c: {} for c in check_types},
                           'checks': [{'type': c, 'status': 'AWAITING_APPLICANT_SUBMISSION', 'score': None}
                                      for c in check_types]}
        base = os.getenv('APP_URL', 'http://localhost:5001').rstrip('/')
        return {'id': cid, 'invite_link': f'{base}/api/dev/fake-certn/invite/{cid}', 'raw': self.cases[cid]}

    def get_case(self, case_id):
        if case_id not in self.cases:
            raise CertnError('Not found', 404)
        return dict(self.cases[case_id])

    def cancel_case(self, case_id):
        self.set_case(case_id, 'CANCELLED')
        return self.cases[case_id]

    def report_url(self, case_id):
        return f'https://example.invalid/fake-certn/report/{case_id}.pdf'

    # test helpers
    def set_case(self, case_id, overall_status, overall_score=None):
        c = self.cases.setdefault(case_id, {'id': case_id, 'checks': []})
        c['overall_status'], c['overall_score'] = overall_status, overall_score
        return c


_override = None


def set_client(client):
    """Tests: install a specific client (None = automatic)."""
    global _override
    _override = client


def get_client():
    if _override is not None:
        return _override
    if is_configured():
        return CertnClient()
    return FakeCertnClient()
