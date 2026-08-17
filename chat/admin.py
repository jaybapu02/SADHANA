from django.contrib import admin

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("sender", "receiver", "text", "attachment", "is_read", "is_delivered", "is_deleted", "created_at")
    readonly_fields = ("sender", "receiver", "created_at")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "parent", "child", "last_message_at")
    search_fields = ("parent__username", "child__username")
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "receiver", "is_read", "is_delivered", "is_deleted", "attachment", "created_at")
    list_filter = ("is_read", "is_delivered", "is_deleted", "attachment_type", "created_at")
    search_fields = ("sender__username", "receiver__username", "text")