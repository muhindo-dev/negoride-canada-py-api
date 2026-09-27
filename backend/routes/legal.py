"""Legal documents & consent API (spec §12).

GET  /api/legal/documents?audience=&lang=      current published version of each type (public)
GET  /api/legal/documents/<type>?lang=         one document (public — the website renders /terms etc.)
POST /api/legal/accept                         record acceptances (auth)
GET  /api/legal/pending?lang=                  documents the user must (re)accept (auth; blocking modal)
GET  /api/legal/acceptances                    the caller's acceptance history (auth)
"""
from flask import Blueprint, request

from backend.models import db
from backend.models.identity import LegalAcceptance, LegalDocument
from backend.services import legal_service as L
from backend.utils.auth import jwt_required_with_user
from backend.utils.client_info import app_version, client_ip, user_agent
from backend.utils.response import error_response, success_response

legal_bp = Blueprint('legal', __name__)


def _lang(user=None):
    return L.normalize_lang(request.args.get('lang') or request.headers.get('Accept-Language', '')[:2]
                            or (user.preferred_language if user else None))


@legal_bp.route('/api/legal/documents', methods=['GET'])
def documents():
    lang = _lang()
    audience = request.args.get('audience') or None
    ctx = L.render_context()
    full = request.args.get('full') in ('1', 'true')
    items = [L.render(d, ctx) if full else {**L.summary_of(d),
                                            'summary_markdown': L.render_text(d.summary_markdown, ctx)}
             for d in L.current_all(audience, lang)]
    return success_response('Legal documents', {'language': lang, 'items': items})


@legal_bp.route('/api/legal/documents/<doc_type>', methods=['GET'])
def document(doc_type):
    if doc_type not in L.TYPES:
        # website aliases (/guidelines → community_guidelines)
        doc_type = {'guidelines': 'community_guidelines', 'cancellation-policy': 'cancellation_policy',
                    'cancellation': 'cancellation_policy', 'safety': 'safety_policy',
                    'recording': 'recording_notice', 'driver-agreement': 'driver_agreement'}.get(doc_type, doc_type)
    if doc_type not in L.TYPES:
        return error_response('Unknown document.', data={'error_code': 'unknown_document'}, status_code=404)
    version = request.args.get('version')
    lang = _lang()
    if version:
        doc = (LegalDocument.query.filter_by(type=doc_type, version=version, language=lang)
               .filter(LegalDocument.status.in_(('published', 'archived'))).first())
    else:
        doc = L.current(doc_type, lang)
    if not doc:
        return error_response('Document not found.', data={'error_code': 'document_missing'}, status_code=404)
    return success_response(doc.title, L.render(doc))


@legal_bp.route('/api/legal/accept', methods=['POST'])
@jwt_required_with_user
def accept(user):
    data = request.get_json(silent=True) or request.form or {}
    ids = data.get('document_ids') or []
    types = data.get('types') or []
    if isinstance(ids, (str, int)):
        ids = [ids]
    if isinstance(types, str):
        types = [t.strip() for t in types.split(',') if t.strip()]
    if not ids and not types:
        return error_response('Provide document_ids or types.', data={'error_code': 'nothing_to_accept'})
    method = data.get('method') or 'modal'
    try:
        docs = L.resolve(ids, types, _lang(user))
        if any(d.type == L.BGC_CONSENT for d in docs) or method == 'esignature':
            if not (data.get('signature_name') or '').strip():
                return error_response('Type your full legal name to sign.',
                                      data={'error_code': 'signature_required'})
            if any(d.type == L.BGC_CONSENT for d in docs):
                method = 'esignature'
        rows = L.accept(user, docs, method=method, app_version=app_version(data),
                        signature_name=data.get('signature_name'), ip=client_ip(), user_agent=user_agent())
    except L.LegalError as e:
        db.session.rollback()
        return error_response(e.message, data={**e.data, 'error_code': e.code}, status_code=e.status)
    db.session.commit()
    return success_response('Thank you — your acceptance has been recorded.', {
        'accepted': [r.to_dict() for r in rows], 'pending': L.pending_for(user, _lang(user))})


@legal_bp.route('/api/legal/pending', methods=['GET'])
@jwt_required_with_user
def pending(user):
    items = L.pending_for(user, _lang(user))
    return success_response('Pending documents', {'blocking': bool(items), 'items': items})


@legal_bp.route('/api/legal/acceptances', methods=['GET'])
@jwt_required_with_user
def my_acceptances(user):
    rows = LegalAcceptance.query.filter_by(user_id=user.id).order_by(LegalAcceptance.id.desc()).all()
    return success_response('Acceptances', {'items': [r.to_dict() for r in rows]})
