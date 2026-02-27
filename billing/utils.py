# billing: 유틸리티

from .models import Plan, Subscription


# 기본 tier (구독 없을 때)
DEFAULT_TIER = Plan.Tier.BASIC


def get_user_plan(user):
    """유저의 현재 ACTIVE 구독 플랜 반환. 없으면 None."""
    if not user or not user.pk:
        return None
    sub = (
        user.subscriptions.select_related('plan')
        .filter(status=Subscription.Status.ACTIVE)
        .order_by('-started_at')
        .first()
    )
    return sub.plan if sub else None


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
    if sub and sub.plan and sub.plan.tier is not None:
        return sub.plan.tier
    return DEFAULT_TIER


def get_user_grade_display(user):
    """
    고객에게 보여줄 등급명. 요금제 이름(plan.get_display_name()) 사용.
    구독 없으면 기본 '베이직'.
    """
    plan = get_user_plan(user)
    if plan:
        return plan.get_display_name()
    from .models import Plan
    return dict(Plan.Tier.choices).get(DEFAULT_TIER, '베이직')


def get_user_plan_policy(user):
    """
    유저의 요금제 정책 반환 (can_use_llm, has_agent_assistance 등).
    구독 플랜이 있으면 해당 요금제 정책, 없으면 tier 기반 기본.
    """
    from .service_tiers import get_plan_policy
    plan = get_user_plan(user)
    return get_plan_policy(plan)


def get_user_plan_service_description(user):
    """
    유저의 등급/요금제에 따른 서비스 설명 (name, description, llm, agent_mode 등).
    요금제 이름을 등급으로 표시.
    """
    from .service_tiers import get_plan_service_description
    plan = get_user_plan(user)
    return get_plan_service_description(plan)


def get_user_free_agent_services(user):
    """
    고객 유저의 현재 플랜에서 무료로 제공하는 Agent 서비스 목록.
    반환: [(code, label), ...] 또는 [].
    """
    plan = get_user_plan(user)
    if not plan or not getattr(plan, 'free_agent_service_codes', None):
        return []
    from settlement.constants import get_service_label
    codes = plan.free_agent_service_codes or []
    return [(c, get_service_label(c)) for c in codes if c]
