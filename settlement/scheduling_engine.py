"""
ML-assisted schedule drafting service (rule-based first, pluggable for real ML later).

Inputs: SurveySubmission answers, requested services, quote items, entry_date/region,
        agent availability windows, service durations, service type per service.
Outputs: draft ServiceSchedulePlan with ServiceScheduleItems (start/end, score, reason, assigned_agent).

Hard constraints: no past dates, no double-booking agent, valid ordering.
Soft constraints: proximity to entry_date, same-day grouping, minimal fragmentation.
Uncertain items (low score / no agent availability) are marked for admin review.

Pluggable: To use a real ML model later, replace or wrap suggest_placements() and pass
a backend into generate_schedule_draft (e.g. backend='ml' → call external API and map
response to same placement dict shape). Keep build_scheduling_context() as the input adapter.
"""
from datetime import date, datetime, timedelta, time
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

# 설문 delivery preference → ServiceScheduleItem.service_type
DELIVERY_PREFERENCE_TO_SERVICE_TYPE = {
    'agent_direct': 'IN_PERSON_AGENT',
    'ai_service': 'AI_AGENT',
    'self_search': 'SELF_SEARCH',
}

DEFAULT_SERVICE_TYPE = 'AI_AGENT'
DEFAULT_DURATION_MINUTES = 60
ADMIN_REVIEW_SCORE_THRESHOLD = 60  # below this → needs_review
REASON_NEEDS_AGENT_AVAIL = 'Agent 가용 시간 없음; Admin 검토 권장'
REASON_PAST_DATE = '과거 날짜 불가'
REASON_ENTRY_NEAR = '입국일 인접'
REASON_GROUPED = '동일일 배치'
REASON_FRAGMENTED = '일정 분산'


# --- Pure functions (unit-test friendly, no DB) ---

def get_service_type_for_code(answers, code, bulk_preference=None, per_service=None):
    """
    설문 answers에서 서비스별 진행 방식 반환.
    answers: submission.answers (dict)
    code: service code
    bulk_preference: answers.get('service_delivery_preference') (일괄 적용 시)
    per_service: answers.get('service_delivery_per_service') (서비스별 시)
    Returns: 'SELF_SEARCH' | 'AI_AGENT' | 'IN_PERSON_AGENT'
    """
    if not answers:
        answers = {}
    per = (per_service or answers.get('service_delivery_per_service') or {})
    if isinstance(per, dict) and per.get(str(code).strip()):
        pref = (per.get(str(code).strip()) or '').strip()
        return DELIVERY_PREFERENCE_TO_SERVICE_TYPE.get(pref, DEFAULT_SERVICE_TYPE)
    bulk = (bulk_preference or answers.get('service_delivery_preference') or '').strip()
    return DELIVERY_PREFERENCE_TO_SERVICE_TYPE.get(bulk, DEFAULT_SERVICE_TYPE)


def parse_entry_date(entry_date):
    """
    entry_date (str or date) → date or None.
    """
    if entry_date is None:
        return None
    if hasattr(entry_date, 'year'):
        return entry_date
    s = (entry_date or '').strip()
    if len(s) >= 10:
        try:
            return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
        except (ValueError, TypeError):
            pass
    return None


