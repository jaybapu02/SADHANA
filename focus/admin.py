from django.contrib import admin
from .models import FocusSession, WhitelistItem, BlacklistItem, AccessRequest, FocusAnalytics

@admin.register(FocusSession)
class FocusSessionAdmin(admin.ModelAdmin):
    list_display = ('child', 'planned_duration', 'actual_focus_seconds', 'status', 'start_time', 'end_time')
    list_filter = ('status', 'start_time')
    search_fields = ('child__username',)

@admin.register(WhitelistItem)
class WhitelistItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_default', 'created_by', 'created_at')
    list_filter = ('category', 'is_default')
    search_fields = ('name',)

@admin.register(BlacklistItem)
class BlacklistItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_default', 'created_by', 'created_at')
    list_filter = ('category', 'is_default')
    search_fields = ('name',)

@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display = ('child', 'parent', 'blacklist_item', 'status', 'requested_at', 'responded_at')
    list_filter = ('status', 'requested_at')
    search_fields = ('child__username', 'parent__username', 'blacklist_item__name')

@admin.register(FocusAnalytics)
class FocusAnalyticsAdmin(admin.ModelAdmin):
    list_display = ('child', 'period', 'period_start', 'period_end', 'total_focus_seconds', 'completed_sessions')
    list_filter = ('period',)
    search_fields = ('child__username',)
