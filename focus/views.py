import json
from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q

from .models import (
    FocusSession, WhitelistItem, BlacklistItem, AccessRequest, FocusAnalytics,
    FocusDevice, FocusDeviceCommand, FocusLockEvent,
)
from tasks.models import Task
from notifications.models import Notification
from notifications.services import NotificationService
from relationships.models import ConnectionRequest
from rewards.services import on_focus_session_completed
from studydna.services import analyze_child as studydna_analyze


# ─── Seeding default whitelist/blacklist ───

DEFAULT_WHITELIST = [
    {'name': 'Sadhana', 'category': 'WEBSITE', 'url_pattern': 'sadhana'},
    {'name': 'VS Code', 'category': 'APP', 'app_name': 'code.exe'},
    {'name': 'PyCharm', 'category': 'APP', 'app_name': 'pycharm64.exe'},
    {'name': 'Google Docs', 'category': 'WEBSITE', 'url_pattern': 'docs.google.com'},
    {'name': 'Microsoft Word', 'category': 'APP', 'app_name': 'WINWORD.EXE'},
    {'name': 'PDF Reader', 'category': 'APP', 'app_name': 'Acrobat.exe'},
    {'name': 'Calculator', 'category': 'APP', 'app_name': 'calc.exe'},
    {'name': 'Notepad', 'category': 'APP', 'app_name': 'notepad.exe'},
    {'name': 'Khan Academy', 'category': 'WEBSITE', 'url_pattern': 'khanacademy.org'},
    {'name': 'Wikipedia', 'category': 'WEBSITE', 'url_pattern': 'wikipedia.org'},
    {'name': 'Stack Overflow', 'category': 'WEBSITE', 'url_pattern': 'stackoverflow.com'},
    {'name': 'GeeksforGeeks', 'category': 'WEBSITE', 'url_pattern': 'geeksforgeeks.org'},
    {'name': 'Coursera', 'category': 'WEBSITE', 'url_pattern': 'coursera.org'},
    {'name': 'udemy', 'category': 'WEBSITE', 'url_pattern': 'udemy.com'},
    {'name': 'LeetCode', 'category': 'WEBSITE', 'url_pattern': 'leetcode.com'},
    {'name': 'GitHub', 'category': 'WEBSITE', 'url_pattern': 'github.com'},
]

DEFAULT_BLACKLIST = [
    {'name': 'Instagram', 'category': 'WEBSITE', 'url_pattern': 'instagram.com'},
    {'name': 'Facebook', 'category': 'WEBSITE', 'url_pattern': 'facebook.com'},
    {'name': 'YouTube', 'category': 'WEBSITE', 'url_pattern': 'youtube.com'},
    {'name': 'WhatsApp', 'category': 'APP', 'app_name': 'WhatsApp.exe'},
    {'name': 'Discord', 'category': 'APP', 'app_name': 'Discord.exe'},
    {'name': 'Telegram', 'category': 'APP', 'app_name': 'Telegram.exe'},
    {'name': 'Netflix', 'category': 'WEBSITE', 'url_pattern': 'netflix.com'},
    {'name': 'Prime Video', 'category': 'WEBSITE', 'url_pattern': 'primevideo.com'},
    {'name': 'Steam', 'category': 'APP', 'app_name': 'Steam.exe'},
    {'name': 'Epic Games', 'category': 'APP', 'app_name': 'EpicGamesLauncher.exe'},
    {'name': 'Games', 'category': 'APP', 'app_name': ''},
]


def seed_default_lists():
    for item in DEFAULT_WHITELIST:
        if not WhitelistItem.objects.filter(name=item['name']).exists():
            WhitelistItem.objects.create(**item, is_default=True)
    for item in DEFAULT_BLACKLIST:
        if not BlacklistItem.objects.filter(name=item['name']).exists():
            BlacklistItem.objects.create(**item, is_default=True)


# ─── Helper ───

TICK_MAX_DELTA_SECONDS = 60  # clamp per-tick accumulation (bounds drift & abuse)


def get_connected_parents(child):
    connections = ConnectionRequest.objects.filter(
        child=child, status='ACCEPTED'
    ).select_related('parent')
    return [conn.parent for conn in connections]


def get_device_from_request(request):
    """Resolve the authenticated FocusDevice from a bearer token."""
    auth = request.headers.get('Authorization', '')
    token = request.headers.get('X-Device-Token', '')
    if auth.startswith('Bearer '):
        token = auth[7:]
    if not token:
        return None
    return FocusDevice.objects.filter(token=token, is_active=True).first()


def get_active_session(child):
    return FocusSession.objects.filter(
        child=child, status=FocusSession.Status.ACTIVE
    ).select_related('task').first()


def _finalize_approved_usage(access_req, expired=False):
    """Close out an approved-app usage period: account the used seconds,
    unfreeze the focus session and record the audit event."""
    now = timezone.now()
    used_delta = 0
    if access_req.usage_started_at:
        used_delta = max(0, int((now - access_req.usage_started_at).total_seconds()))
        access_req.usage_seconds += used_delta
        access_req.usage_started_at = None
    access_req.in_use = False
    access_req.save(update_fields=['in_use', 'usage_started_at', 'usage_seconds'])

    session = access_req.session
    if session and session.paused_at:
        paused_delta = max(0, int((now - session.paused_at).total_seconds()))
        session.pause_seconds_total += paused_delta
        session.paused_at = None
        session.save(update_fields=['pause_seconds_total', 'paused_at'])

    event_type = (FocusLockEvent.EventType.ACCESS_EXPIRED if expired
                  else FocusLockEvent.EventType.APPROVED_APP_END)
    if session:
        record_lock_event(
            session, access_req.child, None,
            event_type,
            detail=(
                f'Approved access to "{access_req.blacklist_item.name}" expired after '
                f'{access_req.usage_seconds}s of use'
                if expired else
                f'Child returned to Focus Mode from "{access_req.blacklist_item.name}" '
                f'(used {used_delta}s)'
            ),
            metadata={'request_id': access_req.id, 'used_seconds': access_req.usage_seconds},
            notify=False,
        )
    return used_delta


def sweep_approved_usage(child):
    """Auto-revoke approvals whose grant window has ended (server-side timer,
    not trusting the frontend). Releases any that are mid-use and unfreezes
    the focus session so the child is sent back to Focus Mode."""
    now = timezone.now()
    stale_in_use = AccessRequest.objects.filter(
        child=child,
        status=AccessRequest.Status.APPROVED,
        in_use=True,
        granted_until__lt=now,
    ).select_related('blacklist_item', 'session')
    for req in stale_in_use:
        _finalize_approved_usage(req, expired=True)
    # Mark long-expired approvals so they stop showing up as "approved".
    AccessRequest.objects.filter(
        child=child,
        status=AccessRequest.Status.APPROVED,
        granted_until__lt=now - timedelta(seconds=1),
        in_use=False,
    ).update(status=AccessRequest.Status.EXPIRED)


def get_active_approval(child):
    """The approved restricted app currently being used (if any)."""
    return AccessRequest.objects.filter(
        child=child,
        status=AccessRequest.Status.APPROVED,
        in_use=True,
        usage_started_at__isnull=False,
    ).select_related('blacklist_item', 'session').first()


