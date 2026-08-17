from django.contrib import admin
from .models import (
    FocusSession, WhitelistItem, BlacklistItem, AccessRequest, FocusAnalytics,
    FocusDevice, FocusLockEvent,
)

@admin.register(FocusSession)
class FocusSessionAdmin(admin.ModelAdmin):
    list_display = ('child', 'planned_duration', 'actual_focus_seconds', 'status', 'lock_enabled', 'start_time', 'end_time')
    list_filter = ('status', 'lock_enabled', 'start_time')
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

@admin.register(FocusDevice)
class FocusDeviceAdmin(admin.ModelAdmin):
    list_display = ('child', 'name', 'device_type', 'is_active', 'last_seen', 'created_at')
    list_filter = ('device_type', 'is_active')
    search_fields = ('child__username', 'name')

@admin.register(FocusLockEvent)
class FocusLockEventAdmin(admin.ModelAdmin):
    list_display = ('child', 'event_type', 'severity', 'detail', 'source', 'notified', 'created_at')
    list_filter = ('event_type', 'severity', 'notified')
    search_fields = ('child__username', 'detail')

    def source(self, obj):
        return obj.device.name if obj.device else 'Web'
    source.short_description = 'Source'
