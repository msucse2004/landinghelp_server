"""
정착 서비스 종류 및 카테고리 (DB 기반)
"""
# 카테고리 순서 (SettlementService.Category display 값)
CATEGORY_ORDER = ['주거/임대', '교통/차량', '생활편의', '의료/교육', '행정/문서', '기타']

# 코드 → 우선순위 (스케줄 생성 시 사용, DB에 없으면 order 기반)
SCHEDULE_PRIORITY = {
    'SSN_APPLICATION': 1, 'SSN_APPOINTMENT': 1, 'SSN_ACCOMPANIMENT': 2,
    'AIRPORT_PICKUP': 3, 'PHONE_SETUP': 4, 'BANK_ACCOUNT': 5,
    'RENTAL_APPROVAL': 6, 'RENTAL_SUPPORT': 7, 'HOUSING_TOUR': 8, 'HOUSING_RESEARCH': 9,
    'RENTAL_CONTRACT': 10, 'RENTAL_CHECK_PAYMENT': 11, 'UTILITY_SETUP': 12,
    'UTILITY_ACCOUNT_SETUP': 13, 'RENTER_INSURANCE': 14,
    'DRIVERS_LICENSE': 15, 'DMV_WRITTEN_TEST': 16, 'DMV_ROAD_TEST': 17,
    'CONSULATE_LICENSE_CERT': 18, 'VEHICLE_PURCHASE': 19, 'VEHICLE_INSURANCE': 20,
    'VEHICLE_REGISTRATION': 21, 'VEHICLE_RENT': 22, 'VEHICLE_RENT_RETURN': 23,
    'HOSPITAL_VISIT': 24, 'PUBLIC_SCHOOL_ENROLLMENT': 25, 'PRIVATE_SCHOOL_SUPPORT': 26,
    'SCHOOL_VISIT': 27, 'HEALTH_INSURANCE': 28,
    'HOUSING_VIDEO': 29, 'HOUSE_KEY_PICKUP': 30, 'AREA_TOUR': 31,
    'AMAZON_PURCHASE': 32, 'LLC_FORMATION': 33,
}

