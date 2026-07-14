from django.contrib import admin
from .models import RewardProfile, Badge, BadgeAward, Transaction


@admin.register(RewardProfile)
class RewardProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'xp', 'coins', 'level', 'current_streak', 'total_tasks_completed', 'total_focus_sessions')
    search_fields = ('user__username',)
    list_filter = ('last_active_date',)


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'icon', 'xp_reward', 'coin_reward')
    prepopulated_fields = {'code': ('name',)}


@admin.register(BadgeAward)
class BadgeAwardAdmin(admin.ModelAdmin):
    list_display = ('user', 'badge', 'awarded_at')
    list_filter = ('awarded_at',)
    search_fields = ('user__username', 'badge__name')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'source', 'xp_amount', 'coin_amount', 'timestamp')
    list_filter = ('source', 'timestamp')
    search_fields = ('user__username', 'description')
