"""
Socket.IO signaling event handlers for WebRTC calling.

Architecture:
    - All media (audio/video) flows peer-to-peer via WebRTC.
    - This server only relays signaling messages: offers, answers, ICE candidates.
    - In-memory dictionaries track active calls and sessions.
    - 120-second grace period survives socket disconnections during active calls.
    - 45-second ring timeout auto-cancels unanswered calls.

Events (Client → Server → Client):
    authenticate       → maps socket SID to user_id
    call_user          → incoming_call (to callee)
    call_accepted      → call_accepted (to caller)
    call_rejected      → call_rejected (to caller)
    ice_candidate      → ice_candidate (to peer)
    end_call           → call_ended (to peer)
    media_state_changed→ remote_media_state (to peer)
    renegotiate_offer  → renegotiate_offer (to peer)
    renegotiate_answer → renegotiate_answer (to peer)
    call_session_check → call_session_restore (to self, if session exists)
"""

import time
import uuid
import threading
from datetime import datetime

from flask import request
from flask_socketio import emit

from backend.models import db
from backend.models.call_log import CallLog
from backend.models.negotiation import Negotiation
from backend.models.user import AdminUser


# ══════════════════════════════════════════════════════════════
# In-memory state (per server instance)
# ══════════════════════════════════════════════════════════════

# Socket mapping: user_id ↔ socket SID
user_sockets = {}          # {user_id: sid}
user_sockets_reverse = {}  # {sid: user_id}

# Active calls: user_id → partner_user_id
active_calls = {}          # {13039: 13041, 13041: 13039}

# Call metadata
call_meta = {}             # {caller_id: {call_type, started_at, call_id}}

# Ring timeout tracking
ring_start = {}            # {caller_id: timestamp}
ring_timers = {}           # {caller_id: Timer}

# Media state tracking
call_media_state = {}      # {user_id: {muted, video_on}}

# Persistent call sessions (survive socket reconnects)
call_sessions = {}         # {session_id: {session_id, caller_id, callee_id, ...}}
user_call_session = {}     # {user_id: session_id}

# Disconnection grace period tracking
disconnected_users = {}    # {user_id: {timer, session_id, disconnected_at}}

# Constants
RING_TIMEOUT_SECONDS = 45
DISCONNECT_GRACE_SECONDS = 120
STALE_ACTIVE_LOCK_SECONDS = 180

# Guard shared in-memory call maps against race conditions
state_lock = threading.RLock()


# ══════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════

def get_user_sid(user_id):
    """Get socket SID for a user_id."""
    return user_sockets.get(user_id)


def get_sid_user(sid):
    """Get user_id for a socket SID."""
    return user_sockets_reverse.get(sid)


def _get_user_info(user_id):
    """Fetch minimal user info for signaling payloads."""
    user = db.session.get(AdminUser, user_id)
    if not user:
        return {'id': user_id, 'name': 'Unknown', 'avatar': None}
    return {
        'id': user.id,
        'name': user.name or user.username,
        'avatar': user.avatar,
    }


def _is_participant(negotiation, user_id):
    return user_id in (negotiation.customer_id, negotiation.driver_id)


def _create_call_session(caller_id, callee_id, call_type, call_id=None):
    """Create a persistent call session that survives socket reconnects."""
    session_id = str(uuid.uuid4())
    call_sessions[session_id] = {
        'session_id': session_id,
        'caller_id': caller_id,
        'callee_id': callee_id,
        'call_type': call_type,
        'started_at': datetime.utcnow().isoformat(),
        'call_id': call_id,
        'status': 'active',
    }
    user_call_session[caller_id] = session_id
    user_call_session[callee_id] = session_id
    return session_id


def _end_call_session(session_id, reason='normal'):
    """Clean up a call session."""
    session = call_sessions.pop(session_id, None)
    if session:
        user_call_session.pop(session.get('caller_id'), None)
        user_call_session.pop(session.get('callee_id'), None)

        # Update the CallLog in DB
        call_id = session.get('call_id')
        if call_id:
            try:
                call_log = db.session.get(CallLog, int(call_id))
                if call_log and call_log.status != 'ended':
                    call_log.status = 'ended'
                    call_log.ended_at = datetime.utcnow()
                    call_log.end_reason = reason
                    if call_log.answered_at:
                        call_log.duration = int(
                            (call_log.ended_at - call_log.answered_at).total_seconds()
                        )
                    db.session.commit()
            except Exception as e:
                print(f'[Call] Failed to update call log: {e}', flush=True)


