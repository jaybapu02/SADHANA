from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='admin_dashboard'),

    # Users
    path('users/', views.list_users, name='admin_list_users'),
    path('users/<int:user_id>/edit/', views.edit_user, name='admin_edit_user'),
    path('users/<int:user_id>/delete/', views.delete_user, name='admin_delete_user'),

    # Study Sessions
    path('sessions/', views.list_sessions, name='admin_list_sessions'),
    path('sessions/<int:session_id>/delete/', views.delete_session, name='admin_delete_session'),

    # Goals
    path('goals/', views.list_goals, name='admin_list_goals'),
    path('goals/<int:goal_id>/edit/', views.edit_goal, name='admin_edit_goal'),
    path('goals/<int:goal_id>/delete/', views.delete_goal, name='admin_delete_goal'),

    # Tasks
    path('tasks/', views.list_tasks, name='admin_list_tasks'),
    path('tasks/<int:task_id>/edit/', views.edit_task, name='admin_edit_task'),
    path('tasks/<int:task_id>/delete/', views.delete_task, name='admin_delete_task'),

    # Notifications
    path('notifications/', views.list_notifications, name='admin_list_notifications'),
    path('notifications/<int:notif_id>/delete/', views.delete_notification, name='admin_delete_notification'),

    # Connection Requests
    path('connections/', views.list_connections, name='admin_list_connections'),
    path('connections/<int:conn_id>/edit/', views.edit_connection, name='admin_edit_connection'),
    path('connections/<int:conn_id>/delete/', views.delete_connection, name='admin_delete_connection'),
]
