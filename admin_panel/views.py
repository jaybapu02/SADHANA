from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.core.paginator import Paginator
from django.urls import reverse

from users.models import User
from study.models import StudySession, Goal
from tasks.models import Task
from notifications.models import Notification
from relationships.models import ConnectionRequest


def is_admin(user):
    return user.is_authenticated and (user.is_staff or user.role == 'ADMIN')


@user_passes_test(is_admin, login_url='login')
def dashboard(request):
    total_users = User.objects.count()
    total_children = User.objects.filter(role='CHILD').count()
    total_parents = User.objects.filter(role='PARENT').count()
    total_sessions = StudySession.objects.count()
    total_tasks = Task.objects.count()
    total_notifications = Notification.objects.count()
    total_connections = ConnectionRequest.objects.count()
    pending_connections = ConnectionRequest.objects.filter(status='PENDING').count()
    total_goals = Goal.objects.count()

    recent_sessions = StudySession.objects.select_related('child').order_by('-start_time')[:10]

    context = {
        'total_users': total_users,
        'total_children': total_children,
        'total_parents': total_parents,
        'total_sessions': total_sessions,
        'total_tasks': total_tasks,
        'total_notifications': total_notifications,
        'total_connections': total_connections,
        'pending_connections': pending_connections,
        'total_goals': total_goals,
        'recent_sessions': recent_sessions,
    }
    return render(request, 'admin_panel/dashboard.html', context)


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


@user_passes_test(is_admin, login_url='login')
def list_sessions(request):
    sessions = StudySession.objects.select_related('child').all().order_by('-start_time')
    paginator = Paginator(sessions, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'admin_panel/session_list.html', {'sessions': page})


@user_passes_test(is_admin, login_url='login')
def delete_session(request, session_id):
    session = get_object_or_404(StudySession, id=session_id)
    if request.method == 'POST':
        session.delete()
        messages.success(request, 'Study session deleted.')
        return redirect('admin_list_sessions')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': session, 'label': 'Study Session'})


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
        if name:
            task.task_name = name
            task.status = status
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


@user_passes_test(is_admin, login_url='login')
def list_notifications(request):
    notifications = Notification.objects.select_related('parent', 'child').all().order_by('-time')
    paginator = Paginator(notifications, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'admin_panel/notification_list.html', {'notifications': page})


@user_passes_test(is_admin, login_url='login')
def delete_notification(request, notif_id):
    notif = get_object_or_404(Notification, id=notif_id)
    if request.method == 'POST':
        notif.delete()
        messages.success(request, 'Notification deleted.')
        return redirect('admin_list_notifications')
    return render(request, 'admin_panel/confirm_delete.html', {'obj': notif, 'label': 'Notification'})


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
