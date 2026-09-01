from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Avg
from datetime import timedelta

from relationships.models import ConnectionRequest
from tasks.models import Task
from focus.models import FocusSession, AccessRequest
from notifications.models import Notification
from notifications.services import NotificationService
from django.contrib.auth import get_user_model
from rewards.services import get_reward_context, get_leaderboard
User = get_user_model()


@login_required
def dashboard_router(request):
    if request.user.role == 'PARENT':
        return redirect('parent_dashboard')
    elif request.user.role == 'CHILD':
        return redirect('child_dashboard')
    else:
        return redirect('/admin/')


@login_required
def parent_dashboard(request):
    if request.user.role != 'PARENT':
        return redirect('dashboard_router')

    sent_requests = ConnectionRequest.objects.filter(parent=request.user).order_by('-created_at')
    connected_children = [req.child for req in sent_requests if req.status == 'ACCEPTED']

    today = timezone.now().date()
    children_todo = []
    for child in connected_children:
        today_tasks = Task.objects.filter(child=child, date=today)
        tt = today_tasks.count()
        tc = today_tasks.filter(status=True).count()
        tp = today_tasks.filter(status=False).count()
        pct = round((tc / tt * 100) if tt > 0 else 0)

        week_start = today - timedelta(days=today.weekday())
        week_tasks = Task.objects.filter(child=child, date__gte=week_start)
        wt = week_tasks.count()
        wc = week_tasks.filter(status=True).count()
        wpct = round((wc / wt * 100) if wt > 0 else 0)

        children_todo.append({
            'child': child,
            'today_total': tt,
            'today_completed': tc,
            'today_pending': tp,
            'today_pct': pct,
            'week_pct': wpct,
        })

        if tt > 0 and pct < 50:
            existing = Notification.objects.filter(
                recipient=request.user, sender=child,
                notification_type=Notification.NotificationType.LOW_COMPLETION,
                timestamp__date=today
            )
            if not existing:
                NotificationService.low_completion(request.user, child, pct)

        if tt > 0 and tc == tt:
            existing = Notification.objects.filter(
                recipient=request.user, sender=child,
                notification_type=Notification.NotificationType.ALL_TASKS_DONE,
                timestamp__date=today
            )
            if not existing:
                NotificationService.all_tasks_done(request.user, child)

    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    attention_count = Notification.objects.filter(
        recipient=request.user, is_read=False,
        priority=Notification.Priority.ATTENTION_REQUIRED
    ).count()

    context = {
        'sent_requests': sent_requests,
        'connected_children': connected_children,
        'children_todo': children_todo,
        'unread_count': unread_count,
        'attention_count': attention_count,
    }
    return render(request, 'dashboard/parent.html', context)


@login_required
def parent_child_stats(request, child_id):
    if request.user.role != 'PARENT':
        return redirect('dashboard_router')

    req = ConnectionRequest.objects.filter(parent=request.user, child_id=child_id, status='ACCEPTED').first()
    if not req:
        return redirect('parent_dashboard')

    child = req.child
    today = timezone.now().date()
    now = timezone.now()

    sessions = FocusSession.objects.filter(child=child)
    today_sessions = [s for s in sessions if s.start_time.date() == today]

    today_duration = 0
    today_distraction_seconds = 0
    total_focus_sec = 0
    combined = []

    for fs in sessions:
        if fs.status == FocusSession.Status.ACTIVE:
            elapsed = int((now - fs.start_time).total_seconds())
            foc_sec = max(0, elapsed)
            dist_sec = 0
        else:
            foc_sec = fs.actual_focus_seconds
            dist_sec = fs.distraction_seconds

        total_sec = foc_sec + dist_sec
        score = fs.focus_score if fs.focus_score > 0 else (round((foc_sec / total_sec * 100), 2) if total_sec > 0 else 0)
        combined.append({
            'start_time': fs.start_time,
            'duration': round(foc_sec / 60),
            'focus_score': score,
        })

        if fs.start_time.date() == today:
            today_duration += round(foc_sec / 60)
            today_distraction_seconds += dist_sec
            total_focus_sec += foc_sec

    if total_focus_sec + today_distraction_seconds > 0:
        avg_focus = (total_focus_sec / (total_focus_sec + today_distraction_seconds)) * 100
    else:
        avg_focus = 0

    combined.sort(key=lambda x: x['start_time'], reverse=True)
    today_combined = [s for s in combined if s['start_time'].date() == today]
    labels = [s['start_time'].strftime('%H:%M') for s in reversed(today_combined)]
    durations = [s['duration'] for s in reversed(today_combined)]

    context = {
        'child': child,
        'sessions': combined[:10],
        'today_duration': today_duration,
        'today_distraction': round(today_distraction_seconds),
        'avg_focus': round(avg_focus, 2),
        'chart_labels': labels,
        'chart_data': durations,
    }
    return render(request, 'dashboard/child_stats.html', context)


