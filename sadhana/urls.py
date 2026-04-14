from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('users.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('study/', include('study.urls')),
    path('tasks/', include('tasks.urls')),
    # path('notifications/', include('notifications.urls')),
    path('relationships/', include('relationships.urls')),
]
