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
from collections import defaultdict
from statistics import median
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

REMAINING_DAYS_URGENT_MAX = 14
REMAINING_DAYS_NORMAL_MAX = 60


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
    from .schedule_features import build_current_submission_feature_context

    answers = submission.answers or {}
    current_features = build_current_submission_feature_context(submission)
    entry_date = current_features.get('entry_date')
    preferred_agent_id = (current_features.get('preferred_agent_id') or '').strip() if current_features.get('preferred_agent_id') else ''
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
    service_type_map = {
        str(code or '').strip().upper(): stype
        for code, stype in (current_features.get('service_types_by_code') or {}).items()
    }

    services_with_meta = []
    for s in services:
        code = s['code']
        stype = service_type_map.get(str(code or '').strip().upper()) or get_service_type_for_code(answers, code)
        services_with_meta.append({
            'code': code,
            'label': s.get('label') or code,
            'service_type': stype,
            'duration_minutes': durations.get(code, DEFAULT_DURATION_MINUTES),
        })
    agent_windows = get_agent_availability_for_submission(submission)
    state_code = current_features.get('state_code') or None
    return {
        'services_with_meta': services_with_meta,
        'entry_date': entry_date,
        'agent_windows_by_agent': agent_windows,
        'preferred_agent_id': preferred_agent_id,
        'state_code': state_code,
        'current_features': current_features,
    }


def _jaccard_similarity(a_values, b_values):
    a = set(a_values or [])
    b = set(b_values or [])
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return float(len(a & b)) / float(len(union))


def _safe_int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _weighted_median(values_with_weights):
    if not values_with_weights:
        return None
    cleaned = []
    total_weight = 0.0
    for value, weight in values_with_weights:
        if value is None:
            continue
        w = float(weight or 0.0)
        if w <= 0:
            continue
        cleaned.append((float(value), w))
        total_weight += w
    if not cleaned or total_weight <= 0:
        return None
    cleaned.sort(key=lambda x: x[0])
    threshold = total_weight / 2.0
    cumulative = 0.0
    for value, weight in cleaned:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return cleaned[-1][0]


def get_remaining_days_band(remaining_days):
    if remaining_days is None:
        return 'normal'
    value = _safe_int_or_none(remaining_days)
    if value is None:
        return 'normal'
    if value <= REMAINING_DAYS_URGENT_MAX:
        return 'urgent'
    if value <= REMAINING_DAYS_NORMAL_MAX:
        return 'normal'
    return 'long'


def get_remaining_days_policy_profile(current_features):
    remaining_days = _safe_int_or_none((current_features or {}).get('remaining_days_to_entry'))
    band = get_remaining_days_band(remaining_days)
    if band == 'urgent':
        return {
            'band': band,
            'remaining_days': remaining_days,
            'min_spacing_days': 0,
            'max_offset_days': 7,
            'preferred_hist_offset_max': 10,
            'preferred_hist_offset_min': 0,
        }
    if band == 'long':
        return {
            'band': band,
            'remaining_days': remaining_days,
            'min_spacing_days': 2,
            'max_offset_days': 45,
            'preferred_hist_offset_max': 40,
            'preferred_hist_offset_min': 5,
        }
    return {
        'band': 'normal',
        'remaining_days': remaining_days,
        'min_spacing_days': 1,
        'max_offset_days': 21,
        'preferred_hist_offset_max': 24,
        'preferred_hist_offset_min': 1,
    }


def _remaining_days_offset_compatibility(current_features, historical_row):
    profile = get_remaining_days_policy_profile(current_features)
    row_offset = _safe_int_or_none(historical_row.get('days_from_entry'))
    if row_offset is None:
        return 0.0

    if profile['preferred_hist_offset_min'] <= row_offset <= profile['preferred_hist_offset_max']:
        return 8.0
    if profile['band'] == 'urgent' and row_offset <= 14:
        return 4.0
    if profile['band'] == 'long' and row_offset >= 3:
        return 3.0
    if row_offset < 0:
        return -6.0
    return -2.0


