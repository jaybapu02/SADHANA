import json
import math
from datetime import timedelta
from collections import defaultdict

from django.db.models import Sum
from django.utils import timezone

from focus.models import FocusSession
from tasks.models import Task
from rewards.models import RewardProfile, Badge, BadgeAward, Transaction
from study.models import Goal
from .models import StudyDNAProfile

SUBJECT_LABELS = dict(Task.SUBJECT_CHOICES)


def get_or_create_profile(user):
    profile, _ = StudyDNAProfile.objects.get_or_create(child=user)
    return profile


def analyze_child(child):
    profile = get_or_create_profile(child)
    today = timezone.now().date()
    cutoff_90 = today - timedelta(days=90)
    cutoff_30 = today - timedelta(days=30)
    cutoff_60 = today - timedelta(days=60)

    sessions_90 = FocusSession.objects.filter(
        child=child,
        start_time__date__gte=cutoff_90
    ).exclude(status='ACTIVE')

    sessions_30 = sessions_90.filter(start_time__date__gte=cutoff_30)
    completed_90 = sessions_90.filter(status='COMPLETED')
    completed_30 = sessions_30.filter(status='COMPLETED')
    interrupted_90 = sessions_90.filter(status='INTERRUPTED')

    tasks_90 = Task.objects.filter(child=child, date__gte=cutoff_90)
    tasks_30 = tasks_90.filter(date__gte=cutoff_30)

    reward_profile = RewardProfile.objects.filter(user=child).first()

    total_data = sessions_90.count() + tasks_90.count()

    best_study_time_label, best_study_hour = _analyze_best_study_time(completed_90)
    favorite_subj, weakest_subj = _analyze_subjects(tasks_90)
    avg_focus_minutes = _analyze_avg_focus_duration(completed_90)
    most_prod_day, least_prod_day = _analyze_productivity_days(sessions_90, tasks_90)
    distraction_time = _analyze_common_distractions(interrupted_90)
    consistency_improvement = _analyze_consistency_improvement(sessions_90, cutoff_30, cutoff_60)
    prod_score = _compute_productivity_score(completed_90, interrupted_90, tasks_90, sessions_90)
    cons_score = _compute_consistency_score(child, sessions_90, tasks_90, reward_profile)

    streak = reward_profile.current_streak if reward_profile else 0
    longest_streak = reward_profile.longest_streak if reward_profile else 0

    weekly_focus = _get_weekly_focus_data(sessions_90, today)
    weekly_tasks = _get_weekly_task_data(tasks_90, today)
    monthly_focus = _get_monthly_focus_trend(sessions_90, today)
    monthly_tasks = _get_monthly_task_trend(tasks_90, today)

    missed_deadlines = _analyze_missed_deadlines(tasks_90)
    parent_task_data = _analyze_parent_task_completion(tasks_90)
    reward_insights = _get_reward_insights(reward_profile, child)
    goal_progress = _analyze_goal_progress(child)

    subject_data = _get_subject_data(tasks_90)
    recommendations = _generate_recommendations(
        child, best_study_time_label, avg_focus_minutes,
        favorite_subj, weakest_subj, most_prod_day,
        least_prod_day, distraction_time, prod_score,
        cons_score, streak, consistency_improvement,
        reward_profile, completed_90, interrupted_90,
        missed_deadlines, parent_task_data
    )

    profile.best_study_time_label = best_study_time_label
    profile.favorite_subject = favorite_subj
    profile.weakest_subject = weakest_subj
    profile.average_focus_duration_minutes = avg_focus_minutes
    profile.most_productive_day = most_prod_day
    profile.least_productive_day = least_prod_day
    profile.common_distraction_time = distraction_time
    profile.productivity_score = prod_score
    profile.consistency_score = cons_score
    profile.consistency_improvement = consistency_improvement
    profile.study_streak_days = streak
    profile.longest_streak_days = longest_streak
    profile.weekly_focus_data = json.dumps(weekly_focus)
    profile.weekly_task_data = json.dumps(weekly_tasks)
    profile.monthly_focus_trend = json.dumps(monthly_focus)
    profile.monthly_task_trend = json.dumps(monthly_tasks)
    profile.recommendations = json.dumps(recommendations)
    profile.subject_data_json = json.dumps(subject_data)
    profile.missed_deadlines_json = json.dumps(missed_deadlines)
    profile.parent_tasks_json = json.dumps(parent_task_data)
    profile.reward_insights_json = json.dumps(reward_insights)
    profile.goal_progress_json = json.dumps(goal_progress)
    profile.data_points = total_data
    profile.save()

    return profile


