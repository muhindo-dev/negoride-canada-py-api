"""Legal documents, versions and acceptances (spec §12).

Documents are Markdown with Jinja2 placeholders filled from app_settings at
read time, so the cancellation policy (and every other number quoted in a
policy) can never drift from what the refund engine actually applies.

  current(type, lang)             current published version (falls back to EN)
  render(doc)                     public JSON shape
  accept(user, docs, …)           proof rows (ip, user agent, app version, method, e-signature)
  pending_for(user, lang)         documents the user must (re)accept — the blocking modal
  publish(doc, admin, …)          archive the previous version, notify users on re-acceptance
"""
import logging
from datetime import datetime

from jinja2 import Undefined
from jinja2.sandbox import SandboxedEnvironment

from backend import jobs
from backend.models import db
from backend.models.identity import DriverApplication, LegalAcceptance, LegalDocument
from backend.models.user import AdminUser
from backend.services import settings_service as S
from backend.services.audit import audit
from backend.utils.money import fmt

log = logging.getLogger('negoride.legal')

TYPES = ('terms', 'privacy', 'community_guidelines', 'driver_agreement', 'cancellation_policy',
         'safety_policy', 'recording_notice', 'background_check_consent')
SIGNUP_REQUIRED = ('terms', 'privacy', 'community_guidelines')
DRIVER_REQUIRED = ('driver_agreement', 'safety_policy')
BGC_CONSENT = 'background_check_consent'
LANGS = ('en', 'fr')
NAMES = {
    'terms': ('Terms & Conditions', 'Conditions d’utilisation'),
    'privacy': ('Privacy Policy', 'Politique de confidentialité'),
    'community_guidelines': ('Community Guidelines', 'Lignes directrices de la communauté'),
    'driver_agreement': ('Driver Agreement', 'Entente du chauffeur'),
    'cancellation_policy': ('Cancellation & Refund Policy', 'Politique d’annulation et de remboursement'),
    'safety_policy': ('Safety Policy', 'Politique de sécurité'),
    'recording_notice': ('Audio Recording Notice', 'Avis sur l’enregistrement audio'),
    'background_check_consent': ('Background Check Disclosure & Consent',
                                 'Divulgation et consentement — vérification des antécédents'),
}

_env = SandboxedEnvironment(undefined=Undefined, autoescape=False)


class LegalError(Exception):
    def __init__(self, message, code='legal_error', status=400, data=None):
        super().__init__(message)
        self.message, self.code, self.status, self.data = message, code, status, data or {}


def display_name(doc_type, lang='en'):
    en, fr = NAMES.get(doc_type, (doc_type, doc_type))
    return fr if lang == 'fr' else en


# ── rendering ───────────────────────────────────────────────────────────────

def render_context():
    """Every number a policy quotes, straight from app_settings."""
    g = S.get_int
    return {
        'company_legal_name': S.get('company.legal_name'),
        'company_address': S.get('company.address'),
        'support_email': S.get('safety.support_email'),
        'website': S.get('company.website'),
        'tracking_retention_days': g('tracking.retention_days'),
        'recording_retention_days': g('recording.retention_days'),
        'recording_hold_after_case_days': g('recording.hold_after_case_days'),
        'min_driver_age': g('onboarding.min_driver_age'),
        'min_vehicle_year': g('onboarding.min_vehicle_year'),
        'recheck_months': g('onboarding.recheck_months'),
        'commission_pct': g('pricing.commission_pct'),
        'bgc_fee': fmt(g('onboarding.bgc_fee_cents')),
        'certn_dispute_contact': S.get('onboarding.certn_dispute_contact'),
        'free_window_min': round(g('cancel.free_window_s') / 60, 1) if g('cancel.free_window_s') % 60 else g('cancel.free_window_s') // 60,
        'cancel_fee': fmt(g('cancel.fee_cents')),
        'cancel_fee_pct_cap': g('cancel.fee_pct_cap'),
        'after_arrival_fee': fmt(g('cancel.after_arrival_fee_cents')),
        'wait_free_min': g('wait.free_s') // 60 if g('wait.free_s') % 60 == 0 else round(g('wait.free_s') / 60, 1),
        'wait_rate_per_min': fmt(g('wait.rate_cents_per_min')),
        'wait_window_min': g('ride.wait_window_s') // 60 if g('ride.wait_window_s') % 60 == 0 else round(g('ride.wait_window_s') / 60, 1),
        'noshow_fee': fmt(g('noshow.customer_fee_cents')),
        'driver_credit': fmt(g('noshow.driver_credit_cents')),
        'driver_no_show_grace_min': g('ride.driver_no_show_grace_s') // 60,
        'rideshare_refund_full_h': g('rideshare.refund_full_h'),
        'rideshare_refund_half_h': g('rideshare.refund_half_h'),
        'rideshare_refund_half_pct': g('rideshare.refund_half_pct'),
        'strikes_warn_after': g('strikes.warn_after'),
        'strikes_window_days': g('strikes.window_days'),
        'strikes_suspend_after': g('strikes.suspend_after'),
        'strikes_suspend_days': g('strikes.suspend_days'),
    }


