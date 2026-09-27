"""Server-Sent Events (SSE) endpoint.

Keeps one persistent HTTP connection per client.
Pushes a JSON event only when DB state actually changes — no unnecessary
network round-trips on the Flutter side.

Auth: a verified `Authorization: Bearer <token>` JWT, same as every other
  endpoint (via get_current_user). There is no user_id impersonation fallback.

IMPORTANT: The Flask dev server MUST run with threaded=True so that this
long-lived connection does not block all other requests.
"""
import json
import time
import threading
from datetime import datetime, timedelta
from flask import Response, stream_with_context, Blueprint, current_app

from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.negotiation_record import NegotiationRecord
from backend.utils.auth import get_current_user

stream_bp = Blueprint('stream', __name__)

# How often the server re-checks the DB (seconds).
_POLL_INTERVAL = 3
# Send a keepalive comment every N polls so proxies/NAT don't drop the conn.
_KEEPALIVE_EVERY = 10  # 10 * 3s = 30s

# Track active SSE connections for debugging
_active_connections: dict[int, float] = {}
_conn_lock = threading.Lock()


@stream_bp.route('/api/stream/events', methods=['GET'])
def stream_events():
    """SSE endpoint for both drivers and customers.

    Drivers  → receive negotiations where they are the assigned driver.
    Customers → receive negotiations where they are the originator.

    The stream never ends; the client keeps the connection open and reconnects
    automatically if it drops.
    """
    user = get_current_user()
    if not user:
        def _unauth():
            yield 'data: {"type":"error","msg":"Unauthorized"}\n\n'
        return Response(_unauth(), mimetype='text/event-stream', status=401)

    user_id = user.id
    is_driver = user.user_type in ('Driver', 'Pending Driver')

    # Track this connection
    with _conn_lock:
        _active_connections[user_id] = time.time()

    def generate():
        last_neg_hash = None
        last_rec_hash = None
        keepalive_counter = 0

        # Send an immediate handshake so the client knows the connection works
        yield f'data: {json.dumps({"type": "connected", "user_id": user_id, "role": "driver" if is_driver else "customer"})}\n\n'

        try:
            while True:
                try:
                    # ── Fresh session for each poll ──────────────────────────
                    db.session.expire_all()

                    # ── 1) Query negotiations relevant to this user ──────────
                    # Active negotiations, PLUS terminal ones (Cancelled/Completed)
                    # updated in the last 60s so the final state is delivered to the
                    # peer exactly once — otherwise a cancelled/completed trip simply
                    # vanishes from the feed and the other party's screen never reacts.
                    recent_cutoff = datetime.utcnow() - timedelta(seconds=60)
                    relevant = db.or_(
                        Negotiation.is_active == 'Yes',
                        Negotiation.status.in_(['Active', 'Accepted', 'Started']),
                        db.and_(
                            Negotiation.status.in_(['Cancelled', 'Canceled', 'Completed']),
                            Negotiation.updated_at >= recent_cutoff,
                        ),
                    )
                    owner_col = Negotiation.driver_id if is_driver else Negotiation.customer_id
                    negs = (
                        Negotiation.query
                        .filter(owner_col == user_id, relevant)
                        .order_by(Negotiation.id.desc())
                        .limit(10)
                        .all()
                    )

                    something_pushed = False

                    # ── Push negotiations if changed ─────────────────────────
                    curr_neg_hash = ','.join(
                        f'{n.id}:{n.trip_stage}:{n.status}:{n.customer_accepted}:{n.customer_driver}:{n.agreed_price}:{n.payment_status}:{n.stripe_paid}:{n.is_active}:{n.updated_at}'
                        for n in negs
                    )
                    if curr_neg_hash != last_neg_hash:
                        last_neg_hash = curr_neg_hash
                        payload = [n.to_dict() for n in negs]
                        yield f'data: {json.dumps({"type": "negotiations", "payload": payload})}\n\n'
                        something_pushed = True

                    # ── 2) Query records for all active negotiations ─────────
                    neg_ids = [n.id for n in negs]
                    if neg_ids:
                        records = (
                            NegotiationRecord.query
                            .filter(NegotiationRecord.negotiation_id.in_(neg_ids))
                            .order_by(NegotiationRecord.id.asc())
                            .all()
                        )
                    else:
                        records = []

                    curr_rec_hash = ','.join(
                        f'{r.id}:{r.price_accepted}:{r.is_seen}'
                        for r in records
                    )
                    if curr_rec_hash != last_rec_hash:
                        last_rec_hash = curr_rec_hash
                        rec_payload = [r.to_dict() for r in records]
                        yield f'data: {json.dumps({"type": "records", "payload": rec_payload})}\n\n'
                        something_pushed = True

                    # ── Keepalive if nothing was pushed ──────────────────────
                    if not something_pushed:
                        keepalive_counter += 1
                        if keepalive_counter >= _KEEPALIVE_EVERY:
                            keepalive_counter = 0
                            yield ': ping\n\n'
                    else:
                        keepalive_counter = 0

                    # ── Close session to release DB conn back to pool ────────
                    db.session.close()

                except GeneratorExit:
                    break
                except Exception as exc:
                    try:
                        db.session.close()
                    except Exception:
                        pass
                    yield f'data: {json.dumps({"type": "error", "msg": str(exc)})}\n\n'

                time.sleep(_POLL_INTERVAL)
        finally:
            # Cleanup connection tracking
            with _conn_lock:
                _active_connections.pop(user_id, None)
            try:
                db.session.close()
            except Exception:
                pass

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',   # tells nginx not to buffer SSE
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
        },
    )


@stream_bp.route('/api/stream/status', methods=['GET'])
def stream_status():
    """Debug endpoint: see active SSE connections."""
    with _conn_lock:
        conns = {
            str(uid): {'connected_since': ct}
            for uid, ct in _active_connections.items()
        }
    return {'active_connections': conns, 'count': len(conns)}
