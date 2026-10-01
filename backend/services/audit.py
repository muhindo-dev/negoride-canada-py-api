"""audit_logs writer (spec §2.8). Every admin action and every safety event
calls `audit(...)`. It adds to the current session; the caller commits."""
from flask import has_request_context, request

from backend.models import db
from backend.models.platform import AuditLog


def _jsonable(value):
    if value is None:
        return None
    if hasattr(value, 'to_dict'):
        value = value.to_dict()
    import json
    return json.loads(json.dumps(value, default=str))


def audit(action, actor=None, entity_type=None, entity_id=None, before=None, after=None,
          meta=None, actor_type=None):
    actor_id = getattr(actor, 'id', actor) if actor is not None else None
    if actor_type is None:
        if actor is None:
            actor_type = 'system'
        elif getattr(actor, 'user_type', None) in ('Admin', 'Super Admin') or getattr(actor, 'admin_roles', None):
            actor_type = 'admin'
        else:
            actor_type = 'user'
    ip = ua = None
    if has_request_context():
        # ProxyFix (app.py, TRUSTED_PROXY_COUNT) already resolved the real client
        # address into remote_addr; never trust the raw, client-controlled header.
        ip = (request.remote_addr or '')[:64]
        ua = (request.headers.get('User-Agent') or '')[:500]
    row = AuditLog(
        actor_id=actor_id, actor_type=actor_type, action=action,
        entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None,
        before_json=_jsonable(before), after_json=_jsonable(after), meta=_jsonable(meta),
        ip=ip, user_agent=ua,
    )
    db.session.add(row)
    return row
