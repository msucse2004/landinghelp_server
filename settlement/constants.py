"""
정착 서비스 종류 및 카테고리 (DB 기반)
"""
# 카테고리 순서 (SettlementService.Category display 값)
CATEGORY_ORDER = ['주거/임대', '교통/차량', '생활편의', '의료/교육', '행정/문서', '기타']

# 코드 → 우선순위 (스케줄 생성 시 사용, DB에 없으면 order 기반)
SCHEDULE_PRIORITY = {
    'SSN_APPLICATION': 1, 'AIRPORT_PICKUP': 2, 'PHONE_SETUP': 3, 'BANK_ACCOUNT': 4,
    'RENTAL_APPROVAL': 5, 'RENTAL_SUPPORT': 6, 'HOUSING_TOUR': 7, 'HOUSING_RESEARCH': 8,
    'RENTAL_CONTRACT': 9, 'UTILITY_SETUP': 10, 'DRIVERS_LICENSE': 11, 'VEHICLE_PURCHASE': 12,
    'VEHICLE_REGISTRATION': 13, 'VEHICLE_RENT': 14, 'HOSPITAL_VISIT': 15, 'SCHOOL_VISIT': 16,
    'HOUSING_VIDEO': 17, 'AREA_TOUR': 18,
}


def _get_services_qs():
    from .models import SettlementService
    return SettlementService.objects.filter(is_active=True).order_by('category', 'name')


def get_services_by_category():
    """카테고리별 서비스 딕셔너리 (템플릿용) - DB에서 읽음"""
    result = {}
    for s in _get_services_qs():
        cat = s.get_category_display()
        key = s.code or str(s.id)
        result.setdefault(cat, []).append((key, s.name))
    return {cat: result[cat] for cat in CATEGORY_ORDER if cat in result}


def get_all_service_codes():
    """LLM 매칭용: 전체 서비스 코드/ id 목록"""
    return [s.code or str(s.id) for s in _get_services_qs()]


def get_service_label(code_or_id):
    """코드 또는 id → 한글명"""
    from .models import SettlementService
    s = SettlementService.objects.filter(code=code_or_id).first()
    if not s and code_or_id:
        try:
            s = SettlementService.objects.filter(id=int(code_or_id)).first()
        except (TypeError, ValueError):
            pass
    return s.name if s else str(code_or_id)


def get_schedule_ordered_services(codes: list) -> list:
    """우선순위 기준으로 서비스 정렬"""
    return sorted(codes, key=lambda c: SCHEDULE_PRIORITY.get(str(c), 99))


def calc_checkout_total(schedule: dict, free_agent_service_codes=None, agent_assigned_only=True):
    """
    일정(schedule)에서 과금 대상 합계 반환. (total, breakdown)
    - agent_assigned_only: True면 Agent가 할당된(Agent support 요청된) 항목만 과금. False면 스케줄 전체 서비스 과금.
    - free_agent_service_codes: 요금제 무료 Agent 서비스 코드 집합/목록이면 해당 서비스는 0원 처리.
    """
    from decimal import Decimal
    from .models import SettlementService
    from django.db.models import Q

    # Agent 할당된 항목의 서비스 코드만 수집 (과금 대상)
    codes = set()
    if schedule and isinstance(schedule, dict):
        for date_str, items in schedule.items():
            for item in items or []:
                if not isinstance(item, dict):
                    if isinstance(item, (list, tuple)) and len(item) >= 1 and not agent_assigned_only:
                        codes.add(item[0])
                    continue
                code = item.get('code')
                if not code:
                    continue
                if agent_assigned_only and not item.get('agent_id'):
                    continue
                codes.add(code)

    free_set = set(free_agent_service_codes or [])

    total = Decimal('0')
    breakdown = []
    for code in codes:
        q = Q(code=code)
        if code and str(code).isdigit():
            q = q | Q(id=int(code))
        svc = SettlementService.objects.filter(q).first()
        if svc:
            price = Decimal('0') if code in free_set else (svc.customer_price or Decimal('0'))
            total += price
            breakdown.append((svc.name, price))

    return total, breakdown


