from django.db import models
from django.conf import settings

class StudySession(models.Model):
    child = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='study_sessions')
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    duration = models.IntegerField(default=0, help_text="Total session time in minutes")
    break_time = models.IntegerField(default=0, help_text="Total break time taken in minutes")
    distraction_time = models.IntegerField(default=0, help_text="Total distracted time in seconds")
    focus_score = models.FloatField(default=0.0)
    
    def save(self, *args, **kwargs):
        # Calculate focus score before saving if duration is available
        if self.duration > 0:
            total_study_seconds = self.duration * 60
            if total_study_seconds + self.distraction_time > 0:
                score = (total_study_seconds / (total_study_seconds + self.distraction_time)) * 100
                self.focus_score = round(score, 2)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.child.username} - {self.start_time.strftime('%Y-%m-%d %H:%M')}"

class Goal(models.Model):
    child = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='study_goal')
    daily_goal = models.IntegerField(default=120, help_text="Daily study goal in minutes")
    weekly_goal = models.IntegerField(default=600, help_text="Weekly study goal in minutes")

    def __str__(self):
        return f"Goals for {self.child.username}"