def render_text(text, ctx=None):
    if not text:
        return text or ''
    try:
        return _env.from_string(text).render(**(ctx or render_context()))
    except Exception as exc:   # never break a policy page on a template typo
        log.warning('Legal template render failed: %s', exc)
        return text


def render(doc, ctx=None, raw=False):
    ctx = ctx or render_context()
    return {
        'id': doc.id,
        'type': doc.type,
        'version': doc.version,
        'title': doc.title,
        'language': doc.language,
        'audience': doc.audience,
        'status': doc.status,
        'summary_markdown': doc.summary_markdown if raw else render_text(doc.summary_markdown, ctx),
        'body_markdown': doc.body_markdown if raw else render_text(doc.body_markdown, ctx),
        'what_changed': doc.what_changed,
        'requires_reacceptance': bool(doc.requires_reacceptance),
        'effective_at': _iso(doc.effective_at or doc.published_at),
        'published_at': _iso(doc.published_at),
        'updated_at': _iso(doc.updated_at),
    }


def summary_of(doc):
    return {'id': doc.id, 'type': doc.type, 'version': doc.version, 'title': doc.title, 'language': doc.language,
            'audience': doc.audience, 'requires_reacceptance': bool(doc.requires_reacceptance),
            'what_changed': doc.what_changed, 'effective_at': _iso(doc.effective_at or doc.published_at)}


def _iso(v):
    return v.strftime('%Y-%m-%dT%H:%M:%SZ') if v else None


# ── lookups ─────────────────────────────────────────────────────────────────

def normalize_lang(lang):
    lang = (lang or 'en').lower()[:2]
    return lang if lang in LANGS else 'en'


def current(doc_type, lang='en'):
    lang = normalize_lang(lang)
    q = LegalDocument.query.filter_by(type=doc_type, status='published')
    doc = q.filter_by(language=lang).order_by(LegalDocument.published_at.desc(), LegalDocument.id.desc()).first()
    if not doc and lang != 'en':
        doc = q.filter_by(language='en').order_by(LegalDocument.published_at.desc(), LegalDocument.id.desc()).first()
    return doc


def current_all(audience=None, lang='en'):
    out = []
    for t in TYPES:
        d = current(t, lang)
        if not d:
            continue
        if audience and audience != 'all' and d.audience not in ('all', audience):
            continue
        out.append(d)
    return out


def resolve(document_ids=None, types=None, lang='en'):
    """Documents to accept, by id (must be a current published version) or by type."""
    docs = []
    for did in document_ids or []:
        try:
            d = db.session.get(LegalDocument, int(did))
        except (TypeError, ValueError):
            d = None
        if not d or d.status != 'published':
            raise LegalError('This document version is no longer current. Please review the latest version.',
                             'document_outdated', 409, {'document_id': did})
        docs.append(d)
    for t in types or []:
        d = current(t, lang)
        if not d:
            raise LegalError(f'No published {t.replace("_", " ")} document.', 'document_missing', 404)
        docs.append(d)
    seen, uniq = set(), []
    for d in docs:
        if d.id not in seen:
            seen.add(d.id)
            uniq.append(d)
    return uniq