def _cleanup_call_tracking(user_id, partner_id=None):
    """Remove all in-memory call tracking for a user pair."""
    timer = ring_timers.pop(user_id, None)
    if timer:
        timer.cancel()

    active_calls.pop(user_id, None)
    call_meta.pop(user_id, None)
    ring_start.pop(user_id, None)
    call_media_state.pop(user_id, None)

    if partner_id:
        partner_timer = ring_timers.pop(partner_id, None)
        if partner_timer:
            partner_timer.cancel()

        active_calls.pop(partner_id, None)
        call_meta.pop(partner_id, None)
        ring_start.pop(partner_id, None)
        call_media_state.pop(partner_id, None)


def _prune_stale_user_state(user_id):
    """Best-effort cleanup of stale in-memory locks for a user."""
    now = time.time()

    # If user points to a non-existent session, clear that stale mapping.
    session_id = user_call_session.get(user_id)
    if session_id and session_id not in call_sessions:
        user_call_session.pop(user_id, None)

    partner_id = active_calls.get(user_id)
    if partner_id is None:
        return

    # Active pair without session is stale unless still in ring window.
    has_valid_session = bool(user_call_session.get(user_id) in call_sessions)
    started = ring_start.get(user_id) or ring_start.get(partner_id)

    is_stale_ringing = started and (now - started) > RING_TIMEOUT_SECONDS
    is_stale_active = (not has_valid_session) and (
        started is None or (now - started) > STALE_ACTIVE_LOCK_SECONDS
    )

    if is_stale_ringing or is_stale_active:
        _cleanup_call_tracking(user_id, partner_id)


def _has_live_call_lock(user_id):
    """Return True only when the user appears to be in a genuinely live call/ring."""
    partner_id = active_calls.get(user_id)
    if partner_id is None:
        return False

    # A tracked session is authoritative for active calls.
    session_id = user_call_session.get(user_id)
    if session_id and session_id in call_sessions:
        return True

    # Pending ring calls only track the caller in active_calls. Treat recent
    # ring windows as live; otherwise aggressively release stale lock state.
    started = ring_start.get(user_id) or ring_start.get(partner_id)
    if started and (time.time() - started) <= (RING_TIMEOUT_SECONDS + 5):
        return True

    _cleanup_call_tracking(user_id, partner_id)
    return False


# ══════════════════════════════════════════════════════════════
# Register all Socket.IO event handlers
# ══════════════════════════════════════════════════════════════

