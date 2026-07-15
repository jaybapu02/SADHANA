import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import get_user_model

from relationships.models import ConnectionRequest
from .models import StudyDNAProfile
from .services import analyze_child, get_or_create_profile

User = get_user_model()


@login_required
def child_dashboard(request):
    if request.user.role != 'CHILD':
        return redirect('dashboard_router')

    profile = analyze_child(request.user)

    context = _build_child_context(profile)
    return render(request, 'studydna/child_dashboard.html', context)


@login_required
def parent_dashboard(request, child_id):
    if request.user.role != 'PARENT':
        return redirect('dashboard_router')

    conn = ConnectionRequest.objects.filter(
        parent=request.user, child_id=child_id, status='ACCEPTED'
    ).first()
    if not conn:
        return redirect('parent_dashboard')

    child = conn.child
    profile = analyze_child(child)

    context = _build_parent_context(profile, child)
    return render(request, 'studydna/parent_dashboard.html', context)


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_refresh_insights(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    profile = analyze_child(request.user)
    context = _build_child_context(profile)
    return JsonResponse({'status': 'success', 'data': context})


@login_required
def api_get_insights(request):
    if request.user.role == 'CHILD':
        profile = get_or_create_profile(request.user)
        context = _build_child_context(profile)
        return JsonResponse(context)
    elif request.user.role == 'PARENT':
        child_id = request.GET.get('child_id')
        if not child_id:
            return JsonResponse({'error': 'child_id required'}, status=400)
        conn = ConnectionRequest.objects.filter(
            parent=request.user, child_id=child_id, status='ACCEPTED'
        ).first()
        if not conn:
            return JsonResponse({'error': 'Not connected'}, status=403)
        profile = analyze_child(conn.child)
        context = _build_parent_context(profile, conn.child)
        return JsonResponse(context)
    return JsonResponse({'error': 'Unauthorized'}, status=403)


def _build_child_context(profile):
    recs = _safe_parse_json(profile.recommendations, [])
    weekly_focus = _safe_parse_json(profile.weekly_focus_data, [])
    weekly_tasks = _safe_parse_json(profile.weekly_task_data, [])
    monthly_focus = _safe_parse_json(profile.monthly_focus_trend, [])
    monthly_tasks = _safe_parse_json(profile.monthly_task_trend, [])
    subject_data = _safe_parse_json(profile.subject_data_json, {})
    missed_deadlines = _safe_parse_json(profile.missed_deadlines_json, {})
    parent_tasks = _safe_parse_json(profile.parent_tasks_json, {})
    reward_insights = _safe_parse_json(profile.reward_insights_json, {})
    goal_progress = _safe_parse_json(profile.goal_progress_json, {})

    return {
        'profile': profile,
        'best_study_time': profile.best_study_time_label,
        'favorite_subject': profile.favorite_subject,
        'weakest_subject': profile.weakest_subject,
        'avg_focus_duration': profile.average_focus_duration_minutes,
        'most_productive_day': profile.most_productive_day,
        'least_productive_day': profile.least_productive_day,
        'distraction_pattern': profile.common_distraction_time,
        'productivity_score': profile.productivity_score,
        'consistency_score': profile.consistency_score,
        'consistency_improvement': profile.consistency_improvement,
        'streak': profile.study_streak_days,
        'longest_streak': profile.longest_streak_days,
        'weekly_focus': weekly_focus,
        'weekly_tasks': weekly_tasks,
        'monthly_focus': monthly_focus,
        'monthly_tasks': monthly_tasks,
        'subject_data': subject_data,
        'recommendations': recs,
        'missed_deadlines': missed_deadlines,
        'parent_tasks': parent_tasks,
        'reward_insights': reward_insights,
        'goal_progress': goal_progress,
    }


def _build_parent_context(profile, child):
    context = _build_child_context(profile)
    context['child'] = child
    return context


def _safe_parse_json(text, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default
