from django.db import migrations


BADGES = [
    {'code': 'early-bird', 'name': 'Early Bird', 'description': 'Completed a task before 8 AM', 'icon': '🌅', 'xp_reward': 25, 'coin_reward': 10},
    {'code': 'study-warrior', 'name': 'Study Warrior', 'description': 'Completed 100 tasks overall', 'icon': '⚔️', 'xp_reward': 200, 'coin_reward': 100},
    {'code': 'task-champion', 'name': 'Task Champion', 'description': 'Completed all tasks for 7 days in a row', 'icon': '🏆', 'xp_reward': 150, 'coin_reward': 75},
    {'code': 'focus-master', 'name': 'Focus Master', 'description': 'Completed 50 focus sessions', 'icon': '🧘', 'xp_reward': 250, 'coin_reward': 125},
    {'code': 'goal-achiever', 'name': 'Goal Achiever', 'description': 'Achieved a weekly goal', 'icon': '🎯', 'xp_reward': 100, 'coin_reward': 50},
    {'code': 'discipline-master', 'name': 'Discipline Master', 'description': 'Completed 90%+ of monthly tasks', 'icon': '💎', 'xp_reward': 300, 'coin_reward': 150},
    {'code': 'consistency-hero', 'name': 'Consistency Hero', 'description': 'Maintained a 30+ day study streak', 'icon': '🔥', 'xp_reward': 500, 'coin_reward': 250},
]


def seed_badges(apps, schema_editor):
    Badge = apps.get_model('rewards', 'Badge')
    for badge in BADGES:
        Badge.objects.get_or_create(code=badge['code'], defaults=badge)


def reverse_badges(apps, schema_editor):
    Badge = apps.get_model('rewards', 'Badge')
    Badge.objects.filter(code__in=[b['code'] for b in BADGES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("rewards", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_badges, reverse_badges),
    ]
