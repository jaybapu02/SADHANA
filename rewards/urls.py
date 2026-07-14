from django.urls import path
from . import views

urlpatterns = [
    path('leaderboard/', views.leaderboard_view, name='reward_leaderboard'),
    path('api/my-rewards/', views.api_my_rewards, name='api_my_rewards'),
    path('api/check-new-badges/', views.api_check_new_badges, name='api_check_new_badges'),
    path('api/check-level-up/', views.api_check_level_up, name='api_check_level_up'),
    path('parent/<int:child_id>/', views.parent_reward_view, name='parent_reward_view'),
]