def _analyze_best_study_time(completed_sessions):
    hourly = defaultdict(lambda: {'count': 0, 'total_focus': 0, 'total_distraction': 0})
    for s in completed_sessions:
        hour = s.start_time.hour
        hourly[hour]['count'] += 1
        hourly[hour]['total_focus'] += s.actual_focus_seconds
        hourly[hour]['total_distraction'] += s.distraction_seconds

    if not hourly:
        return 'Not enough data', None

    best_hour = max(hourly.keys(), key=lambda h: _hour_score(hourly[h]))
    best_hour_end = (best_hour + 2) % 24

    def fmt(h):
        if h == 0:
            return '12 AM'
        elif h < 12:
            return f'{h} AM'
        elif h == 12:
            return '12 PM'
        else:
            return f'{h - 12} PM'

    label = f'{fmt(best_hour)} - {fmt(best_hour_end)}'

    if 5 <= best_hour < 12:
        time_category = 'morning'
    elif 12 <= best_hour < 17:
        time_category = 'afternoon'
    elif 17 <= best_hour < 21:
        time_category = 'evening'
    else:
        time_category = 'night'

    summary = f'Your peak productivity is in the {time_category} ({label}).'
    return summary, best_hour


def _hour_score(data):
    if data['count'] == 0:
        return 0
    total = data['total_focus'] + data['total_distraction']
    if total == 0:
        return 0
    avg_focus_ratio = data['total_focus'] / total
    return avg_focus_ratio * math.log1p(data['count'])


def _analyze_subjects(tasks_90):
    subject_counts = {}
    for task in tasks_90.filter(status=True):
        subj = task.subject or 'OTHER'
        label = SUBJECT_LABELS.get(subj, subj)
        subject_counts[label] = subject_counts.get(label, 0) + 1

    if not subject_counts:
        return 'No subject data', 'No subject data'

    favorite = max(subject_counts, key=subject_counts.get)

    weak_counts = {}
    for task in tasks_90:
        subj = task.subject or 'OTHER'
        label = SUBJECT_LABELS.get(subj, subj)
        if label not in weak_counts:
            weak_counts[label] = {'total': 0, 'done': 0}
        weak_counts[label]['total'] += 1
        if task.status:
            weak_counts[label]['done'] += 1

    candidates = {k: v for k, v in weak_counts.items() if v['total'] >= 2}
    if not candidates:
        return favorite, favorite

    weakest = min(candidates, key=lambda k: candidates[k]['done'] / candidates[k]['total'])
    return favorite, weakest


def _analyze_avg_focus_duration(completed_sessions):
    if not completed_sessions.exists():
        return 0.0
    total = completed_sessions.aggregate(Sum('actual_focus_seconds'))['actual_focus_seconds__sum'] or 0
    count = completed_sessions.count()
    if count == 0:
        return 0.0
    return round((total / count) / 60, 1)


def _analyze_productivity_days(sessions_90, tasks_90):
    days = list(range(7))
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    day_scores = {d: {'focus_time': 0, 'completed_sessions': 0, 'total_sessions': 0, 'task_done': 0, 'task_total': 0} for d in days}

    for s in sessions_90:
        d = s.start_time.weekday()
        day_scores[d]['focus_time'] += s.actual_focus_seconds
        day_scores[d]['total_sessions'] += 1
        if s.status == 'COMPLETED':
            day_scores[d]['completed_sessions'] += 1

    for t in tasks_90:
        d = t.date.weekday()
        if d in day_scores:
            day_scores[d]['task_total'] += 1
            if t.status:
                day_scores[d]['task_done'] += 1

    composites = {}
    for d in days:
        data = day_scores[d]
        focus_score = (data['completed_sessions'] / max(data['total_sessions'], 1)) * 100
        task_score = (data['task_done'] / max(data['task_total'], 1)) * 100
        time_score = min(data['focus_time'] / 3600, 4) / 4 * 100
        composites[d] = (focus_score * 0.35 + task_score * 0.35 + time_score * 0.30)

    if not any(v > 0 for v in composites.values()):
        return 'Insufficient data', 'Insufficient data'

    best = max(composites, key=composites.get)
    worst = min(composites, key=composites.get)
    return day_names[best], day_names[worst]


