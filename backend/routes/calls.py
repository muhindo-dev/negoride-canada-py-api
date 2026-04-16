"""
REST API endpoints for the in-app calling system.

Endpoints:
    GET  /api/call/ice-config    → STUN/TURN server configuration
    POST /api/call/log           → Create call log entry (on initiation)
    PUT  /api/call/log/<id>      → Update call status (active/ended/quality)
    GET  /api/call/history       → Paginated call history for user
    GET  /api/call/active        → List currently active calls (admin)
"""

import os
import socket
from datetime import datetime

from flask import Blueprint, request
from backend.models import db
from backend.models.call_log import CallLog
from backend.models.negotiation import Negotiation
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

calls_bp = Blueprint('calls', __name__)


def _is_participant(negotiation, user_id):
    return user_id in (negotiation.customer_id, negotiation.driver_id)


def _get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


# ──────────────────────────────────────────────────────────────
# ICE Configuration (STUN/TURN servers for WebRTC)
# ──────────────────────────────────────────────────────────────

@calls_bp.route('/api/call/ice-config', methods=['GET'])
@jwt_required_with_user
def get_ice_config(user):
    """Return STUN/TURN servers for WebRTC clients."""
    local_ip = _get_local_ip()
    request_host = (request.host or '').split(':')[0]
    # Prefer explicit TURN_HOST. If not set, use the request host so emulator
    # clients (e.g. 10.0.2.2) receive a reachable TURN/STUN endpoint.
    turn_host = (
        os.environ.get('TURN_HOST')
        or request_host
        or local_ip
    )
    turn_port = int(os.environ.get('TURN_PORT', '3478'))
    turn_user = os.environ.get('TURN_USER', 'negoride')
    turn_pass = os.environ.get('TURN_PASSWORD', 'negoride2026')

    ice_servers = [
        {
            'urls': [
                f'turn:{turn_host}:{turn_port}',
                f'turn:{turn_host}:{turn_port}?transport=tcp',
            ],
            'username': turn_user,
            'credential': turn_pass,
        },
        {'urls': f'stun:{turn_host}:{turn_port}'},
        {'urls': 'stun:stun.l.google.com:19302'},
        {'urls': 'stun:stun1.l.google.com:19302'},
    ]

    return success_response("ICE config", {
        'iceServers': ice_servers,
        'turnHost': turn_host,
        'localIp': local_ip,
    })


# ──────────────────────────────────────────────────────────────
# Call Log CRUD
# ──────────────────────────────────────────────────────────────

@calls_bp.route('/api/call/log', methods=['POST'])
@jwt_required_with_user
def create_call_log(user):
    """Create a new call log entry when a call is initiated."""
    data = request.get_json(silent=True) or {}

    callee_id = data.get('callee_id')
    negotiation_id = data.get('negotiation_id')
    call_type = data.get('call_type', 'voice')

    if call_type not in ('voice', 'video'):
        return error_response("Invalid call_type. Must be 'voice' or 'video'.")

    if not callee_id:
        return error_response("callee_id is required")

    # Validate callee exists
    callee = db.session.get(AdminUser, int(callee_id))
    if not callee:
        return error_response("Callee not found", status_code=404)

    # Validate negotiation context if provided
    if negotiation_id:
        neg = db.session.get(Negotiation, int(negotiation_id))
        if not neg:
            return error_response("Negotiation not found", status_code=404)
        if not _is_participant(neg, user.id):
            return error_response("You are not a participant in this negotiation", status_code=403)

    call_log = CallLog(
        caller_id=user.id,
        callee_id=int(callee_id),
        negotiation_id=int(negotiation_id) if negotiation_id else None,
        call_type=call_type,
        status='initiated',
    )
    db.session.add(call_log)
    db.session.commit()

    return success_response("Call log created", call_log.to_dict(), status_code=201)


@calls_bp.route('/api/call/log/<int:call_id>', methods=['PUT'])
@jwt_required_with_user
def update_call_log(user, call_id):
    """Update call status, end reason, or quality score."""
    call_log = db.session.get(CallLog, call_id)
    if not call_log:
        return error_response("Call not found", status_code=404)

    # Only participants can update
    if call_log.caller_id != user.id and call_log.callee_id != user.id:
        return error_response("Forbidden", status_code=403)

    data = request.get_json(silent=True) or {}
    new_status = data.get('status')

    if new_status:
        valid_statuses = ('ringing', 'active', 'ended', 'missed', 'rejected')
        if new_status not in valid_statuses:
            return error_response(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")

        call_log.status = new_status

        if new_status == 'active' and not call_log.answered_at:
            call_log.answered_at = datetime.utcnow()

        if new_status == 'ended':
            call_log.ended_at = datetime.utcnow()
            if call_log.answered_at:
                call_log.duration = int(
                    (call_log.ended_at - call_log.answered_at).total_seconds()
                )

        if new_status == 'missed':
            call_log.ended_at = datetime.utcnow()
            if not call_log.end_reason:
                call_log.end_reason = 'no_answer'

        if new_status == 'rejected':
            call_log.ended_at = datetime.utcnow()
            if not call_log.end_reason:
                call_log.end_reason = 'rejected'

    if data.get('end_reason'):
        valid_reasons = ('normal', 'no_answer', 'rejected', 'error', 'network_timeout', 'busy',
                         'caller_hangup', 'callee_hangup', 'disconnect', 'timeout')
        if data['end_reason'] in valid_reasons:
            call_log.end_reason = data['end_reason']

    score = data.get('quality_score')
    if score is not None:
        try:
            score = int(score)
            if 1 <= score <= 5:
                call_log.quality_score = score
        except (TypeError, ValueError):
            pass

    db.session.commit()
    return success_response("Call log updated", call_log.to_dict())


# ──────────────────────────────────────────────────────────────
# Call History
# ──────────────────────────────────────────────────────────────

@calls_bp.route('/api/call/history', methods=['GET'])
@jwt_required_with_user
def get_call_history(user):
    """Paginated call history for the logged-in user."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)

    query = CallLog.query.filter(
        (CallLog.caller_id == user.id) | (CallLog.callee_id == user.id)
    ).order_by(CallLog.started_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Enrich each entry with partner name
    calls = []
    for c in pagination.items:
        d = c.to_dict()
        partner_id = c.callee_id if c.caller_id == user.id else c.caller_id
        partner = db.session.get(AdminUser, partner_id) if partner_id else None
        d['partner_name'] = partner.name if partner else 'Unknown'
        d['partner_avatar'] = partner.avatar if partner else None
        d['direction'] = 'outgoing' if c.caller_id == user.id else 'incoming'
        calls.append(d)

    return success_response("Call history", {
        'calls': calls,
        'total': pagination.total,
        'page': pagination.page,
        'pages': pagination.pages,
    })


# ──────────────────────────────────────────────────────────────
# Active Calls (Admin/Debug)
# ──────────────────────────────────────────────────────────────

@calls_bp.route('/api/call/active', methods=['GET'])
@jwt_required_with_user
def get_active_calls(user):
    """List all currently active calls. Useful for admin dashboards."""
    active = CallLog.query.filter_by(status='active').all()

    result = []
    for c in active:
        caller = db.session.get(AdminUser, c.caller_id)
        callee = db.session.get(AdminUser, c.callee_id) if c.callee_id else None
        result.append({
            'call': c.to_dict(),
            'caller_name': caller.name if caller else 'Unknown',
            'callee_name': callee.name if callee else 'Unknown',
        })

    return success_response("Active calls", {
        'active_calls': result,
        'count': len(result),
    })
