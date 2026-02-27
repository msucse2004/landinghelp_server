"""
서비스 등급(Tier)별 제공 정책

- Basic: 기본 메뉴얼을 보고 따라 할 수 있는 서비스 제공
- Standard: LLM 서비스 기본 지원, 필요 시 에이전트 도움, 패키지/단일 항목 계약
- Premium: LLM 서비스, 모든 항목 에이전트 도움
"""
from .models import Plan


# Tier 값 (Plan.Tier와 동일)
TIER_BASIC = 1
TIER_STANDARD = 2
TIER_PREMIUM = 3


def get_tier_value(tier):
    """Plan.Tier enum 또는 int → 숫자 값"""
    if tier is None:
        return TIER_BASIC
    return getattr(tier, 'value', tier) if hasattr(tier, 'value') else int(tier)


def can_use_llm(tier) -> bool:
    """LLM(AI) 서비스 사용 가능 여부. Standard, Premium만 가능."""
    return get_tier_value(tier) >= TIER_STANDARD


def has_agent_assistance(tier) -> bool:
    """에이전트 도움 사용 가능 여부. Standard(필요시), Premium(전체) 모두 True."""
    return get_tier_value(tier) >= TIER_STANDARD


def has_full_agent_assistance(tier) -> bool:
    """모든 항목 에이전트 도움. Premium만 True."""
    return get_tier_value(tier) >= TIER_PREMIUM


def can_contract_package_or_single(tier) -> bool:
    """패키지/단일 항목 계약 가능. Standard 이상."""
    return get_tier_value(tier) >= TIER_STANDARD


def has_manual_services(tier) -> bool:
    """기본 메뉴얼 기반 서비스. Basic 포함 모든 등급."""
    return True


def get_tier_service_description(tier) -> dict:
    """
    Tier별 서비스 설명 (템플릿/UI용)
    """
    v = get_tier_value(tier)
    if v >= TIER_PREMIUM:
        return {
            'name': '프리미엄',
            'llm': True,
            'agent_mode': 'full',  # all items get agent help
            'contract_mode': 'all',
            'description': 'LLM 서비스를 지원하며, 모든 항목에 에이전트가 도움을 드립니다.',
        }
    if v >= TIER_STANDARD:
        return {
            'name': '스탠다드',
            'llm': True,
            'agent_mode': 'on_demand',  # agent help when needed
            'contract_mode': 'package_or_single',
            'description': 'LLM 서비스를 기본 지원하며, 필요 시 에이전트의 도움을 받을 수 있습니다. 패키지 또는 단일 항목으로 계약 가능합니다.',
        }
    return {
        'name': '베이직',
        'llm': False,
        'agent_mode': None,
        'contract_mode': 'manual',
        'description': '기본 메뉴얼을 보고 따라 할 수 있는 서비스를 제공합니다.',
    }


def get_plan_policy(plan):
    """
    요금제(Plan)의 서비스 정책 반환.
    Plan에 정책 필드가 설정되어 있으면 사용, 없으면 plan.tier 기반.
    plan이 None이면 베이직 정책.
    반환: dict with can_use_llm, has_agent_assistance, has_full_agent_assistance, can_contract_package_or_single
    """
    if not plan:
        tier = None
    else:
        # Plan에 명시적 정책이 하나라도 있으면 그 필드들만 사용, 나머지는 tier로
        use_plan_llm = getattr(plan, 'can_use_llm', None)
        use_plan_agent = getattr(plan, 'has_agent_assistance', None)
        use_plan_full_agent = getattr(plan, 'has_full_agent_assistance', None)
        use_plan_contract = getattr(plan, 'can_contract_package_or_single', None)
        if any(x is not None for x in (use_plan_llm, use_plan_agent, use_plan_full_agent, use_plan_contract)):
            return {
                'can_use_llm': use_plan_llm if use_plan_llm is not None else can_use_llm(plan.tier),
                'has_agent_assistance': use_plan_agent if use_plan_agent is not None else has_agent_assistance(plan.tier),
                'has_full_agent_assistance': use_plan_full_agent if use_plan_full_agent is not None else has_full_agent_assistance(plan.tier),
                'can_contract_package_or_single': use_plan_contract if use_plan_contract is not None else can_contract_package_or_single(plan.tier),
            }
        tier = plan.tier
    return {
        'can_use_llm': can_use_llm(tier),
        'has_agent_assistance': has_agent_assistance(tier),
        'has_full_agent_assistance': has_full_agent_assistance(tier),
        'can_contract_package_or_single': can_contract_package_or_single(tier),
    }


def get_plan_service_description(plan) -> dict:
    """
    요금제 기준 서비스 설명 (등급명 = 요금제 이름, 정책 = 요금제 정책).
    plan이 없으면 tier 기반 기본 설명.
    """
    if not plan:
        return get_tier_service_description(None)
    policy = get_plan_policy(plan)
    name = plan.get_display_name()
    # 설명 문구: 정책에 맞게
    if policy['has_full_agent_assistance']:
        description = 'LLM 서비스를 지원하며, 모든 항목에 에이전트가 도움을 드립니다.'
        agent_mode = 'full'
        contract_mode = 'all'
    elif policy['has_agent_assistance']:
        description = 'LLM 서비스를 기본 지원하며, 필요 시 에이전트의 도움을 받을 수 있습니다. 패키지 또는 단일 항목으로 계약 가능합니다.'
        agent_mode = 'on_demand'
        contract_mode = 'package_or_single'
    else:
        description = '기본 메뉴얼을 보고 따라 할 수 있는 서비스를 제공합니다.'
        agent_mode = None
        contract_mode = 'manual'
    if not policy['can_use_llm'] and (policy['has_agent_assistance'] or policy['has_full_agent_assistance']):
        description = '필요 시 에이전트의 도움을 받을 수 있습니다. 패키지 또는 단일 항목으로 계약 가능합니다.' if policy['has_agent_assistance'] else description
    return {
        'name': name,
        'llm': policy['can_use_llm'],
        'agent_mode': agent_mode,
        'contract_mode': contract_mode,
        'description': description,
    }