def register_call_events(socketio, app):
    """Register all call-related Socket.IO event handlers."""

    # ─── Authentication ──────────────────────────────────

    @socketio.on('authenticate')
    def handle_authenticate(data):
        """Map socket SID to authenticated user_id."""
        token = data.get('token', '')
        if not token:
            emit('auth_error', {'error': 'Token required'})
            return

        with app.app_context():
            from flask_jwt_extended import decode_token
            try:
                decoded = decode_token(token)
                user_id = int(decoded['sub'])
                user = db.session.get(AdminUser, user_id)
                if not user:
                    emit('auth_error', {'error': 'User not found'})
                    return

                sid = request.sid

                # Clean up old socket mapping for this user
                old_sid = user_sockets.get(user_id)
                if old_sid and old_sid != sid:
                    user_sockets_reverse.pop(old_sid, None)

                user_sockets[user_id] = sid
                user_sockets_reverse[sid] = user_id

                print(f'[Call] User {user_id} ({user.name}) authenticated (sid={sid[:8]}...)', flush=True)

                emit('authenticated', {
                    'user_id': user_id,
                    'name': user.name,
                })

                # Check if user was disconnected from an active call
                _handle_user_reconnect(user_id, socketio, app)

            except Exception as e:
                print(f'[Call] Auth failed: {e}', flush=True)
                emit('auth_error', {'error': 'Invalid token'})

    # ─── Call Initiation ─────────────────────────────────

    @socketio.on('call_user')
    def handle_call_user(data):
        """Caller initiates a call to target user."""
        caller_id = get_sid_user(request.sid)
        if not caller_id:
            emit('call_error', {'error': 'Not authenticated'})
            return

        target_id = data.get('target_id') or data.get('callee_id')
        call_type = data.get('call_type', 'voice')
        negotiation_id = data.get('negotiation_id')

        if not target_id:
            emit('call_error', {'error': 'target_id is required'})
            return

        target_id = int(target_id)

        with app.app_context():
            # Validate negotiation participation
            if negotiation_id:
                neg = db.session.get(Negotiation, int(negotiation_id))
                if not neg:
                    emit('call_error', {'error': 'Negotiation not found'})
                    return
                if not _is_participant(neg, caller_id) or not _is_participant(neg, target_id):
                    emit('call_error', {'error': 'Not a participant in this negotiation'})
                    return

            with state_lock:
                _prune_stale_user_state(caller_id)
                _prune_stale_user_state(target_id)

                # Check if caller is already in a call
                if _has_live_call_lock(caller_id):
                    emit('call_error', {'error': 'You are already in a call'})
                    return

                # Check if target is online
                target_sid = get_user_sid(target_id)
                if not target_sid:
                    target_info = _get_user_info(target_id)
                    emit('call_error', {
                        'error': f'{target_info["name"]} is offline',
                        'reason': 'offline',
                    })
                    return

                # Check if target is already in a call
                if _has_live_call_lock(target_id):
                    target_info = _get_user_info(target_id)
                    emit('call_error', {
                        'error': f'{target_info["name"]} is on another call',
                        'reason': 'busy',
                    })
                    return

                # Track pending call (caller side only initially)
                active_calls[caller_id] = target_id
                ring_start[caller_id] = time.time()
                call_media_state[caller_id] = {
                    'muted': False,
                    'video_on': call_type == 'video',
                }

                # Auto-release stale unanswered calls on server side.
                timer = ring_timers.pop(caller_id, None)
                if timer:
                    timer.cancel()

                call_id = data.get('call_id')

                def _ring_timeout_expired():
                    with app.app_context():
                        with state_lock:
                            # Skip if no longer the same pending call.
                            if active_calls.get(caller_id) != target_id:
                                return
                            if user_call_session.get(caller_id) in call_sessions:
                                return

                            _cleanup_call_tracking(caller_id, target_id)

                        # Best-effort DB update for missed/no-answer calls.
                        if call_id:
                            try:
                                call_log = db.session.get(CallLog, int(call_id))
                                if call_log and call_log.status in ('initiated', 'ringing'):
                                    call_log.status = 'missed'
                                    call_log.ended_at = datetime.utcnow()
                                    call_log.end_reason = 'no_answer'
                                    db.session.commit()
                            except Exception as e:
                                print(f'[Call] Failed to mark ring-timeout log: {e}', flush=True)

                        caller_sid = get_user_sid(caller_id)
                        callee_sid = get_user_sid(target_id)
                        payload = {
                            'from_id': caller_id,
                            'reason': 'no_answer',
                            'call_id': call_id,
                        }
                        if caller_sid:
                            socketio.emit('call_ended', payload, room=caller_sid)
                        if callee_sid:
                            socketio.emit('call_ended', payload, room=callee_sid)

                timeout_timer = threading.Timer(RING_TIMEOUT_SECONDS, _ring_timeout_expired)
                timeout_timer.daemon = True
                timeout_timer.start()
                ring_timers[caller_id] = timeout_timer

            caller_info = _get_user_info(caller_id)

            print(f'[Call] === CALL_USER ===', flush=True)
            print(f'[Call]   {caller_info["name"]} ({caller_id}) → {target_id} ({call_type})', flush=True)
            print(f'[Call]   negotiation_id={negotiation_id}', flush=True)
            print(f'[Call]   call_id={data.get("call_id")}', flush=True)
            print(f'[Call]   has offer: {data.get("offer") is not None}', flush=True)
            if data.get('offer'):
                print(f'[Call]   offer type: {data["offer"].get("type")}', flush=True)
                print(f'[Call]   offer sdp length: {len(data["offer"].get("sdp", ""))}', flush=True)
            print(f'[Call]   target_sid: {target_sid[:8]}...', flush=True)

            # Forward to callee
            emit('incoming_call', {
                'caller_id': caller_id,
                'caller': caller_info,
                'call_type': call_type,
                'offer': data.get('offer'),
                'call_id': data.get('call_id'),
                'negotiation_id': negotiation_id,
            }, room=target_sid)

            print(f'[Call]   incoming_call emitted to {target_id}', flush=True)

    # ─── Call Acceptance ─────────────────────────────────

    @socketio.on('call_accepted')
    def handle_call_accepted(data):
        """Callee accepts the incoming call."""
        callee_id = get_sid_user(request.sid)
        if not callee_id:
            emit('call_error', {'error': 'Not authenticated'})
            return

        caller_id = data.get('caller_id')
        if not caller_id:
            return

        caller_id = int(caller_id)
        caller_sid = get_user_sid(caller_id)
        call_type = data.get('call_type', 'voice')

        with app.app_context():
            with state_lock:
                _prune_stale_user_state(caller_id)
                _prune_stale_user_state(callee_id)

                # Track both sides as active
                active_calls[callee_id] = caller_id
                active_calls[caller_id] = callee_id
                ring_start.pop(caller_id, None)
                timer = ring_timers.pop(caller_id, None)
                if timer:
                    timer.cancel()

                # Initialize media state for callee
                call_media_state[callee_id] = {
                    'muted': False,
                    'video_on': call_type == 'video',
                }

                # Create persistent session
                session_id = _create_call_session(
                    caller_id, callee_id, call_type,
                    call_id=data.get('call_id'),
                )

            callee_info = _get_user_info(callee_id)

            print(f'[Call] === CALL_ACCEPTED ===', flush=True)
            print(f'[Call]   {callee_info["name"]} ({callee_id}) accepted call from {caller_id}', flush=True)
            print(f'[Call]   has answer: {data.get("answer") is not None}', flush=True)
            if data.get('answer'):
                print(f'[Call]   answer type: {data["answer"].get("type")}', flush=True)
                print(f'[Call]   answer sdp length: {len(data["answer"].get("sdp", ""))}', flush=True)
            print(f'[Call]   session_id: {session_id}', flush=True)
            print(f'[Call]   caller_sid: {caller_sid[:8] if caller_sid else "NONE"}...', flush=True)

            # Forward answer to caller
            if caller_sid:
                emit('call_accepted', {
                    'callee_id': callee_id,
                    'callee': callee_info,
                    'answer': data.get('answer'),
                    'call_id': data.get('call_id'),
                    'session_id': session_id,
                }, room=caller_sid)
                print(f'[Call]   call_accepted emitted to caller {caller_id}', flush=True)
            else:
                print(f'[Call]   WARNING: caller_sid is None! Caller {caller_id} not connected!', flush=True)

            # Broadcast call status
            emit('user_call_status', {
                'user_id': caller_id,
                'in_call': True,
            }, broadcast=True)
            emit('user_call_status', {
                'user_id': callee_id,
                'in_call': True,
            }, broadcast=True)

    # ─── Call Rejection ──────────────────────────────────

    @socketio.on('call_rejected')
    def handle_call_rejected(data):
        """Callee rejects the incoming call."""
        callee_id = get_sid_user(request.sid)
        if not callee_id:
            return

        caller_id = data.get('caller_id')
        if not caller_id:
            return

        caller_id = int(caller_id)
        caller_sid = get_user_sid(caller_id)

        with app.app_context():
            with state_lock:
                _cleanup_call_tracking(caller_id, callee_id)

            callee_info = _get_user_info(callee_id)

            print(f'[Call] {callee_info["name"]} rejected call from {caller_id}', flush=True)

            if caller_sid:
                emit('call_rejected', {
                    'callee_id': callee_id,
                    'call_id': data.get('call_id'),
                }, room=caller_sid)

    # ─── ICE Candidate Exchange ──────────────────────────

    @socketio.on('ice_candidate')
    def handle_ice_candidate(data):
        """Trickle ICE candidates to the peer."""
        user_id = get_sid_user(request.sid)
        if not user_id:
            return

        target_id = data.get('target_id')
        if not target_id:
            return

        target_sid = get_user_sid(int(target_id))
        if target_sid:
            print(f'[Call] ICE candidate: {user_id} → {target_id}', flush=True)
            emit('ice_candidate', {
                'candidate': data.get('candidate'),
                'from_id': user_id,
            }, room=target_sid)

    # ─── Call Termination ────────────────────────────────

    @socketio.on('end_call')
    def handle_end_call(data):
        """End the call (either party)."""
        user_id = get_sid_user(request.sid)
        if not user_id:
            return

        target_id = data.get('target_id') or data.get('callee_id')
        reason = data.get('reason', 'normal')

        with app.app_context():
            with state_lock:
                _prune_stale_user_state(user_id)

                # End call session if one exists
                session_id = user_call_session.get(user_id)

                print(f'[Call] === END_CALL ===', flush=True)
                print(f'[Call]   user_id: {user_id}', flush=True)
                print(f'[Call]   target_id: {target_id}', flush=True)
                print(f'[Call]   reason: {reason}', flush=True)
                print(f'[Call]   session_id: {session_id}', flush=True)
                print(f'[Call]   active_calls: {active_calls}', flush=True)

                if session_id:
                    _end_call_session(session_id, reason=reason)

                partner_id = None
                if target_id:
                    partner_id = int(target_id)
                elif user_id in active_calls:
                    partner_id = active_calls[user_id]

                _cleanup_call_tracking(user_id, partner_id)

            print(f'[Call] User {user_id} ended call (reason: {reason})', flush=True)

            if partner_id:
                partner_sid = get_user_sid(partner_id)
                if partner_sid:
                    emit('call_ended', {
                        'from_id': user_id,
                        'call_id': data.get('call_id'),
                        'reason': reason,
                    }, room=partner_sid)

                # Broadcast call status
                emit('user_call_status', {
                    'user_id': user_id,
                    'in_call': False,
                }, broadcast=True)
                emit('user_call_status', {
                    'user_id': partner_id,
                    'in_call': False,
                }, broadcast=True)

    # ─── Media State Sync ────────────────────────────────

    @socketio.on('media_state_changed')
    def handle_media_state_changed(data):
        """Sync mute/video state to partner."""
        user_id = get_sid_user(request.sid)
        if not user_id:
            return

        call_media_state[user_id] = {
            'muted': data.get('muted', False),
            'video_on': data.get('video_on', False),
        }

        target_id = data.get('target_id')
        if target_id:
            target_sid = get_user_sid(int(target_id))
            if target_sid:
                emit('remote_media_state', {
                    'user_id': user_id,
                    'muted': data.get('muted', False),
                    'video_on': data.get('video_on', False),
                }, room=target_sid)

    # ─── Renegotiation (add/remove video mid-call) ──────

    @socketio.on('renegotiate_offer')
    def handle_renegotiate_offer(data):
        """Forward renegotiation offer (e.g., add video to voice call)."""
        user_id = get_sid_user(request.sid)
        if not user_id:
            return

        target_id = data.get('target_id')
        if target_id:
            target_sid = get_user_sid(int(target_id))
            if target_sid:
                emit('renegotiate_offer', {
                    'from_id': user_id,
                    'offer': data.get('offer'),
                }, room=target_sid)

    @socketio.on('renegotiate_answer')
    def handle_renegotiate_answer(data):
        """Forward renegotiation answer."""
        user_id = get_sid_user(request.sid)
        if not user_id:
            return

        target_id = data.get('target_id')
        if target_id:
            target_sid = get_user_sid(int(target_id))
            if target_sid:
                emit('renegotiate_answer', {
                    'from_id': user_id,
                    'answer': data.get('answer'),
                }, room=target_sid)

    # ─── Session Recovery ────────────────────────────────

    @socketio.on('call_session_check')
    def handle_call_session_check(data):
        """Check if user has an active call session (for reconnection)."""
        user_id = get_sid_user(request.sid)
        if not user_id:
            emit('call_session_restore', {'session': None})
            return

        with app.app_context():
            session_id = user_call_session.get(user_id)
            if not session_id or session_id not in call_sessions:
                emit('call_session_restore', {'session': None})
                return

            session = call_sessions[session_id]
            partner_id = (
                session['callee_id'] if session['caller_id'] == user_id
                else session['caller_id']
            )
            partner_info = _get_user_info(partner_id)

            emit('call_session_restore', {
                'session': {
                    'session_id': session_id,
                    'partner_id': partner_id,
                    'partner': partner_info,
                    'call_type': session['call_type'],
                    'started_at': session['started_at'],
                    'call_id': session.get('call_id'),
                },
            })

    # ─── Socket Disconnect Handling ──────────────────────

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle socket disconnection — start grace period if in a call."""
        sid = request.sid
        user_id = user_sockets_reverse.pop(sid, None)
        if not user_id:
            return

        # Clean up socket mapping
        if user_sockets.get(user_id) == sid:
            user_sockets.pop(user_id, None)

        print(f'[Call] User {user_id} disconnected (sid={sid[:8]}...)', flush=True)

        _handle_user_disconnect(user_id, socketio, app)

    # ─── Utility: Online Status ──────────────────────────

    @socketio.on('check_user_online')
    def handle_check_user_online(data):
        """Check if a specific user is currently online."""
        target_id = data.get('user_id')
        if target_id:
            online = get_user_sid(int(target_id)) is not None
            emit('user_online_status', {
                'user_id': int(target_id),
                'online': online,
            })


# ══════════════════════════════════════════════════════════════
# Disconnect / Reconnect Grace Period (120 seconds)
# ══════════════════════════════════════════════════════════════

def _handle_user_disconnect(user_id, socketio, app):
    """Called when a user's socket disconnects. Start grace period if in a call."""
    with state_lock:
        _prune_stale_user_state(user_id)
        session_id = user_call_session.get(user_id)

        if not session_id:
            # Not in a tracked call session — clean up any pending call state
            partner_id = active_calls.get(user_id)
            _cleanup_call_tracking(user_id, partner_id)
            return

    session = call_sessions.get(session_id)
    if not session:
        return

    partner_id = (
        session['callee_id'] if session['caller_id'] == user_id
        else session['caller_id']
    )

    # Notify partner that peer disconnected (grace period starts)
    partner_sid = get_user_sid(partner_id)
    if partner_sid:
        socketio.emit('call_peer_disconnected', {
            'user_id': user_id,
            'session_id': session_id,
            'grace_seconds': DISCONNECT_GRACE_SECONDS,
        }, room=partner_sid)

    # Start grace period timer
    def _grace_expired():
        with app.app_context():
            print(f'[Call] Grace period expired for user {user_id}', flush=True)

            _end_call_session(session_id, reason='network_timeout')
            _cleanup_call_tracking(user_id, partner_id)
            disconnected_users.pop(user_id, None)

            p_sid = get_user_sid(partner_id)
            if p_sid:
                socketio.emit('call_ended', {
                    'from_id': user_id,
                    'reason': 'network_timeout',
                    'session_id': session_id,
                }, room=p_sid)

                socketio.emit('user_call_status', {
                    'user_id': user_id,
                    'in_call': False,
                }, broadcast=True)
                socketio.emit('user_call_status', {
                    'user_id': partner_id,
                    'in_call': False,
                }, broadcast=True)

    timer = threading.Timer(DISCONNECT_GRACE_SECONDS, _grace_expired)
    timer.daemon = True
    timer.start()

    disconnected_users[user_id] = {
        'timer': timer,
        'session_id': session_id,
        'disconnected_at': time.time(),
    }


