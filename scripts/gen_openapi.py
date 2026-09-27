#!/usr/bin/env python3
"""Generate docs/openapi.yaml from the live Flask route table (spec §19.2).

Every /api route is listed with its methods, path parameters, auth
requirement (derived from the decorators) and the first paragraph of the view's
docstring. Response bodies use the standard envelope schema. Detailed shapes
are in docs/API.md, docs/SAFETY.md, docs/PAYMENTS_AND_REFUNDS.md,
docs/DRIVER_ONBOARDING.md.

    .venv/bin/python scripts/gen_openapi.py
"""
import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('FLASK_ENV', 'development')

import yaml  # noqa: E402

from backend.app import app  # noqa: E402

TAGS = [
    ('/api/admin/safety', 'Admin · Safety'), ('/api/admin/finance', 'Admin · Finance'),
    ('/api/admin/receipts', 'Admin · Finance'), ('/api/admin/ratings', 'Admin · Ratings'),
    ('/api/admin/reports', 'Admin · Reports'), ('/api/admin/analytics', 'Admin · Reports'),
    ('/api/admin/live', 'Admin · Live map'), ('/api/admin', 'Admin'),
    ('/api/rides', 'Rides (v4)'), ('/api/safety', 'Safety'), ('/api/public', 'Public'),
    ('/api/recordings', 'Safety'), ('/api/verify', 'Identity'), ('/api/auth', 'Identity'),
    ('/api/otp', 'Identity'), ('/api/legal', 'Legal'), ('/api/driver/onboarding', 'Driver onboarding'),
    ('/api/driver', 'Driver'), ('/api/account', 'Account'), ('/api/support', 'Support'),
    ('/api/notification', 'Notifications'), ('/api/devices', 'Notifications'), ('/api/app', 'App'),
    ('/api/rideshare', 'Rideshare (v4)'), ('/api/carhire', 'Car hire (v4)'),
    ('/api/favourite-drivers', 'Car hire (v4)'), ('/api/ratings', 'Ratings'), ('/api/drivers', 'Ratings'),
    ('/api/pricing', 'Experience'), ('/api/places', 'Experience'), ('/api/analytics', 'Experience'),
    ('/api/receipts', 'Receipts'), ('/api/webhooks', 'Webhooks'), ('/api/negotiation', 'Legacy · Car hire'),
    ('/api/bookings', 'Legacy · Bookings'), ('/api/trips', 'Legacy · Rideshare'), ('/api/', 'Legacy'),
]


def tag_for(path):
    for prefix, tag in TAGS:
        if path.startswith(prefix):
            return tag
    return 'Other'


def build():
    paths = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if not rule.rule.startswith('/api/'):
            continue
        view = app.view_functions[rule.endpoint]
        mod = sys.modules.get(getattr(inspect.unwrap(view), '__module__', ''), None)
        try:
            src = inspect.getsource(mod) if mod else ''
        except (OSError, TypeError):
            src = ''
        fname = inspect.unwrap(view).__name__
        m = re.search(r'((?:@[^\n]+\n)+)def ' + re.escape(fname) + r'\(', src)
        decos = m.group(1) if m else ''
        if 'admin_role_required' in decos or 'admin_required' in decos:
            security = [{'bearerAuth': []}]
            auth_note = 'Admin (role-based)'
        elif 'jwt_required_with_user' in decos or '/api/rides/' in rule.rule:
            security = [{'bearerAuth': []}]
            auth_note = 'User JWT'
        else:
            security = []
            auth_note = 'Public / signature-verified'
        doc = inspect.getdoc(inspect.unwrap(view)) or ''
        summary = doc.split('\n\n')[0].replace('\n', ' ')[:200] if doc else fname.replace('_', ' ')
        oapath = re.sub(r'<(?:[a-z]+:)?([a-zA-Z_]+)>', r'{\1}', rule.rule)
        params = [{'name': p, 'in': 'path', 'required': True,
                   'schema': {'type': 'integer' if f'int:{p}' in rule.rule else 'string'}}
                  for p in re.findall(r'<(?:[a-z]+:)?([a-zA-Z_]+)>', rule.rule)]
        for method in sorted(rule.methods - {'HEAD', 'OPTIONS'}):
            op = {
                'tags': [tag_for(rule.rule)], 'summary': summary, 'operationId': f'{rule.endpoint}_{method.lower()}',
                'description': f'{doc}\n\nAuth: {auth_note}.' if doc else f'Auth: {auth_note}.',
                'responses': {'200': {'description': 'Envelope', 'content': {'application/json': {
                    'schema': {'$ref': '#/components/schemas/Envelope'}}}},
                    '4XX': {'description': 'Error envelope (code 0, data.error_code)', 'content': {
                        'application/json': {'schema': {'$ref': '#/components/schemas/Envelope'}}}}},
            }
            if params:
                op['parameters'] = params
            if security:
                op['security'] = security
            if method in ('POST', 'PUT', 'PATCH') and security:
                op.setdefault('parameters', []).append({'name': 'Idempotency-Key', 'in': 'header', 'required': False,
                                                         'schema': {'type': 'string'}})
            paths.setdefault(oapath, {})[method.lower()] = op
    return {
        'openapi': '3.0.3',
        'info': {'title': 'NegoRide Canada API', 'version': '4.0.0',
                 'description': 'Generated from the Flask route table by scripts/gen_openapi.py. '
                                'Every response uses the envelope {code: 1|0, message, data}. '
                                'Money is integer cents (CAD) in v4 endpoints; timestamps are ISO-8601 UTC. '
                                'Detailed payloads: docs/API.md, docs/SAFETY.md, docs/PAYMENTS_AND_REFUNDS.md, '
                                'docs/DRIVER_ONBOARDING.md, docs/TRIP_STATE_MACHINE.md, docs/NOTIFICATIONS.md.'},
        'servers': [{'url': 'https://negoride.ugnews24.info'}, {'url': 'http://localhost:5001'}],
        'components': {
            'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}},
            'schemas': {'Envelope': {'type': 'object', 'required': ['code', 'message'], 'properties': {
                'code': {'type': 'integer', 'enum': [0, 1]}, 'message': {'type': 'string'},
                'data': {'description': 'Payload; on errors may contain error_code'}}}},
        },
        'paths': paths,
    }


if __name__ == '__main__':
    spec = build()
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'openapi.yaml')
    with open(out, 'w') as f:
        yaml.safe_dump(spec, f, sort_keys=False, allow_unicode=True, width=120)
    print(f'{len(spec["paths"])} paths → {out}')
