import secrets

from django.db import models
from django.conf import settings


class FocusSession(models.Model):
    class Type(models.TextChoices):
        FOCUS = 'FOCUS', 'Focus'
        STUDY = 'STUDY', 'Study'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        COMPLETED = 'COMPLETED', 'Completed'
        INTERRUPTED = 'INTERRUPTED', 'Interrupted'

    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='focus_sessions'
    )
    session_type = models.CharField(max_length=10, choices=Type.choices, default=Type.FOCUS, help_text="FOCUS = Pomodoro with app blocking, STUDY = free-form timer")
    planned_duration = models.IntegerField(help_text="Planned duration in minutes (25, 50, 90, or custom)")
    actual_focus_seconds = models.IntegerField(default=0, help_text="Actual focused time in seconds")
    distraction_seconds = models.IntegerField(default=0, help_text="Total distracted time in seconds")
    break_seconds = models.IntegerField(default=0, help_text="Total break time in seconds")
    focus_score = models.FloatField(default=0.0, help_text="Calculated focus percentage")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    task = models.ForeignKey(
        'tasks.Task',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='focus_sessions',
        help_text="To-Do task the child is working on during this session"
    )
    blocked_attempts = models.IntegerField(default=0, help_text="Number of blocked access attempts during this session")
    lock_violations = models.IntegerField(default=0, help_text="Number of lock violations (tab switch / minimize / leave attempt)")
    lock_enabled = models.BooleanField(default=False, help_text="Super Power Saving Mode - OS/browser level lock is enforced")
    early_exit = models.BooleanField(default=False, help_text="Child ended the session before the planned duration")

    class Meta:
        ordering = ['-start_time']

    def save(self, *args, **kwargs):
        total = self.actual_focus_seconds + self.distraction_seconds
        if total > 0:
            self.focus_score = round((self.actual_focus_seconds / total) * 100, 2)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.child.username} - {self.get_session_type_display()} ({self.status})"


class WhitelistItem(models.Model):
    CATEGORY_CHOICES = (
        ('APP', 'Application'),
        ('WEBSITE', 'Website'),
    )

    name = models.CharField(max_length=100)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default='APP')
    url_pattern = models.CharField(max_length=500, blank=True, null=True, help_text="URL pattern for websites")
    app_name = models.CharField(max_length=100, blank=True, null=True, help_text="Executable name for applications")
    is_default = models.BooleanField(default=False, help_text="Pre-seeded system default")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_whitelist_items'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Whitelist items'

    def __str__(self):
        return self.name


class BlacklistItem(models.Model):
    CATEGORY_CHOICES = (
        ('APP', 'Application'),
        ('WEBSITE', 'Website'),
    )

    name = models.CharField(max_length=100)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default='APP')
    url_pattern = models.CharField(max_length=500, blank=True, null=True, help_text="URL pattern for websites")
    app_name = models.CharField(max_length=100, blank=True, null=True, help_text="Executable name for applications")
    is_default = models.BooleanField(default=False, help_text="Pre-seeded system default")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_blacklist_items'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Blacklist items'

    def __str__(self):
        return self.name


class AccessRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        EXPIRED = 'EXPIRED', 'Expired'

    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='access_requests'
    )
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviewed_access_requests'
    )
    session = models.ForeignKey(
        FocusSession,
        on_delete=models.CASCADE,
        related_name='access_requests'
    )
    blacklist_item = models.ForeignKey(
        BlacklistItem,
        on_delete=models.CASCADE,
        related_name='access_requests'
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    granted_until = models.DateTimeField(null=True, blank=True, help_text="If approved, access granted until this time")
    in_use = models.BooleanField(default=False, help_text="Child is currently using this approved app")

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"{self.child.username} -> {self.blacklist_item.name} ({self.status})"


class FocusAnalytics(models.Model):
    class Period(models.TextChoices):
        DAILY = 'DAILY', 'Daily'
        WEEKLY = 'WEEKLY', 'Weekly'
        MONTHLY = 'MONTHLY', 'Monthly'

    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='focus_analytics'
    )
    period = models.CharField(max_length=10, choices=Period.choices)
    period_start = models.DateField()
    period_end = models.DateField()
    total_focus_seconds = models.IntegerField(default=0)
    completed_sessions = models.IntegerField(default=0)
    interrupted_sessions = models.IntegerField(default=0)
    total_requests = models.IntegerField(default=0)
    approved_requests = models.IntegerField(default=0)
    rejected_requests = models.IntegerField(default=0)

    class Meta:
        verbose_name_plural = 'Focus analytics'
        unique_together = ('child', 'period', 'period_start')

    def __str__(self):
        return f"{self.child.username} - {self.period} ({self.period_start})"


