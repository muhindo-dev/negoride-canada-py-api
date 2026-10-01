"""Socket.IO `/rt` namespace (spec §5.2).

Connect with the JWT:  io(url + '/rt', {auth: {token: '<jwt>'}})   (or ?token=…)
Unauthenticated / revoked / suspended sockets are REJECTED at connect.

Rooms joined automatically: user:{id}; admins also admin:ops (+ admin:sos for
super_admin / ops / safety_reviewer).

Client → server events
  ride:subscribe      {ride_type, ride_id}      join ride:{type}:{id} (parties/admin only)
  ride:unsubscribe    {ride_type, ride_id}
  location:update     {lat, lng, speed?, heading?, accuracy?, recorded_at?} and/or
                      {points: [{lat, lng, speed, heading, accuracy, recorded_at}]}  (offline catch-up)
                      ack → {ok, live, stored, received, rejected}
  notification:ack    {id}                      marks the notification opened
  ping                {}                         → pong

Sessions: Flask-SocketIO runs each handler in its own app context, whose
teardown releases the DB session — handlers only roll back on errors.

Server → client events (the same ride event can arrive via user:{id} AND ride:{type}:{id}
— dedupe on `event_id`): ride.stage_changed, ride.driver_location,
ride.eta_updated, notification, negotiation.updated, safety.sos, safety.sos_updated,
driver.location (admins), alert (admins)
"""
import logging

from flask import request
from flask_socketio import emit, join_room, leave_room, disconnect

from backend.models import db
from backend.services.realtime import NAMESPACE

log = logging.getLogger('negoride.rt')
_sid_user = {}   # sid → user_id


def register_realtime_events(socketio, app):

    @socketio.on('connect', namespace=NAMESPACE)
    def rt_connect(auth=None):
        from backend.utils.auth import user_from_token
        token = None
        if isinstance(auth, dict):
            token = auth.get('token')
        token = token or request.args.get('token') or request.headers.get('Authorization')
        user = user_from_token(token)
        if user is None or not user.is_account_active():
            return False  # reject: unauthenticated, revoked or inactive
        _sid_user[request.sid] = user.id
        join_room(f'user:{user.id}')
        roles = user.get_admin_roles()
        rooms = [f'user:{user.id}']
        if roles:
            join_room('admin:ops')
            rooms.append('admin:ops')
            if user.has_admin_role('ops', 'safety_reviewer'):
                join_room('admin:sos')
                rooms.append('admin:sos')
        emit('connected', {'user_id': user.id, 'rooms': rooms})
        return True

    @socketio.on('disconnect', namespace=NAMESPACE)
    def rt_disconnect(*_args):
        _sid_user.pop(request.sid, None)

    def _user():
        from backend.models.user import AdminUser
        uid = _sid_user.get(request.sid)
        return db.session.get(AdminUser, uid) if uid else None

    @socketio.on('ride:subscribe', namespace=NAMESPACE)
    def rt_ride_subscribe(data):
        from backend.services import rides as R
        try:
            user = _user()
            if not user:
                return disconnect()
            rt = R.normalize_type((data or {}).get('ride_type'))
            ride = R.load(rt, int((data or {}).get('ride_id')))
            if R.role_of(user, rt, ride) is None:
                emit('error', {'event': 'ride:subscribe', 'message': 'Forbidden'})
                return
            join_room(f'ride:{rt}:{ride.id}')
            emit('ride:subscribed', {'ride_type': rt, 'ride_id': ride.id, 'stage': R.current_stage(rt, ride)})
        except Exception as e:
            db.session.rollback()
            emit('error', {'event': 'ride:subscribe', 'message': str(e)})

    @socketio.on('ride:unsubscribe', namespace=NAMESPACE)
    def rt_ride_unsubscribe(data):
        try:
            from backend.services import rides as R
            rt = R.normalize_type((data or {}).get('ride_type'))
            leave_room(f'ride:{rt}:{int((data or {}).get("ride_id"))}')
        except Exception:
            pass

    @socketio.on('location:update', namespace=NAMESPACE)
    def rt_location(data):
        from backend.services import tracking
        try:
            user = _user()
            if not user:
                return disconnect()
            _p, _ctx, stats = tracking.ingest_batch(user, data or {})
            return {'ok': True, 'live': stats['live'], 'stored': stats['stored'],
                    'received': stats['received'], 'rejected': stats['rejected']}
        except tracking.LocationError as e:
            db.session.rollback()
            return {'ok': False, 'error': str(e)}
        except Exception:
            db.session.rollback()
            log.exception('location:update failed')
            return {'ok': False}

    @socketio.on('notification:ack', namespace=NAMESPACE)
    def rt_notification_ack(data):
        from backend.services.notify import mark_opened
        try:
            uid = _sid_user.get(request.sid)
            if uid and (data or {}).get('id'):
                mark_opened(uid, int(data['id']))
            return {'ok': True}
        except Exception:
            db.session.rollback()
            return {'ok': False}

    @socketio.on('ping', namespace=NAMESPACE)
    def rt_ping(_data=None):
        emit('pong', {})
