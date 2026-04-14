from django.urls import path
from . import views

urlpatterns = [
    path('session/', views.study_session, name='study_session'),
    path('save-session/', views.save_session, name='save_session'),
]
