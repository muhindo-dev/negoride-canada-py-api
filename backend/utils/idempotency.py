"""`Idempotency-Key` support (spec §2.4).

Decorate a state-changing endpoint (after the auth decorator):

    @bp.route(...)
    @jwt_required_with_user
    @idempotent
    def pay(user, ...): ...

A repeated request with the same key from the same user to the same endpoint
returns the stored response instead of executing again. Requests without the
header run normally (older app builds).
"""
import json
from functools import wraps

from flask import request
from sqlalchemy.exc import IntegrityError

from backend.models import db
from backend.models.platform import IdempotencyKey


def idempotent(fn):
    @wraps(fn)
    def wrapper(user, *args, **kwargs):
        key = (request.headers.get('Idempotency-Key') or '').strip()[:120]
        if not key:
            return fn(user, *args, **kwargs)
        endpoint = f'{request.method} {request.path}'[:191]
        prior = IdempotencyKey.query.filter_by(user_id=user.id, endpoint=endpoint, idem_key=key).first()
        if prior and prior.response_json is not None:
            from flask import Response
            resp = Response(prior.response_json, status=prior.status_code or 200, mimetype='application/json')
            resp.headers['Idempotent-Replayed'] = 'true'
            return resp
        rv = fn(user, *args, **kwargs)
        resp, status = (rv if isinstance(rv, tuple) else (rv, 200))
        code = getattr(resp, 'status_code', status) if not isinstance(rv, tuple) else status
        # Only successful responses are stored; failures may be retried.
        if 200 <= int(code) < 300:
            try:
                body = resp.get_data(as_text=True)
                json.loads(body)
                db.session.add(IdempotencyKey(user_id=user.id, endpoint=endpoint, idem_key=key,
                                              status_code=int(code), response_json=body))
                db.session.commit()
            except (IntegrityError, ValueError):
                db.session.rollback()
        return rv
    return wrapper
