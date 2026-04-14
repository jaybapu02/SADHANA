from django.urls import path
from . import views

urlpatterns = [
    path('router/', views.dashboard_router, name='dashboard_router'),
    path('parent/', views.parent_dashboard, name='parent_dashboard'),
    path('parent/child/<int:child_id>/', views.parent_child_stats, name='parent_child_stats'),
    path('child/', views.child_dashboard, name='child_dashboard'),
]