def score_placement(
    service_code,
    service_type,
    starts_at,
    entry_date,
    agent_id,
    has_agent_availability,
    same_day_count,
    day_index_from_entry,
):
    """
    단일 배치에 대한 점수와 사유 (0~100, reason string).
    Pure function for testing.
    - Hard: IN_PERSON_AGENT인데 agent 없으면 감점 + needs_review.
    - Soft: entry_date에 가까울수록, 같은 날 서비스 많을수록(그룹화) 가산.
    """
    score = 70.0
    reasons = []
    needs_review = False

    if starts_at and entry_date and hasattr(starts_at, 'date'):
        d = starts_at.date() if hasattr(starts_at, 'date') else starts_at
        if d < entry_date:
            return 0.0, REASON_PAST_DATE, True
        days_diff = (d - entry_date).days
        day_index_from_entry = days_diff
        if days_diff <= 1:
            score += 15
            reasons.append(REASON_ENTRY_NEAR)
        elif days_diff <= 7:
            score += 5

    if service_type == 'IN_PERSON_AGENT':
        if not agent_id or not has_agent_availability:
            score -= 30
            reasons.append(REASON_NEEDS_AGENT_AVAIL)
            needs_review = True
        elif has_agent_availability:
            score += 10

    if same_day_count and same_day_count > 1:
        score += min(10, (same_day_count - 1) * 5)
        reasons.append(REASON_GROUPED)

    if day_index_from_entry is not None and day_index_from_entry > 14:
        score -= 5
        reasons.append(REASON_FRAGMENTED)

    score = max(0.0, min(100.0, score))
    reason = '; '.join(reasons) if reasons else '규칙 기반 배치'
    return round(score, 1), reason, needs_review


def suggest_placements(
    services_with_meta,
    entry_date,
    agent_windows_by_agent,
    preferred_agent_id,
    default_duration_minutes=60,
):
    """
    Pure: 서비스 목록과 제약을 받아 (code, label, type, starts_at, ends_at, agent_id, score, reason, needs_review) 리스트 반환.
    services_with_meta: list of dict with keys: code, label, service_type, duration_minutes
    entry_date: date or None
    agent_windows_by_agent: { agent_id: [ (start_dt, end_dt), ... ] }
    preferred_agent_id: int or None or 'admin_assign'
    default_duration_minutes: used when duration_minutes missing
    """
    from django.utils import timezone
    today = timezone.now().date()
    base = entry_date or today
    # 시작일: entry_date 또는 오늘 중 늦은 쪽
    if base < today:
        base = today
    result = []
    # 단순 전략: base부터 하루씩, 같은 날 여러 건 배치 가능 (그룹화 보너스)
    current_date = base
    same_day_count = 0
    day_index = 0
    for idx, svc in enumerate(services_with_meta):
        code = svc.get('code') or ''
        label = svc.get('label') or code
        service_type = svc.get('service_type') or DEFAULT_SERVICE_TYPE
        dur = svc.get('duration_minutes') or default_duration_minutes

        agent_id = None
        if service_type == 'IN_PERSON_AGENT' and preferred_agent_id and str(preferred_agent_id) != 'admin_assign':
            try:
                agent_id = int(preferred_agent_id)
            except (ValueError, TypeError):
                pass

        # 해당 agent 가용창에서 이 날짜에 넣을 수 있는 첫 슬롯
        start_dt = None
        end_dt = None
        has_agent_availability = False
        if agent_id and agent_windows_by_agent.get(agent_id):
            for w_start, w_end in agent_windows_by_agent[agent_id]:
                w_date = w_start.date() if hasattr(w_start, 'date') else w_start
                if w_date == current_date:
                    has_agent_availability = True
                    start_dt = datetime.combine(current_date, time(9, 0))
                    if timezone.is_naive(start_dt):
                        start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
                    end_dt = start_dt + timedelta(minutes=dur)
                    break
        if not start_dt:
            start_dt = datetime.combine(current_date, time(9, 0))
            if timezone.is_naive(start_dt):
                start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
            end_dt = start_dt + timedelta(minutes=dur)

        same_day_count += 1
        days_from_entry = (current_date - base).days if base else 0
        sc, reason, needs_review = score_placement(
            code,
            service_type,
            start_dt,
            entry_date or base,
            agent_id,
            has_agent_availability,
            same_day_count,
            days_from_entry,
        )
        result.append({
            'code': code,
            'label': label,
            'service_type': service_type,
            'starts_at': start_dt,
            'ends_at': end_dt,
            'duration_minutes': dur,
            'assigned_agent_id': agent_id,
            'score': sc,
            'reason': reason,
            'needs_review': needs_review or sc < ADMIN_REVIEW_SCORE_THRESHOLD,
        })
        # 다음 서비스는 다음 날로 (단순 분산; 나중에 ML이 같은 날 그룹화 최적화 가능)
        current_date = current_date + timedelta(days=1)
        same_day_count = 0
        day_index += 1
    return result


