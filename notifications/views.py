from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from .models import Notification


def _unread_count(user):
    return Notification.objects.filter(recipient=user, is_read=False).count()


@login_required
def notification_list(request):
    notifications = Notification.objects.filter(recipient=request.user)
    unread_count = notifications.filter(is_read=False).count()
    context = {
        'notifications': notifications,
        'unread_count': unread_count,
    }
    return render(request, 'notifications/list.html', context)


@login_required
def api_notifications(request):
    notifications = Notification.objects.filter(recipient=request.user)
    data = [
        {
            'id': n.id,
            'sender_name': n.sender_name,
            'notification_type': n.notification_type,
            'message': n.message,
            'timestamp': n.timestamp.isoformat(),
            'is_read': n.is_read,
        }
        for n in notifications
    ]
    return JsonResponse({'notifications': data, 'count': len(data)})


@login_required
def api_unread_count(request):
    count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({'unread_count': count})


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_mark_read(request, notif_id):
    notif = get_object_or_404(Notification, id=notif_id, recipient=request.user)
    if not notif.is_read:
        notif.is_read = True
        notif.save(update_fields=['is_read'])
    return JsonResponse({'status': 'ok', 'unread_count': _unread_count(request.user)})


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'status': 'ok', 'unread_count': 0})


@login_required
@require_http_methods(['POST', 'DELETE'])
@csrf_exempt
def api_delete_notification(request, notif_id):
    try:
        notif = Notification.objects.get(id=notif_id, recipient=request.user)
    except Notification.DoesNotExist:
        # Already deleted (or not owned by this user) — report so the UI can sync.
        return JsonResponse(
            {'status': 'error', 'message': 'Notification not found.', 'unread_count': _unread_count(request.user)},
            status=404,
        )
    was_unread = not notif.is_read
    notif.delete()
    unread_count = _unread_count(request.user)
    return JsonResponse({
        'status': 'ok',
        'deleted_id': notif_id,
        'was_unread': was_unread,
        'unread_count': unread_count,
    })
