# billing: 유틸리티

from .models import Plan, Subscription


# 기본 tier (구독 없을 때)
DEFAULT_TIER = Plan.Tier.BASIC


def get_user_plan(user):
    """
    유저의 현재 ACTIVE 구독 플랜 반환. 없으면 None.
    플랜/구독 조회는 이 함수 한 곳에서만 수행(헤더·본문·정책 등 모두 여기 사용).
    """
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


def get_plan_display_key(plan):
    """
    Plan 인스턴스에서 번역 DB 조회용 키 반환. 항상 DB(Plan) 기준.
    표시명 없으면 '미설정' 키 사용.
    """
    if not plan:
        return '미설정'
    raw = plan.get_display_name()
    return (raw or '').strip() or '미설정'


def get_user_grade_display(user, language_code=None):
    """
    헤더·본문 공통: 유저 플랜 표시문. 항상 DB에서 쿼리 후 설정 언어로 표시.
    1) get_user_plan(user) 로 DB에서 구독/플랜 조회
    2) 플랜 없으면 '미설정', 있으면 플랜 표시명을 키로 사용
    3) get_display_text(key, lang) 로 번역 DB(StaticTranslation)에서 해당 언어 문구 조회·반환
    """
    from django.utils import translation
    from translations.utils import get_display_text
    lang = language_code or translation.get_language() or 'en'
    if not user or not user.pk:
        return get_display_text('미설정', lang)
    if getattr(user, 'is_superuser', False):
        return get_display_text('Super User', lang)
    plan = get_user_plan(user)
    key = get_plan_display_key(plan)
    return get_display_text(key, lang)


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