def suggest_placements_with_availability(
    services_with_meta,
    entry_date,
    agent_windows_by_agent,
    preferred_agent_id,
    state_code,
    submission=None,
    default_duration_minutes=60,
    initial_used_slots_by_agent=None,
):
    """
    Agent 가용 창 + 설문 제약을 반영한 배치. IN_PERSON_AGENT는 가용 창 내에 배치하고
    scoring으로 Agent 선택(confidence 충분 시 배정, 아니면 admin-review).
    동일 Agent 겹침 없음(used_slots_by_agent 추적).
    initial_used_slots_by_agent: 이미 배정된 슬롯 { agent_id: [(start, end), ...] } (재배치 시 사용).
    """
    from django.utils import timezone
    from .agent_scoring import get_agent_scores_for_submission, ASSIGNMENT_CONFIDENCE_THRESHOLD

    today = timezone.now().date()
    base = entry_date or today
    if base < today:
        base = today
    base_dt = timezone.make_aware(datetime.combine(base, time(0, 0)))
    result = []
    used_slots_by_agent = dict(initial_used_slots_by_agent) if initial_used_slots_by_agent else {}
    current_date = base
    for idx, svc in enumerate(services_with_meta):
        code = svc.get('code') or ''
        label = svc.get('label') or code
        service_type = svc.get('service_type') or DEFAULT_SERVICE_TYPE
        dur = svc.get('duration_minutes') or default_duration_minutes

        agent_id = None
        start_dt = None
        end_dt = None
        has_agent_availability = False
        assignment_reason = ''
        assignment_score = 0.0

        if service_type == 'IN_PERSON_AGENT' and agent_windows_by_agent:
            day_start = timezone.make_aware(datetime.combine(current_date, time(0, 0)))
            candidates = get_agent_scores_for_submission(
                submission,
                code,
                state_code,
                agent_windows_by_agent,
                used_slots_by_agent,
            )
            if preferred_agent_id and str(preferred_agent_id) != 'admin_assign':
                try:
                    pref_id = int(preferred_agent_id)
                    if pref_id in agent_windows_by_agent:
                        pref_candidates = [(aid, sc, r) for aid, sc, r in candidates if aid == pref_id]
                        if pref_candidates:
                            candidates = pref_candidates + [(a, s, r) for a, s, r in candidates if a != pref_id]
                except (ValueError, TypeError):
                    pass
            for aid, sc, reason in candidates:
                if sc < ASSIGNMENT_CONFIDENCE_THRESHOLD:
                    continue
                windows = agent_windows_by_agent.get(aid) or []
                slot = _first_free_window(windows, used_slots_by_agent.get(aid) or [], day_start, dur)
                if slot:
                    agent_id = aid
                    start_dt, end_dt = slot
                    has_agent_availability = True
                    assignment_score = sc
                    assignment_reason = reason
                    used_slots_by_agent.setdefault(aid, []).append((start_dt, end_dt))
                    break
            if not agent_id and candidates:
                aid, sc, reason = candidates[0]
                windows = agent_windows_by_agent.get(aid) or []
                slot = _first_free_window(windows, used_slots_by_agent.get(aid) or [], day_start, dur)
                if slot:
                    agent_id = aid
                    start_dt, end_dt = slot
                    has_agent_availability = True
                    assignment_score = sc
                    assignment_reason = reason + '; 자동선택'
                    used_slots_by_agent.setdefault(aid, []).append((start_dt, end_dt))
        if start_dt is None:
            start_dt = timezone.make_aware(datetime.combine(current_date, time(9, 0)))
            end_dt = start_dt + timedelta(minutes=dur)
        days_from_entry = (current_date - base).days if base else 0
        sc, reason, needs_review = score_placement(
            code,
            service_type,
            start_dt,
            entry_date or base,
            agent_id,
            has_agent_availability,
            1,
            days_from_entry,
        )
        if assignment_reason:
            reason = assignment_reason
        if agent_id and assignment_score < ASSIGNMENT_CONFIDENCE_THRESHOLD:
            needs_review = True
        if service_type == 'IN_PERSON_AGENT' and not agent_id:
            needs_review = True
        result.append({
            'code': code,
            'label': label,
            'service_type': service_type,
            'starts_at': start_dt,
            'ends_at': end_dt,
            'duration_minutes': dur,
            'assigned_agent_id': agent_id,
            'score': assignment_score if assignment_score else sc,
            'reason': reason,
            'needs_review': needs_review or sc < ADMIN_REVIEW_SCORE_THRESHOLD,
        })
        current_date = current_date + timedelta(days=1)
    return result


