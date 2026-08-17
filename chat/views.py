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
    return {
        "id": conv.id,
        "other_id": other.id,
        "other_name": other.username,
        "other_role": other.role,
        "last_message": last.text if last else "",
        "last_message_at": last.created_at.isoformat() if last else None,
        "last_sender": last.sender.username if last else None,
        "unread_count": unread,
    }


@login_required
def chat_page(request):
    conversations = _conversation_list(request.user)
    payload = [_conversation_payload(request.user, c) for c in conversations]
    total_unread = Message.unread_count_for(request.user)
    context = {
        "conversations": payload,
        "total_unread": total_unread,
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


@login_required
def api_messages(request, conversation_id):
    conv = get_object_or_404(Conversation, id=conversation_id)
    if not conv.is_participant(request.user):
        return JsonResponse({"error": "Forbidden."}, status=403)

    before_id = request.GET.get("before_id")
    qs = conv.messages.select_related("sender").order_by("-created_at")
    if before_id:
        qs = qs.filter(id__lt=before_id)
    qs = qs[:50]

    messages = [{
        "id": m.id,
        "sender_id": m.sender_id,
        "sender_name": m.sender.username,
        "text": m.text,
        "is_read": m.is_read,
        "created_at": m.created_at.isoformat(),
    } for m in reversed(list(qs))]

    return JsonResponse({
        "conversation_id": conversation_id,
        "other": {
            "id": conv.other_participant(request.user).id,
            "name": conv.other_participant(request.user).username,
        },
        "messages": messages,
    })


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
    msg = Message.objects.create(
        conversation=conv, sender=request.user, receiver=receiver, text=text,
    )
    conv.last_message_at = msg.created_at
    conv.save(update_fields=["last_message_at"])

    return JsonResponse({
        "status": "ok",
        "id": msg.id,
        "created_at": msg.created_at.isoformat(),
    })


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