def _analyze_common_distractions(interrupted_sessions):
    if not interrupted_sessions.exists():
        return 'No interruptions recorded'

    hourly = defaultdict(int)
    for s in interrupted_sessions:
        hour = s.start_time.hour
        for h in range(hour, min(hour + 2, 25)):
            hourly[h] += 1

    if not hourly:
        return 'No interruption pattern detected'

    peak_hour = max(hourly, key=hourly.get)
    peak_hour_end = (peak_hour + 2) % 24

    def fmt(h):
        if h == 0:
            return '12 AM'
        elif h < 12:
            return f'{h} AM'
        elif h == 12:
            return '12 PM'
        else:
            return f'{h - 12} PM'

    total_interrupted = interrupted_sessions.count()
    peak_count = hourly[peak_hour]
    pct = round((peak_count / total_interrupted) * 100)

    return f'Most interruptions occur between {fmt(peak_hour)} - {fmt(peak_hour_end)} ({pct}% of interruptions)'


def _analyze_consistency_improvement(sessions_90, cutoff_30, cutoff_60):
    recent_30 = sessions_90.filter(start_time__date__gte=cutoff_30)
    prior_30 = sessions_90.filter(
        start_time__date__gte=cutoff_60,
        start_time__date__lt=cutoff_30
    )

    def avg_focus_score(qs):
        agg = qs.aggregate(
            total_focus=Sum('actual_focus_seconds'),
            total_dist=Sum('distraction_seconds')
        )
        total = (agg['total_focus'] or 0) + (agg['total_dist'] or 0)
        if total == 0:
            return 0
        return ((agg['total_focus'] or 0) / total) * 100

    recent_score = avg_focus_score(recent_30)
    prior_score = avg_focus_score(prior_30)

    if prior_score == 0 and recent_score > 0:
        return 100.0
    if prior_score == 0:
        return 0.0

    change = ((recent_score - prior_score) / prior_score) * 100
    return round(change, 1)


def _compute_productivity_score(completed_90, interrupted_90, tasks_90, sessions_90):
    total_sessions = completed_90.count() + interrupted_90.count()
    completion_rate = (completed_90.count() / max(total_sessions, 1)) * 100

    task_total = tasks_90.count()
    task_done = tasks_90.filter(status=True).count()
    task_rate = (task_done / max(task_total, 1)) * 100

    focus_agg = completed_90.aggregate(
        tf=Sum('actual_focus_seconds'), td=Sum('distraction_seconds')
    )
    tf = focus_agg['tf'] or 0
    td = focus_agg['td'] or 0
    focus_quality = (tf / max(tf + td, 1)) * 100

    days_with_data = sessions_90.dates('start_time', 'day').count()
    freq_score = min((days_with_data / 30) * 100, 100)

    score = (completion_rate * 0.30 + task_rate * 0.30 + focus_quality * 0.20 + freq_score * 0.20)
    return round(min(score, 100), 1)


def _compute_consistency_score(child, sessions_90, tasks_90, reward_profile):
    today = timezone.now().date()
    days_studied = 0
    for i in range(30):
        day = today - timedelta(days=i)
        if sessions_90.filter(start_time__date=day).exists():
            days_studied += 1
    study_freq = (days_studied / 30) * 100

    streak_score = 0
    if reward_profile:
        streak_score = min((reward_profile.current_streak / 30) * 100, 100)

    task_days = 0
    task_done_days = 0
    for i in range(30):
        day = today - timedelta(days=i)
        day_tasks = tasks_90.filter(date=day)
        if day_tasks.exists():
            task_days += 1
            done = day_tasks.filter(status=True).count()
            if done == day_tasks.count():
                task_done_days += 1
    task_consistency = (task_done_days / max(task_days, 1)) * 100 if task_days > 0 else 0

    score = (study_freq * 0.40 + streak_score * 0.30 + task_consistency * 0.30)
    return round(min(score, 100), 1)


