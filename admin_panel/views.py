from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.core.paginator import Paginator
from django.utils import timezone

from users.models import User
from study.models import Goal
from tasks.models import Task
from notifications.models import Notification
from relationships.models import ConnectionRequest
from focus.models import FocusSession, WhitelistItem, BlacklistItem, AccessRequest, FocusAnalytics
from rewards.models import RewardProfile, Badge, BadgeAward, Transaction


def is_admin(user):
    return user.is_authenticated and (user.is_staff or user.role == 'ADMIN')


# ─── Dashboard ───

@user_passes_test(is_admin, login_url='login')
def dashboard(request):
    total_users = User.objects.count()
    total_children = User.objects.filter(role='CHILD').count()
    total_parents = User.objects.filter(role='PARENT').count()
    total_sessions = FocusSession.objects.count()
    active_sessions = FocusSession.objects.filter(status=FocusSession.Status.ACTIVE).count()
    total_tasks = Task.objects.count()
    total_notifications = Notification.objects.count()
    total_connections = ConnectionRequest.objects.count()
    pending_connections = ConnectionRequest.objects.filter(status='PENDING').count()
    total_goals = Goal.objects.count()
    total_whitelist = WhitelistItem.objects.count()
    total_blacklist = BlacklistItem.objects.count()
    total_access_requests = AccessRequest.objects.count()
    pending_access_requests = AccessRequest.objects.filter(status=AccessRequest.Status.PENDING).count()

    total_reward_profiles = RewardProfile.objects.count()
    total_badges = Badge.objects.count()
    total_badge_awards = BadgeAward.objects.count()
    total_xp_awarded = Transaction.objects.aggregate(t=Sum('xp_amount'))['t'] or 0
    total_coins_awarded = Transaction.objects.aggregate(t=Sum('coin_amount'))['t'] or 0

    recent_sessions = FocusSession.objects.select_related('child').order_by('-start_time')[:10]

    context = {
        'total_users': total_users,
        'total_children': total_children,
        'total_parents': total_parents,
        'total_sessions': total_sessions,
        'active_sessions': active_sessions,
        'total_tasks': total_tasks,
        'total_notifications': total_notifications,
        'total_connections': total_connections,
        'pending_connections': pending_connections,
        'total_goals': total_goals,
        'total_whitelist': total_whitelist,
        'total_blacklist': total_blacklist,
        'total_access_requests': total_access_requests,
        'pending_access_requests': pending_access_requests,
        'total_reward_profiles': total_reward_profiles,
        'total_badges': total_badges,
        'total_badge_awards': total_badge_awards,
        'total_xp_awarded': total_xp_awarded,
        'total_coins_awarded': total_coins_awarded,
        'recent_sessions': recent_sessions,
    }
    return render(request, 'admin_panel/dashboard.html', context)


# ─── Users ───

@user_passes_test(is_admin, login_url='login')
def list_users(request):
    role_filter = request.GET.get('role', '')
    users = User.objects.all().order_by('-date_joined')
    if role_filter:
        users = users.filter(role=role_filter)
    paginator = Paginator(users, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'admin_panel/user_list.html', {'users': page, 'role_filter': role_filter})


@user_passes_test(is_admin, login_url='login')
def edit_user(request, user_id):
    user_obj = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email', '')
        role = request.POST.get('role')
        is_active = request.POST.get('is_active') == 'on'
        is_staff = request.POST.get('is_staff') == 'on'
        if username:
            user_obj.username = username
            user_obj.email = email
            user_obj.role = role
            user_obj.is_active = is_active
            user_obj.is_staff = is_staff
            user_obj.save()
            messages.success(request, f'User "{user_obj.username}" updated.')
            return redirect('admin_list_users')
        else:
            messages.error(request, 'Username is required.')
    return render(request, 'admin_panel/user_form.html', {'user_obj': user_obj})


@user_passes_test(is_admin, login_url='login')
def delete_user(request, user_id):
    user_obj = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        uname = user_obj.username
        user_obj.delete()
        messages.success(request, f'User "{uname}" deleted.')
        return redirect('admin_list_users')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': user_obj, 'label': 'User'})


# ─── Goals ───

@user_passes_test(is_admin, login_url='login')
def list_goals(request):
    goals = Goal.objects.select_related('child').all()
    return render(request, 'admin_panel/goal_list.html', {'goals': goals})


@user_passes_test(is_admin, login_url='login')
def edit_goal(request, goal_id):
    goal = get_object_or_404(Goal, id=goal_id)
    if request.method == 'POST':
        daily = request.POST.get('daily_goal')
        weekly = request.POST.get('weekly_goal')
        if daily and weekly:
            goal.daily_goal = int(daily)
            goal.weekly_goal = int(weekly)
            goal.save()
            messages.success(request, f'Goal for {goal.child.username} updated.')
            return redirect('admin_list_goals')
        else:
            messages.error(request, 'Both daily and weekly goals are required.')
    return render(request, 'admin_panel/goal_form.html', {'goal': goal})


