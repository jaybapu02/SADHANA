import math
from django.db import models
from django.conf import settings


def xp_for_level(n):
    return 100 * n * (n + 1) // 2


def get_level_info(xp):
    level = 1
    while True:
        threshold = xp_for_level(level)
        if xp < threshold:
            prev = xp_for_level(level - 1) if level > 1 else 0
            return level, threshold - prev, xp - prev
        level += 1


class RewardProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='reward_profile'
    )
    xp = models.IntegerField(default=0)
    coins = models.IntegerField(default=0)
    total_tasks_completed = models.IntegerField(default=0)
    total_focus_sessions = models.IntegerField(default=0)
    current_streak = models.IntegerField(default=0, help_text="Consecutive days with at least one study session")
    longest_streak = models.IntegerField(default=0)
    last_active_date = models.DateField(null=True, blank=True)
    all_tasks_done_streak = models.IntegerField(default=0, help_text="Consecutive days all tasks completed")
    best_all_tasks_done_streak = models.IntegerField(default=0)
    weekly_goals_met = models.IntegerField(default=0)
    monthly_goals_met = models.IntegerField(default=0)
    tasks_completed_before_8am = models.IntegerField(default=0)

    @property
    def level(self):
        return get_level_info(self.xp)[0]

    @property
    def level_progress(self):
        _, needed, current = get_level_info(self.xp)
        return round((current / needed) * 100) if needed > 0 else 100

    @property
    def xp_for_next_level(self):
        _, needed, _ = get_level_info(self.xp)
        return needed

    @property
    def xp_in_current_level(self):
        _, _, current = get_level_info(self.xp)
        return current

    def __str__(self):
        return f"{self.user.username} - Lv.{self.level} ({self.xp}XP)"

    class Meta:
        ordering = ['-xp']


class Badge(models.Model):
    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=10, help_text="Emoji or icon character")
    xp_reward = models.IntegerField(default=0)
    coin_reward = models.IntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class BadgeAward(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='badge_awards'
    )
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name='awards')
    awarded_at = models.DateTimeField(auto_now_add=True)
    is_new = models.BooleanField(default=True)

    class Meta:
        unique_together = ('user', 'badge')
        ordering = ['-awarded_at']

    def __str__(self):
        return f"{self.user.username} - {self.badge.name}"


class Transaction(models.Model):
    class Type(models.TextChoices):
        EARN = 'EARN', 'Earned'
        SPEND = 'SPEND', 'Spent'

    class Source(models.TextChoices):
        TASK_COMPLETE = 'TASK_COMPLETE', 'Task Completed'
        ALL_TASKS_DONE = 'ALL_TASKS_DONE', 'All Daily Tasks Done'
        FOCUS_SESSION = 'FOCUS_SESSION', 'Focus Session Completed'
        STUDY_STREAK = 'STUDY_STREAK', 'Study Streak'
        WEEKLY_GOAL = 'WEEKLY_GOAL', 'Weekly Goal Achieved'
        MONTHLY_GOAL = 'MONTHLY_GOAL', 'Monthly Goal Achieved'
        BADGE_REWARD = 'BADGE_REWARD', 'Badge Earned'
        LEVEL_UP = 'LEVEL_UP', 'Level Up'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='reward_transactions'
    )
    transaction_type = models.CharField(max_length=10, choices=Type.choices, default=Type.EARN)
    xp_amount = models.IntegerField(default=0)
    coin_amount = models.IntegerField(default=0)
    source = models.CharField(max_length=50, choices=Source.choices)
    description = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.username} - {self.source} ({self.xp_amount}XP, {self.coin_amount} coins)"
