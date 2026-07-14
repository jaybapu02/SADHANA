from django.urls import path
from . import views

urlpatterns = [
    # Child: Focus session UI
    path('', views.focus_session_view, name='focus_session'),

    # Child: API endpoints
    path('api/start-session/', views.api_start_session, name='api_start_session'),
    path('api/start-study-session/', views.api_start_study_session, name='api_start_study_session'),
    path('api/end-session/', views.api_end_session, name='api_end_session'),
    path('api/active-session/', views.api_active_session, name='api_active_session'),
    path('api/request-access/', views.api_request_access, name='api_request_access'),
    path('api/check-whitelist/', views.api_check_whitelist, name='api_check_whitelist'),
    path('api/check-blacklist/', views.api_check_blacklist, name='api_check_blacklist'),
    path('api/child-history/', views.api_child_focus_history, name='api_child_focus_history'),
    path('api/approved-apps/', views.api_get_approved_apps, name='api_get_approved_apps'),
    path('api/mark-app-usage/', views.api_mark_app_usage, name='api_mark_app_usage'),

    # Parent: Dashboard & management
    path('parent/', views.parent_focus_dashboard, name='parent_focus_dashboard'),
    path('parent/api/requests/', views.api_get_access_requests, name='api_get_access_requests'),
    path('parent/api/approve/<int:request_id>/', views.api_approve_request, name='api_approve_request'),
    path('parent/api/reject/<int:request_id>/', views.api_reject_request, name='api_reject_request'),
    path('parent/api/auto-expire/', views.api_auto_expire_requests, name='api_auto_expire_requests'),
    path('parent/api/analytics/<int:child_id>/', views.api_focus_analytics, name='api_focus_analytics'),
    path('parent/api/sessions/<int:child_id>/', views.api_parent_child_sessions, name='api_parent_child_sessions'),

    # Parent: Whitelist / Blacklist management
    path('parent/api/whitelist/', views.api_list_whitelist, name='api_list_whitelist'),
    path('parent/api/whitelist/add/', views.api_add_whitelist, name='api_add_whitelist'),
    path('parent/api/whitelist/remove/<int:item_id>/', views.api_remove_whitelist, name='api_remove_whitelist'),
    path('parent/api/blacklist/', views.api_list_blacklist, name='api_list_blacklist'),
    path('parent/api/blacklist/add/', views.api_add_blacklist, name='api_add_blacklist'),
    path('parent/api/blacklist/remove/<int:item_id>/', views.api_remove_blacklist, name='api_remove_blacklist'),
]
