from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.chat_page, name="chat_page"),
    path("api/conversations/", views.api_conversations, name="api_conversations"),
    path("api/conversations/<int:conversation_id>/messages/", views.api_messages, name="api_messages"),
    path("api/conversations/<int:conversation_id>/mark-read/", views.api_mark_read, name="api_mark_read"),
    path("api/conversations/<int:conversation_id>/send/", views.api_send, name="api_send"),
    path("api/unread-count/", views.api_unread_count, name="api_unread_count"),
    path("api/quick/<int:other_user_id>/", views.api_quick_conversation, name="api_quick_conversation"),
]