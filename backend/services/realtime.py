"""Realtime event emitter (spec §5.1, §5.2).

Socket.IO namespace `/rt` with rooms:
    user:{id}            everything addressed to one user
    ride:{type}:{id}     live stage / location / ETA for one ride
    admin:ops            live operations (all stage changes, driver positions)
    admin:sos            safety alarms

The API process emits through its own SocketIO server. RQ worker processes
call `use_external_emitter()` and publish through the Redis message queue,
which the API's SocketIO server relays to connected clients.

Emits are best-effort: a realtime failure never breaks a business action.
"""
import logging

log = logging.getLogger('negoride.realtime')

NAMESPACE = '/rt'
_external = None
SENT = []          # test introspection when RECORD is on
RECORD = False


def use_external_emitter():
    """Worker processes: emit via the Redis message queue."""
    global _external
    from backend import jobs
    url = jobs.redis_url()
    if not url or not jobs.get_redis():
        return None
    from flask_socketio import SocketIO
    _external = SocketIO(message_queue=url)
    return _external


def _server():
    if _external is not None:
        return _external
    from backend.app import socketio
    return socketio


def emit(event, data, room):
    if RECORD:
        SENT.append((event, data, room))
    try:
        _server().emit(event, data, to=room, namespace=NAMESPACE)
    except Exception as exc:
        log.warning('realtime emit %s → %s failed: %s', event, room, exc)


def to_user(user_id, event, data):
    if user_id:
        emit(event, data, f'user:{int(user_id)}')


def to_ride(ride_type, ride_id, event, data):
    emit(event, data, f'ride:{ride_type}:{int(ride_id)}')


def to_admins(event, data, room='admin:ops'):
    emit(event, data, room)
