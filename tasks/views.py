from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta, datetime, date
from .models import Task
from notifications.models import Notification
from relationships.models import ConnectionRequest

@login_required
def todo_dashboard(request):
    if request.user.role != 'CHILD':
        return redirect('dashboard_router')

    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    today_tasks = Task.objects.filter(child=request.user, date=today)
    pending_tasks = today_tasks.filter(status=False)
    completed_tasks = today_tasks.filter(status=True)
    parent_tasks = today_tasks.filter(parent__isnull=False)

    today_total = today_tasks.count()
    today_completed = completed_tasks.count()
    today_pending = pending_tasks.count()
    today_pct = round((today_completed / today_total * 100) if today_total > 0 else 0)

    all_tasks = Task.objects.filter(child=request.user)
    week_tasks = all_tasks.filter(date__gte=week_start)
    month_tasks = all_tasks.filter(date__gte=month_start)

    week_total = week_tasks.count()
    week_completed = week_tasks.filter(status=True).count()
    week_pct = round((week_completed / week_total * 100) if week_total > 0 else 0)

    month_total = month_tasks.count()
    month_completed = month_tasks.filter(status=True).count()
    month_pct = round((month_completed / month_total * 100) if month_total > 0 else 0)

    last_30 = all_tasks.filter(date__gte=today - timedelta(days=30))
    consistency_days = 0
    for i in range(30):
        day = today - timedelta(days=i)
        day_tasks = last_30.filter(date=day)
        day_total = day_tasks.count()
        if day_total > 0:
            day_done = day_tasks.filter(status=True).count()
            if (day_done / day_total) >= 0.5:
                consistency_days += 1
    consistency_score = round((consistency_days / 30) * 100)

    context = {
        'today_tasks': today_tasks.order_by('-priority', 'due_date'),
        'pending_tasks': pending_tasks,
        'completed_tasks': completed_tasks,
        'parent_tasks': parent_tasks,
        'today_total': today_total,
        'today_completed': today_completed,
        'today_pending': today_pending,
        'today_pct': today_pct,
        'week_pct': week_pct,
        'month_pct': month_pct,
        'consistency_score': consistency_score,
        'today': today,
    }
    return render(request, 'tasks/todo_dashboard.html', context)

@login_required
def add_task(request):
    if request.method == 'POST' and request.user.role == 'CHILD':
        task_name = request.POST.get('task_name', '').strip()
        priority = request.POST.get('priority', 'MEDIUM')
        due_date_str = request.POST.get('due_date', '')
        due_date = None
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        if task_name:
            Task.objects.create(
                child=request.user,
                task_name=task_name,
                priority=priority,
                due_date=due_date,
                date=timezone.now().date()
            )
            messages.success(request, 'Task added successfully!')
        else:
            messages.error(request, 'Task name cannot be empty.')
    return redirect('todo_dashboard')

@login_required
def edit_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, child=request.user)
    if request.method == 'POST':
        task_name = request.POST.get('task_name', '').strip()
        priority = request.POST.get('priority', task.priority)
        due_date_str = request.POST.get('due_date', '')
        due_date = None
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        if task_name:
            task.task_name = task_name
            task.priority = priority
            task.due_date = due_date
            task.save()
            messages.success(request, 'Task updated!')
        else:
            messages.error(request, 'Task name cannot be empty.')
        return redirect('todo_dashboard')

    context = {'edit_task': task}
    return render(request, 'tasks/todo_dashboard.html', context)

@login_required
def toggle_task(request, task_id):
    if request.user.role == 'CHILD':
        task = get_object_or_404(Task, id=task_id, child=request.user)
        task.status = not task.status
        task.save()

        parents = ConnectionRequest.objects.filter(child=request.user, status='ACCEPTED')
        if task.status:
            for p in parents:
                Notification.objects.create(
                    parent=p.parent,
                    child=request.user,
                    message=f"{request.user.username} completed task: {task.task_name}"
                )
            all_today = Task.objects.filter(child=request.user, date=timezone.now().date())
            if all_today.count() > 0 and all_today.filter(status=False).count() == 0:
                for p in parents:
                    Notification.objects.create(
                        parent=p.parent,
                        child=request.user,
                        message=f"{request.user.username} completed ALL tasks for today! "
                    )
        else:
            for p in parents:
                Notification.objects.create(
                    parent=p.parent,
                    child=request.user,
                    message=f"{request.user.username} re-opened task: {task.task_name}"
                )
    return redirect('todo_dashboard')

@login_required
def delete_task(request, task_id):
    if request.user.role == 'CHILD':
        task = get_object_or_404(Task, id=task_id, child=request.user)
        task.delete()
        messages.info(request, 'Task deleted.')
    return redirect('todo_dashboard')

@login_required
def parent_assign_task(request, child_id):
    if request.user.role != 'PARENT':
        return redirect('dashboard_router')

    conn = ConnectionRequest.objects.filter(parent=request.user, child_id=child_id, status='ACCEPTED').first()
    if not conn:
        messages.error(request, 'Not connected to this child.')
        return redirect('parent_dashboard')

    child = conn.child
    if request.method == 'POST':
        task_name = request.POST.get('task_name', '').strip()
        priority = request.POST.get('priority', 'MEDIUM')
        due_date_str = request.POST.get('due_date', '')
        due_date = None
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        if task_name:
            Task.objects.create(
                child=child,
                parent=request.user,
                task_name=task_name,
                priority=priority,
                due_date=due_date,
                date=timezone.now().date()
            )
            Notification.objects.create(
                parent=request.user,
                child=child,
                message=f"You assigned a new task to {child.username}: {task_name}"
            )
            Notification.objects.create(
                parent=request.user,
                child=child,
                message=f"New task from {request.user.username}: {task_name}"
            )
            messages.success(request, f'Task assigned to {child.username}!')
        return redirect('parent_child_todo', child_id=child_id)

    context = {'child': child}
    return render(request, 'tasks/parent_assign_task.html', context)

@login_required
def parent_child_todo(request, child_id):
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

    today_pending_pct = round((today_pending / today_total * 100) if today_total > 0 else 0)

    context = {
        'child': child,
        'all_tasks': all_tasks[:50],
        'today_tasks': today_tasks,
        'today_total': today_total,
        'today_completed': today_completed,
        'today_pending': today_pending,
        'today_pct': today_pct,
        'today_pending_pct': today_pending_pct,
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
def parent_remove_task(request, task_id):
    if request.user.role != 'PARENT':
        return redirect('dashboard_router')
    task = get_object_or_404(Task, id=task_id, parent=request.user)
    child_id = task.child.id
    task.delete()
    messages.info(request, 'Task removed.')
    return redirect('parent_child_todo', child_id=child_id)
