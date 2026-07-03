from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Notification

@login_required
def notification_list(request):
    if request.user.role == 'PARENT':
        notifs = Notification.objects.filter(parent=request.user).order_by('-time')
    elif request.user.role == 'CHILD':
        notifs = Notification.objects.filter(child=request.user).order_by('-time')
    else:
        notifs = Notification.objects.none()
    unread_count = notifs.filter(status=False).count()
    context = {
        'notifications': notifs,
        'unread_count': unread_count,
    }
    return render(request, 'notifications/list.html', context)

@login_required
def mark_read(request, notif_id):
    notif = get_object_or_404(Notification, id=notif_id)
    if request.user == notif.parent or request.user == notif.child:
        notif.status = True
        notif.save()
    return redirect('notification_list')

@login_required
def mark_all_read(request):
    if request.user.role == 'PARENT':
        Notification.objects.filter(parent=request.user, status=False).update(status=True)
    elif request.user.role == 'CHILD':
        Notification.objects.filter(child=request.user, status=False).update(status=True)
    messages.success(request, 'All notifications marked as read.')
    return redirect('notification_list')
