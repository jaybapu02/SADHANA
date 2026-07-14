from django.db import transaction as db_transaction
from django.utils import timezone
from .models import RewardProfile, Badge, BadgeAward, Transaction
from notifications.services import NotificationService
from relationships.models import ConnectionRequest


def get_or_create_profile(user):
    profile, _ = RewardProfile.objects.get_or_create(user=user)
    return profile


def award_xp(user, xp, coins, source, description):
    profile = get_or_create_profile(user)
    old_level = profile.level

    with db_transaction.atomic():
        profile.xp += xp
        profile.coins += coins
        profile.save()

        Transaction.objects.create(
            user=user,
            transaction_type=Transaction.Type.EARN,
            xp_amount=xp,
            coin_amount=coins,
            source=source,
            description=description,
        )

    new_level = profile.level
    if new_level > old_level:
        _handle_level_up(user, profile, new_level)

    return profile


def _handle_level_up(user, profile, new_level):
    bonus_xp = new_level * 5
    bonus_coins = new_level * 3
    profile.xp += bonus_xp
    profile.coins += bonus_coins
    profile.save(update_fields=['xp', 'coins'])

    Transaction.objects.create(
        user=user,
        transaction_type=Transaction.Type.EARN,
        xp_amount=bonus_xp,
        coin_amount=bonus_coins,
        source=Transaction.Source.LEVEL_UP,
        description=f"Reached Level {new_level}!",
    )

    parents = ConnectionRequest.objects.filter(
        child=user, status='ACCEPTED'
    ).select_related('parent')
    for conn in parents:
        NotificationService._create(
            recipient=conn.parent,
            sender=user,
            sender_name=user.username,
            notification_type='LEVEL_UP',
            message=f"Your child \"{user.username}\" reached Level {new_level}!",
        )


def check_and_award_badge(user, badge_code):
    try:
        badge = Badge.objects.get(code=badge_code)
    except Badge.DoesNotExist:
        return None

    awarded, created = BadgeAward.objects.get_or_create(user=user, badge=badge)
    if created:
        award_xp(
            user, badge.xp_reward, badge.coin_reward,
            Transaction.Source.BADGE_REWARD,
            f"Earned badge: {badge.name}",
        )
        parents = ConnectionRequest.objects.filter(
            child=user, status='ACCEPTED'
        ).select_related('parent')
        for conn in parents:
            NotificationService._create(
                recipient=conn.parent,
                sender=user,
                sender_name=user.username,
                notification_type='BADGE_EARNED',
                message=f"Your child \"{user.username}\" earned the \"{badge.name}\" badge!",
            )
        return badge
    return None


def update_streak(user, profile=None):
    if profile is None:
        profile = get_or_create_profile(user)
    today = timezone.now().date()

    if profile.last_active_date == today:
        return profile

    if profile.last_active_date == today - timezone.timedelta(days=1):
        profile.current_streak += 1
        if profile.current_streak > profile.longest_streak:
            profile.longest_streak = profile.current_streak
    else:
        profile.current_streak = 1

    profile.last_active_date = today
    profile.save(update_fields=['current_streak', 'longest_streak', 'last_active_date'])

    if profile.current_streak in (7, 14, 21, 30, 60, 90, 365):
        xp = profile.current_streak * 15
        coins = profile.current_streak * 7
        award_xp(
            user, xp, coins,
            Transaction.Source.STUDY_STREAK,
            f"{profile.current_streak}-day study streak!",
        )

    return profile


def on_task_completed(user):
    profile = get_or_create_profile(user)
    profile.total_tasks_completed += 1
    profile.save(update_fields=['total_tasks_completed'])

    award_xp(user, 10, 5, Transaction.Source.TASK_COMPLETE, "Completed a task")

    now = timezone.now()
    if now.hour < 8:
        profile.tasks_completed_before_8am += 1
        profile.save(update_fields=['tasks_completed_before_8am'])
        if profile.tasks_completed_before_8am >= 1:
            check_and_award_badge(user, 'early-bird')

    if profile.total_tasks_completed >= 100:
        check_and_award_badge(user, 'study-warrior')

    return profile


def on_all_tasks_done(user):
    award_xp(user, 50, 25, Transaction.Source.ALL_TASKS_DONE, "Completed all daily tasks!")

    profile = get_or_create_profile(user)
    profile.all_tasks_done_streak += 1
    if profile.all_tasks_done_streak > profile.best_all_tasks_done_streak:
        profile.best_all_tasks_done_streak = profile.all_tasks_done_streak
    profile.save(update_fields=['all_tasks_done_streak', 'best_all_tasks_done_streak'])

    if profile.all_tasks_done_streak >= 7:
        check_and_award_badge(user, 'task-champion')


def on_task_uncompleted(user):
    profile = get_or_create_profile(user)
    profile.all_tasks_done_streak = 0
    profile.save(update_fields=['all_tasks_done_streak'])


def on_focus_session_completed(user):
    award_xp(user, 20, 10, Transaction.Source.FOCUS_SESSION, "Completed a focus session")

    profile = get_or_create_profile(user)
    profile.total_focus_sessions += 1
    profile.save(update_fields=['total_focus_sessions'])

    if profile.total_focus_sessions >= 50:
        check_and_award_badge(user, 'focus-master')


def on_weekly_goal_achieved(user):
    award_xp(user, 75, 30, Transaction.Source.WEEKLY_GOAL, "Achieved weekly goal!")

    profile = get_or_create_profile(user)
    profile.weekly_goals_met += 1
    profile.save(update_fields=['weekly_goals_met'])

    check_and_award_badge(user, 'goal-achiever')


def on_monthly_goal_achieved(user):
    award_xp(user, 150, 75, Transaction.Source.MONTHLY_GOAL, "Achieved monthly goal!")

    profile = get_or_create_profile(user)
    profile.monthly_goals_met += 1
    profile.save(update_fields=['monthly_goals_met'])


def check_monthly_discipline(user):
    from django.utils import timezone
    from tasks.models import Task

    today = timezone.now().date()
    month_start = today.replace(day=1)
    month_tasks = Task.objects.filter(child=user, date__gte=month_start, date__lte=today)
    total = month_tasks.count()
    if total > 0:
        completed = month_tasks.filter(status=True).count()
        pct = (completed / total) * 100
        if pct >= 90:
            check_and_award_badge(user, 'discipline-master')

    if profile := getattr(user, 'reward_profile', None):
        if profile.current_streak >= 30:
            check_and_award_badge(user, 'consistency-hero')


def get_leaderboard(limit=20):
    return RewardProfile.objects.select_related('user').filter(
        user__role='CHILD'
    ).order_by('-xp')[:limit]


def get_reward_context(user):
    profile = get_or_create_profile(user)
    badges = []
    all_badges = Badge.objects.all()
    earned_codes = set(
        BadgeAward.objects.filter(user=user).values_list('badge__code', flat=True)
    )
    for badge in all_badges:
        badges.append({
            'badge': badge,
            'earned': badge.code in earned_codes,
        })

    recent_transactions = Transaction.objects.filter(user=user)[:10]

    return {
        'profile': profile,
        'badges': badges,
        'recent_transactions': recent_transactions,
        'level': profile.level,
        'level_progress': profile.level_progress,
        'xp_for_next_level': profile.xp_for_next_level,
        'xp_in_current_level': profile.xp_in_current_level,
    }
