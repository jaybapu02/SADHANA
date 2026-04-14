from django.contrib import admin
from .models import StudySession, Goal

@admin.register(StudySession)
class StudySessionAdmin(admin.ModelAdmin):
    list_display = ('child', 'start_time', 'duration', 'distraction_time', 'focus_score')
    list_filter = ('start_time',)
    search_fields = ('child__username',)

admin.site.register(Goal)