def _handle_user_reconnect(user_id, socketio, app):
    """Called when a user re-authenticates. Restore call session if within grace period."""
    dc = disconnected_users.pop(user_id, None)
    if not dc:
        return

    # Cancel grace timer
    timer = dc.get('timer')
    if timer:
        timer.cancel()

    session_id = dc['session_id']
    session = call_sessions.get(session_id)
    if not session:
        return  # Session already ended by partner

    partner_id = (
        session['callee_id'] if session['caller_id'] == user_id
        else session['caller_id']
    )

    # Restore active_calls tracking
    with state_lock:
        active_calls[user_id] = partner_id
        active_calls[partner_id] = user_id

    elapsed = int(time.time() - dc['disconnected_at'])
    print(f'[Call] User {user_id} reconnected after {elapsed}s — restoring call session', flush=True)

    # Notify reconnecting user to resume
    user_sid = get_user_sid(user_id)
    if user_sid:
        partner_info = _get_user_info(partner_id)
        socketio.emit('call_session_restore', {
            'session': {
                'session_id': session_id,
                'partner_id': partner_id,
                'partner': partner_info,
                'call_type': session['call_type'],
                'started_at': session['started_at'],
                'call_id': session.get('call_id'),
            },
        }, room=user_sid)

    # Notify partner
    partner_sid = get_user_sid(partner_id)
    if partner_sid:
        socketio.emit('call_peer_reconnected', {
            'user_id': user_id,
        }, room=partner_sid)
