from django.contrib import admin
from .models import Notification

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'recipient', 'sender_name', 'notification_type', 'message_short', 'timestamp', 'is_read']
    list_filter = ['notification_type', 'is_read', 'timestamp']
    search_fields = ['message', 'sender_name', 'recipient__username']

    def message_short(self, obj):
        return obj.message[:60]
    message_short.short_description = 'Message'
