from django.db import models
from django.conf import settings


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        TASK_ASSIGNED = 'TASK_ASSIGNED', 'Task Assigned'
        TASK_EDITED = 'TASK_EDITED', 'Task Edited'
        DEADLINE_CHANGED = 'DEADLINE_CHANGED', 'Deadline Changed'
        APPRECIATION = 'APPRECIATION', 'Appreciation'
        TASK_COMPLETED = 'TASK_COMPLETED', 'Task Completed'
        ALL_TASKS_DONE = 'ALL_TASKS_DONE', 'All Tasks Done'
        DEADLINE_MISSED = 'DEADLINE_MISSED', 'Deadline Missed'
        LOW_COMPLETION = 'LOW_COMPLETION', 'Low Completion'
        STUDY_STREAK = 'STUDY_STREAK', 'Study Streak'
        DISTRACTION_ALERT = 'DISTRACTION_ALERT', 'Distraction Alert'
        TASK_REOPENED = 'TASK_REOPENED', 'Task Reopened'
        ACCESS_REQUESTED = 'ACCESS_REQUESTED', 'Access Requested'
        ACCESS_APPROVED = 'ACCESS_APPROVED', 'Access Approved'
        ACCESS_REJECTED = 'ACCESS_REJECTED', 'Access Rejected'
        LOCK_VIOLATION = 'LOCK_VIOLATION', 'Lock Violation'
        LOCK_ACTIVATED = 'LOCK_ACTIVATED', 'Lock Activated'
        LOCK_DEACTIVATED = 'LOCK_DEACTIVATED', 'Lock Deactivated'
        DEVICE_OFFLINE = 'DEVICE_OFFLINE', 'Device Offline'
        FOCUS_COMPLETED = 'FOCUS_COMPLETED', 'Focus Session Completed'
        FOCUS_INTERRUPTED = 'FOCUS_INTERRUPTED', 'Focus Session Interrupted'
        LEVEL_UP = 'LEVEL_UP', 'Level Up'
        BADGE_EARNED = 'BADGE_EARNED', 'Badge Earned'
        CHAT_MESSAGE = 'CHAT_MESSAGE', 'Chat Message'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sent_notifications'
    )
    sender_name = models.CharField(max_length=150)
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices
    )
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"To {self.recipient.username} - {self.message[:50]}"
