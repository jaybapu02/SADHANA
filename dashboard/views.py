from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, Avg

from relationships.models import ConnectionRequest
from study.models import StudySession
from django.contrib.auth import get_user_model
User = get_user_model()

@login_required
def dashboard_router(request):
    """
    Redirects users to their respective dashboards based on their role.
    """
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
    
    # We can pass daily stats for each child directly, but let's keep it simple first
    context = {
        'sent_requests': sent_requests,
        'connected_children': connected_children
    }
    return render(request, 'dashboard/parent.html', context)

@login_required
def parent_child_stats(request, child_id):
    if request.user.role != 'PARENT':
        return redirect('dashboard_router')
        
    # Verify connection
    req = ConnectionRequest.objects.filter(parent=request.user, child_id=child_id, status='ACCEPTED').first()
    if not req:
        return redirect('parent_dashboard')
        
    child = req.child
    sessions = StudySession.objects.filter(child=child).order_by('start_time')
    
    # Aggregations for today
    today = timezone.now().date()
    today_sessions = sessions.filter(start_time__date=today)
    
    today_duration = today_sessions.aggregate(Sum('duration'))['duration__sum'] or 0
    today_distraction = today_sessions.aggregate(Sum('distraction_time'))['distraction_time__sum'] or 0
    avg_focus = today_sessions.aggregate(Avg('focus_score'))['focus_score__avg'] or 0
    
    # Data for Chart.js
    labels = [s.start_time.strftime('%H:%M') for s in today_sessions]
    scores = [s.focus_score for s in today_sessions]
    
    context = {
        'child': child,
        'sessions': sessions.order_by('-start_time')[:10],
        'today_duration': today_duration,
        'today_distraction': today_distraction,
        'avg_focus': round(avg_focus, 2),
        'chart_labels': labels,
        'chart_scores': scores
    }
    return render(request, 'dashboard/child_stats.html', context)

@login_required
def child_dashboard(request):
    if request.user.role != 'CHILD':
        return redirect('dashboard_router')

    # ✅ Get ALL pending requests
    pending_requests = ConnectionRequest.objects.filter(
        child=request.user,
        status='PENDING'
    ).order_by('-created_at')

    # ✅ Get ALL accepted parents (FIXED)
    accepted_requests = ConnectionRequest.objects.filter(
        child=request.user,
        status='ACCEPTED'
    )

    parents = [req.parent for req in accepted_requests]

    # 📊 Study Stats
    today = timezone.now().date()

    sessions = StudySession.objects.filter(
        child=request.user,
        start_time__date=today
    )

    today_study_time = sessions.aggregate(Sum('duration'))['duration__sum'] or 0
    today_distraction = sessions.aggregate(Sum('distraction_time'))['distraction_time__sum'] or 0
    avg_focus = sessions.aggregate(Avg('focus_score'))['focus_score__avg'] or 0

    # 📈 Chart Data
    chart_labels = [s.start_time.strftime('%H:%M') for s in sessions]
    chart_scores = [s.focus_score for s in sessions]

    # ✅ Final Context
    context = {
        'pending_requests': pending_requests,
        'parents': parents,  # ✅ IMPORTANT CHANGE
        'today_study_time': today_study_time,
        'today_distraction': today_distraction,
        'avg_focus': round(avg_focus, 2),
        'chart_labels': chart_labels,
        'chart_scores': chart_scores
    }

    return render(request, 'dashboard/child.html', context)