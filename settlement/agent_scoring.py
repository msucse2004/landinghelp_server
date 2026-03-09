"""
Agent 배정 점수화 (규칙 기반, 나중에 ML/LLM으로 교체 가능).
rating, 수락/완료 이력, state·service 매칭, 가용 창 적합도, 작업량 균형을 반영.
"""
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

# 이 점수 이상이면 자동 배정, 미만이면 Admin 검토 권장
ASSIGNMENT_CONFIDENCE_THRESHOLD = 65.0


def score_agent_for_assignment(
    agent_id,
    agent_rating_avg,
    agent_rating_count,
    agent_accept_rate,
    state_match,
    service_match,
    has_availability_fit,
    workload_count,
):
    """
    단일 Agent에 대한 배정 적합도 점수 (0~100) 및 사유.
    Pure function for testing. 나중에 외부 ML API로 대체 가능.
    - agent_rating_avg: float or None (평균 별점 1~5)
    - agent_rating_count: int (평가 수)
    - agent_accept_rate: float or None (0~1 수락률)
    - state_match: bool (region/state가 agent_states에 포함)
    - service_match: bool (서비스가 agent_services에 포함)
    - has_availability_fit: bool (해당 구간에 가용 창 있음)
    - workload_count: int (이번 플랜에서 이미 배정된 건수)
    """
    score = 50.0
    reasons = []

    if agent_rating_avg is not None:
        # 1~5 → 0~20 점 (5점 만점이면 20)
        score += (float(agent_rating_avg) - 1) * 5
        reasons.append(f'별점{agent_rating_avg:.1f}')
    if agent_rating_count and agent_rating_count >= 3:
        score += 5
        reasons.append('평가다수')
    if agent_accept_rate is not None and agent_accept_rate >= 0.8:
        score += 10
        reasons.append('수락률높음')
    elif agent_accept_rate is not None and agent_accept_rate >= 0.5:
        score += 5

    if state_match:
        score += 10
        reasons.append('State일치')
    else:
        score -= 15
    if service_match:
        score += 10
        reasons.append('서비스일치')
    else:
        score -= 20
    if has_availability_fit:
        score += 15
        reasons.append('가용창적합')
    else:
        score -= 30
    if workload_count > 0:
        score -= min(15, workload_count * 5)
        reasons.append('작업균형')

    score = max(0.0, min(100.0, score))
    reason = '; '.join(reasons) if reasons else '규칙기반'
    return round(score, 1), reason


def get_agent_scores_for_submission(submission, service_code, state_code, agent_ids_with_windows, used_slots_by_agent):
    """
    DB 사용: agent_ids_with_windows = { agent_id: [(starts_at, ends_at), ...] }.
    used_slots_by_agent = { agent_id: [(start, end), ...] } 이미 배정된 슬롯.
    Returns: list of (agent_id, score, reason) for agents who have at least one free window.
    """
    from django.contrib.auth import get_user_model
    from settlement.models import SettlementService
    from django.db.models import Q, Count

    User = get_user_model()
    if not agent_ids_with_windows:
        return []
    service_id = None
    if service_code:
        svc = SettlementService.objects.filter(Q(code=service_code) | Q(id=service_code)).first()
        if svc:
            service_id = svc.id
    state_code = (state_code or '').strip()[:10]

    result = []
    for agent_id in agent_ids_with_windows:
        windows = agent_ids_with_windows[agent_id]
        used = used_slots_by_agent.get(agent_id) or []
        has_free = False
        for w_start, w_end in windows:
            overlap = any(not (w_end <= u[0] or w_start >= u[1]) for u in used)
            if not overlap:
                has_free = True
                break
        if not has_free:
            continue
        try:
            agent = User.objects.get(pk=agent_id)
        except User.DoesNotExist:
            continue
        if getattr(agent, 'role', None) != User.Role.AGENT:
            continue
        rating = agent.get_agent_rating_summary() or {}
        rating_avg = rating.get('avg')
        rating_count = rating.get('count') or 0
        accept_rate = getattr(agent, 'accept_rate', None)
        if accept_rate is not None:
            try:
                accept_rate = float(accept_rate)
            except (TypeError, ValueError):
                accept_rate = None
        states = getattr(agent, 'agent_states', None) or []
        state_match = bool(state_code and state_code in states)
        services = getattr(agent, 'agent_services', None) or []
        service_match = bool(service_id and (service_id in services or str(service_id) in [str(s) for s in services]))
        workload = len(used)
        sc, reason = score_agent_for_assignment(
            agent_id,
            float(rating_avg) if rating_avg is not None else None,
            rating_count,
            accept_rate,
            state_match,
            service_match,
            has_availability_fit=True,
            workload_count=workload,
        )
        result.append((agent_id, sc, reason))
    return sorted(result, key=lambda x: -x[1])