@user_passes_test(is_admin, login_url='login')
def delete_goal(request, goal_id):
    goal = get_object_or_404(Goal, id=goal_id)
    if request.method == 'POST':
        goal.delete()
        messages.success(request, 'Goal deleted.')
        return redirect('admin_list_goals')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': goal, 'label': 'Goal'})


# ─── Tasks ───

@user_passes_test(is_admin, login_url='login')
def list_tasks(request):
    child_filter = request.GET.get('child', '')
    tasks = Task.objects.select_related('child').all().order_by('-date')
    if child_filter:
        tasks = tasks.filter(child_id=child_filter)
    paginator = Paginator(tasks, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'admin_panel/task_list.html', {'tasks': page})


@user_passes_test(is_admin, login_url='login')
def edit_task(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    if request.method == 'POST':
        name = request.POST.get('task_name')
        status = request.POST.get('status') == 'on'
        priority = request.POST.get('priority', 'MEDIUM')
        due_date_str = request.POST.get('due_date', '')
        due_date = None
        if due_date_str:
            try:
                from datetime import datetime
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        if name:
            task.task_name = name
            task.status = status
            task.priority = priority
            task.due_date = due_date
            task.save()
            messages.success(request, 'Task updated.')
            return redirect('admin_list_tasks')
        else:
            messages.error(request, 'Task name is required.')
    return render(request, 'admin_panel/task_form.html', {'task': task})


@user_passes_test(is_admin, login_url='login')
def delete_task(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    if request.method == 'POST':
        task.delete()
        messages.success(request, 'Task deleted.')
        return redirect('admin_list_tasks')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': task, 'label': 'Task'})


# ─── Notifications ───

@user_passes_test(is_admin, login_url='login')
def list_notifications(request):
    type_filter = request.GET.get('type', '')
    notifications = Notification.objects.select_related('recipient', 'sender').all().order_by('-timestamp')
    if type_filter:
        notifications = notifications.filter(notification_type=type_filter)
    paginator = Paginator(notifications, 20)
    page = paginator.get_page(request.GET.get('page'))
    types = Notification.NotificationType.choices
    return render(request, 'admin_panel/notification_list.html', {
        'notifications': page,
        'type_filter': type_filter,
        'types': types,
    })


@user_passes_test(is_admin, login_url='login')
def delete_notification(request, notif_id):
    notif = get_object_or_404(Notification, id=notif_id)
    if request.method == 'POST':
        notif.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'ok', 'deleted_id': notif_id})
        messages.success(request, 'Notification deleted.')
        return redirect('admin_list_notifications')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': notif, 'label': 'Notification'})


# ─── Connection Requests ───

@user_passes_test(is_admin, login_url='login')
def list_connections(request):
    status_filter = request.GET.get('status', '')
    connections = ConnectionRequest.objects.select_related('parent', 'child').all().order_by('-created_at')
    if status_filter:
        connections = connections.filter(status=status_filter)
    paginator = Paginator(connections, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'admin_panel/connection_list.html', {'connections': page, 'status_filter': status_filter})


@user_passes_test(is_admin, login_url='login')
def edit_connection(request, conn_id):
    conn = get_object_or_404(ConnectionRequest, id=conn_id)
    if request.method == 'POST':
        status = request.POST.get('status')
        if status in dict(ConnectionRequest.STATUS_CHOICES):
            conn.status = status
            conn.save()
            messages.success(request, 'Connection request updated.')
            return redirect('admin_list_connections')
        else:
            messages.error(request, 'Invalid status.')
    return render(request, 'admin_panel/connection_form.html', {'conn': conn})


@user_passes_test(is_admin, login_url='login')
def delete_connection(request, conn_id):
    conn = get_object_or_404(ConnectionRequest, id=conn_id)
    if request.method == 'POST':
        conn.delete()
        messages.success(request, 'Connection request deleted.')
        return redirect('admin_list_connections')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': conn, 'label': 'Connection Request'})


# ─── Focus Sessions ───

@user_passes_test(is_admin, login_url='login')
def list_focus_sessions(request):
    status_filter = request.GET.get('status', '')
    child_search = request.GET.get('child', '')
    sessions = FocusSession.objects.select_related('child').all().order_by('-start_time')
    if status_filter:
        sessions = sessions.filter(status=status_filter)
    if child_search:
        sessions = sessions.filter(child__username__icontains=child_search)
    paginator = Paginator(sessions, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'admin_panel/session_list.html', {
        'sessions': page,
        'status_filter': status_filter,
        'child_search': child_search,
    })


