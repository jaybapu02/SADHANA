import json
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.utils import timezone

from .models import RewardProfile, Badge, BadgeAward, Transaction
from .services import get_reward_context, get_leaderboard
from relationships.models import ConnectionRequest


@login_required
def leaderboard_view(request):
    leaderboard = get_leaderboard()
    return render(request, 'rewards/leaderboard.html', {
        'leaderboard': leaderboard,
    })


@login_required
def api_my_rewards(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Only children have rewards.'}, status=403)
    ctx = get_reward_context(request.user)
    badges_data = []
    for b in ctx['badges']:
        badges_data.append({
            'code': b['badge'].code,
            'name': b['badge'].name,
            'description': b['badge'].description,
            'icon': b['badge'].icon,
            'earned': b['earned'],
        })
    txns = []
    for t in ctx['recent_transactions']:
        txns.append({
            'xp': t.xp_amount,
            'coins': t.coin_amount,
            'source': t.get_source_display(),
            'description': t.description,
            'timestamp': t.timestamp.isoformat(),
        })
    return JsonResponse({
        'xp': ctx['profile'].xp,
        'coins': ctx['profile'].coins,
        'level': ctx['level'],
        'level_progress': ctx['level_progress'],
        'xp_for_next_level': ctx['xp_for_next_level'],
        'xp_in_current_level': ctx['xp_in_current_level'],
        'badges': badges_data,
        'transactions': txns,
    })


@login_required
def api_check_new_badges(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    new_awards = BadgeAward.objects.filter(
        user=request.user, is_new=True
    ).select_related('badge')
    results = []
    for award in new_awards:
        results.append({
            'name': award.badge.name,
            'description': award.badge.description,
            'icon': award.badge.icon,
            'xp': award.badge.xp_reward,
            'coins': award.badge.coin_reward,
        })
        award.is_new = False
        award.save(update_fields=['is_new'])
    return JsonResponse({'new_badges': results})


@login_required
def api_check_level_up(request):
    if request.user.role != 'CHILD':
        return JsonResponse({'error': 'Unauthorized.'}, status=403)
    profile = getattr(request.user, 'reward_profile', None)
    if not profile:
        return JsonResponse({'level_up': False})
    last_txn = Transaction.objects.filter(
        user=request.user, source=Transaction.Source.LEVEL_UP
    ).first()
    return JsonResponse({
        'level_up': False,
        'level': profile.level,
    })


@login_required
def parent_reward_view(request, child_id):
    if request.user.role != 'PARENT':
        return redirect('dashboard_router')

    conn = ConnectionRequest.objects.filter(
        parent=request.user, child_id=child_id, status='ACCEPTED'
    ).first()
    if not conn:
        return redirect('dashboard_router')

    child = conn.child
    ctx = get_reward_context(child)
    recent_txns = Transaction.objects.filter(user=child)[:20]

    context = {
        'child': child,
        'profile': ctx['profile'],
        'badges': ctx['badges'],
        'recent_transactions': recent_txns,
        'level': ctx['level'],
    }
    return render(request, 'rewards/parent_rewards.html', context)
