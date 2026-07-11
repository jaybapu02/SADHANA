import json
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from .models import StudySession
from notifications.services import NotificationService


@login_required
def study_session(request):
    if request.user.role != 'CHILD':
        return redirect('dashboard_router')

    return render(request, 'study/session.html')


@login_required
def save_session(request):
    if request.method == 'POST' and request.user.role == 'CHILD':
        try:
            data = json.loads(request.body)

            duration_minutes = data.get('duration_minutes', 0)
            break_minutes = data.get('break_minutes', 0)
            distraction_seconds = data.get('distraction_seconds', 0)

            session = StudySession.objects.create(
                child=request.user,
                end_time=timezone.now(),
                duration=duration_minutes,
                break_time=break_minutes,
                distraction_time=distraction_seconds
            )

            if distraction_seconds > 120:
                NotificationService.notify_all_parents(
                    request.user,
                    NotificationService.distraction_alert,
                    distraction_minutes=distraction_seconds // 60,
                    duration_minutes=duration_minutes
                )

            return JsonResponse({
                'status': 'success',
                'focus_score': session.focus_score
            })

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)

    return JsonResponse({'status': 'invalid'}, status=400)
