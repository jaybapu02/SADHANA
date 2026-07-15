from django.db import models
from django.conf import settings

class Task(models.Model):
    PRIORITY_CHOICES = (
        ('HIGH', 'High'),
        ('MEDIUM', 'Medium'),
        ('LOW', 'Low'),
    )

    SUBJECT_CHOICES = (
        ('MATH', 'Mathematics'),
        ('SCIENCE', 'Science'),
        ('PROGRAMMING', 'Programming'),
        ('ENGLISH', 'English'),
        ('HISTORY', 'History'),
        ('PHYSICS', 'Physics'),
        ('CHEMISTRY', 'Chemistry'),
        ('BIOLOGY', 'Biology'),
        ('OTHER', 'Other'),
    )

    child = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tasks')
    parent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='assigned_tasks')
    task_name = models.CharField(max_length=255)
    status = models.BooleanField(default=False)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    subject = models.CharField(max_length=20, choices=SUBJECT_CHOICES, null=True, blank=True, help_text="Academic subject category")
    due_date = models.DateField(null=True, blank=True)
    date = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.task_name} ({'Done' if self.status else 'Pending'})"