def accept(user, docs, method='checkbox', app_version=None, signature_name=None, ip=None, user_agent=None):
    """Adds one LegalAcceptance per document (idempotent). Caller commits."""
    if method not in ('checkbox', 'modal', 'esignature'):
        method = 'checkbox'
    rows = []
    for d in docs:
        row = LegalAcceptance.query.filter_by(user_id=user.id, document_id=d.id).first()
        if not row:
            row = LegalAcceptance(user_id=user.id, document_id=d.id, document_type=d.type, version=d.version,
                                  accepted_at=datetime.utcnow(), ip=ip, user_agent=(user_agent or '')[:500] or None,
                                  app_version=app_version, method=method,
                                  signature_name=(signature_name or '').strip()[:200] or None)
            db.session.add(row)
            db.session.flush()
        rows.append(row)
    return rows


def is_driverish(user):
    if user.user_type in ('Driver', 'Pending Driver') or user.is_approved_driver():
        return True
    return DriverApplication.query.filter_by(user_id=user.id).first() is not None


def has_accepted_version(user_id, doc_type, version):
    return LegalAcceptance.query.filter_by(user_id=user_id, document_type=doc_type, version=version).first() is not None


def pending_for(user, lang='en'):
    """Documents requiring (re)acceptance by this user (blocking modal)."""
    lang = normalize_lang(lang or user.preferred_language)
    required = set(SIGNUP_REQUIRED)
    if is_driverish(user):
        required |= set(DRIVER_REQUIRED)
    out = []
    for t in TYPES:
        if t == BGC_CONSENT:
            continue
        d = current(t, lang)
        if not d:
            continue
        if has_accepted_version(user.id, t, d.version):
            continue
        ever = LegalAcceptance.query.filter_by(user_id=user.id, document_type=t).first() is not None
        if (t in required and not ever) or (d.requires_reacceptance and (ever or t in required)):
            item = summary_of(d)
            item['reason'] = 'updated' if ever else 'not_accepted'
            out.append(item)
    return out


# ── admin: versions ─────────────────────────────────────────────────────────

def create_draft(admin, doc_type, version, language='en', title=None, body_markdown=None, summary_markdown=None,
                 audience=None, from_id=None, what_changed=None):
    if doc_type not in TYPES:
        raise LegalError('Unknown document type.', 'invalid_type')
    language = normalize_lang(language)
    if not version:
        raise LegalError('Version is required (e.g. "1.1").', 'version_required')
    if LegalDocument.query.filter_by(type=doc_type, version=str(version), language=language).first():
        raise LegalError('This version already exists.', 'version_exists', 409)
    base = db.session.get(LegalDocument, int(from_id)) if from_id else current(doc_type, language)
    doc = LegalDocument(
        type=doc_type, version=str(version)[:20], language=language, status='draft',
        title=title or (base.title if base else display_name(doc_type, language)),
        summary_markdown=summary_markdown if summary_markdown is not None else (base.summary_markdown if base else ''),
        body_markdown=body_markdown if body_markdown is not None else (base.body_markdown if base else ''),
        audience=audience or (base.audience if base else 'all'), what_changed=what_changed,
        created_at=datetime.utcnow())
    db.session.add(doc)
    db.session.flush()
    audit('legal.draft_created', admin, 'legal_document', doc.id,
          after={'type': doc_type, 'version': doc.version, 'language': language})
    return doc


def publish(doc, admin, requires_reacceptance=False, what_changed=None, effective_at=None):
    if doc.status == 'published':
        raise LegalError('This version is already published.', 'already_published', 409)
    if not (doc.body_markdown or '').strip():
        raise LegalError('The document body is empty.', 'empty_body')
    previous = current(doc.type, doc.language)
    if previous and previous.language != doc.language:
        previous = None
    now = datetime.utcnow()
    if previous:
        previous.status = 'archived'
    doc.status = 'published'
    doc.published_at = now
    doc.published_by = admin.id if admin else None
    doc.effective_at = effective_at or now
    doc.requires_reacceptance = bool(requires_reacceptance)
    if what_changed is not None:
        doc.what_changed = what_changed
    audit('legal.published', admin, 'legal_document', doc.id,
          before={'previous_id': previous.id if previous else None, 'previous_version': previous.version if previous else None},
          after={'type': doc.type, 'version': doc.version, 'language': doc.language,
                 'requires_reacceptance': doc.requires_reacceptance})
    if doc.requires_reacceptance:
        jobs.enqueue_after_commit('backend.services.legal_service.notify_policy_update', doc.id)
    invalidate_gate_cache()
    return previous