def approval_payload(req, now=None):
    """Serialized form of an approved restricted app for the child UI/devices."""
    now = now or timezone.now()
    item = req.blacklist_item
    remaining = max(0, int((req.granted_until - now).total_seconds())) if req.granted_until else 0
    url = ''
    if item.category == 'WEBSITE' and item.url_pattern:
        url = 'https://' + item.url_pattern
    return {
        'id': req.id,
        'app_name': item.name,
        'category': item.category,
        'url_pattern': item.url_pattern or '',
        'app_name_exe': item.app_name or '',
        'url': url,
        'granted_until': req.granted_until.isoformat() if req.granted_until else None,
        'remaining_seconds': remaining,
        'in_use': req.in_use,
        'usage_seconds': req.usage_seconds,
    }


def notify_lock_event(event):
    """Notify all linked parents for a recorded lock event (deduplicated per event)."""
    if event.notified:
        return
    parents = get_connected_parents(event.child)
    task_name = event.session.task.task_name if event.session and event.session.task else None
    for parent in parents:
        NotificationService.lock_violation(
            parent, event.child, event.event_type,
            detail=event.detail, task_name=task_name
        )
    event.notified = True
    event.save(update_fields=['notified'])


def record_lock_event(session, child, device, event_type, detail='', metadata=None, notify=True):
    """Persist a FocusLockEvent, bump counters, and notify parents when required."""
    event = FocusLockEvent.objects.create(
        session=session,
        child=child,
        device=device,
        event_type=event_type,
        severity=FocusLockEvent.SEVERITY_BY_EVENT.get(
            event_type, FocusLockEvent.Severity.INFO
        ),
        detail=detail,
        metadata=metadata or {},
    )
    update_fields = []
    if event_type in (FocusLockEvent.EventType.APP_BLOCKED,
                      FocusLockEvent.EventType.WEBSITE_BLOCKED):
        session.blocked_attempts += 1
        update_fields.append('blocked_attempts')
    if event_type in (FocusLockEvent.EventType.TAB_SWITCH,
                      FocusLockEvent.EventType.TAB_HIDE,
                      FocusLockEvent.EventType.MINIMIZE,
                      FocusLockEvent.EventType.WINDOW_CLOSE,
                      FocusLockEvent.EventType.LEAVE_ATTEMPT):
        session.lock_violations += 1
        update_fields.append('lock_violations')
    if update_fields:
        session.save(update_fields=update_fields)

    if notify and event.severity in (FocusLockEvent.Severity.WARNING,
                                     FocusLockEvent.Severity.CRITICAL):
        notify_lock_event(event)
    return event


def device_status_payload(child, session, device=None):
    """Shared payload returned to enforcement devices (extension / agent)."""
    now = timezone.now()
    sweep_approved_usage(child)
    active_approval = get_active_approval(child)
    approved = AccessRequest.objects.filter(
        child=child,
        status=AccessRequest.Status.APPROVED,
        granted_until__gte=now,
    ).select_related('blacklist_item')

    commands = []
    if device and device.device_type == FocusDevice.DeviceType.AGENT:
        commands = [{
            'id': c.id,
            'command_type': c.command_type,
            'app_name': c.app_name,
            'category': c.category,
            'url_pattern': c.url_pattern,
        } for c in FocusDeviceCommand.objects.filter(
            requested_by=child,
            status=FocusDeviceCommand.Status.QUEUED,
        ).order_by('created_at')[:10]]

    return {
        'active': session is not None and session.status == FocusSession.Status.ACTIVE,
        'lock_enabled': bool(session and session.lock_enabled),
        'session_id': session.id if session else None,
        'task_name': session.task.task_name if session and session.task else None,
        'planned_duration': session.planned_duration if session else 0,
        'start_time': session.start_time.isoformat() if session else None,
        'focus_seconds': session.actual_focus_seconds if session else 0,
        'paused': bool(session and session.paused_at),
        'approval_active': active_approval is not None,
        'active_approval': approval_payload(active_approval, now) if active_approval else None,
        'blocked_attempts': session.blocked_attempts if session else 0,
        'lock_violations': session.lock_violations if session else 0,
        'whitelist': [{
            'name': w.name, 'category': w.category,
            'url_pattern': w.url_pattern, 'app_name': w.app_name,
        } for w in WhitelistItem.objects.all()],
        'blacklist': [{
            'name': b.name, 'category': b.category,
            'url_pattern': b.url_pattern, 'app_name': b.app_name,
        } for b in BlacklistItem.objects.all()],
        'approved': [approval_payload(r, now) for r in approved],
        'commands': commands,
    }


# ─── Child: Focus Session Management ───

