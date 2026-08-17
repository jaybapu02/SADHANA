from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('admin-panel/', include('admin_panel.urls')),
    path('', include('users.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('study/', include('study.urls')),
    path('tasks/', include('tasks.urls')),
    path('notifications/', include('notifications.urls')),
    path('relationships/', include('relationships.urls')),
    path('focus/', include('focus.urls')),
    path('rewards/', include('rewards.urls')),
    path('studydna/', include('studydna.urls')),
    path('chat/', include('chat.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