def notify_policy_update(doc_id):
    """Job: tell every affected user (in their language) that a policy changed."""
    from backend.services.notify import notify
    doc = db.session.get(LegalDocument, doc_id)
    if not doc:
        return 0
    q = AdminUser.query.filter(AdminUser.deleted_at.is_(None))
    if doc.language == 'fr':
        q = q.filter(AdminUser.preferred_language == 'fr')
    else:
        q = q.filter((AdminUser.preferred_language.is_(None)) | (AdminUser.preferred_language != 'fr'))
    if doc.audience == 'driver':
        q = q.filter(AdminUser.user_type.in_(('Driver', 'Pending Driver')))
    elif doc.audience == 'customer':
        q = q.filter(~AdminUser.user_type.in_(('Driver', 'Pending Driver')))
    ids = [r[0] for r in q.with_entities(AdminUser.id).all()]
    for i in range(0, len(ids), 500):
        notify('legal.policy_updated', ids[i:i + 500],
               {'document': display_name(doc.type, 'en'), 'document_type': doc.type, 'document_id': doc.id,
                'version': doc.version})
    db.session.commit()
    return len(ids)


DRIVER_TYPES = ('Driver', 'Pending Driver')


def _audience_counts():
    """{(is_driver, is_fr): n} over live accounts — one grouped query."""
    from sqlalchemy import case, func
    is_drv = case((AdminUser.user_type.in_(DRIVER_TYPES), 1), else_=0)
    is_fr = case((AdminUser.preferred_language == 'fr', 1), else_=0)
    rows = (db.session.query(is_drv, is_fr, func.count(AdminUser.id))
            .filter(AdminUser.deleted_at.is_(None)).group_by(is_drv, is_fr).all())
    return {(int(a), int(b)): int(n) for a, b, n in rows}


def audience_size(doc, counts=None):
    """Users a document applies to: its audience (all|customer|driver) AND its language
    (FR documents → users whose preferred language is French; EN → everyone else)."""
    counts = counts if counts is not None else _audience_counts()
    fr = 1 if doc.language == 'fr' else 0
    drivers = counts.get((1, fr), 0)
    customers = counts.get((0, fr), 0)
    return {'driver': drivers, 'customer': customers}.get(doc.audience, drivers + customers)


def acceptance_stats(doc_type=None):
    from sqlalchemy import func
    q = LegalDocument.query
    if doc_type:
        q = q.filter_by(type=doc_type)
    docs = q.order_by(LegalDocument.type, LegalDocument.language, LegalDocument.id.desc()).all()
    counts = dict(db.session.query(LegalAcceptance.document_id, func.count(LegalAcceptance.id))
                  .filter(LegalAcceptance.document_id.in_([d.id for d in docs] or [0]))
                  .group_by(LegalAcceptance.document_id).all())
    aud = _audience_counts()
    total_users = sum(aud.values())
    out = []
    for d in docs:
        n = int(counts.get(d.id, 0))
        denom = audience_size(d, aud)
        out.append({**summary_of(d), 'status': d.status, 'published_at': _iso(d.published_at),
                    'acceptances': n, 'audience_users': denom,
                    'acceptance_rate_pct': min(100.0, round(100.0 * n / denom, 1)) if denom else 0.0})
    return {'total_users': total_users, 'items': out}


# ── re-acceptance gate (spec §12) ───────────────────────────────────────────
# Exempt API prefixes: the user must still be able to read / accept the policy,
# see their account, finish a ride in progress, reach support and raise an SOS.
REACCEPT_EXEMPT_PREFIXES = (
    '/api/legal', '/api/users/me', '/api/account', '/api/app/config', '/api/notifications',
    '/api/notification-preferences', '/api/devices', '/api/rides/', '/api/support', '/api/safety',
    '/api/sos', '/api/update-location', '/api/tracking', '/api/verify', '/api/profile/delete-account',
    '/api/stream', '/api/calls',
)
_GATE_TTL_S = 30.0
_gate_cache = {'at': 0.0, 'docs': None}


def invalidate_gate_cache():
    _gate_cache['at'] = 0.0
    _gate_cache['docs'] = None


