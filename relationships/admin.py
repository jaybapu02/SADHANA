from django.contrib import admin
from .models import ConnectionRequest

@admin.register(ConnectionRequest)
class ConnectionRequestAdmin(admin.ModelAdmin):
    list_display = ('parent', 'child', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('parent__username', 'child__username')