# --- DB-backed context (for engine use) ---

def get_requested_services_from_quote(quote):
    """Quote items → list of {code, label}."""
    out = []
    for it in (quote.items or []) if quote else []:
        if not isinstance(it, dict):
            continue
        code = (it.get('code') or '').strip()
        if not code:
            continue
        out.append({'code': code, 'label': (it.get('label') or code).strip()})
    return out


def get_requested_services_from_submission(submission):
    """Submission requested_required + requested_optional → list of {code, label} (label from DB if possible)."""
    from .constants import get_schedule_ordered_services, get_service_label
    codes = list(set(
        list(submission.requested_required_services or []) +
        list(submission.requested_optional_services or [])
    ))
    codes = [c for c in codes if (c or '').strip()]
    if not codes:
        return []
    ordered = get_schedule_ordered_services(codes)
    return [{'code': c, 'label': get_service_label(c)} for c in ordered]


def get_durations_for_codes(codes):
    """DB: service code → duration_minutes."""
    from .models import SettlementService
    from django.db.models import Q
    out = {}
    for code in (codes or []):
        if not (code or '').strip():
            continue
        q = Q(code=code)
        if str(code).isdigit():
            q = q | Q(id=int(code))
        svc = SettlementService.objects.filter(q).first()
        out[code] = (svc.required_time or DEFAULT_DURATION_MINUTES) if svc else DEFAULT_DURATION_MINUTES
    return out


def get_agent_availability_for_submission(submission, schedule_plan=None):
    """
    submission(또는 schedule_plan)에 연결된 AgentAvailabilityWindow (AVAILABLE) → { agent_id: [ (starts_at, ends_at), ... ] }.
    schedule_plan이 있으면 submission 대신 plan 기준으로도 조회 (동일 submission이면 결합).
    """
    from .models import AgentAvailabilityWindow
    by_agent = {}
    if submission:
        qs = AgentAvailabilityWindow.objects.filter(
            submission=submission,
            status=AgentAvailabilityWindow.WindowStatus.AVAILABLE,
        ).order_by('agent_id', 'starts_at')
        for w in qs:
            if w.agent_id not in by_agent:
                by_agent[w.agent_id] = []
            by_agent[w.agent_id].append((w.starts_at, w.ends_at))
    if schedule_plan and schedule_plan.id:
        qs = AgentAvailabilityWindow.objects.filter(
            schedule_plan=schedule_plan,
            status=AgentAvailabilityWindow.WindowStatus.AVAILABLE,
        ).order_by('agent_id', 'starts_at')
        for w in qs:
            if w.agent_id not in by_agent:
                by_agent[w.agent_id] = []
            by_agent[w.agent_id].append((w.starts_at, w.ends_at))
    return by_agent