def _is_row_offset_compatible(row, profile):
    day_offset = _safe_int_or_none(row.get('days_from_entry'))
    if day_offset is None:
        return False
    if day_offset < 0:
        return False
    if day_offset < profile['preferred_hist_offset_min']:
        return False
    if day_offset > profile['preferred_hist_offset_max']:
        return False
    return True


def apply_remaining_days_policy(placements, current_features):
    rows = [dict(p) for p in (placements or [])]
    if not rows:
        return rows

    from django.utils import timezone

    profile = get_remaining_days_policy_profile(current_features or {})
    entry_date = (current_features or {}).get('entry_date')
    today = timezone.now().date()
    now_dt = timezone.now()
    anchor_date = entry_date or today
    if anchor_date < today:
        anchor_date = today
    max_allowed_date = anchor_date + timedelta(days=int(profile.get('max_offset_days') or 21))

    dependency_sensitive = {
        str(code or '').strip().upper()
        for code in ((current_features or {}).get('dependency_sensitive_service_codes') or [])
        if str(code or '').strip()
    }

    def _sort_key(row):
        code = (row.get('code') or '').strip().upper()
        priority = 0
        if profile['band'] == 'urgent':
            priority = 0 if code in dependency_sensitive else 1
        starts_at = row.get('starts_at')
        return (
            priority,
            starts_at or timezone.make_aware(datetime.combine(anchor_date, time(9, 0))),
            code,
        )

    ordered = sorted(rows, key=_sort_key)

    previous_date = None
    for idx, row in enumerate(ordered):
        starts_at = row.get('starts_at')
        if starts_at is None:
            starts_at = timezone.make_aware(datetime.combine(anchor_date, time(9, 0)))
        target_date = starts_at.date()

        if target_date < today:
            target_date = today
        if target_date < anchor_date:
            target_date = anchor_date

        if previous_date is not None:
            min_date = previous_date + timedelta(days=int(profile.get('min_spacing_days') or 0))
            if target_date < min_date:
                target_date = min_date

        if target_date > max_allowed_date:
            target_date = max_allowed_date

        adjusted_start = starts_at.replace(year=target_date.year, month=target_date.month, day=target_date.day)
        if adjusted_start.date() < today:
            adjusted_start = timezone.make_aware(datetime.combine(today, time(9, 0)))
        if adjusted_start < now_dt:
            next_hour = (now_dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            if next_hour <= now_dt:
                next_hour = next_hour + timedelta(hours=1)
            adjusted_start = next_hour
        adjusted_end = adjusted_start + timedelta(minutes=int(row.get('duration_minutes') or 60))
        row['starts_at'] = adjusted_start
        row['ends_at'] = adjusted_end

        row['remaining_days_band'] = profile['band']
        row['remaining_days_value'] = profile.get('remaining_days')
        base_reason = (row.get('reason') or '').strip()
        row['reason'] = (
            (base_reason + '; ') if base_reason else ''
        ) + (
            f"remaining-days-band={profile['band']}; "
            f"remaining-days={profile.get('remaining_days')}; "
            f"min-spacing={profile.get('min_spacing_days')}d; "
            f"max-offset={profile.get('max_offset_days')}d"
        )

        previous_date = target_date

    return ordered


def compute_similarity_score(current_features, historical_row):
    score = 0.0
    current_state = (current_features.get('state_code') or '').strip().upper()
    current_city = (current_features.get('city') or '').strip().upper()
    hist_state = (historical_row.get('state_code') or '').strip().upper()
    hist_city = (historical_row.get('city') or '').strip().upper()

    if current_state and hist_state and current_state == hist_state:
        score += 18.0
    if current_city and hist_city and current_city == hist_city:
        score += 8.0

    svc_sim = _jaccard_similarity(
        current_features.get('requested_service_codes') or [],
        historical_row.get('requested_service_codes') or [],
    )
    score += (svc_sim * 35.0)

    cur_service_count = _safe_int_or_none(current_features.get('service_count'))
    hist_service_count = _safe_int_or_none(historical_row.get('service_count'))
    if cur_service_count is not None and hist_service_count is not None:
        count_gap = abs(cur_service_count - hist_service_count)
        if count_gap == 0:
            score += 8.0
        elif count_gap == 1:
            score += 4.0

    # historical row는 remaining_days 대신 schedule_week_span 보유.
    # current는 expected_schedule_weeks(= remaining_days/7)로 비교.
    cur_weeks = current_features.get('expected_schedule_weeks')
    hist_weeks = historical_row.get('schedule_week_span')
    try:
        cur_weeks = float(cur_weeks) if cur_weeks is not None else None
        hist_weeks = float(hist_weeks) if hist_weeks is not None else None
    except (TypeError, ValueError):
        cur_weeks = hist_weeks = None
    if cur_weeks is not None and hist_weeks is not None:
        week_diff = abs(cur_weeks - hist_weeks)
        if week_diff < 1.0:
            score += 10.0
        elif week_diff < 2.0:
            score += 5.0

    # 선호/배정 Agent 일치: 같은 Agent의 과거 스케줄 패턴을 우선 참조.
    cur_preferred_agent = str(current_features.get('preferred_agent_id') or '').strip()
    hist_agent = str(historical_row.get('assigned_agent_id') or '').strip()
    if cur_preferred_agent and hist_agent and cur_preferred_agent == hist_agent:
        score += 10.0

    cur_household = _safe_int_or_none(current_features.get('household_size'))
    hist_household = _safe_int_or_none(historical_row.get('household_size'))
    if cur_household is not None and hist_household is not None:
        household_gap = abs(cur_household - hist_household)
        if household_gap == 0:
            score += 6.0
        elif household_gap <= 1:
            score += 3.0

    cur_constraints = bool(current_features.get('has_special_requirements'))
    hist_constraints = bool(historical_row.get('has_special_requirements'))
    if cur_constraints == hist_constraints:
        score += 4.0

    cur_mode = (current_features.get('preferred_support_mode') or '').strip().lower()
    hist_mode = (historical_row.get('preferred_support_mode') or '').strip().lower()
    if cur_mode and hist_mode and cur_mode == hist_mode:
        score += 3.0

    cur_dep = current_features.get('dependency_sensitive_service_codes') or []
    hist_dep = historical_row.get('dependency_sensitive_service_codes') or []
    dep_sim = _jaccard_similarity(cur_dep, hist_dep)
    score += (dep_sim * 8.0)

    score += _remaining_days_offset_compatibility(current_features, historical_row)

    in_person_gap = abs(
        int(current_features.get('in_person_service_count') or 0)
        - int(historical_row.get('in_person_service_count') or 0)
    )
    if in_person_gap == 0:
        score += 5.0
    elif in_person_gap == 1:
        score += 2.5

    return round(max(0.0, min(100.0, score)), 1)


def rank_historical_examples(current_features, historical_rows):
    ranked = []
    for row in (historical_rows or []):
        ranked.append((compute_similarity_score(current_features, row), row))
    ranked.sort(key=lambda x: (-x[0], x[1].get('plan_id') or 0, x[1].get('item_id') or 0))
    return ranked


def learn_historical_pattern_priors(current_features, historical_rows):
    rows = list(historical_rows or [])
    if not rows:
        return {
            'selected_plan_count': 0,
            'service_day_offset_priors': {},
            'sequence_priors_by_service': {},
            'grouping_pair_priors': {},
        }

    plan_scores = defaultdict(list)
    plan_rows = defaultdict(list)
    for row in rows:
        plan_id = row.get('plan_id')
        if not plan_id:
            continue
        sim = compute_similarity_score(current_features, row)
        plan_scores[plan_id].append(sim)
        plan_rows[plan_id].append(row)

    ranked_plans = []
    for plan_id, scores in plan_scores.items():
        top_sim = max(scores)
        avg_sim = (sum(scores) / float(len(scores))) if scores else 0.0
        blended = (top_sim * 0.65) + (avg_sim * 0.35)
        ranked_plans.append((round(blended, 1), plan_id, plan_rows.get(plan_id, [])))
    ranked_plans.sort(key=lambda x: (-x[0], x[1]))

    selected = [(score, pid, prow) for score, pid, prow in ranked_plans if score >= 30.0]
    if len(selected) < 2:
        selected = ranked_plans[: max(2, min(10, len(ranked_plans)))]

    if not selected:
        return {
            'selected_plan_count': 0,
            'service_day_offset_priors': {},
            'sequence_priors_by_service': {},
            'grouping_pair_priors': {},
        }

    weighted_offsets_by_service = defaultdict(list)
    weighted_hours_by_service = defaultdict(list)
    sequence_prev_counts = defaultdict(lambda: defaultdict(float))
    sequence_total_counts = defaultdict(float)
    grouping_pair_counts = defaultdict(float)
    grouping_pair_total_by_service = defaultdict(float)

    for plan_score, _plan_id, prow in selected:
        weight = max(0.1, float(plan_score) / 100.0)
        for row in prow:
            code = (row.get('service_code') or '').strip().upper()
            day_offset = _safe_int_or_none(row.get('days_from_entry'))
            starts_at = row.get('starts_at')
            if code and day_offset is not None:
                weighted_offsets_by_service[code].append((day_offset, weight))
                if starts_at is not None:
                    weighted_hours_by_service[code].append((int(starts_at.hour), weight))

        ordered = sorted(
            [r for r in prow if r.get('starts_at') is not None and (r.get('service_code') or '').strip()],
            key=lambda r: (
                r.get('starts_at'),
                r.get('sort_order') or 0,
                r.get('item_id') or 0,
            ),
        )
        ordered_codes = []
        seen_codes = set()
        for row in ordered:
            code = (row.get('service_code') or '').strip().upper()
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            ordered_codes.append(code)
        for idx in range(1, len(ordered_codes)):
            prev_code = ordered_codes[idx - 1]
            code = ordered_codes[idx]
            sequence_prev_counts[code][prev_code] += weight
            sequence_total_counts[code] += weight

        by_day = defaultdict(set)
        for row in ordered:
            starts_at = row.get('starts_at')
            code = (row.get('service_code') or '').strip().upper()
            if starts_at is None or not code:
                continue
            by_day[starts_at.date()].add(code)
        for _day, codes in by_day.items():
            code_list = sorted(list(codes))
            if len(code_list) < 2:
                continue
            for idx in range(len(code_list)):
                for jdx in range(idx + 1, len(code_list)):
                    a = code_list[idx]
                    b = code_list[jdx]
                    key = (a, b)
                    grouping_pair_counts[key] += weight
                    grouping_pair_total_by_service[a] += weight
                    grouping_pair_total_by_service[b] += weight

    service_day_offset_priors = {}
    for code, values in weighted_offsets_by_service.items():
        if len(values) < 2:
            continue
        med = _weighted_median(values)
        hour_med = _weighted_median(weighted_hours_by_service.get(code, []))
        service_day_offset_priors[code] = {
            'day_offset': int(round(med)) if med is not None else 0,
            'representative_hour': int(round(hour_med)) if hour_med is not None else 9,
            'sample_count': len(values),
        }

    sequence_priors_by_service = {}
    for code, prev_counts in sequence_prev_counts.items():
        if not prev_counts:
            continue
        likely_prev, support_weight = max(prev_counts.items(), key=lambda x: x[1])
        total_weight = sequence_total_counts.get(code) or 0.0
        if total_weight <= 0:
            continue
        confidence = support_weight / total_weight
        if support_weight >= 1.0:
            sequence_priors_by_service[code] = {
                'likely_predecessor': likely_prev,
                'confidence': round(confidence, 2),
                'support_weight': round(support_weight, 2),
            }

    grouping_pair_priors = {}
    for pair, support_weight in grouping_pair_counts.items():
        a, b = pair
        total_a = grouping_pair_total_by_service.get(a) or 0.0
        total_b = grouping_pair_total_by_service.get(b) or 0.0
        denom = max(total_a, total_b, 1e-9)
        confidence = support_weight / denom
        if support_weight >= 1.0:
            grouping_pair_priors[pair] = {
                'confidence': round(confidence, 2),
                'support_weight': round(support_weight, 2),
            }

    return {
        'selected_plan_count': len(selected),
        'service_day_offset_priors': service_day_offset_priors,
        'sequence_priors_by_service': sequence_priors_by_service,
        'grouping_pair_priors': grouping_pair_priors,
    }


def _compute_historical_similarity(current_features, historical_row):
    return compute_similarity_score(current_features, historical_row)


def apply_grouping_pattern_adjustments(placements, grouping_pair_priors):
    rows = [dict(p) for p in (placements or [])]
    if not rows or not grouping_pair_priors:
        return rows

    by_code = {
        (row.get('code') or '').strip().upper(): row
        for row in rows
        if (row.get('code') or '').strip()
    }

    for (a, b), prior in (grouping_pair_priors or {}).items():
        row_a = by_code.get((a or '').strip().upper())
        row_b = by_code.get((b or '').strip().upper())
        if not row_a or not row_b:
            continue
        support = float(prior.get('support_weight') or 0.0)
        confidence = float(prior.get('confidence') or 0.0)
        if support < 1.0 or confidence < 0.55:
            continue
        if not row_a.get('starts_at') or not row_b.get('starts_at'):
            continue

        anchor = row_a if row_a['starts_at'] <= row_b['starts_at'] else row_b
        other = row_b if anchor is row_a else row_a
        if anchor['starts_at'].date() == other['starts_at'].date():
            continue

        original = other['starts_at']
        target_date = anchor['starts_at'].date()
        new_start = original.replace(year=target_date.year, month=target_date.month, day=target_date.day)
        new_end = new_start + timedelta(minutes=int(other.get('duration_minutes') or 60))
        other['starts_at'] = new_start
        other['ends_at'] = new_end
        base_reason = (other.get('reason') or '').strip()
        other['reason'] = (
            (base_reason + '; ') if base_reason else ''
        ) + (
            f'evidence=grouping-prior; paired-with={anchor.get("code")}; '
            f'group_confidence={confidence}'
        )

    return rows


def _build_historical_recommendation_context(context):
    from .schedule_features import build_historical_schedule_feature_contexts

    current_features = context.get('current_features') or {}
    requested_codes = current_features.get('requested_service_codes') or []
    historical_rows = build_historical_schedule_feature_contexts(
        service_codes=requested_codes,
        max_items=800,
    )

    per_service_rows = {}
    for row in historical_rows:
        code = (row.get('service_code') or '').strip().upper()
        if not code:
            continue
        per_service_rows.setdefault(code, []).append(row)

    for code, rows in per_service_rows.items():
        rows.sort(key=lambda r: (
            r.get('plan_id') or 0,
            r.get('item_id') or 0,
        ))

    priors = learn_historical_pattern_priors(current_features, historical_rows)

    return {
        'current_features': current_features,
        'historical_rows': historical_rows,
        'per_service_rows': per_service_rows,
        'priors': priors,
    }


def _infer_timing_for_service(service_code, rec_ctx):
    normalized_code = (service_code or '').strip().upper()
    rows = list(rec_ctx.get('per_service_rows', {}).get(normalized_code, []))
    if not rows:
        return None

    current_features = rec_ctx.get('current_features') or {}
    priors = rec_ctx.get('priors') or {}
    remaining_profile = get_remaining_days_policy_profile(current_features)
    compatible_rows = [row for row in rows if _is_row_offset_compatible(row, remaining_profile)]
    target_rows = compatible_rows if len(compatible_rows) >= 2 else rows
    scored = rank_historical_examples(current_features, target_rows)

    strong = [(sim, row) for sim, row in scored if sim >= 55.0 and row.get('days_from_entry') is not None]
    all_with_offsets = [(sim, row) for sim, row in scored if row.get('days_from_entry') is not None]

    if len(strong) >= 2:
        day_offsets = [int(row['days_from_entry']) for _sim, row in strong]
        hours = [int((row.get('starts_at')).hour) for _sim, row in strong if row.get('starts_at')]
        top_sim = strong[0][0]
        return {
            'evidence_type': 'historical-match',
            'day_offset': int(round(median(day_offsets))),
            'hour': int(round(median(hours))) if hours else 9,
            'matched_sample_count': len(strong),
            'confidence': round(min(98.0, 74.0 + (top_sim * 0.22) + min(len(strong), 8)), 1),
        }

    service_prior = (priors.get('service_day_offset_priors') or {}).get(normalized_code)
    if service_prior and int(service_prior.get('sample_count') or 0) >= 2:
        return {
            'evidence_type': 'statistical-prior',
            'day_offset': int(service_prior.get('day_offset') or 0),
            'hour': int(service_prior.get('representative_hour') or 9),
            'matched_sample_count': int(service_prior.get('sample_count') or 0),
            'confidence': round(min(86.0, 62.0 + int(service_prior.get('sample_count') or 0) * 1.4), 1),
        }

    if not all_with_offsets:
        return None

    day_offsets = [int(row['days_from_entry']) for _sim, row in all_with_offsets]
    hours = [int((row.get('starts_at')).hour) for _sim, row in all_with_offsets if row.get('starts_at')]
    if len(day_offsets) >= 2:
        return {
            'evidence_type': 'statistical-prior',
            'day_offset': int(round(median(day_offsets))),
            'hour': int(round(median(hours))) if hours else 9,
            'matched_sample_count': len(all_with_offsets),
            'confidence': round(min(84.0, 60.0 + min(len(day_offsets), 12) * 1.6), 1),
        }
    return None


def _apply_historical_recommendation_pipeline(base_placements, context):
    if not base_placements:
        return []

    from django.utils import timezone

    rec_ctx = _build_historical_recommendation_context(context or {})
    current_features = rec_ctx.get('current_features') or {}
    entry_date = current_features.get('entry_date')
    priors = rec_ctx.get('priors') or {}
    today = timezone.now().date()

    out = []
    for p in base_placements:
        row = dict(p)
        code = (row.get('code') or '').strip()
        inferred = _infer_timing_for_service(code, rec_ctx)

        base_score = float(row.get('score') or 0.0)
        base_reason = (row.get('reason') or '').strip()

        if inferred:
            anchor_date = entry_date or today
            day_offset = max(0, int(inferred.get('day_offset') or 0))
            target_date = anchor_date + timedelta(days=day_offset)
            if target_date < today:
                target_date = today

            hour = max(8, min(18, int(inferred.get('hour') or 9)))
            minute = 0
            dur = int(row.get('duration_minutes') or 60)

            tz = timezone.get_current_timezone()
            starts_at = timezone.make_aware(datetime.combine(target_date, time(hour, minute)), tz)
            ends_at = starts_at + timedelta(minutes=dur)

            row['starts_at'] = starts_at
            row['ends_at'] = ends_at
            row['matched_historical_sample_count'] = int(inferred.get('matched_sample_count') or 0)
            row['similar_historical_sample_count'] = row['matched_historical_sample_count']
            row['suggested_day_offset_from_entry'] = day_offset
            row['recommendation_evidence_type'] = inferred.get('evidence_type') or 'historical-match'
            row['score'] = round(max(base_score, float(inferred.get('confidence') or base_score)), 1)
            row['recommendation_source'] = 'historical'
            row['reason'] = (
                (base_reason + '; ') if base_reason else ''
            ) + (
                f"evidence={inferred.get('evidence_type')}; "
                f"samples={row['matched_historical_sample_count']}; "
                f"offset≈{day_offset}d; hour≈{hour}"
            )
        else:
            row['matched_historical_sample_count'] = 0
            row['similar_historical_sample_count'] = 0
            row['suggested_day_offset_from_entry'] = None
            row['recommendation_evidence_type'] = 'rule-based-fallback'
            row['score'] = round(base_score, 1)
            row['recommendation_source'] = 'fallback'
            row['reason'] = (
                (base_reason + '; ') if base_reason else ''
            ) + 'evidence=rule-based-fallback; samples=0'

        if row.get('service_type') == 'IN_PERSON_AGENT' and not row.get('assigned_agent_id'):
            row['needs_review'] = True

        row['needs_review'] = bool(row.get('needs_review')) or (float(row.get('score') or 0.0) < ADMIN_REVIEW_SCORE_THRESHOLD)
        out.append(row)

    out = apply_grouping_pattern_adjustments(
        out,
        priors.get('grouping_pair_priors') or {},
    )

    sequence_priors = priors.get('sequence_priors_by_service') or {}
    by_code = {
        (row.get('code') or '').strip().upper(): row
        for row in out
        if (row.get('code') or '').strip()
    }
    for code, row in by_code.items():
        seq = sequence_priors.get(code)
        if not seq:
            continue
        if float(seq.get('confidence') or 0.0) < 0.6:
            continue
        prev_code = (seq.get('likely_predecessor') or '').strip().upper()
        prev_row = by_code.get(prev_code)
        if not prev_row or not prev_row.get('starts_at') or not row.get('starts_at'):
            continue
        if row['starts_at'] < prev_row['starts_at']:
            target_date = prev_row['starts_at'].date() + timedelta(days=1)
            row['starts_at'] = row['starts_at'].replace(
                year=target_date.year,
                month=target_date.month,
                day=target_date.day,
            )
            row['ends_at'] = row['starts_at'] + timedelta(minutes=int(row.get('duration_minutes') or 60))
            base_reason = (row.get('reason') or '').strip()
            row['reason'] = (
                (base_reason + '; ') if base_reason else ''
            ) + f"sequence-prior={prev_code}->{code}; conf={seq.get('confidence')}"

    out = apply_remaining_days_policy(out, current_features)

    return out


def recommend_schedule_placements(context, submission=None):
    """
    추천 레이어(ML-ready abstraction):
    1) 현재 컨텍스트 생성/정규화
    2) historical similarity/pattern match 추천
    3) statistical prior 추천
    4) deterministic rule fallback
    """
    if not context:
        return []
    services = context.get('services_with_meta') or []
    if not services:
        return []

    if context.get('agent_windows_by_agent'):
        base_placements = suggest_placements_with_availability(
            services,
            context.get('entry_date'),
            context.get('agent_windows_by_agent') or {},
            context.get('preferred_agent_id'),
            context.get('state_code'),
            submission=submission,
        )
    else:
        base_placements = suggest_placements(
            services,
            context.get('entry_date'),
            context.get('agent_windows_by_agent') or {},
            context.get('preferred_agent_id'),
        )
    if not base_placements:
        return []
    return _apply_historical_recommendation_pipeline(base_placements, context)


def _persist_draft_schedule_plan(submission, quote, customer, placements, actor=None):
    """placement 결과를 ServiceSchedulePlan/Item으로 저장."""
    from .models import ServiceSchedulePlan, ServiceScheduleItem

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
        recommendation_metadata = {
            'confidence_score': float(p.get('score') or 0.0),
            'recommendation_reason': (p.get('reason') or ''),
            'evidence_type': (p.get('recommendation_evidence_type') or ''),
            'similar_historical_sample_count': int(p.get('similar_historical_sample_count') or 0),
            'suggested_day_offset_from_entry': p.get('suggested_day_offset_from_entry'),
            'needs_admin_review': bool(p.get('needs_review')),
            'recommendation_source': (p.get('recommendation_source') or 'fallback'),
            'remaining_days_band': p.get('remaining_days_band'),
            'remaining_days_value': p.get('remaining_days_value'),
        }
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
            recommendation_source=(p.get('recommendation_source') or 'fallback')[:30],
            needs_admin_review=bool(p.get('needs_review')),
            recommendation_metadata=recommendation_metadata,
            notes=notes[:500] if notes else '',
            sort_order=idx + 1,
        )
    return schedule_plan