def schedule_has_agent_assignment(schedule: dict) -> bool:
    """일정(schedule)에 Agent가 하나라도 할당되어 있으면 True"""
    if not schedule or not isinstance(schedule, dict):
        return False
    for date_str, items in schedule.items():
        for item in items or []:
            if isinstance(item, dict) and item.get('agent_id'):
                return True
    return False


# AgentAppointmentRequest 상태 → 사용자 표시 라벨
APPOINTMENT_STATUS_LABELS = {
    'PENDING': '에이전트 수락 대기',
    'CONFIRMED': '약속 확정',
    'CANCELLED': '취소',
}


def enrich_schedule_with_appointment_status(user, schedule: dict):
    """
    일정의 각 항목에 customer·(service_date, service_code) 기준으로 약속을 매핑하여 반환.

    약속 데이터는 항상 DB의 AgentAppointmentRequest에서만 읽음 (admin/customer/agent 공통).
    - schedule: UserSettlementPlan.service_schedule (날짜·서비스 슬롯만 보관, 약속 내용 아님).
    - 실제 약속(상태·에이전트·메시지 등)은 이 함수 내부에서 AgentAppointmentRequest 쿼리로 조회.
    - (date, code)에 해당하는 약속이 있으면 agent_id, status 등 상세를 붙여 반환.
    """
    if not user or not user.is_authenticated or not schedule or not isinstance(schedule, dict):
        return schedule if schedule else {}
    from .models import AgentAppointmentRequest
    from messaging.models import Conversation

    # (service_date, service_code)당 최신 약속 1건만 사용 (customer 매핑됨).
    appts = list(
        AgentAppointmentRequest.objects.filter(customer=user)
        .select_related('agent')
        .order_by('-created_at')
    )
    appt_ids = [a.id for a in appts]
    conv_by_appointment = {}
    if appt_ids:
        for c in Conversation.objects.filter(appointment_id__in=appt_ids).values('id', 'appointment_id'):
            conv_by_appointment[c['appointment_id']] = c['id']
    # (date_str, code) -> { agent_id, agent_name, status, ... } (먼저 나온 것 = 최신)
    by_date_code = {}
    for a in appts:
        date_str = str(a.service_date)
        code = (a.service_code or '').strip()
        if not code:
            continue
        key = (date_str, code)
        if key in by_date_code:
            continue
        agent = a.agent
        by_date_code[key] = {
            'appointment_id': a.id,
            'conversation_id': conv_by_appointment.get(a.id),
            'agent_id': agent.id if agent else None,
            'agent_name': (agent.get_full_name() or (agent.username if agent else '')) or 'Agent',
            'status': a.status,
            'status_label': APPOINTMENT_STATUS_LABELS.get(a.status, a.status),
            'preferred_time': a.preferred_time or '',
            'message': a.message or '',
            'created_at': a.created_at.strftime('%Y-%m-%d %H:%M') if a.created_at else '',
        }

    result = {}
    for date_str, items in schedule.items():
        if not isinstance(items, list):
            result[date_str] = items
            continue
        new_items = []
        for item in items or []:
            if not isinstance(item, dict):
                new_items.append(item)
                continue
            new_item = dict(item)
            code = (new_item.get('code') or '').strip()
            key = (date_str, code)
            detail = by_date_code.get(key)
            if detail:
                new_item['appointment_id'] = detail.get('appointment_id')
                new_item['conversation_id'] = detail.get('conversation_id')
                new_item['agent_id'] = new_item.get('agent_id') or detail['agent_id']
                new_item['agent_name'] = new_item.get('agent_name') or detail['agent_name']
                new_item['appointment_status'] = detail['status']
                new_item['appointment_status_label'] = detail['status_label']
                new_item['appointment_preferred_time'] = detail['preferred_time']
                new_item['appointment_message'] = detail['message']
                new_item['appointment_created_at'] = detail['created_at']
            new_items.append(new_item)
        result[date_str] = new_items
    return result
