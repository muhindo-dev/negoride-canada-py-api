from datetime import datetime
from flask import Blueprint, request
from backend.models import db
from backend.models.user import AdminUser
from backend.models.chat_head import ChatHead
from backend.models.chat_message import ChatMessage
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/api/chat-heads', methods=['GET'])
@jwt_required_with_user
def chat_heads(user):
    """Get all chat heads for user (as product_owner or customer)."""
    heads = ChatHead.query.filter(
        (ChatHead.product_owner_id == user.id) | (ChatHead.customer_id == user.id)
    ).order_by(ChatHead.updated_at.desc()).all()

    result = []
    for h in heads:
        hd = h.to_dict()
        unread = ChatMessage.query.filter_by(
            chat_head_id=h.id
        ).filter(
            ChatMessage.sender_id != user.id,
            ChatMessage.status != 'read',
        ).count()
        hd['unread_count'] = unread
        result.append(hd)

    return success_response("Success", result)


@chat_bp.route('/api/chat-heads-create', methods=['POST'])
@jwt_required_with_user
def create_chat_head(user):
    """Create or find existing chat head."""
    data = request.get_json(silent=True) or request.form
    receiver_id = data.get('receiver_id')

    if not receiver_id:
        return error_response("receiver_id is required")

    receiver_id = int(receiver_id)
    receiver = AdminUser.query.get(receiver_id)
    if not receiver:
        return error_response("Receiver not found", status_code=404)

    existing = ChatHead.query.filter(
        ((ChatHead.product_owner_id == user.id) & (ChatHead.customer_id == receiver_id)) |
        ((ChatHead.product_owner_id == receiver_id) & (ChatHead.customer_id == user.id))
    ).first()

    if not existing:
        existing = ChatHead(
            product_owner_id=user.id,
            product_owner_name=user.name,
            product_owner_photo=user.avatar if hasattr(user, 'avatar') else None,
            customer_id=receiver_id,
            customer_name=receiver.name,
            customer_photo=receiver.avatar if hasattr(receiver, 'avatar') else None,
        )
        db.session.add(existing)
        db.session.commit()

    return success_response("Success", existing.to_dict())


@chat_bp.route('/api/chat-messages', methods=['GET'])
@jwt_required_with_user
def messages(user):
    """Get messages by chat_head_id or all for user."""
    chat_head_id = request.args.get('chat_head_id')

    if chat_head_id:
        msgs = ChatMessage.query.filter_by(
            chat_head_id=int(chat_head_id)
        ).order_by(ChatMessage.created_at.asc()).all()

        ChatMessage.query.filter_by(
            chat_head_id=int(chat_head_id)
        ).filter(
            ChatMessage.sender_id != user.id,
            ChatMessage.status != 'read',
        ).update({'status': 'read'})
        db.session.commit()
    else:
        msgs = ChatMessage.query.filter(
            (ChatMessage.sender_id == user.id) | (ChatMessage.receiver_id == user.id)
        ).order_by(ChatMessage.created_at.desc()).all()

    return success_response("Success", [m.to_dict() for m in msgs])


@chat_bp.route('/api/chat-send', methods=['POST'])
@jwt_required_with_user
def send_message(user):
    """Send a text message."""
    data = request.get_json(silent=True) or request.form

    receiver_id = data.get('receiver_id')
    chat_head_id = data.get('chat_head_id')
    body = data.get('body') or data.get('message')

    if not all([receiver_id, chat_head_id, body]):
        return error_response("receiver_id, chat_head_id, and body are required")

    receiver = AdminUser.query.get(int(receiver_id))

    msg = ChatMessage(
        chat_head_id=int(chat_head_id),
        sender_id=user.id,
        receiver_id=int(receiver_id),
        sender_name=user.name,
        sender_photo=user.avatar if hasattr(user, 'avatar') else None,
        receiver_name=receiver.name if receiver else None,
        receiver_photo=receiver.avatar if receiver and hasattr(receiver, 'avatar') else None,
        body=body,
        type=data.get('type', 'text'),
        status='sent',
    )
    db.session.add(msg)

    head = ChatHead.query.get(int(chat_head_id))
    if head:
        head.last_message_body = body[:200] if len(body) > 200 else body
        head.last_message_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        head.last_message_status = 'sent'
        head.updated_at = datetime.utcnow()

    db.session.commit()

    return success_response("Message sent", msg.to_dict())