def _filter_services_for_schedule_draft(services_with_meta, service_type_whitelist=None):
    """
    서비스 타입 화이트리스트가 주어지면 해당 타입만 초안 생성 대상으로 남긴다.
    service_type_whitelist 예: {'IN_PERSON_AGENT'}
    """
    if not services_with_meta:
        return []
    if not service_type_whitelist:
        return list(services_with_meta)
    allowed = {str(t).strip() for t in service_type_whitelist if str(t).strip()}
    if not allowed:
        return list(services_with_meta)
    out = []
    for svc in services_with_meta:
        stype = (svc.get('service_type') or DEFAULT_SERVICE_TYPE).strip()
        if stype in allowed:
            out.append(svc)
    return out


def ensure_submission_schedule_draft(submission, actor=None, service_type_whitelist=None):
    """
    설문 제출 기준 Admin 검토용 스케줄 draft를 1회 보장한다.
    - idempotent: 같은 submission의 DRAFT/REVIEWING 플랜이 이미 있으면 재생성하지 않음.
    - service_type_whitelist를 주면 해당 타입 서비스만 초안 대상.
    Returns: (plan_or_none, created_bool)
    """
    from .models import ServiceSchedulePlan

    if not submission or not getattr(submission, 'user_id', None):
        return None, False

    existing = (
        ServiceSchedulePlan.objects.filter(
            submission=submission,
            status__in=(ServiceSchedulePlan.Status.DRAFT, ServiceSchedulePlan.Status.REVIEWING),
        )
        .order_by('-updated_at')
        .first()
    )
    if existing:
        return existing, False

    try:
        plan = generate_schedule_draft(
            submission,
            quote=None,
            plan=None,
            actor=actor,
            service_type_whitelist=service_type_whitelist,
        )
        return plan, True
    except ValueError:
        return None, False


