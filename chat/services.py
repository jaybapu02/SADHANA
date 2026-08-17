"""Shared chat business logic used by both the sync views and the async consumer."""

from .models import Message

# In-process presence registry (single-process dev server).
ONLINE_USERS = set()

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_ATTACHMENT_TYPES = ("image", "pdf")


def message_payload(msg, include_reply=True):
    """Wire payload for a message (both WS and JSON APIs)."""
    preview = ""
    if msg.is_deleted:
        preview = "🚫 This message was deleted"
    elif msg.text:
        preview = msg.text
    elif msg.attachment:
        preview = "🖼️ Photo" if msg.attachment_type == "image" else "📄 PDF"

    payload = {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "sender_id": msg.sender_id,
        "sender_name": msg.sender.username,
        "text": msg.text if not msg.is_deleted else "",
        "preview": preview,
        "is_deleted": msg.is_deleted,
        "is_edited": msg.is_edited,
        "is_read": msg.is_read,
        "is_delivered": msg.is_delivered,
        "created_at": msg.created_at.isoformat(),
        "attachment_url": msg.attachment.url if msg.attachment else None,
        "attachment_name": msg.attachment_name,
        "attachment_type": msg.attachment_type,
        "reply_to": None,
    }
    if include_reply and msg.parent_msg_id:
        parent = msg.parent_msg
        payload["reply_to"] = {
            "id": parent.id,
            "sender_name": parent.sender.username,
            "text": ("🖼️ Photo" if parent.attachment and not parent.text else
                     "🚫 This message was deleted" if parent.is_deleted else parent.text),
        }
    return payload


def create_message(conversation, sender, receiver, text, reply_to_id=None):
    """Create a message, wire the reply link and refresh the conversation preview."""
    parent = None
    if reply_to_id:
        parent = Message.objects.filter(
            id=reply_to_id, conversation=conversation, is_deleted=False
        ).first()
    msg = Message.objects.create(
        conversation=conversation,
        sender=sender,
        receiver=receiver,
        text=text,
        parent_msg=parent,
    )
    conversation.last_message_at = msg.created_at
    conversation.save(update_fields=["last_message_at"])
    if receiver.id in ONLINE_USERS:
        msg.is_delivered = True
        msg.save(update_fields=["is_delivered"])
    # Eagerly load related objects so payloads work inside async contexts.
    return Message.objects.select_related(
        "sender", "parent_msg", "parent_msg__sender"
    ).get(pk=msg.pk)


def edit_message(msg, text):
    """Edit a message (caller must verify ownership)."""
    msg.text = text
    msg.is_edited = True
    msg.save(update_fields=["text", "is_edited"])


def delete_message(msg):
    """Tombstone-delete a message (caller must verify ownership)."""
    msg.text = ""
    msg.is_deleted = True
    msg.save(update_fields=["text", "is_deleted"])


def maybe_notify_chat_message(receiver, sender, preview):
    """Notify the receiver only when they are not online on the chat."""
    from notifications.services import NotificationService

    if receiver.id in ONLINE_USERS:
        return None
    return NotificationService.chat_message(receiver, sender, preview)


def broadcast(event_type, conversation_id, payload):
    """Send an event to the conversation group from a sync context (views)."""
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    group = f"chat_{conversation_id}"
    handler = {
        "chat_message": "chat.message",
        "chat_edit": "chat.edit",
        "chat_delete": "chat.delete",
        "chat_typing": "chat.typing",
        "chat_read": "chat.read",
    }.get(event_type, event_type)
    payload = dict(payload)
    payload["type"] = event_type
    async_to_sync(get_channel_layer().group_send)(
        group, {"type": handler, "payload": payload}
    )