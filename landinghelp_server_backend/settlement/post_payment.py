"""
결제(PAID) 후 스케줄·에이전트 단계 자동 준비.
승인된 견적(quote.items)을 기준으로 UserSettlementPlan.service_schedule 초기화 및
PlanServiceTask(필요 작업) 생성. Admin이 작업 목록·배정 현황 확인용.
"""
from datetime import date, timedelta

from .constants import get_schedule_ordered_services
from .models import PlanServiceTask, UserSettlementPlan


def build_initial_schedule_from_quote(quote):
    """
    견적 항목으로 UserSettlementPlan.service_schedule 초기 구조 생성.
    entry_date가 있으면 그 주간으로, 없으면 오늘+7일 기준. 항목은 SCHEDULE_PRIORITY 순.
    반환: {"YYYY-MM-DD": [{"code":"X","label":"Y"}, ...], ...}
    """
    items = quote.items or []
    if not items:
        return {}
    code_to_label = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        code = (it.get('code') or '').strip()
        label = (it.get('label') or code or '').strip()
        if code:
            code_to_label[code] = label
    if not code_to_label:
        return {}
    ordered = get_schedule_ordered_services(list(code_to_label.keys()))
    base_date = date.today() + timedelta(days=7)
    if quote.submission_id:
        try:
            from survey.quote_input import get_quote_input_data
            data = get_quote_input_data(quote.submission)
            ed = data.get('entry_date')
            if ed:
                if isinstance(ed, str) and len(ed) >= 10:
                    base_date = date(int(ed[:4]), int(ed[5:7]), int(ed[8:10]))
                elif hasattr(ed, 'year'):
                    base_date = ed
        except Exception:
            pass
    # 단일 날짜에 전체 항목 배치 (기존과 동일). 고객/Admin이 날짜 배정 시 변경 가능.
    date_str = base_date.isoformat()
    slots = [{'code': c, 'label': code_to_label.get(c, c)} for c in ordered]
    return {date_str: slots}


def ensure_plan_service_tasks(plan, quote):
    """
    결제된 견적 항목으로 PlanServiceTask 생성(이미 있으면 건너뜀).
    Admin이 "필요 작업" 목록으로 확인·에이전트 배정 현황 파악.
    """
    if not plan or not quote or not quote.items:
        return
    from .constants import get_schedule_ordered_services
    codes_seen = set()
    order = 0
    all_codes = []
    for it in quote.items:
        if not isinstance(it, dict):
            continue
        code = (it.get('code') or '').strip()
        if not code or code in codes_seen:
            continue
        codes_seen.add(code)
        all_codes.append((code, it.get('label') or code))
    ordered_codes = get_schedule_ordered_services([c for c, _ in all_codes])
    code_to_label = dict(all_codes)
    for code in ordered_codes:
        label_str = code_to_label.get(code, code)
        order += 1
        PlanServiceTask.objects.get_or_create(
            plan=plan,
            service_code=code,
            defaults={'label': (label_str or code)[:200], 'display_order': order},
        )