def _analyze_missed_deadlines(tasks_90):
    today = timezone.now().date()
    missed = tasks_90.filter(status=False, due_date__lt=today)
    total_with_deadlines = tasks_90.exclude(due_date__isnull=True).count()
    return {
        'missed_count': missed.count(),
        'total_with_deadlines': total_with_deadlines,
        'missed_rate': round((missed.count() / max(total_with_deadlines, 1)) * 100, 1)
    }


def _analyze_parent_task_completion(tasks_90):
    parent_tasks = tasks_90.filter(parent__isnull=False)
    total = parent_tasks.count()
    done = parent_tasks.filter(status=True).count()
    return {
        'total': total,
        'completed': done,
        'pct': round((done / max(total, 1)) * 100)
    }


def _get_reward_insights(reward_profile, child):
    if not reward_profile:
        return {
            'total_xp_earned': 0, 'total_coins_earned': 0,
            'badges_earned': 0, 'total_badges': 0,
            'level': 0, 'current_xp': 0, 'current_coins': 0
        }
    total_xp = Transaction.objects.filter(
        user=child, transaction_type=Transaction.Type.EARN
    ).aggregate(Sum('xp_amount'))['xp_amount__sum'] or 0
    total_coins = Transaction.objects.filter(
        user=child, transaction_type=Transaction.Type.EARN
    ).aggregate(Sum('coin_amount'))['coin_amount__sum'] or 0
    badges_earned = BadgeAward.objects.filter(user=child).count()
    total_badges = Badge.objects.count()
    return {
        'total_xp_earned': total_xp,
        'total_coins_earned': total_coins,
        'badges_earned': badges_earned,
        'total_badges': total_badges,
        'level': reward_profile.level,
        'current_xp': reward_profile.xp,
        'current_coins': reward_profile.coins,
    }


def _analyze_goal_progress(child):
    goal = Goal.objects.filter(child=child).first()
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    week_sessions = FocusSession.objects.filter(
        child=child, start_time__date__gte=week_start, status='COMPLETED'
    )
    week_minutes = (week_sessions.aggregate(Sum('actual_focus_seconds'))['actual_focus_seconds__sum'] or 0) / 60

    month_sessions = FocusSession.objects.filter(
        child=child, start_time__date__gte=month_start, status='COMPLETED'
    )
    month_minutes = (month_sessions.aggregate(Sum('actual_focus_seconds'))['actual_focus_seconds__sum'] or 0) / 60

    return {
        'daily_goal_minutes': goal.daily_goal if goal else 120,
        'weekly_goal_minutes': goal.weekly_goal if goal else 600,
        'weekly_focus_minutes': round(week_minutes, 1),
        'monthly_focus_minutes': round(month_minutes, 1),
    }


def _get_weekly_focus_data(sessions_90, today):
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    result = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_sessions = sessions_90.filter(start_time__date=day)
        total_minutes = sum(
            (s.actual_focus_seconds / 60) for s in day_sessions
        )
        result.append({
            'day': day_names[day.weekday()],
            'minutes': round(total_minutes, 1)
        })
    return result


def _get_weekly_task_data(tasks_90, today):
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    result = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_tasks = tasks_90.filter(date=day)
        total = day_tasks.count()
        done = day_tasks.filter(status=True).count()
        result.append({
            'day': day_names[day.weekday()],
            'total': total,
            'completed': done,
            'pct': round((done / max(total, 1)) * 100)
        })
    return result


def _get_monthly_focus_trend(sessions_90, today):
    result = []
    for i in range(5, -1, -1):
        month = today.month - i
        year = today.year
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        month_sessions = sessions_90.filter(
            start_time__date__year=year,
            start_time__date__month=month
        )
        total_minutes = sum(
            (s.actual_focus_seconds / 60) for s in month_sessions
        )
        result.append({
            'month': f'{year}-{month:02d}',
            'label': timezone.datetime(year, month, 1).strftime('%b'),
            'minutes': round(total_minutes, 1)
        })
    return result


