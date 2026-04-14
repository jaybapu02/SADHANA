from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Task

@login_required
def add_task(request):
    if request.method == 'POST' and request.user.role == 'CHILD':
        task_name = request.POST.get('task_name')
        if task_name:
            Task.objects.create(child=request.user, task_name=task_name)
            messages.success(request, 'Task added successfully!')
    return redirect('child_dashboard')

@login_required
def toggle_task(request, task_id):
    if request.user.role == 'CHILD':
        task = get_object_or_404(Task, id=task_id, child=request.user)
        task.status = not task.status
        task.save()
    return redirect('child_dashboard')

@login_required
def delete_task(request, task_id):
    if request.user.role == 'CHILD':
        task = get_object_or_404(Task, id=task_id, child=request.user)
        task.delete()
        messages.info(request, 'Task deleted.')
    return redirect('child_dashboard')
