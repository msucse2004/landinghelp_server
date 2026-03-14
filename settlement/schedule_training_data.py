from datetime import date

from survey.quote_input import get_quote_input_data

from .models import ServiceScheduleItem, ServiceSchedulePlan


TRAINING_ELIGIBLE_PLAN_STATUSES = (
    ServiceSchedulePlan.Status.SENT,
    ServiceSchedulePlan.Status.ACTIVE,
)


def _parse_entry_date(value):
    if value is None:
        return None
    if hasattr(value, 'year'):
        return value
    raw = str(value or '').strip()
    if len(raw) < 10:
        return None
    try:
        return date(int(raw[:4]), int(raw[5:7]), int(raw[8:10]))
    except (ValueError, TypeError):
        return None


def _extract_state_code(quote_input_data):
    settlement_state = (quote_input_data.get('settlement_state') or '').strip().upper()
    if settlement_state:
        return settlement_state
    region = (quote_input_data.get('region') or '').strip()
    if not region:
        return ''
    return region.split(',')[0].strip().upper()


def _is_item_complete_for_training(item):
    if not (item.service_code or '').strip():
        return False
    if not item.starts_at or not item.ends_at:
        return False
    if item.ends_at <= item.starts_at:
        return False
    return True


def _plan_relevant_items(plan, service_types):
    relevant = []
    for item in getattr(plan, 'prefetched_items_for_training', []):
        if item.status == ServiceScheduleItem.ItemStatus.CANCELLED:
            continue
        if service_types and item.service_type not in service_types:
            continue
        relevant.append(item)
    return relevant


def get_training_eligible_schedule_items(
    *,
    service_codes=None,
    service_types=None,
    max_items=500,
):
    """
    추천/학습용 과거 일정 예시를 중앙 정의로 반환한다.

    포함 조건:
    - 고객 전달/실행 상태 플랜(SENT/ACTIVE)
    - submission에서 entry_date 추출 가능
    - 관련 서비스 아이템이 모두 complete(start/end/code 유효)

    제외 조건:
    - 임시 draft/review/finalized(LSA sent draft)
    - partial/corrupted item을 포함한 플랜
    - entry_date 컨텍스트 없는 플랜
    """
    normalized_codes = {
        (code or '').strip().upper()
        for code in (service_codes or [])
        if (code or '').strip()
    }
    normalized_types = {
        (stype or '').strip()
        for stype in (service_types or [])
        if (stype or '').strip()
    }
    if not normalized_types:
        normalized_types = {ServiceScheduleItem.ServiceType.IN_PERSON_AGENT}

    plans = list(
        ServiceSchedulePlan.objects.filter(
            status__in=TRAINING_ELIGIBLE_PLAN_STATUSES,
            submission__isnull=False,
        )
        .select_related('submission')
        .prefetch_related('items')
        .order_by('-updated_at')
    )

    rows = []
    for plan in plans:
        plan.prefetched_items_for_training = list(plan.items.all())
        relevant_items = _plan_relevant_items(plan, normalized_types)
        if not relevant_items:
            continue
        if any(not _is_item_complete_for_training(item) for item in relevant_items):
            continue

        quote_input = get_quote_input_data(plan.submission) if plan.submission_id else {}
        entry_date = _parse_entry_date(quote_input.get('entry_date'))
        if not entry_date:
            continue

        state_code = _extract_state_code(quote_input)

        # 플랜 전체 일정이 몇 주에 걸쳐 있는지. 서비스 수/Agent 스케줄 패턴 차이를 반영.
        all_item_starts = sorted(
            it.starts_at for it in plan.prefetched_items_for_training
            if it.starts_at and it.status != ServiceScheduleItem.ItemStatus.CANCELLED
        )
        if len(all_item_starts) >= 2:
            span_days = (all_item_starts[-1].date() - all_item_starts[0].date()).days
            schedule_week_span = round(span_days / 7.0, 1)
        else:
            schedule_week_span = 0.0

        for item in relevant_items:
            code = (item.service_code or '').strip()
            normalized_code = code.upper()
            if normalized_codes and normalized_code not in normalized_codes:
                continue
            rows.append({
                'plan_id': plan.id,
                'item_id': item.id,
                'service_code': normalized_code,
                'starts_at': item.starts_at,
                'entry_date': entry_date,
                'state_code': state_code,
                'schedule_week_span': schedule_week_span,
                'assigned_agent_id': item.assigned_agent_id,
                'plan': plan,
                'submission': plan.submission,
                'item': item,
                'quote_input_data': quote_input,
            })
            if len(rows) >= max_items:
                return rows

    return rows


def get_training_eligible_historical_examples(
    *,
    service_codes=None,
    service_types=None,
    max_items=500,
):
    rows = get_training_eligible_schedule_items(
        service_codes=service_codes,
        service_types=service_types,
        max_items=max_items,
    )

    out = []
    for row in rows:
        out.append({
            'plan_id': row['plan_id'],
            'item_id': row['item_id'],
            'service_code': row['service_code'],
            'starts_at': row['starts_at'],
            'entry_date': row['entry_date'],
            'state_code': row['state_code'],
        })
    return out
