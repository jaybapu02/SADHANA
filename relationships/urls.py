from django.urls import path
from . import views

urlpatterns = [
    path('send-request/', views.send_request, name='send_request'),
    path('respond/<int:request_id>/<str:action>/', views.respond_request, name='respond_request'),
]
