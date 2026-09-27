"""API documentation: Swagger UI at /api/docs over docs/openapi.yaml (spec §19.2).

Protected by an admin login in production. The page first asks for an admin
JWT (paste the token from the admin console) unless API_DOCS_PUBLIC=1 outside
production.
"""
import os

from flask import Blueprint, Response, request, send_file

from backend.utils.auth import get_current_user

docs_bp = Blueprint('docs', __name__)
SPEC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'docs', 'openapi.yaml')

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>NegoRide API docs</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head>
<body style="margin:0"><div id="ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
const token = sessionStorage.getItem('nr_docs_token') || (PUBLIC ? '' : prompt('Admin JWT (from the admin console):'));
if (token) sessionStorage.setItem('nr_docs_token', token);
SwaggerUIBundle({dom_id: '#ui', url: '/api/docs/openapi.yaml', persistAuthorization: true,
  requestInterceptor: r => { if (token && r.url.endsWith('openapi.yaml')) r.headers.Authorization = 'Bearer ' + token; return r; }});
</script></body></html>"""


def _public():
    return os.getenv('API_DOCS_PUBLIC') == '1' and (os.getenv('FLASK_ENV') or '').lower() != 'production'


def _allowed():
    if _public():
        return True
    user = get_current_user()
    return bool(user and user.get_admin_roles())


@docs_bp.route('/api/docs', methods=['GET'])
def docs_page():
    return Response(_PAGE.replace('PUBLIC', 'true' if _public() else 'false'), mimetype='text/html')


@docs_bp.route('/api/docs/openapi.yaml', methods=['GET'])
def docs_spec():
    if not _allowed():
        return {'code': 0, 'message': 'Admin access required'}, 401
    if not os.path.exists(SPEC):
        return {'code': 0, 'message': 'Run scripts/gen_openapi.py'}, 404
    return send_file(SPEC, mimetype='application/yaml')
