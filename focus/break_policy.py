"""
Centralized Break Policy for Sadhana Focus Mode.

This module defines the rules for break eligibility and duration limits.
All break calculations should use this module to ensure consistency.

The policy is based on the ORIGINAL PLANNED SESSION DURATION.
Longer sessions allow longer maximum breaks.
"""

# Break policy configuration
# Each bracket defines: (min_session_minutes, min_break_minutes, max_break_minutes)
# Brackets are evaluated in order; first matching bracket wins.
BREAK_BRACKETS = [
    # (min_session_minutes, min_break_minutes, max_break_minutes)
    (60, 5, 15),    # 60+ min sessions: 5-15 min break
    (45, 5, 12),    # 45-59 min sessions: 5-12 min break
    (30, 5, 10),    # 30-44 min sessions: 5-10 min break
    (25, 5, 8),     # 25-29 min sessions: 5-8 min break
    (0, 0, 0),      # Below 25 min: not eligible for break
]

# Sessions shorter than this (in minutes) are not eligible for breaks
MIN_SESSION_FOR_BREAK = 25

# Minimum break duration in minutes (floor for all brackets)
MIN_BREAK_MINUTES = 5

# Maximum break duration in minutes (ceiling for all brackets)
MAX_BREAK_MINUTES = 15

# Maximum number of breaks allowed per session
MAX_BREAKS_PER_SESSION = 3

# Minimum seconds between consecutive breaks (prevents back-to-back abuse)
MIN_BREAK_INTERVAL_SECONDS = 300  # 5 minutes


def get_break_policy(planned_duration_minutes):
    """
    Calculate break eligibility and limits based on the ORIGINAL planned session duration.

    Args:
        planned_duration_minutes: The original planned focus session duration in minutes.

    Returns:
        dict with keys:
            - eligible (bool): Whether the session is eligible for a break
            - min_minutes (int): Minimum allowed break duration in minutes
            - max_minutes (int): Maximum allowed break duration in minutes
            - max_breaks (int): Maximum number of breaks allowed

    Examples:
        >>> get_break_policy(30)
        {'eligible': True, 'min_minutes': 5, 'max_minutes': 10, 'max_breaks': 3}

        >>> get_break_policy(60)
        {'eligible': True, 'min_minutes': 5, 'max_minutes': 15, 'max_breaks': 3}

        >>> get_break_policy(20)
        {'eligible': False, 'min_minutes': 0, 'max_minutes': 0, 'max_breaks': 0}
    """
    if planned_duration_minutes < MIN_SESSION_FOR_BREAK:
        return {
            'eligible': False,
            'min_minutes': 0,
            'max_minutes': 0,
            'max_breaks': 0,
        }

    # Find the matching bracket
    for min_session, min_break, max_break in BREAK_BRACKETS:
        if planned_duration_minutes >= min_session:
            return {
                'eligible': True,
                'min_minutes': min_break,
                'max_minutes': max_break,
                'max_breaks': MAX_BREAKS_PER_SESSION,
            }

    # Default: not eligible
    return {
        'eligible': False,
        'min_minutes': 0,
        'max_minutes': 0,
        'max_breaks': 0,
    }


def validate_break_duration(planned_duration_minutes, requested_break_minutes, breaks_taken=0):
    """
    Validate whether a requested break duration is allowed.

    Args:
        planned_duration_minutes: The original planned session duration in minutes.
        requested_break_minutes: The requested break duration in minutes.
        breaks_taken: Number of breaks already taken in this session.

    Returns:
        dict with keys:
            - valid (bool): Whether the request is valid
            - error (str): Error message if invalid, empty string if valid
            - policy (dict): The break policy for reference
    """
    policy = get_break_policy(planned_duration_minutes)

    if not policy['eligible']:
        return {
            'valid': False,
            'error': f'Sessions shorter than {MIN_SESSION_FOR_BREAK} minutes are not eligible for breaks.',
            'policy': policy,
        }

    if breaks_taken >= policy['max_breaks']:
        return {
            'valid': False,
            'error': f'You have already taken the maximum of {policy["max_breaks"]} break(s) for this session.',
            'policy': policy,
        }

    if requested_break_minutes < policy['min_minutes']:
        return {
            'valid': False,
            'error': f'Break duration must be at least {policy["min_minutes"]} minutes.',
            'policy': policy,
        }

    if requested_break_minutes > policy['max_minutes']:
        return {
            'valid': False,
            'error': f'Break duration cannot exceed {policy["max_minutes"]} minutes for a {planned_duration_minutes}-minute session.',
            'policy': policy,
        }

    return {
        'valid': True,
        'error': '',
        'policy': policy,
    }


def can_start_break(session):
    """
    Check if a session is eligible to start a break right now.

    Args:
        session: FocusSession instance

    Returns:
        dict with keys:
            - can_start (bool): Whether a break can be started
            - reason (str): Reason why break cannot be started (empty if can_start)
            - policy (dict): The break policy for the session
    """
    from django.utils import timezone
    from .models import FocusSession

    # Must be ACTIVE status
    if session.status != FocusSession.Status.ACTIVE:
        return {
            'can_start': False,
            'reason': 'Session is not active.',
            'policy': get_break_policy(session.planned_duration),
        }

    # Cannot start break if already on break
    if session.break_started_at is not None and session.break_end_time is not None:
        if session.break_end_time > timezone.now():
            return {
                'can_start': False,
                'reason': 'You are already on a break.',
                'policy': get_break_policy(session.planned_duration),
            }

    # Cannot start break if paused (approved app in use)
    if session.paused_at is not None:
        return {
            'can_start': False,
            'reason': 'Cannot start a break while using an approved app.',
            'policy': get_break_policy(session.planned_duration),
        }

    policy = get_break_policy(session.planned_duration)

    if not policy['eligible']:
        return {
            'can_start': False,
            'reason': f'Sessions shorter than {MIN_SESSION_FOR_BREAK} minutes are not eligible for breaks.',
            'policy': policy,
        }

    if session.breaks_taken >= policy['max_breaks']:
        return {
            'can_start': False,
            'reason': f'You have already taken the maximum of {policy["max_breaks"]} break(s) for this session.',
            'policy': policy,
        }

    return {
        'can_start': True,
        'reason': '',
        'policy': policy,
    }