def _first_free_window(agent_windows, used_slots, after_dt, duration_minutes):
    """
    가용 창 목록에서 used_slots와 겹치지 않고 after_dt 이후인 첫 슬롯 반환.
    (start_dt, end_dt) or None. after_dt는 datetime.
    """
    from django.utils import timezone
    for w_start, w_end in sorted(agent_windows, key=lambda x: x[0]):
        if w_end <= after_dt:
            continue
        start_candidate = w_start if w_start >= after_dt else after_dt
        end_candidate = start_candidate + timedelta(minutes=duration_minutes)
        if end_candidate > w_end:
            continue
        overlap = any(
            not (end_candidate <= u[0] or start_candidate >= u[1])
            for u in used_slots
        )
        if not overlap:
            if timezone.is_naive(start_candidate):
                start_candidate = timezone.make_aware(start_candidate, timezone.get_current_timezone())
            if timezone.is_naive(end_candidate):
                end_candidate = timezone.make_aware(end_candidate, timezone.get_current_timezone())
            return start_candidate, end_candidate
    return None


def build_scheduling_context(submission, quote=None):
    """
    submission + optional quote → context for suggest_placements.
    Returns: dict with services_with_meta, entry_date, agent_windows_by_agent, preferred_agent_id.
    """
    from survey.quote_input import get_quote_input_data
    answers = submission.answers or {}
    quote_data = get_quote_input_data(submission) if submission else {}
    entry_date = parse_entry_date(quote_data.get('entry_date'))
    preferred_agent_id = (answers.get('preferred_agent_id') or '').strip()
    if preferred_agent_id == 'admin_assign':
        preferred_agent_id = None

    if quote and quote.items:
        services = get_requested_services_from_quote(quote)
    else:
        services = get_requested_services_from_submission(submission)
    if not services:
        return None

    codes = [s['code'] for s in services]
    durations = get_durations_for_codes(codes)
    bulk_pref = (answers.get('service_delivery_preference') or '').strip()
    per_svc = answers.get('service_delivery_per_service') or {}

    services_with_meta = []
    for s in services:
        code = s['code']
        stype = get_service_type_for_code(answers, code, bulk_preference=bulk_pref, per_service=per_svc)
        services_with_meta.append({
            'code': code,
            'label': s.get('label') or code,
            'service_type': stype,
            'duration_minutes': durations.get(code, DEFAULT_DURATION_MINUTES),
        })
    agent_windows = get_agent_availability_for_submission(submission)
    region = (quote_data.get('region') or '').strip()
    state_code = None
    if region:
        parts = [p.strip() for p in region.split(',')]
        if parts:
            state_code = parts[0][:10] if len(parts[0]) >= 2 else (parts[0] or None)
    return {
        'services_with_meta': services_with_meta,
        'entry_date': entry_date,
        'agent_windows_by_agent': agent_windows,
        'preferred_agent_id': preferred_agent_id,
        'state_code': state_code,
    }