def _get_monthly_task_trend(tasks_90, today):
    result = []
    for i in range(5, -1, -1):
        month = today.month - i
        year = today.year
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        month_tasks = tasks_90.filter(date__year=year, date__month=month)
        total = month_tasks.count()
        done = month_tasks.filter(status=True).count()
        result.append({
            'month': f'{year}-{month:02d}',
            'label': timezone.datetime(year, month, 1).strftime('%b'),
            'total': total,
            'completed': done,
            'pct': round((done / max(total, 1)) * 100)
        })
    return result


def _get_subject_data(tasks_90):
    subject_data = {}
    for task in tasks_90:
        subj = task.subject or 'OTHER'
        label = SUBJECT_LABELS.get(subj, subj)
        if label not in subject_data:
            subject_data[label] = {'total': 0, 'completed': 0}
        subject_data[label]['total'] += 1
        if task.status:
            subject_data[label]['completed'] += 1

    result = []
    for label, data in sorted(subject_data.items()):
        result.append({
            'subject': label,
            'total': data['total'],
            'completed': data['completed'],
            'pct': round((data['completed'] / max(data['total'], 1)) * 100)
        })
    return result


def _generate_recommendations(child, best_time, avg_focus, favorite, weakest,
                               most_prod, least_prod, distraction, prod_score,
                               cons_score, streak, improvement, reward_profile,
                               completed_sessions, interrupted_sessions,
                               missed_deadlines=None, parent_task_data=None):
    recs = []

    if best_time and 'Not enough' not in best_time:
        recs.append({
            'icon': 'clock',
            'text': f'Schedule your most challenging subjects during your peak hours ({best_time.split("(")[-1].rstrip(")") if "(" in best_time else best_time}) for maximum efficiency.',
            'type': 'strategy'
        })

    if avg_focus > 0:
        if avg_focus >= 45:
            recs.append({
                'icon': 'mug-hot',
                'text': f'Your focus sessions average {avg_focus} minutes — that is excellent! Try taking a short 5-minute break after each session to maintain this level.',
                'type': 'positive'
            })
        elif avg_focus >= 25:
            recs.append({
                'icon': 'hourglass',
                'text': f'Your average focus duration is {avg_focus} minutes. Try gradually increasing by 5 minutes each week to build stamina.',
                'type': 'improvement'
            })
        else:
            recs.append({
                'icon': 'bolt',
                'text': f'Your average focus session is {avg_focus} minutes. Try the Pomodoro technique — 25 minutes of focused work followed by a 5-minute break.',
                'type': 'improvement'
            })

    if favorite and 'No subject' not in favorite and weakest and 'No subject' not in weakest:
        if favorite != weakest:
            recs.append({
                'icon': 'book',
                'text': f'{weakest} needs more attention. Try dedicating at least 30 minutes daily to this subject to bring it up to speed.',
                'type': 'action'
            })
            recs.append({
                'icon': 'star',
                'text': f'Your strongest subject is {favorite}. Great job! Use your confidence here to stay motivated when tackling harder subjects.',
                'type': 'positive'
            })

    if most_prod and 'Insufficient' not in most_prod:
        recs.append({
            'icon': 'calendar-check',
            'text': f'{most_prod} is your most productive day. Plan your most important work and difficult subjects on this day.',
            'type': 'strategy'
        })

    if least_prod and 'Insufficient' not in least_prod and least_prod != most_prod:
        recs.append({
            'icon': 'bed',
            'text': f'You tend to complete fewer tasks on {least_prod}s. Consider making this a lighter day or focusing on review rather than new material.',
            'type': 'strategy'
        })

    if distraction and 'No' not in distraction:
        recs.append({
            'icon': 'shield',
            'text': f'You are most likely to lose focus {distraction.replace("Most interruptions occur ", "").lower()}. Try scheduling breaks or easier tasks during this time.',
            'type': 'improvement'
        })

    if streak > 0:
        if streak >= 14:
            recs.append({
                'icon': 'fire',
                'text': f'You are on an impressive {streak}-day streak! Consistency is your superpower. Keep it going to build unshakable discipline.',
                'type': 'positive'
            })
        elif streak >= 7:
            recs.append({
                'icon': 'fire',
                'text': f'Amazing {streak}-day streak! You are building a strong habit. Try to extend it to 14 days for a bigger XP bonus.',
                'type': 'positive'
            })
        else:
            recs.append({
                'icon': 'calendar-day',
                'text': f'You are on a {streak}-day streak. Try to study at least 30 minutes today to keep your streak alive and earn bonus XP!',
                'type': 'motivation'
            })
    else:
        recs.append({
            'icon': 'seedling',
            'text': 'Start your study streak today! Even 25 minutes of focused study counts. Consistency is the key to mastery.',
            'type': 'motivation'
        })

    total_completed = completed_sessions.count()
    total_interrupted = interrupted_sessions.count()
    if total_completed + total_interrupted > 0:
        interrupt_rate = (total_interrupted / (total_completed + total_interrupted)) * 100
        if interrupt_rate > 30:
            recs.append({
                'icon': 'bell',
                'text': f'About {round(interrupt_rate)}% of your focus sessions get interrupted. Try putting your phone away and using the app-blocking feature to minimize distractions.',
                'type': 'improvement'
            })
        elif interrupt_rate < 10 and total_completed > 5:
            recs.append({
                'icon': 'trophy',
                'text': f'You complete over 90% of your focus sessions! You have excellent discipline. Encourage a friend to join Sadhana!',
                'type': 'positive'
            })

    if improvement != 0:
        if improvement > 0:
            recs.append({
                'icon': 'chart-line',
                'text': f'Your focus quality has improved by {improvement}% compared to last month. Keep up the great work!',
                'type': 'positive'
            })
        else:
            recs.append({
                'icon': 'arrow-trend-up',
                'text': f'Your focus score dropped by {abs(improvement)}% this month. Try reducing session length and focusing on quality over quantity.',
                'type': 'improvement'
            })

    if reward_profile:
        sessions_count = reward_profile.total_focus_sessions
        if sessions_count > 0 and sessions_count < 50:
            remaining = 50 - sessions_count
            recs.append({
                'icon': 'medal',
                'text': f'Complete {remaining} more focus sessions to earn the "Focus Master" badge and 250 XP!',
                'type': 'goal'
            })

        tasks_count = reward_profile.total_tasks_completed
        if tasks_count > 0 and tasks_count < 100:
            remaining = 100 - tasks_count
            recs.append({
                'icon': 'sword',
                'text': f'Complete {remaining} more tasks to earn the "Study Warrior" badge and 200 XP!',
                'type': 'goal'
            })

    if cons_score < 50:
        recs.append({
            'icon': 'heart',
            'text': 'Your consistency score is below 50%. Try setting a fixed study time each day to build a routine.',
            'type': 'improvement'
        })
    elif cons_score >= 80:
        recs.append({
            'icon': 'gem',
            'text': 'Exceptional consistency! You are in the top tier of students. Consider setting more ambitious weekly goals.',
            'type': 'positive'
        })

    if missed_deadlines and missed_deadlines.get('missed_count', 0) > 0:
        recs.append({
            'icon': 'calendar-xmark',
            'text': f'You have {missed_deadlines["missed_count"]} missed deadline{"s" if missed_deadlines["missed_count"] > 1 else ""}. Try breaking overdue tasks into smaller steps and completing them first.',
            'type': 'improvement'
        })

    if parent_task_data and parent_task_data.get('total', 0) > 0:
        pct = parent_task_data.get('pct', 0)
        if pct < 50:
            recs.append({
                'icon': 'people-group',
                'text': f'Your parent-assigned task completion is at {pct}%. Talk to your parent about prioritizing these tasks.',
                'type': 'improvement'
            })
        elif pct >= 80:
            recs.append({
                'icon': 'people-group',
                'text': f'Great job completing {pct}% of parent-assigned tasks! Your parents will appreciate your responsibility.',
                'type': 'positive'
            })

    recs.sort(key=lambda r: 0 if r['type'] == 'positive' else (1 if r['type'] == 'motivation' else 2))
    return recs[:8]
