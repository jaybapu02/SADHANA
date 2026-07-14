from django.db import models
from django.conf import settings


class FocusSession(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        COMPLETED = 'COMPLETED', 'Completed'
        INTERRUPTED = 'INTERRUPTED', 'Interrupted'

    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='focus_sessions'
    )
    planned_duration = models.IntegerField(help_text="Planned duration in minutes (25, 50, or custom)")
    actual_focus_seconds = models.IntegerField(default=0, help_text="Actual focused time in seconds")
    distraction_seconds = models.IntegerField(default=0, help_text="Total distracted time in seconds")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-start_time']

    def __str__(self):
        return f"{self.child.username} - {self.planned_duration}min ({self.status})"


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
