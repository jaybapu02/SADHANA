"""
ASGI config for sadhana project.

Routes HTTP (WSGI-compatible) and WebSocket traffic to Django Channels.
Run with:  daphne sadhana.asgi:application
or simply: python manage.py runserver  (daphne is in INSTALLED_APPS)
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sadhana.settings")

# Populate django.conf settings before importing channels routing.
application = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from chat.routing import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": application,
        "websocket": AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        ),
    }
)