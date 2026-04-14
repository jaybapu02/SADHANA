from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('role', 'child_id')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (None, {'fields': ('role', 'child_id')}),
    )
    list_display = ['username', 'email', 'role', 'child_id', 'is_staff']

admin.site.register(User, CustomUserAdmin)
