from django.db import transaction
from .models import Notification


class NotificationService:

    @staticmethod
    def _create(recipient, sender, sender_name, notification_type, message):
        return Notification.objects.create(
            recipient=recipient,
            sender=sender,
            sender_name=sender_name,
            notification_type=notification_type,
            message=message
        )

    @staticmethod
    def _notify_parent(parent, child, notification_type, message):
        return NotificationService._create(
            recipient=parent,
            sender=child,
            sender_name=child.username,
            notification_type=notification_type,
            message=message
        )

    @staticmethod
    def _notify_child(child, parent, notification_type, message):
        return NotificationService._create(
            recipient=child,
            sender=parent,
            sender_name=parent.username,
            notification_type=notification_type,
            message=message
        )

    # Parent → Child notifications

    @staticmethod
    def task_assigned(parent, child, task):
        return NotificationService._notify_child(
            child=child, parent=parent,
            notification_type=Notification.NotificationType.TASK_ASSIGNED,
            message=f"Your parent \"{parent.username}\" assigned you a new task: \"{task.task_name}\"."
        )

    @staticmethod
    def task_edited(parent, child, task):
        return NotificationService._notify_child(
            child=child, parent=parent,
            notification_type=Notification.NotificationType.TASK_EDITED,
            message=f"Your parent \"{parent.username}\" updated the task: \"{task.task_name}\"."
        )

    @staticmethod
    def deadline_changed(parent, child, task):
        return NotificationService._notify_child(
            child=child, parent=parent,
            notification_type=Notification.NotificationType.DEADLINE_CHANGED,
            message=f"Your parent \"{parent.username}\" changed the deadline for task: \"{task.task_name}\"."
        )

    @staticmethod
    def appreciation_sent(parent, child, appreciation_msg):
        return NotificationService._notify_child(
            child=child, parent=parent,
            notification_type=Notification.NotificationType.APPRECIATION,
            message=f"Your parent \"{parent.username}\" appreciated your progress: \"{appreciation_msg}\"."
        )

    # Child → Parent notifications

    @staticmethod
    def task_completed(parent, child, task):
        return NotificationService._notify_parent(
            parent=parent, child=child,
            notification_type=Notification.NotificationType.TASK_COMPLETED,
            message=f"Your child \"{child.username}\" completed the task \"{task.task_name}\"."
        )

    @staticmethod
    def task_reopened(parent, child, task):
        return NotificationService._notify_parent(
            parent=parent, child=child,
            notification_type=Notification.NotificationType.TASK_REOPENED,
            message=f"Your child \"{child.username}\" re-opened the task \"{task.task_name}\"."
        )

    @staticmethod
    def all_tasks_done(parent, child):
        return NotificationService._notify_parent(
            parent=parent, child=child,
            notification_type=Notification.NotificationType.ALL_TASKS_DONE,
            message=f"Your child \"{child.username}\" completed all assigned tasks today!"
        )

    @staticmethod
    def deadline_missed(parent, child, task):
        return NotificationService._notify_parent(
            parent=parent, child=child,
            notification_type=Notification.NotificationType.DEADLINE_MISSED,
            message=f"Your child \"{child.username}\" missed the deadline for \"{task.task_name}\"."
        )

    @staticmethod
    def low_completion(parent, child, percentage):
        return NotificationService._notify_parent(
            parent=parent, child=child,
            notification_type=Notification.NotificationType.LOW_COMPLETION,
            message=f"Your child \"{child.username}\" has completed only {percentage}% of today's tasks."
        )

    @staticmethod
    def study_streak(parent, child, streak_days):
        return NotificationService._notify_parent(
            parent=parent, child=child,
            notification_type=Notification.NotificationType.STUDY_STREAK,
            message=f"Your child \"{child.username}\" achieved a {streak_days}-day study streak!"
        )

    @staticmethod
    def distraction_alert(parent, child, distraction_minutes, duration_minutes):
        return NotificationService._notify_parent(
            parent=parent, child=child,
            notification_type=Notification.NotificationType.DISTRACTION_ALERT,
            message=f"Your child \"{child.username}\" was distracted for {distraction_minutes} minutes during their {duration_minutes}-minute study session."
        )

    # Self/system notifications

    @staticmethod
    def all_tasks_done_child(child):
        return NotificationService._create(
            recipient=child,
            sender=None,
            sender_name="System",
            notification_type=Notification.NotificationType.ALL_TASKS_DONE,
            message="Congratulations! You completed all your tasks today."
        )

    @staticmethod
    def pending_tasks_reminder(child, pending_count):
        return NotificationService._create(
            recipient=child,
            sender=None,
            sender_name="System",
            notification_type=Notification.NotificationType.LOW_COMPLETION,
            message=f"Reminder: You have {pending_count} pending task(s) due today."
        )

    @staticmethod
    def access_requested(parent, child, app_name, session):
        return NotificationService._notify_parent(
            parent=parent, child=child,
            notification_type=Notification.NotificationType.ACCESS_REQUESTED,
            message=f"Your child \"{child.username}\" requested access to \"{app_name}\" during a focus session."
        )

    @staticmethod
    def access_approved(child, parent, app_name):
        return NotificationService._notify_child(
            child=child, parent=parent,
            notification_type=Notification.NotificationType.ACCESS_APPROVED,
            message=f"Your parent approved access to \"{app_name}\"."
        )

    @staticmethod
    def access_rejected(child, parent, app_name):
        return NotificationService._notify_child(
            child=child, parent=parent,
            notification_type=Notification.NotificationType.ACCESS_REJECTED,
            message=f"Your parent denied access to \"{app_name}\". Please continue your study session."
        )

    @staticmethod
    def focus_completed(parent, child, duration_minutes):
        return NotificationService._notify_parent(
            parent=parent, child=child,
            notification_type=Notification.NotificationType.FOCUS_COMPLETED,
            message=f"Your child \"{child.username}\" completed a {duration_minutes}-minute focus session!"
        )

    @staticmethod
    def focus_interrupted(parent, child, duration_minutes):
        return NotificationService._notify_parent(
            parent=parent, child=child,
            notification_type=Notification.NotificationType.FOCUS_INTERRUPTED,
            message=f"Your child \"{child.username}\" ended their focus session early after {duration_minutes} minutes."
        )

    @staticmethod
    def notify_all_parents(child, notify_func, *args, **kwargs):
        from relationships.models import ConnectionRequest
        connections = ConnectionRequest.objects.filter(
            child=child, status='ACCEPTED'
        ).select_related('parent')
        notifications = []
        for conn in connections:
            n = notify_func(conn.parent, child, *args, **kwargs)
            notifications.append(n)
        return notifications
