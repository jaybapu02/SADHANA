import json
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from .models import StudySession
from relationships.models import ConnectionRequest
from notifications.models import Notification


@login_required
def study_session(request):
    # Only child can access
    if request.user.role != 'CHILD':
        return redirect('dashboard_router')

    # ✅ Get ALL accepted parents (NOT just one)
    accepted_requests = ConnectionRequest.objects.filter(
        child=request.user,
        status='ACCEPTED'
    )

    # Extract parents
    parents = [req.parent for req in accepted_requests]

    context = {
        'parent_ids': [parent.id for parent in parents]  # useful if needed in JS
    }

    return render(request, 'study/session.html', context)


@login_required
def save_session(request):
    if request.method == 'POST' and request.user.role == 'CHILD':
        try:
            data = json.loads(request.body)

            duration_minutes = data.get('duration_minutes', 0)
            break_minutes = data.get('break_minutes', 0)
            distraction_seconds = data.get('distraction_seconds', 0)

            # ✅ Save session
            session = StudySession.objects.create(
                child=request.user,
                end_time=timezone.now(),
                duration=duration_minutes,
                break_time=break_minutes,
                distraction_time=distraction_seconds
            )

            # ✅ Notify ALL parents (NOT just one)
            if distraction_seconds > 120:
                accepted_requests = ConnectionRequest.objects.filter(
                    child=request.user,
                    status='ACCEPTED'
                )

                for req in accepted_requests:
                    Notification.objects.create(
                        parent=req.parent,
                        child=request.user,
                        message=(
                            f"{request.user.username} was distracted for "
                            f"{distraction_seconds // 60} minutes during their "
                            f"{duration_minutes}-minute study session."
                        )
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