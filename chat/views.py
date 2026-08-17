import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from relationships.models import ConnectionRequest
from .models import Conversation, Message
from .services import (
    ALLOWED_ATTACHMENT_TYPES,
    MAX_ATTACHMENT_BYTES,
    broadcast,
    create_message,
    delete_message,
    edit_message,
    message_payload,
    maybe_notify_chat_message,
)

PAGE_SIZE = 50


def _conversation_list(user):
    return list(
        Conversation.objects.filter(parent=user).select_related("parent", "child")
    ) + list(
        Conversation.objects.filter(child=user).select_related("parent", "child")
    )


def _conversation_payload(user, conv):
    other = conv.other_participant(user)
    last = conv.messages.order_by("-created_at").first()
    unread = conv.messages.filter(receiver=user, is_read=False).count()
    last_text = ""
    if last:
        if last.is_deleted:
            last_text = "🚫 This message was deleted"
        elif last.text:
            last_text = last.text
        elif last.attachment:
            last_text = "🖼️ Photo" if last.attachment_type == "image" else "📄 PDF"
    return {
        "id": conv.id,
        "other_id": other.id,
        "other_name": other.username,
        "other_role": other.role,
        "last_message": last_text,
        "last_message_at": last.created_at.isoformat() if last else None,
        "last_sender": last.sender.username if last else None,
        "unread_count": unread,
    }


@login_required
def chat_page(request):
    conversations = _conversation_list(request.user)
    payload = [_conversation_payload(request.user, c) for c in conversations]
    context = {
        "conversations": payload,
        "total_unread": Message.unread_count_for(request.user),
    }
    return render(request, "chat/chat.html", context)


@login_required
def api_conversations(request):
    convs = sorted(
        _conversation_list(request.user),
        key=lambda c: c.last_message_at,
        reverse=True,
    )
    return JsonResponse({
        "conversations": [_conversation_payload(request.user, c) for c in convs],
        "total_unread": Message.unread_count_for(request.user),
    })


def _message_queryset(conv, before_id=None, around_id=None):
    """Return (messages oldest-first, has_more). Supports pagination via
    before_id, jumping to a specific message via around_id, and latest page."""
    qs = conv.messages.select_related(
        "sender", "parent_msg", "parent_msg__sender"
    )
    if around_id:
        return (
            list(
                qs.filter(
                    id__gte=around_id - PAGE_SIZE // 2,
                    id__lte=around_id + PAGE_SIZE // 2,
                ).order_by("id")
            ),
            False,
        )
    qs = qs.order_by("-id")
    if before_id:
        qs = qs.filter(id__lt=before_id)
    page = list(qs[:PAGE_SIZE])
    return list(reversed(page)), len(page) == PAGE_SIZE


@login_required
def api_messages(request, conversation_id):
    conv = get_object_or_404(Conversation, id=conversation_id)
    if not conv.is_participant(request.user):
        return JsonResponse({"error": "Forbidden."}, status=403)

    before_id = request.GET.get("before_id")
    around_id = request.GET.get("around_id")
    try:
        before_id = int(before_id) if before_id else None
        around_id = int(around_id) if around_id else None
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid paging."}, status=400)

    qs, has_more = _message_queryset(conv, before_id=before_id, around_id=around_id)
    messages = [message_payload(m) for m in qs]

    return JsonResponse({
        "conversation_id": conversation_id,
        "other": {
            "id": conv.other_participant(request.user).id,
            "name": conv.other_participant(request.user).username,
        },
        "messages": messages,
        "has_more": has_more,
    })


@login_required
def api_search(request):
    """Search messages inside the user's own conversations only."""
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})
    convs = _conversation_list(request.user)
    conv_ids = [c.id for c in convs]
    by_id = {c.id: c for c in convs}
    msgs = (
        Message.objects.filter(
            conversation_id__in=conv_ids, text__icontains=q, is_deleted=False
        )
        .select_related("conversation", "sender")
        .order_by("-created_at")[:30]
    )
    results = []
    for m in msgs:
        conv = by_id.get(m.conversation_id)
        results.append({
            "conversation_id": m.conversation_id,
            "message_id": m.id,
            "other_name": conv.other_participant(request.user).username,
            "sender_name": m.sender.username,
            "text": m.text,
            "created_at": m.created_at.isoformat(),
        })
    return JsonResponse({"results": results})


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def api_send(request, conversation_id):
    """HTTP fallback for sending a message (used when WebSockets are unavailable)."""
    conv = get_object_or_404(Conversation, id=conversation_id)
    if not conv.is_participant(request.user):
        return JsonResponse({"error": "Forbidden."}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    text = (data.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "Empty message."}, status=400)

    receiver = conv.other_participant(request.user)
    msg = create_message(conv, request.user, receiver, text,
                         reply_to_id=data.get("reply_to_id"))
    maybe_notify_chat_message(receiver, request.user, msg.text)
    payload = message_payload(msg)
    broadcast("chat_message", conv.id, payload)
    return JsonResponse({"status": "ok", **payload})


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def api_upload(request, conversation_id):
    """Upload an image/PDF attachment and broadcast it in real time."""
    conv = get_object_or_404(Conversation, id=conversation_id)
    if not conv.is_participant(request.user):
        return JsonResponse({"error": "Forbidden."}, status=403)

    file = request.FILES.get("file")
    if not file:
        return JsonResponse({"error": "No file provided."}, status=400)
    if file.size > MAX_ATTACHMENT_BYTES:
        return JsonResponse({"error": "File too large (max 5 MB)."}, status=400)

    content_type = (file.content_type or "").lower()
    if content_type.startswith("image/"):
        attachment_type = "image"
    elif content_type == "application/pdf":
        attachment_type = "pdf"
    else:
        return JsonResponse({"error": "Only images and PDFs are allowed."}, status=400)

    receiver = conv.other_participant(request.user)
    msg = Message.objects.create(
        conversation=conv,
        sender=request.user,
        receiver=receiver,
        text="",
        attachment=file,
        attachment_name=file.name,
        attachment_type=attachment_type,
    )
    conv.last_message_at = msg.created_at
    conv.save(update_fields=["last_message_at"])
    if receiver.id in _online_users():
        msg.is_delivered = True
        msg.save(update_fields=["is_delivered"])

    maybe_notify_chat_message(receiver, request.user, "🖼️ Photo" if attachment_type == "image" else "📄 PDF")
    payload = message_payload(msg)
    broadcast("chat_message", conv.id, payload)
    return JsonResponse({"status": "ok", **payload})


