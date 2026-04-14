from django.db import models
from django.conf import settings

class Task(models.Model):
    child = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tasks')
    task_name = models.CharField(max_length=255)
    status = models.BooleanField(default=False)
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.task_name} ({self.status})"
