from django.urls import path
from . import views

urlpatterns = [
    path('', views.child_dashboard, name='studydna_dashboard'),
    path('api/refresh/', views.api_refresh_insights, name='studydna_api_refresh'),
    path('api/insights/', views.api_get_insights, name='studydna_api_insights'),
    path('parent/<int:child_id>/', views.parent_dashboard, name='studydna_parent'),
]
