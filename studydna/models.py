from django.db import models
from django.conf import settings


class StudyDNAProfile(models.Model):
    child = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='studydna_profile'
    )

    best_study_time_label = models.CharField(max_length=100, default='', blank=True)
    favorite_subject = models.CharField(max_length=100, default='', blank=True)
    weakest_subject = models.CharField(max_length=100, default='', blank=True)
    average_focus_duration_minutes = models.FloatField(default=0.0)
    most_productive_day = models.CharField(max_length=20, default='', blank=True)
    least_productive_day = models.CharField(max_length=20, default='', blank=True)
    common_distraction_time = models.CharField(max_length=100, default='', blank=True)

    productivity_score = models.FloatField(default=0.0)
    consistency_score = models.FloatField(default=0.0)
    consistency_improvement = models.FloatField(default=0.0)
    study_streak_days = models.IntegerField(default=0)
    longest_streak_days = models.IntegerField(default=0)

    weekly_focus_data = models.TextField(default='[]')
    weekly_task_data = models.TextField(default='[]')
    monthly_focus_trend = models.TextField(default='[]')
    monthly_task_trend = models.TextField(default='[]')

    recommendations = models.TextField(default='[]')
    subject_data_json = models.TextField(default='{}')
    missed_deadlines_json = models.TextField(default='{}')
    parent_tasks_json = models.TextField(default='{}')
    reward_insights_json = models.TextField(default='{}')
    goal_progress_json = models.TextField(default='{}')
    focus_stats_json = models.TextField(default='{}')

    last_analyzed = models.DateTimeField(auto_now=True)
    data_points = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Study DNA Profile"
        verbose_name_plural = "Study DNA Profiles"

    def __str__(self):
        return f"StudyDNA: {self.child.username}"