# 주 전체 이름 → 2글자 코드 (Agent 담당 주 매칭용; "North Carolina" → "NC")
_US_STATE_NAMES_TO_CODE = {
    'ALABAMA': 'AL', 'ALASKA': 'AK', 'ARIZONA': 'AZ', 'ARKANSAS': 'AR',
    'CALIFORNIA': 'CA', 'COLORADO': 'CO', 'CONNECTICUT': 'CT',
    'DELAWARE': 'DE', 'FLORIDA': 'FL', 'GEORGIA': 'GA', 'HAWAII': 'HI',
    'IDAHO': 'ID', 'ILLINOIS': 'IL', 'INDIANA': 'IN', 'IOWA': 'IA',
    'KANSAS': 'KS', 'KENTUCKY': 'KY', 'LOUISIANA': 'LA', 'MAINE': 'ME',
    'MARYLAND': 'MD', 'MASSACHUSETTS': 'MA', 'MICHIGAN': 'MI', 'MINNESOTA': 'MN',
    'MISSISSIPPI': 'MS', 'MISSOURI': 'MO', 'MONTANA': 'MT', 'NEBRASKA': 'NE',
    'NEVADA': 'NV', 'NEW HAMPSHIRE': 'NH', 'NEW JERSEY': 'NJ', 'NEW MEXICO': 'NM',
    'NEW YORK': 'NY', 'NORTH CAROLINA': 'NC', 'NORTH DAKOTA': 'ND', 'OHIO': 'OH',
    'OKLAHOMA': 'OK', 'OREGON': 'OR', 'PENNSYLVANIA': 'PA', 'RHODE ISLAND': 'RI',
    'SOUTH CAROLINA': 'SC', 'SOUTH DAKOTA': 'SD', 'TENNESSEE': 'TN', 'TEXAS': 'TX',
    'UTAH': 'UT', 'VERMONT': 'VT', 'VIRGINIA': 'VA', 'WASHINGTON': 'WA',
    'WEST VIRGINIA': 'WV', 'WISCONSIN': 'WI', 'WYOMING': 'WY',
    'WASHINGTON D.C.': 'DC',
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


# 규칙: status < FINAL_SENT인 메시지에는 금액/총액/checkout을 절대 포함하지 않는다 (코드 강제).
# 이메일·알림·API 응답 등 모든 메시지 본문에서 견적 금액을 넣을 때는 message_may_include_price()로 허용 여부 확인 후 사용.
def message_may_include_price(quote_or_status):
    """
    메시지/이메일 본문에 금액·총액·checkout을 포함해도 되는지.
    FINAL_SENT, PAID일 때만 True. 그 외(DRAFT, NEGOTIATING 등)는 False.
    """
    from .models import SettlementQuote
    if quote_or_status is None:
        return False
    if hasattr(quote_or_status, 'status'):
        status = getattr(quote_or_status, 'status', None)
    else:
        status = quote_or_status
    return status in (SettlementQuote.Status.FINAL_SENT, SettlementQuote.Status.PAID)


def can_view_price(user, quote):
    """
    고객(user)이 견적(quote)의 가격/합계를 볼 수 있는지.
    quote가 None이면 False. SettlementQuote는 status >= FINAL_SENT일 때만 True.
    소유권: submission.user == user 또는 submission.email == user.email 또는 비로그인 시 세션 등으로 별도 검증.
    """
    if not quote:
        return False
    if hasattr(quote, 'customer_can_see_prices'):
        return quote.customer_can_see_prices()
    return False


def has_pending_survey_quote(user):
    """
    사용자가 미송부 견적(status < FINAL_SENT)을 가진 설문 제출이 있으면 True.
    이 경우 달력/대시보드에서도 가격 비노출 정책 적용용.
    """
    if not user or not user.is_authenticated:
        return False
    from .models import SettlementQuote
    from survey.models import SurveySubmission
    sub = SurveySubmission.objects.filter(user=user, status=SurveySubmission.Status.SUBMITTED).order_by('-submitted_at').first()
    if not sub:
        return False
    q = SettlementQuote.objects.filter(submission=sub).order_by('-updated_at').first()
    return q is not None and not q.customer_can_see_prices()


def customer_can_assign_agent(user):
    """
    고객이 전담 Agent를 배정할 수 있는지. 결제(PAID) 후에만 True.
    Agent 목록/가격 노출도 이 조건으로 제한.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'role', None) == 'AGENT':
        return False
    from .models import SettlementQuote
    return SettlementQuote.objects.filter(
        submission__user=user,
        status=SettlementQuote.Status.PAID,
    ).exists()


def quote_for_customer(quote):
    """
    고객 노출용 견적 딕셔너리. status < FINAL_SENT이면 가격/합계 비노출(정책 강제).
    API/뷰에서 고객에게 견적 내려줄 때 이 함수 사용.
    """
    if not quote:
        return None
    can_see_prices = quote.customer_can_see_prices()
    items = []
    for it in (quote.items or []):
        if not isinstance(it, dict):
            continue
        item = dict(it)
        item.pop('_auto', None)
        item.pop('_needs_review', None)
        if not can_see_prices:
            item.pop('price', None)
            item['_masked'] = True  # 프론트에서 '견적 후 공개' 등 표시용
        items.append(item)
    return {
        'id': quote.id,
        'status': quote.status,
        'region': quote.region or '',
        'items': items,
        'total': int(quote.total or 0) if can_see_prices else None,
        'version': quote.version,
        'sent_at': quote.sent_at.isoformat() if quote.sent_at else None,
    }


def _normalize_state_code(region_or_state):
    """지역/State 문자열에서 2글자 State 코드 추출 (예: 'NC, Morrisville' -> 'NC', 'North Carolina' -> 'NC')."""
    if not region_or_state or not isinstance(region_or_state, str):
        return ''
    s = (region_or_state or '').strip()
    if not s:
        return ''
    # 쉼표 있으면 앞부분만 (e.g. "NC, Morrisville" or "North Carolina, Raleigh")
    if ',' in s:
        s = s.split(',')[0].strip()
    s_upper = s.upper()
    # 전체 주 이름이면 2글자 코드로 변환 (North Carolina -> NC)
    if s_upper in _US_STATE_NAMES_TO_CODE:
        return _US_STATE_NAMES_TO_CODE[s_upper]
    # 이미 2글자 코드인 경우 (NC, CA 등)
    if len(s_upper) >= 2:
        return s_upper[:2]
    return s_upper


def get_service_customer_price(service_code, state_code=None):
    """
    서비스 코드 + State 코드로 Customer 가격(USD) 반환.
    ServiceStatePrice에 해당 state가 있으면 그 가격, 없으면 SettlementService.customer_price.
    """
    from decimal import Decimal
    from .models import SettlementService, ServiceStatePrice
    svc = SettlementService.objects.filter(code=service_code).first()
    if not svc:
        try:
            svc = SettlementService.objects.filter(id=int(service_code)).first()
        except (TypeError, ValueError):
            pass
    if not svc:
        return Decimal('0')
    state = (state_code or '').strip().upper()[:2] if state_code else ''
    if state:
        sp = ServiceStatePrice.objects.filter(service=svc, state_code=state).first()
        if sp is not None:
            return Decimal(str(sp.customer_price or 0))
    return Decimal(str(svc.customer_price or 0))


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