def _reaccept_docs():
    """Current published documents flagged requires_reacceptance → [(type, version, audience, language)].
    Cached per process for a few seconds (publish() clears it in-process)."""
    import time
    now = time.monotonic()
    if _gate_cache['docs'] is not None and now - _gate_cache['at'] < _GATE_TTL_S:
        return _gate_cache['docs']
    rows = (db.session.query(LegalDocument.type, LegalDocument.version, LegalDocument.audience,
                             LegalDocument.language)
            .filter(LegalDocument.status == 'published', LegalDocument.requires_reacceptance.is_(True)).all())
    docs = [(t, v, a, lg) for t, v, a, lg in rows if t != BGC_CONSENT]
    _gate_cache.update(at=now, docs=docs)
    return docs


def blocking_for(user):
    """Pending documents that BLOCK the API for this user (requires_reacceptance). Cheap in
    the common case: no flagged document → no query; all flagged versions accepted → one query."""
    docs = _reaccept_docs()
    if not docs:
        return []
    driverish = None
    relevant = []
    for t, v, a, lg in docs:
        if a != 'all':
            if driverish is None:
                driverish = user.user_type in DRIVER_TYPES
            if (a == 'driver') != driverish:
                continue
        relevant.append((t, v))
    if not relevant:
        return []
    accepted = {(t, v) for t, v in db.session.query(LegalAcceptance.document_type, LegalAcceptance.version)
                .filter(LegalAcceptance.user_id == user.id,
                        LegalAcceptance.document_type.in_({t for t, _ in relevant})).all()}
    if all(r in accepted for r in relevant):
        return []
    return [p for p in pending_for(user, user.preferred_language) if p.get('requires_reacceptance')]


def gate_response(user):
    """None, or the 403 legal_pending response for a non-exempt v4 request (spec §12)."""
    from flask import has_request_context, jsonify, request
    if not has_request_context():
        return None
    path = request.path or ''
    if not path.startswith('/api/') or path.startswith('/api/admin') \
            or any(path.startswith(p) for p in REACCEPT_EXEMPT_PREFIXES):
        return None
    try:
        if not S.get('legal.enforce_reacceptance'):
            return None
    except Exception:
        return None
    from backend.utils.client_info import is_v4_client
    if not is_v4_client():
        return None   # v3 builds cannot show the modal (unless legacy clients are disallowed)
    cache_key = f'negoride.legal_blocking.{user.id}'   # per request (the app context may be shared)
    cached = request.environ.get(cache_key)
    if cached is None:
        cached = blocking_for(user)
        request.environ[cache_key] = cached
    if not cached:
        return None
    return jsonify({'code': 0, 'message': 'Please review and accept the updated policies to continue.',
                    'data': {'error_code': 'legal_pending', 'blocking': True, 'items': cached,
                             'pending': cached}}), 403


# ── CASL marketing consent proof ────────────────────────────────────────────

def marketing_wording(lang='en'):
    lang = normalize_lang(lang)
    text = S.get('legal.marketing_consent_text_fr') if lang == 'fr' else S.get('legal.marketing_consent_text')
    return S.get('legal.marketing_consent_version'), text


def record_marketing_consent(user, granted, source, ip=None, user_agent=None, app_version=None, lang=None,
                             wording_version=None, channels='email,sms'):
    """Append a CASL proof row (grant or withdraw). Caller commits."""
    from backend.models.identity import MarketingConsent
    lang = normalize_lang(lang or user.preferred_language)
    version, text = marketing_wording(lang)
    if wording_version and str(wording_version) != str(version):
        text = None   # the client showed another wording version — keep its tag, don't claim our text
        version = str(wording_version)[:40]
    row = MarketingConsent(user_id=user.id, action='grant' if granted else 'withdraw', channels=channels,
                           source=source[:40], wording_version=version, wording_text=text if granted else None,
                           language=lang, ip=ip, user_agent=(user_agent or '')[:500] or None,
                           app_version=app_version, created_at=datetime.utcnow())
    db.session.add(row)
    return row


# ── seed (migration v4_0202) ────────────────────────────────────────────────

def seed_rows():
    """[(type, version, language, title, summary, body, audience)] from legal_content."""
    from backend.services import legal_content as L
    rows = []
    for d in L.DOCUMENTS:
        for lang in LANGS:
            rows.append((d['type'], L.VERSION, lang, d['title'][lang], d['summary'][lang], d['body'][lang],
                         d.get('audience', 'all')))
    return rows
