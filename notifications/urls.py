from django.urls import path
from . import views

urlpatterns = [
    path('', views.notification_list, name='notification_list'),
    path('api/list/', views.api_notifications, name='api_notifications'),
    path('api/unread-count/', views.api_unread_count, name='api_unread_count'),
    path('api/mark-read/<int:notif_id>/', views.api_mark_read, name='api_mark_read'),
    path('api/mark-all-read/', views.api_mark_all_read, name='api_mark_all_read'),
    path('api/delete/<int:notif_id>/', views.api_delete_notification, name='api_delete_notification'),
]
