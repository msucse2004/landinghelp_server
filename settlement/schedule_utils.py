"""
스케줄 도메인 유틸: 신규 ServiceSchedulePlan/Item과 기존 UserSettlementPlan.service_schedule JSON 호환.

- 달력/대시보드: get_schedule_for_display(user_or_plan)으로 통일.
  새 플랜(ACTIVE/SENT)이 있으면 plan_to_legacy_schedule()로 변환해 반환, 없으면 기존 service_schedule JSON 사용.
- 구 JSON → 새 엔티티: legacy_schedule_to_items(schedule_plan, legacy_json)로 Item 생성.
  필요 시 ensure_schedule_plan_from_plan(plan)으로 기존 UserSettlementPlan에서 ServiceSchedulePlan+Item 생성 가능.
"""
from datetime import datetime
from django.utils import timezone


def get_schedule_for_display(user_or_plan):
    """
    달력/대시보드 렌더링용 일정 dict 반환. 기존 형식 유지: {"YYYY-MM-DD": [{"code","label", ...}, ...]}.
    - user_or_plan: User 또는 UserSettlementPlan.
    - 우선: 해당 고객의 ACTIVE/SENT 상태 ServiceSchedulePlan이 있으면 plan_to_legacy_schedule()로 변환해 반환.
    - 없으면: UserSettlementPlan.service_schedule 그대로 반환 (기존 동작).
    """
    from .models import ServiceSchedulePlan, UserSettlementPlan

    user = None
    plan = None
    if hasattr(user_or_plan, 'settlement_plan'):
        user = user_or_plan
        try:
            plan = user.settlement_plan
        except UserSettlementPlan.DoesNotExist:
            plan = None
    elif hasattr(user_or_plan, 'user'):
        plan = user_or_plan
        user = plan.user
    else:
        return {}

    # 새 모델: 고객 기준 ACTIVE 또는 SENT 플랜 1건 사용
    if user:
        schedule_plan = (
            ServiceSchedulePlan.objects.filter(
                customer=user,
                status__in=(ServiceSchedulePlan.Status.ACTIVE, ServiceSchedulePlan.Status.SENT),
            )
            .order_by('-updated_at')
            .first()
        )
        if schedule_plan:
            return plan_to_legacy_schedule(schedule_plan, customer_safe=True)

    # 기존: UserSettlementPlan.service_schedule JSON
    if plan and getattr(plan, 'service_schedule', None) and isinstance(plan.service_schedule, dict):
        return plan.service_schedule
    return {}


def plan_to_legacy_schedule(service_schedule_plan, customer_safe=False):
    """
    ServiceSchedulePlan + items 를 기존 달력 형식 dict로 변환.
    반환: {"YYYY-MM-DD": [{"code", "label", "service_type", "agent_id", "agent_name", ...}, ...], ...}
    service_type: SELF_SEARCH | AI_AGENT | IN_PERSON_AGENT (고객 달력 서비스 타입별 렌더링용).
    """
    from .models import ServiceScheduleItem
    if not service_schedule_plan:
        return {}
    items = list(
        service_schedule_plan.items.filter(
            status__in=(ServiceScheduleItem.ItemStatus.SCHEDULED, ServiceScheduleItem.ItemStatus.CONFIRMED)
        ).select_related('assigned_agent').order_by('sort_order', 'starts_at', 'id')
    )
    if not items:
        return {}
    out = {}
    for it in items:
        date_key = None
        if it.starts_at:
            date_key = it.starts_at.date().isoformat()
        else:
            date_key = timezone.now().date().isoformat()
        entry = {
            'code': it.service_code or '',
            'label': it.service_label or it.service_code or '',
            'service_type': (it.service_type or ServiceScheduleItem.ServiceType.AI_AGENT),
        }
        if it.starts_at:
            entry['starts_at'] = it.starts_at.isoformat()
        if it.ends_at:
            entry['ends_at'] = it.ends_at.isoformat()
        if (not customer_safe) and it.notes:
            entry['notes'] = (it.notes or '')[:1000]
        if (not customer_safe) and it.location_text:
            entry['location_text'] = (it.location_text or '')[:500]
        if it.assigned_agent_id and not customer_safe:
            entry['agent_id'] = it.assigned_agent_id
            if it.assigned_agent:
                entry['agent_name'] = (it.assigned_agent.get_full_name() or it.assigned_agent.username or '')
            else:
                entry['agent_name'] = ''
        elif it.assigned_agent and customer_safe:
            entry['agent_name'] = (it.assigned_agent.get_full_name() or it.assigned_agent.username or '')
        if date_key not in out:
            out[date_key] = []
        out[date_key].append(entry)
    return out