@login_required
def parent_child_todo_dashboard(request, child_id):
    if request.user.role != 'PARENT':
        return redirect('dashboard_router')

    conn = ConnectionRequest.objects.filter(parent=request.user, child_id=child_id, status='ACCEPTED').first()
    if not conn:
        messages.error(request, 'Not connected to this child.')
        return redirect('parent_dashboard')

    child = conn.child
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    all_tasks = Task.objects.filter(child=child).order_by('-date', '-priority')

    today_tasks = all_tasks.filter(date=today)
    today_total = today_tasks.count()
    today_completed = today_tasks.filter(status=True).count()
    today_pending = today_tasks.filter(status=False).count()
    today_pct = round((today_completed / today_total * 100) if today_total > 0 else 0)

    week_tasks = all_tasks.filter(date__gte=week_start)
    week_total = week_tasks.count()
    week_completed = week_tasks.filter(status=True).count()
    week_pct = round((week_completed / week_total * 100) if week_total > 0 else 0)

    month_tasks = all_tasks.filter(date__gte=month_start)
    month_total = month_tasks.count()
    month_completed = month_tasks.filter(status=True).count()
    month_pct = round((month_completed / month_total * 100) if month_total > 0 else 0)

    incomplete_high = today_tasks.filter(status=False, priority='HIGH').count()

    context = {
        'child': child,
        'all_tasks': all_tasks[:50],
        'today_tasks': today_tasks,
        'today_total': today_total,
        'today_completed': today_completed,
        'today_pending': today_pending,
        'today_pct': today_pct,
        'week_pct': week_pct,
        'month_pct': month_pct,
        'week_total': week_total,
        'week_completed': week_completed,
        'month_total': month_total,
        'month_completed': month_completed,
        'incomplete_high': incomplete_high,
    }
    return render(request, 'tasks/parent_child_todo.html', context)


@login_required
def child_dashboard(request):
    if request.user.role != 'CHILD':
        return redirect('dashboard_router')

    pending_requests = ConnectionRequest.objects.filter(
        child=request.user,
        status='PENDING'
    ).order_by('-created_at')

    accepted_requests = ConnectionRequest.objects.filter(
        child=request.user,
        status='ACCEPTED'
    )

    parents = [req.parent for req in accepted_requests]

    today = timezone.now().date()
    now = timezone.now()

    sessions = FocusSession.objects.filter(
        child=request.user,
        start_time__date=today
    )

    today_study_time = 0
    today_distraction = 0
    total_focus_sec = 0
    combined = []

    for fs in sessions:
        if fs.status == FocusSession.Status.ACTIVE:
            elapsed = int((now - fs.start_time).total_seconds())
            foc_sec = max(0, elapsed)
            dist_sec = 0
        else:
            foc_sec = fs.actual_focus_seconds
            dist_sec = fs.distraction_seconds

        total_sec = foc_sec + dist_sec
        score = fs.focus_score if fs.focus_score > 0 else (round((foc_sec / total_sec * 100), 2) if total_sec > 0 else 0)
        combined.append({
            'start_time': fs.start_time,
            'focus_score': score,
        })

        today_study_time += round(foc_sec / 60)
        today_distraction += dist_sec
        total_focus_sec += foc_sec

    combined.sort(key=lambda x: x['start_time'])

    if total_focus_sec + today_distraction > 0:
        avg_focus = (total_focus_sec / (total_focus_sec + today_distraction)) * 100
    else:
        avg_focus = 0

    chart_labels = [s['start_time'].strftime('%H:%M') for s in combined]
    chart_scores = [s['focus_score'] for s in combined]

    today_tasks = Task.objects.filter(child=request.user, date=today)
    today_total = today_tasks.count()
    today_completed = today_tasks.filter(status=True).count()
    today_pending = today_tasks.filter(status=False).count()
    today_pct = round((today_completed / today_total * 100) if today_total > 0 else 0)

    unread_notif = Notification.objects.filter(recipient=request.user, is_read=False).count()

    now = timezone.now()
    approved_access = AccessRequest.objects.filter(
        child=request.user,
        status=AccessRequest.Status.APPROVED,
        granted_until__gte=now,
    ).select_related('blacklist_item')

    reward_ctx = get_reward_context(request.user)

    context = {
        'pending_requests': pending_requests,
        'parents': parents,
        'today_study_time': today_study_time,
        'today_distraction': today_distraction,
        'avg_focus': round(avg_focus, 2),
        'chart_labels': chart_labels,
        'chart_scores': chart_scores,
        'today_tasks': today_tasks.order_by('-priority', 'due_date'),
        'today_total': today_total,
        'today_completed': today_completed,
        'today_pending': today_pending,
        'today_pct': today_pct,
        'unread_notif': unread_notif,
        'approved_apps': approved_access,
        'reward_profile': reward_ctx['profile'],
        'reward_badges': reward_ctx['badges'],
    }

    return render(request, 'dashboard/child.html', context)
