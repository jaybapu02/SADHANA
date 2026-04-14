from django.db import models
from django.conf import settings

class Notification(models.Model):
    parent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications', limit_choices_to={'role': 'PARENT'})
    child = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='caused_notifications')
    message = models.TextField()
    time = models.DateTimeField(auto_now_add=True)
    status = models.BooleanField(default=False, help_text="False = Unread, True = Read")

    def __str__(self):
        return f"To {self.parent.username} - {self.message[:20]}"
