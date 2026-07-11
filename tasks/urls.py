from django.urls import path
from . import views

urlpatterns = [
    path('', views.todo_dashboard, name='todo_dashboard'),
    path('add/', views.add_task, name='add_task'),
    path('edit/<int:task_id>/', views.edit_task, name='edit_task'),
    path('toggle/<int:task_id>/', views.toggle_task, name='toggle_task'),
    path('delete/<int:task_id>/', views.delete_task, name='delete_task'),
    path('parent/assign/<int:child_id>/', views.parent_assign_task, name='parent_assign_task'),
    path('parent/child/<int:child_id>/', views.parent_child_todo, name='parent_child_todo'),
    path('parent/edit/<int:task_id>/', views.parent_edit_task, name='parent_edit_task'),
    path('parent/remove/<int:task_id>/', views.parent_remove_task, name='parent_remove_task'),
    path('parent/appreciation/<int:child_id>/', views.parent_send_appreciation, name='parent_send_appreciation'),
]