class FocusDevice(models.Model):
    """A trusted enforcement device (browser extension or desktop Focus Agent)
    registered by the child. Devices authenticate with a bearer token so they
    can block apps/sites and report lock events to the server."""

    class DeviceType(models.TextChoices):
        EXTENSION = 'EXTENSION', 'Browser Extension'
        AGENT = 'AGENT', 'Desktop Agent'

    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='focus_devices'
    )
    device_type = models.CharField(max_length=10, choices=DeviceType.choices)
    name = models.CharField(max_length=100)
    token = models.CharField(max_length=64, unique=True, editable=False)
    last_seen = models.DateTimeField(null=True, blank=True, help_text="Last heartbeat received")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.child.username} - {self.name} ({self.get_device_type_display()})"


class FocusLockEvent(models.Model):
    """Every interruption / access attempt / approval / denial recorded during
    a locked focus session. Feeds the parent dashboard and notifications."""

    class EventType(models.TextChoices):
        LOCK_ACTIVATED = 'LOCK_ACTIVATED', 'Lock Activated'
        LOCK_DEACTIVATED = 'LOCK_DEACTIVATED', 'Lock Deactivated'
        TAB_SWITCH = 'TAB_SWITCH', 'Tab Switch'
        TAB_HIDE = 'TAB_HIDE', 'Tab Hidden'
        MINIMIZE = 'MINIMIZE', 'Window Minimized'
        WINDOW_CLOSE = 'WINDOW_CLOSE', 'Window Closed'
        LEAVE_ATTEMPT = 'LEAVE_ATTEMPT', 'Leave Attempt'
        APP_BLOCKED = 'APP_BLOCKED', 'App Blocked'
        WEBSITE_BLOCKED = 'WEBSITE_BLOCKED', 'Website Blocked'
        ACCESS_REQUESTED = 'ACCESS_REQUESTED', 'Access Requested'
        ACCESS_APPROVED = 'ACCESS_APPROVED', 'Access Approved'
        ACCESS_DENIED = 'ACCESS_DENIED', 'Access Denied'
        DEVICE_ONLINE = 'DEVICE_ONLINE', 'Device Online'
        DEVICE_OFFLINE = 'DEVICE_OFFLINE', 'Device Offline'

    class Severity(models.TextChoices):
        INFO = 'INFO', 'Info'
        WARNING = 'WARNING', 'Warning'
        CRITICAL = 'CRITICAL', 'Critical'

    SEVERITY_BY_EVENT = {
        EventType.LOCK_ACTIVATED: Severity.INFO,
        EventType.LOCK_DEACTIVATED: Severity.INFO,
        EventType.DEVICE_ONLINE: Severity.INFO,
        EventType.ACCESS_APPROVED: Severity.INFO,
        EventType.ACCESS_REQUESTED: Severity.WARNING,
        EventType.TAB_HIDE: Severity.WARNING,
        EventType.ACCESS_DENIED: Severity.CRITICAL,
        EventType.TAB_SWITCH: Severity.CRITICAL,
        EventType.MINIMIZE: Severity.CRITICAL,
        EventType.WINDOW_CLOSE: Severity.CRITICAL,
        EventType.LEAVE_ATTEMPT: Severity.CRITICAL,
        EventType.APP_BLOCKED: Severity.CRITICAL,
        EventType.WEBSITE_BLOCKED: Severity.CRITICAL,
        EventType.DEVICE_OFFLINE: Severity.CRITICAL,
    }

    session = models.ForeignKey(
        FocusSession,
        on_delete=models.CASCADE,
        related_name='lock_events'
    )
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='focus_lock_events'
    )
    device = models.ForeignKey(
        FocusDevice,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='lock_events'
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.INFO)
    detail = models.TextField(blank=True, default='', help_text="Human readable description, e.g. blocked app or website name")
    metadata = models.JSONField(default=dict, blank=True)
    notified = models.BooleanField(default=False, help_text="Whether the linked parent(s) were notified")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.child.username} - {self.event_type} ({self.created_at:%Y-%m-%d %H:%M})"