def generate_schedule_draft(submission, quote=None, plan=None, actor=None, service_type_whitelist=None):
    """
    Rule-based (or later ML) schedule draft 생성.
    submission: SurveySubmission (required)
    quote: SettlementQuote (optional; 없으면 submission에서 서비스 목록 추출)
    plan: UserSettlementPlan (optional; customer 확보용)
    actor: User (optional; created_by/updated_by)
    Returns: ServiceSchedulePlan (DRAFT, source=HYBRID or ML).
    """
    from .models import ServiceSchedulePlan

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

    services_for_draft = _filter_services_for_schedule_draft(
        context.get('services_with_meta') or [],
        service_type_whitelist=service_type_whitelist,
    )
    if not services_for_draft:
        raise ValueError('No schedulable services for submission')

    working_context = dict(context)
    working_context['services_with_meta'] = services_for_draft
    placements = recommend_schedule_placements(working_context, submission=submission)
    if not placements:
        raise ValueError('no recommendation placements')

    return _persist_draft_schedule_plan(
        submission=submission,
        quote=quote,
        customer=customer,
        placements=placements,
        actor=actor,
    )


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
        it.recommendation_source = (place.get('recommendation_source') or 'rule_based')[:30]
        it.needs_admin_review = bool(place.get('needs_review'))
        it.recommendation_metadata = {
            'confidence_score': float(place.get('score') or 0.0),
            'recommendation_reason': (place.get('reason') or ''),
            'evidence_type': (place.get('recommendation_evidence_type') or ''),
            'similar_historical_sample_count': int(place.get('similar_historical_sample_count') or 0),
            'suggested_day_offset_from_entry': place.get('suggested_day_offset_from_entry'),
            'needs_admin_review': bool(place.get('needs_review')),
            'recommendation_source': (place.get('recommendation_source') or 'rule_based'),
            'remaining_days_band': place.get('remaining_days_band'),
            'remaining_days_value': place.get('remaining_days_value'),
        }
        it.notes = 'Admin 검토 권장' if place.get('needs_review') else ''
        it.save(update_fields=['starts_at', 'ends_at', 'assigned_agent_id', 'source_score', 'source_reason', 'recommendation_source', 'needs_admin_review', 'recommendation_metadata', 'notes'])
        updated += 1
    return updated