@login_required
def focus_session_view(request):
    if request.user.role != 'CHILD':
        return redirect('dashboard_router')
    seed_default_lists()
    whitelist = WhitelistItem.objects.all()
    blacklist = BlacklistItem.objects.all()
    active_session = FocusSession.objects.filter(
        child=request.user, status=FocusSession.Status.ACTIVE
    ).first()
    today = timezone.now().date()
    today_tasks = Task.objects.filter(child=request.user, date=today).order_by('-priority', 'due_date')
    conn = ConnectionRequest.objects.filter(
        child=request.user, status='ACCEPTED'
    ).select_related('parent').first()
    context = {
        'whitelist': whitelist,
        'blacklist': blacklist,
        'whitelist_items': list(WhitelistItem.objects.values(
            'id', 'name', 'category', 'url_pattern', 'app_name')),
        'blacklist_items': list(BlacklistItem.objects.values(
            'id', 'name', 'category', 'url_pattern', 'app_name')),
        'active_session': active_session,
        'today_tasks': today_tasks,
        'connected_parent': conn.parent if conn else None,
    }
    return render(request, 'focus/session.html', context)


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_start_session(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Only children can start focus sessions.'}, status=403)
    try:
        data = json.loads(request.body)
        duration = int(data.get('duration', 25))
        task_id = data.get('task_id')
        lock_enabled = bool(data.get('lock_enabled', False))
        device_token = data.get('device_token') or data.get('token')
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid duration.'}, status=400)

    if duration not in (25, 50, 90) and duration < 1:
        return JsonResponse({'error': 'Duration must be 25, 50, 90, or a positive custom value.'}, status=400)

    existing = FocusSession.objects.filter(
        child=request.user, status=FocusSession.Status.ACTIVE
    ).first()
    if existing:
        return JsonResponse({'error': 'You already have an active focus session.'}, status=400)

    task = None
    if task_id:
        task = get_object_or_404(Task, id=task_id, child=request.user)

    session = FocusSession.objects.create(
        child=request.user,
        planned_duration=duration,
        status=FocusSession.Status.ACTIVE,
        session_type=FocusSession.Type.FOCUS,
        task=task,
        lock_enabled=lock_enabled,
    )

    device = None
    if lock_enabled and device_token:
        device = FocusDevice.objects.filter(
            token=device_token, child=request.user, is_active=True
        ).first()

    if lock_enabled:
        record_lock_event(
            session, request.user, device,
            FocusLockEvent.EventType.LOCK_ACTIVATED,
            detail=f"Super Power Saving Mode active for {duration} minutes",
        )
        task_name = task.task_name if task else None
        for parent in get_connected_parents(request.user):
            NotificationService.lock_activated(parent, request.user, task_name=task_name)

    return JsonResponse({
        'status': 'success',
        'session_id': session.id,
        'planned_duration': session.planned_duration,
        'start_time': session.start_time.isoformat(),
        'task_name': task.task_name if task else None,
        'lock_enabled': session.lock_enabled,
    })


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_end_session(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Only children can end focus sessions.'}, status=403)
    try:
        data = json.loads(request.body)
        client_focus_seconds = int(data.get('focus_seconds', 0))
        client_distraction_seconds = int(data.get('distraction_seconds', 0))
        break_seconds = int(data.get('break_seconds', 0))
        session_id = data.get('session_id')
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid data.'}, status=400)

    session = get_object_or_404(FocusSession, id=session_id, child=request.user)
    if session.status != FocusSession.Status.ACTIVE:
        return JsonResponse({'error': 'Session is not active.'}, status=400)

    # Finalize any approved-app usage so paused time isn't counted either way.
    sweep_approved_usage(request.user)
    # ...and close out anything still open when the child ends mid-use.
    for open_req in AccessRequest.objects.filter(
        child=request.user,
        status=AccessRequest.Status.APPROVED,
        in_use=True,
        usage_started_at__isnull=False,
    ).select_related('blacklist_item', 'session'):
        _finalize_approved_usage(open_req)
    # Finalization may have unfrozen the session - pick up fresh state before
    # deciding where the trailing seconds since the last tick belong.
    session.refresh_from_db(fields=['paused_at', 'pause_seconds_total',
                                    'actual_focus_seconds',
                                    'distraction_seconds'])

    now = timezone.now()
    if session.last_tick_at:
        # Server-authoritative path: trust the accumulated tick counters, and
        # bank the short trailing window since the last tick (≤ one interval).
        # Client-supplied numbers are ignored - they cannot be trusted.
        trailing = int((now - session.last_tick_at).total_seconds())
        if 0 <= trailing <= 15:
            if session.paused_at:
                session.pause_seconds_total += trailing
            else:
                session.actual_focus_seconds += trailing
        focus_seconds = session.actual_focus_seconds
        distraction_seconds = session.distraction_seconds
    else:
        # Legacy clients that never ticked: fall back to reported values.
        focus_seconds = max(0, client_focus_seconds)
        distraction_seconds = max(0, client_distraction_seconds)
        session.actual_focus_seconds = focus_seconds
        session.distraction_seconds = distraction_seconds

    planned_seconds = session.planned_duration * 60
    session.end_time = now
    session.last_tick_at = None

    # Small grace window absorbs tick-interval rounding on the completion line.
    if session.planned_duration == 0 or focus_seconds >= max(0, planned_seconds - 10):
        session.status = FocusSession.Status.COMPLETED
        session.early_exit = False
    else:
        session.status = FocusSession.Status.INTERRUPTED
        session.early_exit = True

    session.save()

    if session.lock_enabled:
        record_lock_event(
            session, request.user, None,
            FocusLockEvent.EventType.LOCK_DEACTIVATED,
            detail=f"Session {session.status.lower()} - lock released",
            notify=False,
        )
        for parent in get_connected_parents(request.user):
            NotificationService.lock_deactivated(parent, request.user)

    parents = get_connected_parents(request.user)
    duration_minutes = round(focus_seconds / 60)
    for parent in parents:
        if session.status == FocusSession.Status.COMPLETED:
            NotificationService.focus_completed(parent, request.user, duration_minutes)
        else:
            NotificationService.focus_interrupted(parent, request.user, duration_minutes)

    if session.status == FocusSession.Status.COMPLETED:
        on_focus_session_completed(request.user)
        NotificationService.focus_completed_child(request.user, duration_minutes)
    else:
        NotificationService.focus_interrupted_child(request.user, duration_minutes)

    studydna_analyze(request.user)

    return JsonResponse({
        'status': 'success',
        'session_status': session.status,
        'early_exit': session.early_exit,
        'actual_focus_seconds': session.actual_focus_seconds,
        'distraction_seconds': session.distraction_seconds,
        'pause_seconds_total': session.pause_seconds_total,
        'approved_usage': {
            r.blacklist_item.name: r.usage_seconds
            for r in AccessRequest.objects.filter(
                session=session, usage_seconds__gt=0
            ).select_related('blacklist_item')
        },
    })


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_start_study_session(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Only children can start sessions.'}, status=403)

    existing = FocusSession.objects.filter(
        child=request.user, status=FocusSession.Status.ACTIVE
    ).first()
    if existing:
        return JsonResponse({'error': 'You already have an active session.'}, status=400)

    session = FocusSession.objects.create(
        child=request.user,
        planned_duration=0,
        status=FocusSession.Status.ACTIVE,
        session_type=FocusSession.Type.STUDY,
    )
    return JsonResponse({
        'status': 'success',
        'session_id': session.id,
        'start_time': session.start_time.isoformat(),
    })


@login_required
def api_active_session(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    session = FocusSession.objects.filter(
        child=request.user, status=FocusSession.Status.ACTIVE
    ).first()
    if not session:
        return JsonResponse({'active': False})
    return JsonResponse({
        'active': True,
        'session_id': session.id,
        'planned_duration': session.planned_duration,
        'start_time': session.start_time.isoformat(),
    })


# ─── Child: Server-Authoritative Timing ───

@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_session_tick(request):
    """Presence tick from the focus page. The SERVER owns the clock: the child
    page only declares what it is doing (focusing / distracted); the server
    clamps every delta so a tampered client can't inflate focus time or hide
    in a paused state forever."""
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    try:
        data = json.loads(request.body)
        session_id = data.get('session_id')
        kind = str(data.get('kind', 'FOCUS')).upper()
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid data.'}, status=400)

    session = get_object_or_404(FocusSession, id=session_id, child=request.user)
    if session.status != FocusSession.Status.ACTIVE:
        return JsonResponse({'status': 'error', 'message': 'Session is not active.'}, status=400)

    sweep_approved_usage(request.user)
    now = timezone.now()
    delta = 0
    if session.last_tick_at:
        delta = max(0, min(TICK_MAX_DELTA_SECONDS,
                           int((now - session.last_tick_at).total_seconds())))

    if delta and not session.paused_at:
        # Approved-app usage freezes the timer completely: neither focus nor
        # distraction accrues while the child is legitimately inside an
        # approved app. Any other kind (e.g. explicit PAUSED) is a no-op too.
        if kind == 'DISTRACTED':
            session.distraction_seconds += delta
        elif kind == 'FOCUS':
            if session.planned_duration:
                planned_seconds = session.planned_duration * 60
                remaining = max(0, planned_seconds - session.actual_focus_seconds)
                session.actual_focus_seconds += min(delta, remaining)
            else:
                session.actual_focus_seconds += delta

    session.last_tick_at = now
    session.save(update_fields=['last_tick_at', 'actual_focus_seconds',
                                'distraction_seconds', 'pause_seconds_total'])

    planned_seconds = session.planned_duration * 60
    remaining_seconds = max(0, planned_seconds - session.actual_focus_seconds) \
        if planned_seconds else None
    return JsonResponse({
        'status': 'success',
        'focus_seconds': session.actual_focus_seconds,
        'distraction_seconds': session.distraction_seconds,
        'paused': bool(session.paused_at),
        'remaining_seconds': remaining_seconds,
    })


@login_required
def api_session_state(request):
    """Single unified poll for the child's Focus Stage UI: server-owned timer,
    pause state, live approvals (with countdowns), counters."""
    if request.user.role != 'CHILD':
        return JsonResponse({'status': 'error', 'message': 'Unauthorized.'}, status=403)
    sweep_approved_usage(request.user)
    session = get_active_session(request.user)
    now = timezone.now()
    if not session:
        return JsonResponse({
            'active': False,
            'approved': [],
            'server_time': now.isoformat(),
        })

    active_approval = get_active_approval(request.user)
    approved_reqs = AccessRequest.objects.filter(
        child=request.user,
        session=session,
        status=AccessRequest.Status.APPROVED,
        granted_until__gte=now,
    ).select_related('blacklist_item')

    planned_seconds = session.planned_duration * 60
    agent_online = FocusDevice.objects.filter(
        child=request.user,
        device_type=FocusDevice.DeviceType.AGENT,
        is_active=True,
        last_seen__gte=now - timedelta(seconds=120),
    ).exists()

    return JsonResponse({
        'active': True,
        'session_id': session.id,
        'session_type': session.session_type,
        'task_name': session.task.task_name if session.task else None,
        'lock_enabled': session.lock_enabled,
        'planned_duration': session.planned_duration,
        'focus_seconds': session.actual_focus_seconds,
        'distraction_seconds': session.distraction_seconds,
        'remaining_seconds': max(0, planned_seconds - session.actual_focus_seconds)
            if planned_seconds else None,
        'paused': bool(session.paused_at),
        'blocked_attempts': session.blocked_attempts,
        'lock_violations': session.lock_violations,
        'agent_online': agent_online,
        'active_approval': approval_payload(active_approval, now) if active_approval else None,
        'approved': [approval_payload(r, now) for r in approved_reqs],
        'server_time': now.isoformat(),
    })


# ─── Child: Approved App Use (pause / resume the focus timer) ───

@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_use_approved_app(request, request_id):
    """Child opens an approved restricted app. The focus timer FREEZES for the
    remainder of the grant window - this is sanctioned use, not distraction."""
    if request.user.role != 'CHILD':
        return JsonResponse({'status': 'error', 'message': 'Only children.'}, status=403)
    access_req = get_object_or_404(
        AccessRequest.objects.select_related('blacklist_item', 'session'),
        id=request_id, child=request.user,
    )
    sweep_approved_usage(request.user)
    access_req.refresh_from_db()

    if access_req.status != AccessRequest.Status.APPROVED or not access_req.is_grant_active:
        return JsonResponse({
            'status': 'error',
            'message': 'This approval has expired. Ask your parent again.',
        }, status=400)

    session = access_req.session
    if not session or session.status != FocusSession.Status.ACTIVE:
        return JsonResponse({
            'status': 'error',
            'message': 'No active focus session for this approval.',
        }, status=400)

    now = timezone.now()

    # Only one approved app at a time: politely close any previous usage first.
    previous = AccessRequest.objects.filter(
        child=request.user, status=AccessRequest.Status.APPROVED,
        in_use=True, usage_started_at__isnull=False,
    ).exclude(id=access_req.id).first()
    if previous and previous.id != access_req.id:
        _finalize_approved_usage(previous)

    already_using = access_req.in_use
    if not already_using:
        access_req.in_use = True
        access_req.usage_started_at = now
        access_req.save(update_fields=['in_use', 'usage_started_at'])
        session.paused_at = now
        session.save(update_fields=['paused_at'])
        record_lock_event(
            session, request.user, None,
            FocusLockEvent.EventType.APPROVED_APP_START,
            detail=f'Focus timer paused - child opened approved app '
                   f'"{access_req.blacklist_item.name}"',
            metadata={'request_id': access_req.id},
            notify=False,
        )

    remaining = max(0, int((access_req.granted_until - now).total_seconds()))
    item = access_req.blacklist_item
    url = ('https://' + item.url_pattern) if item.category == 'WEBSITE' and item.url_pattern else ''
    return JsonResponse({
        'status': 'success',
        'message': f'Using "{item.name}" - focus timer paused.',
        'app_name': item.name,
        'category': item.category,
        'url': url,
        'remaining_seconds': remaining,
        'focus_seconds': session.actual_focus_seconds,
        'already_using': already_using,
    })


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_release_approved_app(request, request_id):
    """Child returns to Focus Mode; accounting is finalized and the timer
    resumes from exactly where it froze."""
    if request.user.role != 'CHILD':
        return JsonResponse({'status': 'error', 'message': 'Only children.'}, status=403)
    access_req = get_object_or_404(
        AccessRequest.objects.select_related('blacklist_item', 'session'),
        id=request_id, child=request.user,
    )
    sweep_approved_usage(request.user)
    access_req.refresh_from_db()

    used_delta = _finalize_approved_usage(access_req)
    session = access_req.session
    return JsonResponse({
        'status': 'success',
        'message': 'Welcome back to Focus Mode.',
        'used_seconds': used_delta,
        'total_used_seconds': access_req.usage_seconds,
        'focus_seconds': session.actual_focus_seconds if session else None,
        'paused': bool(session and session.paused_at),
    })


# ─── Child: Launch Allowed Apps Through Sadhana ───

def _queue_launch_command(child, session, app_name, category, url_pattern=''):
    return FocusDeviceCommand.objects.create(
        requested_by=child,
        session=session,
        command_type=FocusDeviceCommand.CommandType.LAUNCH_APP,
        app_name=app_name,
        category=category,
        url_pattern=url_pattern,
    )


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_launch_app(request):
    """Clicking an allowed app icon inside Focus Mode. Websites are opened by
    the browser (extension permits them); desktop APPs are launched by the
    Desktop Agent via a queued command - the child never touches the taskbar."""
    if request.user.role != 'CHILD':
        return JsonResponse({'status': 'error', 'message': 'Only children.'}, status=403)
    try:
        data = json.loads(request.body)
        source = str(data.get('source', '')).upper()
        item_id = data.get('item_id')
        req_id = data.get('request_id')
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid data.'}, status=400)

    sweep_approved_usage(request.user)
    session = get_active_session(request.user)
    now = timezone.now()

    if source == 'WHITELIST':
        if not item_id:
            return JsonResponse({'status': 'error', 'message': 'Missing item_id.'}, status=400)
        item = get_object_or_404(WhitelistItem, id=item_id)
        if item.category == 'WEBSITE':
            url = 'https://' + item.url_pattern if item.url_pattern else ''
            return JsonResponse({
                'status': 'success', 'action': 'OPEN_URL', 'url': url,
                'message': f'Opening "{item.name}"...',
            })
        cmd = _queue_launch_command(
            request.user, session, item.app_name or item.name, 'APP'
        )
        agent_online = FocusDevice.objects.filter(
            child=request.user, device_type=FocusDevice.DeviceType.AGENT,
            is_active=True, last_seen__gte=now - timedelta(seconds=120),
        ).exists()
        return JsonResponse({
            'status': 'success', 'action': 'LAUNCH_APP', 'command_id': cmd.id,
            'app_name': cmd.app_name, 'agent_online': agent_online,
            'message': f'Launching "{cmd.app_name}" via Desktop Agent...',
        })

    if source == 'APPROVED':
        if not req_id:
            return JsonResponse({'status': 'error', 'message': 'Missing request_id.'}, status=400)
        access_req = get_object_or_404(
            AccessRequest.objects.select_related('blacklist_item'),
            id=req_id, child=request.user,
        )
        if access_req.status != AccessRequest.Status.APPROVED or not access_req.is_grant_active:
            return JsonResponse({
                'status': 'error', 'message': 'This approval has expired.',
            }, status=400)
        item = access_req.blacklist_item
        if item.category == 'WEBSITE':
            url = 'https://' + item.url_pattern if item.url_pattern else ''
            return JsonResponse({
                'status': 'success', 'action': 'OPEN_URL', 'url': url,
                'message': f'Opening "{item.name}" (approved)...',
            })
        cmd = _queue_launch_command(
            request.user, session, item.app_name or item.name, 'APP',
            url_pattern=item.url_pattern or '',
        )
        return JsonResponse({
            'status': 'success', 'action': 'LAUNCH_APP', 'command_id': cmd.id,
            'app_name': cmd.app_name,
            'message': f'Launching "{cmd.app_name}" via Desktop Agent...',
        })

    return JsonResponse({'status': 'error', 'message': 'Unknown source.'}, status=400)


# ─── Device: Command Acknowledgement ───

@csrf_exempt
@require_http_methods(['POST'])
def api_device_command_ack(request):
    device = get_device_from_request(request)
    if not device or not device.child:
        return JsonResponse({'status': 'error', 'message': 'Invalid device token.'}, status=401)
    try:
        data = json.loads(request.body)
        command_id = int(data.get('command_id'))
        ok = bool(data.get('ok', True))
        detail = str(data.get('detail', ''))[:500]
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid data.'}, status=400)

    command = get_object_or_404(
        FocusDeviceCommand, id=command_id, requested_by=device.child
    )
    command.status = FocusDeviceCommand.Status.DONE if ok \
        else FocusDeviceCommand.Status.FAILED
    command.detail = detail
    command.completed_at = timezone.now()
    command.save(update_fields=['status', 'detail', 'completed_at'])

    if ok and command.command_type == FocusDeviceCommand.CommandType.LAUNCH_APP:
        record_lock_event(
            command.session, device.child, device,
            FocusLockEvent.EventType.APP_LAUNCHED,
            detail=f'Desktop Agent launched "{command.app_name}" through Sadhana',
            metadata={'command_id': command.id},
            notify=False,
        )
    return JsonResponse({'status': 'success'})


# ─── Child: Check / Request Access to Blacklisted Item ───

@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_request_access(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    try:
        data = json.loads(request.body)
        blacklist_item_id = data.get('blacklist_item_id')
        session_id = data.get('session_id')
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid data.'}, status=400)

    blacklist_item = get_object_or_404(BlacklistItem, id=blacklist_item_id)
    session = get_object_or_404(FocusSession, id=session_id, child=request.user)

    if session.status != FocusSession.Status.ACTIVE:
        return JsonResponse({'error': 'No active focus session.'}, status=400)

    parents = get_connected_parents(request.user)
    if not parents:
        return JsonResponse({'error': 'No connected parent found.'}, status=400)

    requests_created = []
    for parent in parents:
        access_req, created = AccessRequest.objects.get_or_create(
            child=request.user,
            parent=parent,
            session=session,
            blacklist_item=blacklist_item,
            status=AccessRequest.Status.PENDING,
        )
        if created:
            record_lock_event(
                session, request.user, None,
                FocusLockEvent.EventType.ACCESS_REQUESTED,
                detail=f'Child requested access to "{blacklist_item.name}"',
                metadata={'request_id': access_req.id},
                notify=False,
            )
            NotificationService.access_requested(
                parent, request.user, blacklist_item.name, session,
                task_name=session.task.task_name if session.task else None
            )
        requests_created.append({'parent_id': parent.id, 'request_id': access_req.id, 'created': created})

    return JsonResponse({
        'status': 'success',
        'message': f'Access request sent to your parent(s) for "{blacklist_item.name}".',
        'requests': requests_created,
    })


@login_required
def api_check_whitelist(request):
    query = request.GET.get('q', '')
    results = []
    whitelist_items = WhitelistItem.objects.filter(
        Q(name__icontains=query) | Q(app_name__icontains=query) | Q(url_pattern__icontains=query)
    )
    for item in whitelist_items:
        results.append({
            'id': item.id,
            'name': item.name,
            'category': item.category,
            'url_pattern': item.url_pattern,
            'app_name': item.app_name,
        })
    return JsonResponse({'results': results})


@login_required
def api_check_blacklist(request):
    query = request.GET.get('q', '')
    results = []
    blacklist_items = BlacklistItem.objects.filter(
        Q(name__icontains=query) | Q(app_name__icontains=query) | Q(url_pattern__icontains=query)
    )
    for item in blacklist_items:
        results.append({
            'id': item.id,
            'name': item.name,
            'category': item.category,
            'url_pattern': item.url_pattern,
            'app_name': item.app_name,
        })
    return JsonResponse({'results': results})


# ─── Parent: Access Requests Management ───

@login_required
def parent_focus_dashboard(request):
    if request.user.role != 'PARENT':
        return redirect('dashboard_router')

    connections = ConnectionRequest.objects.filter(
        parent=request.user, status='ACCEPTED'
    ).select_related('child')
    children = [conn.child for conn in connections]

    pending_requests = AccessRequest.objects.filter(
        parent=request.user, status=AccessRequest.Status.PENDING
    ).select_related('child', 'session', 'blacklist_item').order_by('-requested_at')

    history = AccessRequest.objects.filter(
        parent=request.user
    ).exclude(
        status=AccessRequest.Status.PENDING
    ).select_related('child', 'parent', 'session', 'blacklist_item').order_by('-responded_at')[:50]

    context = {
        'children': children,
        'pending_requests': pending_requests,
        'history': history,
    }
    return render(request, 'focus/parent_dashboard.html', context)


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_approve_request(request, request_id):
    if request.user.role != 'PARENT':
        return JsonResponse({'error': 'Only parents can approve requests.'}, status=403)
    access_req = get_object_or_404(AccessRequest, id=request_id, parent=request.user)
    if access_req.status != AccessRequest.Status.PENDING:
        return JsonResponse({'error': 'Request is not pending.'}, status=400)

    access_req.status = AccessRequest.Status.APPROVED
    access_req.responded_at = timezone.now()
    duration_minutes = request.POST.get('grant_minutes')
    if duration_minutes:
        try:
            duration_minutes = int(duration_minutes)
        except ValueError:
            duration_minutes = None
    else:
        duration_minutes = 60

    if duration_minutes and duration_minutes > 0:
        access_req.granted_until = timezone.now() + timedelta(minutes=duration_minutes)
    else:
        duration_minutes = 60
        access_req.granted_until = timezone.now() + timedelta(hours=1)
    access_req.save()

    record_lock_event(
        access_req.session, access_req.child, None,
        FocusLockEvent.EventType.ACCESS_APPROVED,
        detail=f'Parent "{request.user.username}" approved "{access_req.blacklist_item.name}" for {duration_minutes} minutes',
        metadata={'request_id': access_req.id, 'granted_minutes': duration_minutes},
        notify=False,
    )

    NotificationService.access_approved_with_duration(
        access_req.child, request.user, access_req.blacklist_item.name, duration_minutes
    )

    return JsonResponse({'status': 'success', 'message': f'Access approved for {access_req.blacklist_item.name}.'})


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_reject_request(request, request_id):
    if request.user.role != 'PARENT':
        return JsonResponse({'error': 'Only parents can reject requests.'}, status=403)
    access_req = get_object_or_404(AccessRequest, id=request_id, parent=request.user)
    if access_req.status != AccessRequest.Status.PENDING:
        return JsonResponse({'error': 'Request is not pending.'}, status=400)

    access_req.status = AccessRequest.Status.REJECTED
    access_req.responded_at = timezone.now()
    access_req.save()

    record_lock_event(
        access_req.session, access_req.child, None,
        FocusLockEvent.EventType.ACCESS_DENIED,
        detail=f'Parent "{request.user.username}" denied "{access_req.blacklist_item.name}"',
        metadata={'request_id': access_req.id},
        notify=False,
    )

    NotificationService.access_rejected(
        access_req.child, request.user, access_req.blacklist_item.name
    )

    return JsonResponse({'status': 'success', 'message': f'Access denied for {access_req.blacklist_item.name}.'})


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_auto_expire_requests(request):
    if request.user.role != 'PARENT':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    timeout_minutes = int(request.POST.get('timeout_minutes', 5))
    cutoff = timezone.now() - timedelta(minutes=timeout_minutes)
    expired = AccessRequest.objects.filter(
        parent=request.user,
        status=AccessRequest.Status.PENDING,
        requested_at__lte=cutoff
    )
    count = expired.count()
    expired.update(
        status=AccessRequest.Status.EXPIRED,
        responded_at=timezone.now()
    )
    return JsonResponse({'status': 'success', 'expired_count': count})


# ─── Parent: Whitelist / Blacklist Management ───

@login_required
def api_list_whitelist(request):
    items = WhitelistItem.objects.all().order_by('name')
    data = [{
        'id': i.id,
        'name': i.name,
        'category': i.category,
        'url_pattern': i.url_pattern,
        'app_name': i.app_name,
        'is_default': i.is_default,
    } for i in items]
    return JsonResponse({'items': data})


@login_required
def api_list_blacklist(request):
    items = BlacklistItem.objects.all().order_by('name')
    data = [{
        'id': i.id,
        'name': i.name,
        'category': i.category,
        'url_pattern': i.url_pattern,
        'app_name': i.app_name,
        'is_default': i.is_default,
    } for i in items]
    return JsonResponse({'items': data})


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_add_whitelist(request):
    if request.user.role not in ('PARENT', 'ADMIN'):
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    item = WhitelistItem.objects.create(
        name=data.get('name'),
        category=data.get('category', 'APP'),
        url_pattern=data.get('url_pattern', ''),
        app_name=data.get('app_name', ''),
        created_by=request.user,
    )
    return JsonResponse({'status': 'success', 'id': item.id})


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_remove_whitelist(request, item_id):
    if request.user.role not in ('PARENT', 'ADMIN'):
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    item = get_object_or_404(WhitelistItem, id=item_id)
    if item.is_default:
        return JsonResponse({'error': 'Cannot remove default items.'}, status=400)
    item.delete()
    return JsonResponse({'status': 'success'})


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_add_blacklist(request):
    if request.user.role not in ('PARENT', 'ADMIN'):
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    item = BlacklistItem.objects.create(
        name=data.get('name'),
        category=data.get('category', 'APP'),
        url_pattern=data.get('url_pattern', ''),
        app_name=data.get('app_name', ''),
        created_by=request.user,
    )
    return JsonResponse({'status': 'success', 'id': item.id})


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_remove_blacklist(request, item_id):
    if request.user.role not in ('PARENT', 'ADMIN'):
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    item = get_object_or_404(BlacklistItem, id=item_id)
    if item.is_default:
        return JsonResponse({'error': 'Cannot remove default items.'}, status=400)
    item.delete()
    return JsonResponse({'status': 'success'})


# ─── Analytics ───

@login_required
def api_focus_analytics(request, child_id):
    if request.user.role != 'PARENT':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    conn = ConnectionRequest.objects.filter(
        parent=request.user, child_id=child_id, status='ACCEPTED'
    ).first()
    if not conn:
        return JsonResponse({'error': 'Not connected to this child.'}, status=403)

    today = timezone.now().date()
    now = timezone.now()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    sessions = FocusSession.objects.filter(child_id=child_id)

    def get_focus_distraction(fs):
        if fs.status == FocusSession.Status.ACTIVE:
            if fs.last_tick_at:
                # Ticking sessions: the server already owns live totals.
                return fs.actual_focus_seconds, fs.distraction_seconds
            elapsed = int((now - fs.start_time).total_seconds())
            return max(0, elapsed), 0
        return fs.actual_focus_seconds, fs.distraction_seconds

    # Daily
    daily_sessions = list(sessions.filter(start_time__date=today))
    daily_focus = sum(get_focus_distraction(fs)[0] for fs in daily_sessions)
    daily_distraction = sum(get_focus_distraction(fs)[1] for fs in daily_sessions)
    daily_completed = sum(1 for fs in daily_sessions if fs.status == FocusSession.Status.COMPLETED)
    daily_interrupted = sum(1 for fs in daily_sessions if fs.status == FocusSession.Status.INTERRUPTED)

    # Weekly
    weekly_sessions = list(sessions.filter(start_time__date__gte=week_start))
    weekly_focus = sum(get_focus_distraction(fs)[0] for fs in weekly_sessions)
    weekly_distraction = sum(get_focus_distraction(fs)[1] for fs in weekly_sessions)
    weekly_completed = sum(1 for fs in weekly_sessions if fs.status == FocusSession.Status.COMPLETED)
    weekly_interrupted = sum(1 for fs in weekly_sessions if fs.status == FocusSession.Status.INTERRUPTED)

    # Monthly
    monthly_sessions = list(sessions.filter(start_time__date__gte=month_start))
    monthly_focus = sum(get_focus_distraction(fs)[0] for fs in monthly_sessions)
    monthly_distraction = sum(get_focus_distraction(fs)[1] for fs in monthly_sessions)
    monthly_completed = sum(1 for fs in monthly_sessions if fs.status == FocusSession.Status.COMPLETED)
    monthly_interrupted = sum(1 for fs in monthly_sessions if fs.status == FocusSession.Status.INTERRUPTED)

    # Daily trend data (last 7 days)
    trend_dates = []
    trend_focus_minutes = []
    trend_distraction_minutes = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_sessions = list(sessions.filter(start_time__date=day))
        day_focus = sum(get_focus_distraction(fs)[0] for fs in day_sessions)
        day_distraction = sum(get_focus_distraction(fs)[1] for fs in day_sessions)
        trend_dates.append(day.strftime('%a'))
        trend_focus_minutes.append(round(day_focus / 60))
        trend_distraction_minutes.append(round(day_distraction / 60))

    # Access request stats
    access_requests = AccessRequest.objects.filter(
        child_id=child_id, parent=request.user
    )
    total_requests = access_requests.count()
    approved_requests = access_requests.filter(status=AccessRequest.Status.APPROVED).count()
    rejected_requests = access_requests.filter(status=AccessRequest.Status.REJECTED).count()

    return JsonResponse({
        'daily': {
            'focus_seconds': daily_focus,
            'focus_minutes': round(daily_focus / 60),
            'distraction_seconds': daily_distraction,
            'completed': daily_completed,
            'interrupted': daily_interrupted,
        },
        'weekly': {
            'focus_seconds': weekly_focus,
            'focus_minutes': round(weekly_focus / 60),
            'distraction_seconds': weekly_distraction,
            'completed': weekly_completed,
            'interrupted': weekly_interrupted,
        },
        'monthly': {
            'focus_seconds': monthly_focus,
            'focus_minutes': round(monthly_focus / 60),
            'distraction_seconds': monthly_distraction,
            'completed': monthly_completed,
            'interrupted': monthly_interrupted,
        },
        'trend': {
            'dates': trend_dates,
            'focus_minutes': trend_focus_minutes,
            'distraction_minutes': trend_distraction_minutes,
        },
        'access_requests': {
            'total': total_requests,
            'approved': approved_requests,
            'rejected': rejected_requests,
        }
    })


@login_required
def api_parent_child_sessions(request, child_id):
    if request.user.role != 'PARENT':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    conn = ConnectionRequest.objects.filter(
        parent=request.user, child_id=child_id, status='ACCEPTED'
    ).first()
    if not conn:
        return JsonResponse({'error': 'Not connected to this child.'}, status=403)

    sessions = FocusSession.objects.filter(child_id=child_id).order_by('-start_time')[:50]
    data = []
    for s in sessions:
        data.append({
            'id': s.id,
            'planned_duration': s.planned_duration,
            'actual_focus_seconds': s.actual_focus_seconds,
            'distraction_seconds': s.distraction_seconds,
            'status': s.status,
            'start_time': s.start_time.isoformat(),
            'end_time': s.end_time.isoformat() if s.end_time else None,
        })
    return JsonResponse({'sessions': data})


# ─── CSRF exempt helpers for fetch API calls ───

@login_required
@require_http_methods(['GET'])
def api_get_access_requests(request):
    if request.user.role != 'PARENT':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    pending = AccessRequest.objects.filter(
        parent=request.user, status=AccessRequest.Status.PENDING
    ).select_related('child', 'blacklist_item', 'session')
    data = []
    for req in pending:
        data.append({
            'id': req.id,
            'child_name': req.child.username,
            'child_id': req.child.id,
            'app_name': req.blacklist_item.name,
            'app_category': req.blacklist_item.category,
            'requested_at': req.requested_at.isoformat(),
            'session_id': req.session.id,
            'session_duration': req.session.planned_duration,
            'task_name': req.session.task.task_name if req.session.task else None,
        })
    return JsonResponse({'requests': data})


@login_required
def api_parent_active_sessions(request):
    """Live view of each connected child's active focus session for the parent
    Focus Control dashboard (current task + remaining focus time)."""
    if request.user.role != 'PARENT':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)

    connections = ConnectionRequest.objects.filter(
        parent=request.user, status='ACCEPTED'
    ).select_related('child')
    now = timezone.now()

    data = []
    for conn in connections:
        session = FocusSession.objects.filter(
            child=conn.child, status=FocusSession.Status.ACTIVE
        ).select_related('task').first()
        if not session:
            continue
        sweep_approved_usage(conn.child)
        session.refresh_from_db(fields=['paused_at'])
        if session.last_tick_at:
            focus_seconds = session.actual_focus_seconds
        else:
            focus_seconds = max(0, int((now - session.start_time).total_seconds()))
        remaining = max(0, session.planned_duration * 60 - focus_seconds)
        active_approval = get_active_approval(conn.child)
        data.append({
            'child_id': conn.child.id,
            'child_name': conn.child.username,
            'session_id': session.id,
            'task_name': session.task.task_name if session.task else None,
            'planned_duration': session.planned_duration,
            'focus_seconds': focus_seconds,
            'remaining_seconds': remaining,
            'start_time': session.start_time.isoformat(),
            'lock_enabled': session.lock_enabled,
            'lock_violations': session.lock_violations,
            'paused': bool(session.paused_at),
            'approved_app': (active_approval.blacklist_item.name
                             if active_approval else None),
            'approved_app_remaining': (
                max(0, int((active_approval.granted_until - now).total_seconds()))
                if active_approval and active_approval.granted_until else 0
            ),
        })
    return JsonResponse({'sessions': data})


@login_required
def api_child_focus_history(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    sessions = FocusSession.objects.filter(child=request.user)[:20]
    data = []
    for s in sessions:
        data.append({
            'id': s.id,
            'planned_duration': s.planned_duration,
            'actual_focus_seconds': s.actual_focus_seconds,
            'distraction_seconds': s.distraction_seconds,
            'status': s.status,
            'start_time': s.start_time.isoformat(),
            'end_time': s.end_time.isoformat() if s.end_time else None,
        })
    return JsonResponse({'sessions': data})


@login_required
def api_get_approved_apps(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)

    sweep_approved_usage(request.user)
    now = timezone.now()
    approved = AccessRequest.objects.filter(
        child=request.user,
        status=AccessRequest.Status.APPROVED,
        granted_until__gte=now,
    ).select_related('blacklist_item')

    data = []
    for req in approved:
        payload = approval_payload(req, now)
        payload['app_category'] = payload.pop('category')
        data.append(payload)
    return JsonResponse({'approved_apps': data})


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_mark_app_usage(request):
    """Legacy compatibility endpoint (old clients). New flow prefers
    api_use_approved_app / api_release_approved_app."""
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    try:
        data = json.loads(request.body)
        request_id = data.get('request_id')
        in_use = bool(data.get('in_use', False))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid data.'}, status=400)

    access_req = get_object_or_404(
        AccessRequest.objects.select_related('blacklist_item', 'session'),
        id=request_id, child=request.user,
    )
    sweep_approved_usage(request.user)
    access_req.refresh_from_db()

    if in_use:
        if access_req.status == AccessRequest.Status.APPROVED and access_req.is_grant_active:
            session = access_req.session
            if session and session.paused_at is None:
                access_req.in_use = True
                access_req.usage_started_at = timezone.now()
                access_req.save(update_fields=['in_use', 'usage_started_at'])
                session.paused_at = access_req.usage_started_at
                session.save(update_fields=['paused_at'])
    else:
        _finalize_approved_usage(access_req)
        access_req.refresh_from_db()

    return JsonResponse({
        'status': 'success',
        'app_name': access_req.blacklist_item.name,
        'in_use': access_req.in_use,
        'paused': bool(access_req.session and access_req.session.paused_at),
    })


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_report_blocked(request):
    """Legacy endpoint kept for backward compatibility. Prefer api_report_lock_event."""
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)

    session = FocusSession.objects.filter(
        child=request.user, status=FocusSession.Status.ACTIVE
    ).first()
    if not session:
        return JsonResponse({'error': 'No active focus session.'}, status=400)

    item_name = request.POST.get('app_name') or request.POST.get('item_name') or ''
    event_type = FocusLockEvent.EventType.APP_BLOCKED
    if item_name and not item_name.lower().endswith(('.exe', '.app')):
        event_type = FocusLockEvent.EventType.WEBSITE_BLOCKED
    record_lock_event(session, request.user, None, event_type, detail=item_name)

    return JsonResponse({
        'status': 'success',
        'blocked_attempts': session.blocked_attempts,
    })


# ─── Device management (browser extension + desktop agent) ───

@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_register_device(request):
    """Child registers a new enforcement device. Returns the bearer token that
    the browser extension / desktop agent must store and send with every call."""
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    device_type = data.get('device_type')
    if device_type not in FocusDevice.DeviceType.values:
        return JsonResponse({'error': 'device_type must be EXTENSION or AGENT.'}, status=400)

    name = (data.get('name') or '').strip()[:100]
    if not name:
        name = 'Focus Guard ' + device_type.title()

    device = FocusDevice.objects.create(
        child=request.user,
        device_type=device_type,
        name=name,
        last_seen=timezone.now(),
    )
    return JsonResponse({
        'status': 'success',
        'device_id': device.id,
        'name': device.name,
        'device_type': device.device_type,
        'token': device.token,
    })


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_unregister_device(request, device_id):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    device = get_object_or_404(FocusDevice, id=device_id, child=request.user)
    device.is_active = False
    device.save(update_fields=['is_active'])
    return JsonResponse({'status': 'success', 'revoked': device.name})


@login_required
def api_list_devices(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    devices = FocusDevice.objects.filter(child=request.user, is_active=True)
    data = [{
        'id': d.id,
        'name': d.name,
        'device_type': d.device_type,
        'last_seen': d.last_seen.isoformat() if d.last_seen else None,
        'online': d.last_seen and (timezone.now() - d.last_seen) < timedelta(minutes=2),
        'token': d.token,
    } for d in devices]
    return JsonResponse({'devices': data})


# ─── Device-facing endpoints (token auth) ───

def _device_context(request):
    """Return (device, child, active_session) resolved from token auth."""
    device = get_device_from_request(request)
    if not device:
        return None, None, None
    session = FocusSession.objects.filter(
        child=device.child, status=FocusSession.Status.ACTIVE
    ).select_related('task').first()
    return device, device.child, session


def api_device_status(request):
    """Polled by the browser extension and desktop agent. Returns the current
    lock state + block/allow rules for the authenticated device's child."""
    device, child, session = _device_context(request)
    if not device:
        return JsonResponse({'error': 'Invalid or inactive device token.'}, status=401)
    device.last_seen = timezone.now()
    device.save(update_fields=['last_seen'])
    return JsonResponse(device_status_payload(child, session, device))


@login_required
@require_http_methods(['POST'])
@csrf_exempt
def api_device_heartbeat(request):
    """Extension / agent heartbeat. Optionally carries a batch of lock events
    that were detected client-side while offline."""
    device, child, session = _device_context(request)
    if not device:
        return JsonResponse({'error': 'Invalid or inactive device token.'}, status=401)
    device.last_seen = timezone.now()
    device.save(update_fields=['last_seen'])

    if request.body:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    events = data.get('events') or []
    if session:
        for ev in events:
            event_type = ev.get('event_type')
            if event_type not in FocusLockEvent.EventType.values:
                continue
            record_lock_event(
                session, child, device, event_type,
                detail=ev.get('detail', ''),
                metadata=ev.get('metadata') or {},
            )

    return JsonResponse({
        'status': 'success',
        'session_active': bool(session),
        'lock_enabled': bool(session and session.lock_enabled),
        'session_id': session.id if session else None,
        'blocked_attempts': session.blocked_attempts if session else 0,
        'lock_violations': session.lock_violations if session else 0,
    })


# ─── Unified lock event reporting (cookie or token auth) ───

def resolve_effective_child(request):
    """Return the CHILD user for cookie-authenticated web requests or for
    bearer-token-authenticated device requests, or None if unauthenticated."""
    device = get_device_from_request(request)
    if device:
        return device.child, device
    if request.user.is_authenticated and request.user.role == 'CHILD':
        return request.user, None
    return None, None


@require_http_methods(['POST'])
@csrf_exempt
def api_report_lock_event(request):
    """Record an interruption/access attempt on the active session and notify
    the linked parent immediately. Accepts session-cookie auth (web page) or
    bearer-token auth (extension / agent)."""
    child, device = resolve_effective_child(request)
    if not child:
        return JsonResponse({'error': 'Unauthorized.'}, status=401)

    session = FocusSession.objects.filter(
        child=child, status=FocusSession.Status.ACTIVE
    ).select_related('task').first()

    if not session:
        return JsonResponse({'error': 'No active focus session.'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    event_type = data.get('event_type')
    if event_type not in FocusLockEvent.EventType.values:
        return JsonResponse({'error': 'Invalid event_type.'}, status=400)

    event = record_lock_event(
        session, child, device, event_type,
        detail=data.get('detail', ''),
        metadata=data.get('metadata') or {},
    )
    return JsonResponse({
        'status': 'success',
        'event_id': event.id,
        'event_type': event.event_type,
        'blocked_attempts': session.blocked_attempts,
        'lock_violations': session.lock_violations,
    })


def api_focus_mode_status(request):
    """GET block/allow rules + active session, used by the Browser Extension
    to decide what to block while Focus Mode is active. Accepts cookie auth
    or device bearer token."""
    child, device = resolve_effective_child(request)
    if not child:
        return JsonResponse({'error': 'Unauthorized.'}, status=401)

    session = FocusSession.objects.filter(
        child=child, status=FocusSession.Status.ACTIVE
    ).select_related('task').first()

    return JsonResponse(device_status_payload(child, session, device))


# ─── Parent: lock events & devices feed ───

@login_required
def api_parent_lock_events(request, child_id):
    if request.user.role != 'PARENT':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    conn = ConnectionRequest.objects.filter(
        parent=request.user, child_id=child_id, status='ACCEPTED'
    ).first()
    if not conn:
        return JsonResponse({'error': 'Not connected to this child.'}, status=403)

    events = FocusLockEvent.objects.filter(child_id=child_id).select_related(
        'session', 'device'
    ).order_by('-created_at')[:100]

    data = [{
        'id': e.id,
        'child_name': e.child.username,
        'event_type': e.event_type,
        'severity': e.severity,
        'detail': e.detail,
        'source': e.device.name if e.device else 'Web',
        'notified': e.notified,
        'created_at': e.created_at.isoformat(),
        'session_id': e.session_id,
        'task_name': e.session.task.task_name if e.session and e.session.task else None,
    } for e in events]
    return JsonResponse({'events': data})


@login_required
def api_parent_all_lock_events(request):
    """Lock events across every connected child (for the 'All children' view)."""
    if request.user.role != 'PARENT':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    child_ids = ConnectionRequest.objects.filter(
        parent=request.user, status='ACCEPTED'
    ).values_list('child_id', flat=True)

    events = FocusLockEvent.objects.filter(child_id__in=child_ids).select_related(
        'session', 'device', 'child'
    ).order_by('-created_at')[:200]

    data = [{
        'id': e.id,
        'child_name': e.child.username,
        'event_type': e.event_type,
        'severity': e.severity,
        'detail': e.detail,
        'source': e.device.name if e.device else 'Web',
        'notified': e.notified,
        'created_at': e.created_at.isoformat(),
        'session_id': e.session_id,
        'task_name': e.session.task.task_name if e.session and e.session.task else None,
    } for e in events]
    return JsonResponse({'events': data})


@login_required
def api_parent_devices(request):
    if request.user.role != 'PARENT':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    connections = ConnectionRequest.objects.filter(
        parent=request.user, status='ACCEPTED'
    ).select_related('child')
    now = timezone.now()
    data = []
    for conn in connections:
        devices = FocusDevice.objects.filter(child=conn.child, is_active=True)
        for d in devices:
            data.append({
                'child_id': conn.child.id,
                'child_name': conn.child.username,
                'device_id': d.id,
                'name': d.name,
                'device_type': d.device_type,
                'last_seen': d.last_seen.isoformat() if d.last_seen else None,
                'online': d.last_seen and (now - d.last_seen) < timedelta(minutes=2),
                'created_at': d.created_at.isoformat(),
            })
    return JsonResponse({'devices': data})