def generate_schedule_draft(submission, quote=None, plan=None, actor=None):
    """
    Rule-based (or later ML) schedule draft 생성.
    submission: SurveySubmission (required)
    quote: SettlementQuote (optional; 없으면 submission에서 서비스 목록 추출)
    plan: UserSettlementPlan (optional; customer 확보용)
    actor: User (optional; created_by/updated_by)
    Returns: ServiceSchedulePlan (DRAFT, source=HYBRID or ML).
    """
    from .models import ServiceSchedulePlan, ServiceScheduleItem
    from django.utils import timezone

    if not submission:
        raise ValueError('submission is required')
    customer = getattr(submission, 'user', None)
    if not customer:
        if plan:
            customer = plan.user
        else:
            raise ValueError('submission has no user and plan not provided')
    if not quote and submission:
        from .models import SettlementQuote
        quote = (
            SettlementQuote.objects.filter(submission=submission)
            .order_by('-updated_at')
            .first()
        )

    context = build_scheduling_context(submission, quote=quote)
    if not context:
        logger.warning('build_scheduling_context returned None for submission_id=%s', submission.id)
        raise ValueError('No requested services for submission')

    if context.get('agent_windows_by_agent'):
        placements = suggest_placements_with_availability(
            context['services_with_meta'],
            context['entry_date'],
            context['agent_windows_by_agent'],
            context['preferred_agent_id'],
            context.get('state_code'),
            submission=submission,
        )
    else:
        placements = suggest_placements(
            context['services_with_meta'],
            context['entry_date'],
            context['agent_windows_by_agent'],
            context['preferred_agent_id'],
        )
    if not placements:
        raise ValueError('suggest_placements returned empty')

    schedule_plan = ServiceSchedulePlan.objects.create(
        submission=submission,
        quote=quote,
        customer=customer,
        status=ServiceSchedulePlan.Status.DRAFT,
        source=ServiceSchedulePlan.Source.HYBRID,
        version=1,
        created_by=actor,
        updated_by=actor,
    )
    for idx, p in enumerate(placements):
        notes = ''
        if p.get('needs_review'):
            notes = 'Admin 검토 권장'
        ServiceScheduleItem.objects.create(
            schedule_plan=schedule_plan,
            service_code=p['code'],
            service_label=(p.get('label') or p['code'])[:200],
            service_type=p.get('service_type') or ServiceScheduleItem.ServiceType.AI_AGENT,
            starts_at=p.get('starts_at'),
            ends_at=p.get('ends_at'),
            duration_minutes=p.get('duration_minutes'),
            assigned_agent_id=p.get('assigned_agent_id'),
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            source_score=Decimal(str(p.get('score', 0))),
            source_reason=(p.get('reason') or '')[:500],
            notes=notes[:500] if notes else '',
            sort_order=idx + 1,
        )
    return schedule_plan


def regenerate_agent_dependent_items(schedule_plan, submission):
    """
    기존 플랜에서 IN_PERSON_AGENT 항목만 재배치: 가용 창 + scoring으로 다시 배정.
    이미 배정된(starts_at 있는) 비-IN_PERSON 항목은 유지하고, IN_PERSON 항목만 초기화 후 재계산.
    동일 Agent 겹침 없음.
    Returns: number of items updated.
    """
    from .models import ServiceScheduleItem
    from django.utils import timezone

    if not schedule_plan or not submission:
        return 0
    context = build_scheduling_context(submission, quote=getattr(schedule_plan, 'quote', None))
    if not context or not context.get('agent_windows_by_agent'):
        return 0
    agent_items = list(
        schedule_plan.items.filter(
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            status__in=(ServiceScheduleItem.ItemStatus.SCHEDULED, ServiceScheduleItem.ItemStatus.CONFIRMED),
        ).order_by('sort_order', 'id')
    )
    if not agent_items:
        return 0
    initial_used = {}
    for it in schedule_plan.items.exclude(status=ServiceScheduleItem.ItemStatus.CANCELLED).exclude(service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT):
        if it.starts_at and it.ends_at and it.assigned_agent_id:
            initial_used.setdefault(it.assigned_agent_id, []).append((it.starts_at, it.ends_at))
    services_in = [{'code': it.service_code, 'label': it.service_label or it.service_code, 'service_type': it.service_type or 'IN_PERSON_AGENT', 'duration_minutes': it.duration_minutes or 60} for it in agent_items]
    placements = suggest_placements_with_availability(
        services_in,
        context['entry_date'],
        context['agent_windows_by_agent'],
        context['preferred_agent_id'],
        context.get('state_code'),
        submission=submission,
        initial_used_slots_by_agent=initial_used,
    )
    from .agent_scoring import ASSIGNMENT_CONFIDENCE_THRESHOLD
    updated = 0
    for it, place in zip(agent_items, placements):
        it.starts_at = place.get('starts_at')
        it.ends_at = place.get('ends_at')
        it.assigned_agent_id = place.get('assigned_agent_id')
        it.source_score = Decimal(str(place.get('score', 0)))
        it.source_reason = (place.get('reason') or '')[:500]
        it.notes = 'Admin 검토 권장' if place.get('needs_review') else ''
        it.save(update_fields=['starts_at', 'ends_at', 'assigned_agent_id', 'source_score', 'source_reason', 'notes'])
        updated += 1
    return updated