def get_paid_service_codes_for_user(user):
    """
    고객이 결제 완료한 서비스 코드 집합. PAID 상태 SettlementQuote의 items에서 code 수집.
    고객 달력에서 "구매한 서비스만" 표시할 때 사용.
    """
    if not user or not getattr(user, 'id', None):
        return set()
    from .models import SettlementQuote
    from survey.models import SurveySubmission
    sub = (
        SurveySubmission.objects.filter(user=user)
        .exclude(status=SurveySubmission.Status.DRAFT)
        .order_by('-submitted_at')
        .first()
    )
    if not sub:
        return set()
    quote = (
        SettlementQuote.objects.filter(submission=sub, status=SettlementQuote.Status.PAID)
        .order_by('-updated_at')
        .first()
    )
    if not quote or not getattr(quote, 'items', None):
        return set()
    codes = set()
    for it in (quote.items or []):
        if not isinstance(it, dict):
            continue
        code = (it.get('code') or '').strip()
        if code:
            codes.add(code)
    return codes


def filter_schedule_to_paid_services(schedule_dict, paid_codes):
    """
    schedule_dict에서 paid_codes에 있는 서비스만 남김. paid_codes가 비면 필터 없음(전체 유지).
    """
    if not schedule_dict or not isinstance(schedule_dict, dict) or not paid_codes:
        return schedule_dict
    out = {}
    for date_str, items in schedule_dict.items():
        if not isinstance(items, list):
            out[date_str] = items
            continue
        kept = [i for i in items if isinstance(i, dict) and (i.get('code') or '').strip() in paid_codes]
        if kept:
            out[date_str] = kept
    return out


def legacy_schedule_to_items(schedule_plan, legacy_json, service_type='AI_AGENT'):
    """
    기존 UserSettlementPlan.service_schedule 형식 JSON을 ServiceScheduleItem으로 변환하여 저장.
    schedule_plan: ServiceSchedulePlan 인스턴스.
    legacy_json: {"YYYY-MM-DD": [{"code","label", "agent_id"?, "agent_name"?}, ...]}.
    service_type: ServiceScheduleItem.ServiceType 기본값.
    생성된 Item 수 반환.
    """
    from .models import ServiceScheduleItem

    if not schedule_plan or not isinstance(legacy_json, dict):
        return 0
    count = 0
    sort_order = 0
    for date_str, slots in legacy_json.items():
        if not isinstance(slots, list):
            continue
        try:
            day = datetime.strptime(date_str, '%Y-%m-%d').date()
            base_dt = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
        except (ValueError, TypeError):
            base_dt = None
        for idx, slot in enumerate(slots):
            if not isinstance(slot, dict):
                continue
            code = (slot.get('code') or '').strip()
            if not code:
                continue
            sort_order += 1
            label = (slot.get('label') or code or '').strip()
            agent_id = slot.get('agent_id')
            starts_at = base_dt
            ends_at = None
            if base_dt:
                from datetime import timedelta
                ends_at = base_dt + timedelta(minutes=60)
            ServiceScheduleItem.objects.create(
                schedule_plan=schedule_plan,
                service_code=code,
                service_label=label[:200],
                service_type=service_type,
                sort_order=sort_order,
                starts_at=starts_at,
                ends_at=ends_at,
                duration_minutes=60,
                assigned_agent_id=agent_id if agent_id else None,
                status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            )
            count += 1
    return count