@user_passes_test(is_admin, login_url='login')
def delete_focus_session(request, session_id):
    session = get_object_or_404(FocusSession, id=session_id)
    if request.method == 'POST':
        session.delete()
        messages.success(request, 'Focus session deleted.')
        return redirect('admin_list_focus_sessions')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': session, 'label': 'Focus Session'})


# ─── Whitelist Items ───

@user_passes_test(is_admin, login_url='login')
def list_whitelist(request):
    category_filter = request.GET.get('category', '')
    items = WhitelistItem.objects.all().order_by('name')
    if category_filter:
        items = items.filter(category=category_filter)
    return render(request, 'admin_panel/whitelist_list.html', {'items': items, 'category_filter': category_filter})


@user_passes_test(is_admin, login_url='login')
def edit_whitelist(request, item_id):
    item = get_object_or_404(WhitelistItem, id=item_id)
    if request.method == 'POST':
        name = request.POST.get('name')
        category = request.POST.get('category', 'APP')
        url_pattern = request.POST.get('url_pattern', '')
        app_name = request.POST.get('app_name', '')
        if name:
            item.name = name
            item.category = category
            item.url_pattern = url_pattern
            item.app_name = app_name
            item.save()
            messages.success(request, f'Whitelist item "{name}" updated.')
            return redirect('admin_list_whitelist')
        else:
            messages.error(request, 'Name is required.')
    return render(request, 'admin_panel/whitelist_form.html', {'item': item})


@user_passes_test(is_admin, login_url='login')
def delete_whitelist(request, item_id):
    item = get_object_or_404(WhitelistItem, id=item_id)
    if request.method == 'POST':
        item.delete()
        messages.success(request, 'Whitelist item deleted.')
        return redirect('admin_list_whitelist')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': item, 'label': 'Whitelist Item'})


# ─── Blacklist Items ───

@user_passes_test(is_admin, login_url='login')
def list_blacklist(request):
    category_filter = request.GET.get('category', '')
    items = BlacklistItem.objects.all().order_by('name')
    if category_filter:
        items = items.filter(category=category_filter)
    return render(request, 'admin_panel/blacklist_list.html', {'items': items, 'category_filter': category_filter})


@user_passes_test(is_admin, login_url='login')
def edit_blacklist(request, item_id):
    item = get_object_or_404(BlacklistItem, id=item_id)
    if request.method == 'POST':
        name = request.POST.get('name')
        category = request.POST.get('category', 'APP')
        url_pattern = request.POST.get('url_pattern', '')
        app_name = request.POST.get('app_name', '')
        if name:
            item.name = name
            item.category = category
            item.url_pattern = url_pattern
            item.app_name = app_name
            item.save()
            messages.success(request, f'Blacklist item "{name}" updated.')
            return redirect('admin_list_blacklist')
        else:
            messages.error(request, 'Name is required.')
    return render(request, 'admin_panel/blacklist_form.html', {'item': item})


@user_passes_test(is_admin, login_url='login')
def delete_blacklist(request, item_id):
    item = get_object_or_404(BlacklistItem, id=item_id)
    if request.method == 'POST':
        item.delete()
        messages.success(request, 'Blacklist item deleted.')
        return redirect('admin_list_blacklist')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': item, 'label': 'Blacklist Item'})


# ─── Access Requests ───

@user_passes_test(is_admin, login_url='login')
def list_access_requests(request):
    status_filter = request.GET.get('status', '')
    requests_qs = AccessRequest.objects.select_related('child', 'parent', 'session', 'blacklist_item').all().order_by('-requested_at')
    if status_filter:
        requests_qs = requests_qs.filter(status=status_filter)
    paginator = Paginator(requests_qs, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'admin_panel/access_request_list.html', {
        'requests': page,
        'status_filter': status_filter,
    })


@user_passes_test(is_admin, login_url='login')
def edit_access_request(request, req_id):
    req = get_object_or_404(AccessRequest, id=req_id)
    if request.method == 'POST':
        status = request.POST.get('status')
        if status in dict(AccessRequest.Status.choices):
            req.status = status
            if status != AccessRequest.Status.PENDING:
                req.responded_at = timezone.now()
            req.save()
            messages.success(request, 'Access request updated.')
            return redirect('admin_list_access_requests')
        else:
            messages.error(request, 'Invalid status.')
    return render(request, 'admin_panel/access_request_form.html', {'req': req})


@user_passes_test(is_admin, login_url='login')
def delete_access_request(request, req_id):
    req = get_object_or_404(AccessRequest, id=req_id)
    if request.method == 'POST':
        req.delete()
        messages.success(request, 'Access request deleted.')
        return redirect('admin_list_access_requests')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': req, 'label': 'Access Request'})
