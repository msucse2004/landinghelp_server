# billing: 유틸리티

from .models import Plan


# 기본 tier (구독 없을 때)
DEFAULT_TIER = Plan.Tier.BASIC


def get_user_tier(user):
    """
    유저의 tier 반환.
    ACTIVE 구독이 있으면 해당 plan.tier, 없으면 BASIC(1).
    """
    if not user or not user.pk:
        return DEFAULT_TIER
    sub = (
        user.subscriptions.select_related('plan')
        .filter(status='ACTIVE')
        .order_by('-started_at')
        .first()
    )
    if sub and sub.plan:
        return sub.plan.tier
    return DEFAULT_TIER