def serialize_schedule_items_for_calendar(schedule_plan):
    """
    ServiceSchedulePlan의 항목을 프론트 달력용으로 직렬화.
    Returns: list of dict with id, service_code, service_label, starts_at (iso), ends_at (iso),
             assigned_agent_id, assigned_agent_name, status, notes, sort_order.
    """
    if not schedule_plan:
        return []
    from .models import ServiceScheduleItem
    items = list(
        schedule_plan.items.exclude(status=ServiceScheduleItem.ItemStatus.CANCELLED)
        .order_by('sort_order', 'starts_at', 'id')
        .select_related('assigned_agent')
    )
    out = []
    for it in items:
        rec_meta = it.recommendation_metadata if isinstance(it.recommendation_metadata, dict) else {}
        out.append({
            'id': it.id,
            'service_code': it.service_code,
            'service_label': it.service_label or it.service_code,
            'starts_at': it.starts_at.isoformat() if it.starts_at else None,
            'ends_at': it.ends_at.isoformat() if it.ends_at else None,
            'duration_minutes': it.duration_minutes,
            'assigned_agent_id': it.assigned_agent_id,
            'assigned_agent_name': (it.assigned_agent.get_full_name() or it.assigned_agent.username) if it.assigned_agent else None,
            'status': it.status,
            'notes': it.notes or '',
            'confidence_score': float(it.source_score) if it.source_score is not None else None,
            'recommendation_reason': it.source_reason or '',
            'recommendation_source': it.recommendation_source or 'fallback',
            'evidence_type': rec_meta.get('evidence_type') or None,
            'similar_historical_sample_count': rec_meta.get('similar_historical_sample_count'),
            'suggested_day_offset_from_entry': rec_meta.get('suggested_day_offset_from_entry'),
            'remaining_days_band': rec_meta.get('remaining_days_band'),
            'remaining_days_value': rec_meta.get('remaining_days_value'),
            'recommendation_metadata': rec_meta,
            'needs_admin_review': bool(it.needs_admin_review),
            'sort_order': it.sort_order,
        })
    return out


def ensure_schedule_plan_from_plan(user_settlement_plan, status='DRAFT', source='ADMIN'):
    """
    기존 UserSettlementPlan.service_schedule JSON이 있을 때 ServiceSchedulePlan + ServiceScheduleItem 생성.
    마이그레이션/Admin에서 "기존 플랜을 새 모델로 옮기기" 필요할 때 호출.
    user_settlement_plan: UserSettlementPlan (user, service_schedule 필수).
    반환: (ServiceSchedulePlan, created: bool). 이미 해당 customer의 동일 quote/submission 플랜이 있으면 재사용.
    """
    from .models import ServiceSchedulePlan, UserSettlementPlan

    plan = user_settlement_plan
    if not plan or not getattr(plan, 'user_id', None):
        return None, False
    legacy = plan.service_schedule if isinstance(getattr(plan, 'service_schedule', None), dict) else {}
    if not legacy:
        return None, False
    customer = plan.user
    # 기존 ACTIVE/SENT 플랜이 있으면 재사용
    existing = (
        ServiceSchedulePlan.objects.filter(
            customer=customer,
            status__in=(ServiceSchedulePlan.Status.ACTIVE, ServiceSchedulePlan.Status.SENT),
        )
        .order_by('-updated_at')
        .first()
    )
    if existing:
        return existing, False
    # quote는 customer의 최신 PAID/FINAL_SENT 견적에서 가져올 수 있음 (선택)
    quote = None
    submission = None
    try:
        from .models import SettlementQuote
        q = (
            SettlementQuote.objects.filter(submission__user=customer)
            .filter(status__in=(SettlementQuote.Status.PAID, SettlementQuote.Status.FINAL_SENT))
            .order_by('-updated_at')
            .select_related('submission')
            .first()
        )
        if q:
            quote = q
            submission = getattr(q, 'submission', None)
    except Exception:
        pass
    schedule_plan = ServiceSchedulePlan.objects.create(
        customer=customer,
        submission=submission,
        quote=quote,
        status=status,
        source=source,
        version=1,
    )
    legacy_schedule_to_items(schedule_plan, legacy)
    return schedule_plan, True