def _online_users():
    from .services import ONLINE_USERS
    return ONLINE_USERS


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def api_edit(request, conversation_id):
    """Edit one of the user's own messages (HTTP fallback for the WS action)."""
    conv = get_object_or_404(Conversation, id=conversation_id)
    if not conv.is_participant(request.user):
        return JsonResponse({"error": "Forbidden."}, status=403)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    msg = conv.messages.filter(id=data.get("message_id")).first()
    if not msg or msg.sender_id != request.user.id or msg.is_deleted:
        return JsonResponse({"error": "Cannot edit this message."}, status=403)

    text = (data.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "Empty message."}, status=400)
    edit_message(msg, text)
    payload = message_payload(msg)
    broadcast("chat_edit", conv.id, payload)
    return JsonResponse({"status": "ok", **payload})


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def api_delete(request, conversation_id):
    """Delete one of the user's own messages (HTTP fallback for the WS action)."""
    conv = get_object_or_404(Conversation, id=conversation_id)
    if not conv.is_participant(request.user):
        return JsonResponse({"error": "Forbidden."}, status=403)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    msg = conv.messages.filter(id=data.get("message_id")).first()
    if not msg or msg.sender_id != request.user.id or msg.is_deleted:
        return JsonResponse({"error": "Cannot delete this message."}, status=403)
    delete_message(msg)
    payload = message_payload(msg)
    broadcast("chat_delete", conv.id, payload)
    return JsonResponse({"status": "ok", **payload})


@login_required
@require_http_methods(["POST"])
def api_mark_read(request, conversation_id):
    conv = get_object_or_404(Conversation, id=conversation_id)
    if not conv.is_participant(request.user):
        return JsonResponse({"error": "Forbidden."}, status=403)
    count = conv.messages.filter(receiver=request.user, is_read=False).update(is_read=True)
    return JsonResponse({"status": "ok", "marked": count})


@login_required
def api_unread_count(request):
    return JsonResponse({"unread_count": Message.unread_count_for(request.user)})


@login_required
def api_contacts(request):
    """All linked parents (for a child) or linked children (for a parent),
    for starting a new WhatsApp-style chat."""
    from .services import ONLINE_USERS

    if request.user.role == "PARENT":
        conns = ConnectionRequest.objects.filter(
            parent=request.user, status="ACCEPTED"
        ).select_related("child")
        contacts = [{"id": c.child.id, "name": c.child.username, "role": c.child.role}
                    for c in conns]
    elif request.user.role == "CHILD":
        conns = ConnectionRequest.objects.filter(
            child=request.user, status="ACCEPTED"
        ).select_related("parent")
        contacts = [{"id": c.parent.id, "name": c.parent.username, "role": c.parent.role}
                    for c in conns]
    else:
        contacts = []

    for c in contacts:
        c["online"] = c["id"] in ONLINE_USERS

    return JsonResponse({"contacts": contacts})


@login_required
def api_quick_conversation(request, other_user_id):
    """Return (or create) the conversation with a specific linked user.
    Used by integration quick-actions (e.g. 'Ask parent' from a task)."""
    other = get_object_or_404(get_user_model(), id=other_user_id)
    # Verify a valid parent-child link exists.
    if request.user.role == "PARENT" and other.role == "CHILD":
        linked = ConnectionRequest.objects.filter(
            parent=request.user, child=other, status="ACCEPTED"
        ).exists()
    elif request.user.role == "CHILD" and other.role == "PARENT":
        linked = ConnectionRequest.objects.filter(
            parent=other, child=request.user, status="ACCEPTED"
        ).exists()
    else:
        linked = False
    if not linked:
        return JsonResponse({"error": "Not linked to this user."}, status=403)

    conv, _ = Conversation.objects.get_or_create(
        parent=other if other.role == "PARENT" else request.user,
        child=request.user if request.user.role == "CHILD" else other,
    )
    return JsonResponse({"status": "ok", "conversation_id": conv.id})