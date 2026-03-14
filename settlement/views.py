# settlement views: 견적·결제·Agent 배정·고객 수정 요청 등
# 고객 수정 요청(견적 수정/설문 재개): 직접 상태 변경 없음. customer_request_service.handle_customer_request_flow 사용.
# 상태 전이는 execute_confirmed_action(버튼 클릭) 또는 admin 승인 플로우에서만 수행.
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone
from django.utils import translation
from translations.utils import get_display_text, get_request_language, get_calendar_weekday_display


def _is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'

from billing.utils import get_user_plan_service_description, get_user_plan_policy, get_user_free_agent_services
from billing.service_tiers import get_tier_service_description

from .forms import SettlementQuoteForm
from .models import (
    SettlementQuoteRequest,
    AgentAppointmentRequest,
    SettlementService,
    UserSettlementPlan,
    SettlementQuote,
)
from .constants import (
    get_services_by_category,
    get_all_service_codes,
    get_service_label,
    get_schedule_ordered_services,
    SCHEDULE_PRIORITY,
    calc_checkout_total,
    enrich_schedule_with_appointment_status,
    CATEGORY_ORDER,
    can_view_price,
    has_pending_survey_quote,
    customer_can_assign_agent,
    quote_for_customer,
)


def settlement_quote(request):
    """서비스 견적 신청 (폼 표시 및 제출 처리). 에이전트는 달력으로, 고객은 설문으로 리다이렉트(정착 플랜 비활성화)."""
    lang = get_request_language(request)
    if request.user.is_authenticated:
        if getattr(request.user, 'role', None) == 'AGENT':
            return redirect(reverse('app_agent_appointments'))
        if getattr(request.user, 'role', None) == 'CUSTOMER':
            return redirect(reverse('survey:survey_start'))
    if request.method == 'POST':
        form = SettlementQuoteForm(request.POST)
        if form.is_valid():
            import json
            schedule = {}
            try:
                schedule = json.loads(request.POST.get('service_schedule', '{}') or '{}')
            except (ValueError, TypeError):
                pass
            name = form.cleaned_data.get('name') or ''
            email = form.cleaned_data.get('email') or ''
            if request.user.is_authenticated:
                name = name or (request.user.get_full_name() or request.user.username or '')
                email = email or (request.user.email or '')
            if not name:
                name = get_display_text('스케줄 사용자', lang)  # 스케줄 사용자
            if not email:
                email = 'schedule@placeholder.local'
            # 로그인 사용자: 요금제 무료 Agent 서비스는 0원으로 계산
            free_codes = set()
            if request.user.is_authenticated:
                free_codes = set(c for c, _ in get_user_free_agent_services(request.user))
            checkout_total, _ = calc_checkout_total(schedule, free_agent_service_codes=free_codes)
            quote = SettlementQuoteRequest(
                services=form.cleaned_data.get('services') or [],
                state=form.cleaned_data.get('state') or '',
                city=form.cleaned_data.get('city') or '',
                entry_date=form.cleaned_data.get('entry_date'),
                name=name,
                email=email,
                service_schedule=schedule,
                checkout_total=checkout_total,
                memo=form.cleaned_data.get('memo', ''),
                ai_suggested=request.POST.get('ai_suggested') == '1',
                user=request.user if request.user.is_authenticated else None,
            )
            quote.save()
            # 로그인 사용자면 UserSettlementPlan에도 저장
            if request.user.is_authenticated:
                UserSettlementPlan.objects.update_or_create(
                    user=request.user,
                    defaults={
                        'state': form.cleaned_data.get('state') or '',
                        'city': form.cleaned_data.get('city') or '',
                        'entry_date': form.cleaned_data.get('entry_date'),
                        'service_schedule': schedule,
                        'checkout_total': checkout_total,
                    }
                )
            # 결제 전 가격 비노출: 설문 견적 대기 중이면 합계를 메시지에 넣지 않음
            can_show = (not request.user.is_authenticated) or (not has_pending_survey_quote(request.user))
            if can_show:
                msg = get_display_text('스케줄이 저장되었습니다. 예상 Checkout: %(total)s원', lang) % {'total': f'{checkout_total:,.0f}'}
            else:
                msg = (get_display_text('스케줄이 저장되었습니다.', lang) or '스케줄이 저장되었습니다.') + ' ' + (get_display_text('예상 Checkout', lang) or '예상 Checkout') + ': ' + (get_display_text('견적 후 공개', lang) or '견적 후 공개')
            messages.success(request, msg)
            if _is_ajax(request):
                return JsonResponse({'success': True, 'message': msg})
            return redirect('settlement_quote')
        selected_services = request.POST.getlist('services') or []
        if _is_ajax(request):
            err_msg = get_display_text('입력값을 확인해 주세요.', lang)  # 입력값을 확인해 주세요.
            if form.errors:
                err_list = []
                for field, errs in form.errors.items():
                    err_list.extend([str(e) for e in errs])
                if err_list:
                    err_msg = '\n'.join(err_list)
            return JsonResponse({'success': False, 'message': err_msg}, status=400)
    else:
        form = SettlementQuoteForm()
        selected_services = []
        # 로그인 사용자: 저장된 UserSettlementPlan이 있으면 초기값 설정
        if request.user.is_authenticated:
            try:
                plan = request.user.settlement_plan
                if plan.state or plan.city or plan.entry_date or plan.service_schedule:
                    form = SettlementQuoteForm(initial={
                        'state': plan.state,
                        'city': plan.city,
                        'entry_date': plan.entry_date,
                    })
            except UserSettlementPlan.DoesNotExist:
                pass

    if request.user.is_authenticated:
        tier_info = get_user_plan_service_description(request.user)
        plan_policy = get_user_plan_policy(request.user)
        can_use_llm_user = plan_policy['can_use_llm']
    else:
        tier_info = get_tier_service_description(None)
        can_use_llm_user = False

    # 초기 일정: POST 실패 시 제출값, GET 시 저장된 UserSettlementPlan
    import json
    initial_schedule = {}
    if request.method == 'POST' and request.POST.get('service_schedule'):
        try:
            initial_schedule = json.loads(request.POST.get('service_schedule', '{}') or '{}')
        except (ValueError, TypeError):
            pass
    elif request.user.is_authenticated:
        try:
            plan = request.user.settlement_plan
            if plan.has_schedule():
                initial_schedule = enrich_schedule_with_appointment_status(
                    request.user, plan.service_schedule or {}
                )
                if getattr(plan, 'assigned_agent_id', None) and plan.assigned_agent:
                    for items in initial_schedule.values():
                        if not isinstance(items, list):
                            continue
                        for item in items:
                            if isinstance(item, dict) and not item.get('agent_id'):
                                item['agent_id'] = plan.assigned_agent_id
                                item['agent_name'] = plan.assigned_agent.get_full_name() or plan.assigned_agent.username or ''
        except UserSettlementPlan.DoesNotExist:
            pass

    # 저장된 플랜의 checkout 합계 (표시용) — Agent가 하나라도 할당된 경우에만 표시
    # 가격 비노출 정책: 설문 견적이 아직 송부 전(status < FINAL_SENT)이면 달력/합계도 마스킹
    can_show_plan_prices = not has_pending_survey_quote(request.user) if request.user.is_authenticated else True
    saved_checkout = 0
    if request.user.is_authenticated and can_show_plan_prices:
        try:
            plan = request.user.settlement_plan
            if plan.checkout_total and plan.has_agent_assignment():
                saved_checkout = float(plan.checkout_total)
        except UserSettlementPlan.DoesNotExist:
            pass

    raw_free_agent_services = get_user_free_agent_services(request.user) if request.user.is_authenticated else []
    free_agent_services = [(code, get_display_text(label, lang)) for code, label in raw_free_agent_services]

    # 서비스별 가격 (플로팅 요약 패널용). can_show_plan_prices False면 price 0으로 전달해 프론트에서 '견적 후 공개' 표시
    service_prices = {}
    for s in SettlementService.objects.filter(is_active=True):
        key = s.code or str(s.id)
        price = float(s.customer_price or 0) if can_show_plan_prices else 0
        service_prices[key] = {'name': s.name, 'price': price, '_masked': not can_show_plan_prices}
    service_prices_json = json.dumps(service_prices)
    # 요금제 무료 Agent 서비스 코드 (플로팅 패널에서 0원 표시 및 합계 반영)
    free_agent_service_codes = [c for c, _ in free_agent_services]
    free_agent_service_codes_json = json.dumps(free_agent_service_codes)

    # CSV(StaticTranslation) key 기준 표시 문구. export 시 key 컬럼으로 번역 조회.
    settlement_i18n = {
        'confirm_pay': get_display_text('결제하시겠습니까?', lang),
        'pay': get_display_text('결제하기', lang),
        'payment_failed': get_display_text('결제 처리에 실패했습니다.', lang),
        'request_failed': get_display_text('요청에 실패했습니다.', lang),
        'send_message': get_display_text('메시지 보내기', lang),
        'edit': get_display_text('수정', lang),
        'cancel': get_display_text('취소', lang),
        'preferred_time': get_display_text('희망 시간', lang),
        'message': get_display_text('메시지', lang),
        'additional_notes': get_display_text('추가 요청사항', lang),
        'save': get_display_text('저장', lang),
        'service': get_display_text('서비스', lang),
        'date': get_display_text('일자', lang),
        'agent': get_display_text('Agent', lang),
        'status': get_display_text('상태', lang),
        'applied_at': get_display_text('신청 일시', lang),
        'edit_failed': get_display_text('수정에 실패했습니다.', lang),
        'confirm_cancel_appointment': get_display_text('이 약속을 취소하시겠습니까?', lang),
        'cancel_failed': get_display_text('취소에 실패했습니다.', lang),
        'payment_pending': get_display_text('결재 대기', lang),
        'payment_pending_status': get_display_text('결재 대기중', lang),
        'payment_complete_hint': get_display_text('결제를 완료하면 에이전트에게 약속이 전달됩니다.', lang),
        'available_agents': get_display_text('가능한 Agent', lang),
        'loading': get_display_text('로딩 중...', lang),
        'no_agents': get_display_text('해당 지역·서비스를 담당하는 Agent가 없습니다.', lang),
        'no_rating': get_display_text('평가 없음', lang),
        'accept_rate': get_display_text('수락률', lang),
        'agents_load_failed': get_display_text('Agent 목록을 불러올 수 없습니다.', lang),
        'cover_region': get_display_text('커버 지역', lang),
        'services_offered': get_display_text('제공 서비스', lang),
        'agent_desc_default': get_display_text('정착 서비스를 제공합니다.', lang),
        'sending': get_display_text('전송 중...', lang),
        'appointment_success': get_display_text('약속 신청이 완료되었습니다.', lang),
        'paid_service_notice': get_display_text('이 서비스는 유료입니다. 결제를 완료하시면 에이전트에게 약속이 전달됩니다. 아래 "결제하기" 버튼을 눌러 주세요.', lang),
        'apply_failed': get_display_text('신청에 실패했습니다.', lang),
        'network_error': get_display_text('네트워크 오류가 발생했을 수 있습니다. 다시 시도해 주세요.', lang),
        'cancelled': get_display_text('취소됨', lang),
        'remove': get_display_text('삭제', lang),
        'appointment_cancel_failed': get_display_text('약속 취소에 실패했습니다.', lang),
        'appointment_cancel_request_failed': get_display_text('약속 취소 요청에 실패했습니다.', lang),
        'schedule_select_services': get_display_text('스케줄 생성 전에 아래에서 서비스 카드를 클릭해 선택해 주세요.', lang),
        'enter_entry_date': get_display_text('입국 예정일을 입력해 주세요.', lang),
        'schedule_creating': get_display_text('스케줄 생성 중...', lang),
        'schedule_tier_required': get_display_text('스케줄 생성은 스탠다드 이상 등급에서 이용 가능합니다.', lang),
        'schedule_created': get_display_text('선택한 서비스가 입국일 기준 2주 일정으로 달력에 배치되었습니다.', lang),
        'schedule_failed': get_display_text('스케줄 생성에 실패했습니다.', lang),
        'schedule_request_failed': get_display_text('스케줄 요청에 실패했습니다.', lang),
        'enter_services': get_display_text('필요한 서비스를 입력해 주세요.', lang),
        'recommending': get_display_text('추천 중...', lang),
        'suggest_tier_required': get_display_text('AI 서비스 추천은 스탠다드 이상 등급에서 이용 가능합니다.', lang),
        'suggest_done': get_display_text('추천 서비스가 선택되었습니다. 달력에 드래그하거나 "2주일 스캐쥴 짜줘"로 자동 배치하세요.', lang),
        'no_suggest': get_display_text('관련 서비스를 찾지 못했습니다. 직접 선택해 주세요.', lang),
        'suggest_failed': get_display_text('추천 요청에 실패했습니다.', lang),
        'saving': get_display_text('저장 중...', lang),
        'saved': get_display_text('저장되었습니다.', lang),
        'save_failed': get_display_text('저장에 실패했습니다.', lang),
        'ok': get_display_text('확인', lang),
        'close': get_display_text('닫기', lang),
        'free': get_display_text('무료', lang),
        'agent_required': get_display_text('Agent 선택 필요', lang),
        'total': get_display_text('합계', lang),
        'summary_empty': get_display_text('달력에서 서비스 카드를 클릭해 Agent를 선택한 항목만 과금되며 여기에 표시됩니다.', lang),
        'summary_empty_alt': get_display_text('달력에 서비스를 드래그하고 Agent를 선택하면 결제할 항목이 여기에 표시됩니다. (이미 결제한 항목은 표시되지 않습니다.)', lang),
        'appointment_detail': get_display_text('약속 상세', lang),
        'run': get_display_text('실행', lang),
        'year': get_display_text('년', lang),
        'month': get_display_text('월', lang),
        'prev': get_display_text('이전', lang),
        'next': get_display_text('다음', lang),
        'sun': get_calendar_weekday_display(0, lang),
        'mon': get_calendar_weekday_display(1, lang),
        'tue': get_calendar_weekday_display(2, lang),
        'wed': get_calendar_weekday_display(3, lang),
        'thu': get_calendar_weekday_display(4, lang),
        'fri': get_calendar_weekday_display(5, lang),
        'sat': get_calendar_weekday_display(6, lang),
        'placeholder_time_example': get_display_text('예: 오전 10시', lang),
        # HTML 템플릿용 (locale 미사용, StaticTranslation만 사용)
        'plan_heading': get_display_text('정착 플랜', lang),
        'current_tier': get_display_text('현재 등급', lang),
        'manual_notice': get_display_text('기본 메뉴얼을 보고 따라 할 수 있는 서비스를 제공합니다.', lang),
        'intro_link': get_display_text('정착 서비스 소개', lang),
        'manual_suffix': get_display_text('에서 메뉴얼을 확인하세요.', lang),
        'upgrade_notice': get_display_text('AI 추천 및 에이전트 도움을 원하시면 상위 요금제로 업그레이드하세요.', lang),
        'free_agent_services_label': get_display_text('무료 Agent 서비스', lang),
        'agent_helps_all': get_display_text('모든 항목에 에이전트가 도움을 드립니다.', lang),
        'agent_helps_optional': get_display_text('필요 시 에이전트의 도움을 받을 수 있으며, 패키지 또는 단일 항목으로 계약 가능합니다.', lang),
        'checkout_total': get_display_text('예상 Checkout 합계', lang),
        'customer_pricing_note': get_display_text('서비스별 Customer 가격 기준', lang),
        'settlement_info': get_display_text('이주 정보', lang),
        'state_label': get_display_text('이주할 State', lang),
        'city_label': get_display_text('도시', lang),
        'entry_date_label': get_display_text('입국/이주 예정일', lang),
        'ai_suggest_label': get_display_text('AI 서비스 추천 / 스케줄 생성', lang),
        'ai_suggest_hint': get_display_text('서비스 추천: "이사 직후 운전면허, 은행 필요해요" — 스케줄 생성: "2주일 동안 아래 선택된 항목들의 스캐쥴 짜줘" (위 이주 예정일 입력 후)', lang),
        'ai_input_placeholder': get_display_text('필요한 서비스를 한글로 입력하거나, 2주일 스캐쥴 짜줘 입력', lang),
        'service_selection': get_display_text('서비스 선택', lang),
        'service_selection_hint': get_display_text('카드를 클릭해 선택/해제하고, 드래그하여 달력에 놓으세요. "2주일 스캐쥴 짜줘" 입력 시 선택된 항목이 자동 배치됩니다.', lang),
        'calendar_heading': get_display_text('일정 달력', lang),
        'calendar_hint': get_display_text('카드를 날짜 칸에 드래그하여 배치하세요. 서비스 카드를 클릭해 Agent를 선택한 뒤 저장하면 예상 결제 금액이 홈·대시보드에 표시됩니다. 월/연도를 변경할 수 있습니다.', lang),
        'preferred_date': get_display_text('희망 일자', lang),
        'preferred_time_label': get_display_text('희망 시간대', lang),
        'name_label': get_display_text('이름', lang),
        'email_label': get_display_text('이메일', lang),
        'request_appointment': get_display_text('약속 신청', lang),
        'summary_heading': get_display_text('Agent 신청 항목 · 과금', lang),
        'close_aria': get_display_text('닫기', lang),
        'placeholder_time_range': get_display_text('예: 오전 10시, 오후 2시', lang),
        'placeholder_message': get_display_text('추가 요청사항을 적어주세요.', lang),
    }

    # tier_info.description도 현재 언어로 번역 (상단 부제목용)
    tier_info = dict(tier_info)
    tier_info['description'] = get_display_text(tier_info.get('description') or '', lang)

    # 서비스 카드·카테고리: 현재 언어로 번역 (StaticTranslation)
    raw_services = get_services_by_category()
    services_by_category = {}
    for cat in CATEGORY_ORDER:
        if cat not in raw_services:
            continue
        cat_display = get_display_text(cat, lang)
        services_by_category[cat_display] = [
            (code, get_display_text(name, lang)) for code, name in raw_services[cat]
        ]

    # 달력 제목: 영어는 "Feb. 2026" 형식
    month_keys = ['1월', '2월', '3월', '4월', '5월', '6월', '7월', '8월', '9월', '10월', '11월', '12월']
    for i, key in enumerate(month_keys):
        settlement_i18n[f'month_{i + 1}'] = get_display_text(key, lang)
    settlement_i18n['lang'] = lang
    settlement_i18n['can_show_plan_prices'] = can_show_plan_prices
    settlement_i18n['price_masked_label'] = get_display_text('견적 후 공개', lang)
    can_assign_agent = customer_can_assign_agent(request.user) if request.user.is_authenticated else False
    assigned_agent = None
    if request.user.is_authenticated:
        try:
            plan = request.user.settlement_plan
            assigned_agent = getattr(plan, 'assigned_agent', None)
        except UserSettlementPlan.DoesNotExist:
            pass
    settlement_i18n['dedicated_agent_title'] = get_display_text('전담 Agent 선택', lang)
    settlement_i18n['dedicated_agent_assigned'] = get_display_text('배정된 전담 Agent', lang)
    settlement_i18n['assign_agent_btn'] = get_display_text('이 Agent로 배정', lang)
    settlement_i18n['assign_agent_success'] = get_display_text('전담 Agent가 배정되었습니다.', lang)

    return render(request, 'services/settlement_quote.html', {
        'form': form,
        'services_by_category': services_by_category,
        'selected_services': selected_services,
        'tier_info': tier_info,
        'can_use_llm': can_use_llm_user,
        'initial_schedule_json': json.dumps(initial_schedule),
        'saved_checkout_total': saved_checkout,
        'can_show_plan_prices': can_show_plan_prices,
        'price_masked_label': get_display_text('견적 후 공개', lang),
        'free_agent_services': free_agent_services,
        'service_prices_json': service_prices_json,
        'free_agent_service_codes_json': free_agent_service_codes_json,
        'settlement_i18n': settlement_i18n,
        'can_assign_agent': can_assign_agent,
        'assigned_agent': assigned_agent,
    })


@require_GET
@ensure_csrf_cookie
def customer_quote(request):
    """
    고객 견적 페이지. 상태별 분기:
    status < FINAL_SENT: 가격 전부 마스킹 + 진행 안내
    status == FINAL_SENT: 가격/총액/결제 버튼 노출
    status == PAID: 결제 완료 + 대시보드/달력 링크
    """
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())
    if getattr(request.user, 'role', None) == 'AGENT':
        return redirect(reverse('app_agent_appointments'))

    # Optional: open specific quote from payment link (e.g. ?quote_id=123)
    quote_id_param = request.GET.get('quote_id', '').strip()
    quote = None
    if quote_id_param:
        try:
            qid = int(quote_id_param)
            quote = (
                SettlementQuote.objects.filter(
                    submission__user=request.user,
                    id=qid,
                )
                .select_related('submission')
                .first()
            )
        except (ValueError, TypeError):
            pass
    if not quote:
        quote = (
            SettlementQuote.objects.filter(submission__user=request.user)
            .order_by('-updated_at')
            .select_related('submission')
            .first()
        )
    checkout_error = request.GET.get('error', '').strip()
    if not quote:
        return render(request, 'services/customer_quote.html', {
            'quote': None,
            'can_view_price': False,
            'quote_payload': None,
            'checkout_error': checkout_error,
            'quote_superseded': False,
            'i18n': _customer_quote_i18n(get_request_language(request)),
        })

    lang = get_request_language(request)
    can_show = can_view_price(request.user, quote)
    payload = quote_for_customer(quote)
    # 결제 링크: 이메일/앱 메시지와 동일 헬퍼. quote_id 포함 시 해당 견적로 직행.
    from .quote_email import get_quote_payment_link
    payment_link = get_quote_payment_link(quote) if quote else ''

    quote_superseded = bool(getattr(quote, 'revision_superseded_at', None))

    # 수정 요청 워크플로우: 이 submission의 최신 change request (상태 카드·CTA용)
    change_request = None
    change_request_status_label = ''
    change_request_summary = ''
    change_request_next_step = ''
    show_customer_action_cta = False
    survey_resume_url = reverse('survey:survey_start') + '?resume=1'
    pending_reopen_offer = None
    if quote.submission_id:
        from .models import QuoteChangeRequest, CustomerActionOffer
        cr = (
            QuoteChangeRequest.objects.filter(submission_id=quote.submission_id)
            .order_by('-created_at')
            .select_related('quote')
            .first()
        )
        if cr:
            change_request = cr
            status_to_label = {
                QuoteChangeRequest.Status.OPEN: '접수됨',
                QuoteChangeRequest.Status.ANALYZED: '관리자 검토 중',
                QuoteChangeRequest.Status.IN_REVIEW: '관리자 검토 중',
                QuoteChangeRequest.Status.APPROVED: '새 견적 준비 중',
                QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED: '고객 수정 필요',
                QuoteChangeRequest.Status.APPLIED: '완료',
                QuoteChangeRequest.Status.REJECTED: '반려됨',
                QuoteChangeRequest.Status.CANCELED: '취소됨',
            }
            change_request_status_label = status_to_label.get(cr.status, cr.get_status_display() or cr.status)
            analysis = cr.latest_analysis()
            if analysis:
                change_request_summary = (getattr(analysis, 'normalized_summary', None) or '')[:500]
                change_request_next_step = (getattr(analysis, 'recommended_next_step', None) or '')[:300]
            show_customer_action_cta = cr.status == QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED
        offer = CustomerActionOffer.objects.filter(
            submission_id=quote.submission_id,
            button_action_key='reopen_survey',
            status=CustomerActionOffer.Status.PENDING,
            can_execute=True,
        ).order_by('-created_at').first()
        if offer:
            pending_reopen_offer = {'id': offer.id, 'button_label': offer.button_label or '설문 수정 시작'}

    customer_ui_payload = {}
    try:
        from customer_request_service import build_customer_ui_payload
        customer_ui_payload = build_customer_ui_payload(request.user, quote=quote)
    except Exception:
        pass
    current_request_status = customer_ui_payload.get('current_request_status') or change_request_status_label
    if not current_request_status and (quote_superseded or change_request):
        current_request_status = change_request_status_label

    return render(request, 'services/customer_quote.html', {
        'quote': quote,
        'can_view_price': can_show,
        'quote_payload': payload,
        'checkout_error': checkout_error,
        'payment_link': payment_link,
        'quote_superseded': quote_superseded,
        'change_request': change_request,
        'change_request_status_label': change_request_status_label,
        'change_request_summary': change_request_summary,
        'change_request_next_step': change_request_next_step,
        'show_customer_action_cta': show_customer_action_cta,
        'survey_resume_url': survey_resume_url,
        'pending_reopen_offer': pending_reopen_offer,
        'customer_ui_payload': customer_ui_payload,
        'current_request_status': current_request_status,
        'i18n': _customer_quote_i18n(lang),
    })


@require_GET
@ensure_csrf_cookie
def api_my_quote(request):
    """고객 본인 견적 API. quote_for_customer 적용으로 status < FINAL_SENT이면 가격/합계 필드 제거. customer_ui_payload 포함."""
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.', 'quote': None, 'customer_ui_payload': {}}, status=403)
    quote = (
        SettlementQuote.objects.filter(submission__user=request.user)
        .order_by('-updated_at')
        .first()
    )
    payload = quote_for_customer(quote) if quote else None
    customer_ui_payload = {}
    try:
        from customer_request_service import build_customer_ui_payload
        customer_ui_payload = build_customer_ui_payload(request.user, quote=quote)
    except Exception:
        pass
    return JsonResponse({
        'ok': True,
        'quote': payload,
        'customer_ui_payload': customer_ui_payload,
    })


def _build_plan_schedule_from_quote(quote):
    """견적 항목으로 UserSettlementPlan용 service_schedule 생성. post_payment 모듈 위임."""
    from .post_payment import build_initial_schedule_from_quote
    return build_initial_schedule_from_quote(quote)


# 결제 처리: quote_checkout.process_quote_payment 사용 (상태 전이·플랜·구독 일원화)


@require_POST
@ensure_csrf_cookie
def api_quote_checkout(request):
    """
    FINAL_SENT 견적 결제 처리. 결제 전에는 checkout/total 노출 안 됨(정책 유지).
    - process_quote_payment: quote PAID, submission AGENT_ASSIGNMENT, 이벤트, 플랜/태스크, 구독 업데이트
    - send_payment_complete_notifications: 고객/Admin 앱 메시지(공유 대화) + 고객/Admin/Agent 이메일
    POST JSON: { "quote_id": optional } 또는 form POST: quote_id
    """
    if not request.user.is_authenticated:
        if _is_form_post(request):
            return redirect(reverse('customer_quote') + '?error=login')
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    if getattr(request.user, 'role', None) == 'AGENT':
        if _is_form_post(request):
            return redirect(reverse('customer_quote') + '?error=agent')
        return JsonResponse({'ok': False, 'error': '고객만 결제할 수 있습니다.'}, status=403)

    import json
    quote_id = None
    if _is_form_post(request):
        raw = request.POST.get('quote_id')
        if raw:
            try:
                quote_id = int(raw)
            except (ValueError, TypeError):
                pass
    else:
        try:
            body = json.loads(request.body or '{}')
            quote_id = body.get('quote_id')
        except (ValueError, TypeError):
            pass

    from .quote_checkout import process_quote_payment
    quote, err = process_quote_payment(request.user, quote_id=quote_id)
    if err:
        if _is_form_post(request):
            return redirect(reverse('customer_quote') + '?error=' + ('already_paid' if '이미 결제' in err else 'invalid'))
        status = 400 if '이미 결제' in err else 404
        return JsonResponse({'ok': False, 'error': err, 'already_paid': '이미 결제' in err}, status=status)

    try:
        from .notifications import send_payment_complete_notifications
        from translations.utils import get_request_language
        plan = UserSettlementPlan.objects.filter(user=request.user).first()
        send_payment_complete_notifications(quote, plan, language_code=get_request_language(request))
    except Exception:
        pass

    redirect_url = reverse('app_customer_dashboard')
    if _is_form_post(request):
        return redirect(redirect_url)
    return JsonResponse({
        'ok': True,
        'message': '결제가 완료되었습니다.',
        'redirect_url': redirect_url,
    })


@require_GET
@ensure_csrf_cookie
def mock_quote_checkout(request):
    """
    개발용 모의 결제 화면. FINAL_SENT 견적에 대해 금액 표시 후 [결제 완료 (모의)] 버튼으로
    process_quote_payment 호출 → PAID 처리. 실서비스 연동 시 이 뷰 대신 실제 결제 페이지로 대체.
    """
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())
    if getattr(request.user, 'role', None) == 'AGENT':
        return redirect(reverse('customer_quote') + '?error=agent')
    quote_id = request.GET.get('quote_id', '').strip()
    quote = None
    if quote_id:
        try:
            qid = int(quote_id)
            quote = (
                SettlementQuote.objects.filter(
                    submission__user=request.user,
                    id=qid,
                    status=SettlementQuote.Status.FINAL_SENT,
                )
                .select_related('submission')
                .first()
            )
        except (ValueError, TypeError):
            pass
    if not quote:
        return redirect(reverse('customer_quote') + '?error=invalid')
    # 무효화된 견적은 결제 화면 진입 자체를 막음(결제 버튼 비활성화와 동일 정책)
    if not quote.is_payable():
        return redirect(reverse('customer_quote') + '?error=superseded')
    lang = get_request_language(request)
    total = int(quote.total or 0)
    i18n = {
        'title': get_display_text('모의 결제', lang),
        'amount': get_display_text('결제 금액', lang),
        'notice': get_display_text('개발 단계 모의 결제입니다. 실제 결제가 이루어지지 않습니다.', lang),
        'submit': get_display_text('결제 완료 (모의)', lang),
        'back': get_display_text('견적서로 돌아가기', lang),
    }
    return render(request, 'settlement/mock_checkout.html', {
        'quote': quote,
        'total': total,
        'i18n': i18n,
    })


@require_POST
@ensure_csrf_cookie
def api_quote_request_revision(request):
    """
    고객 견적서 수정 요청 (자유 텍스트) → LLM 분석 워크플로우 진입점.

    - quote → NEGOTIATING, 공유 대화에 고객 메시지 추가.
    - QuoteChangeRequest 생성 (source_type=TEXT, status=OPEN).
    - analyze_quote_change_request() 실행 후 status=ANALYZED로 업데이트.
    - 응답: { ok, change_request, analysis, message }. 설문 재개/quote 삭제/quote 최종 상태 직접 변경 없음.
    POST JSON: { "quote_id": int, "message": str } 또는 form: quote_id, message
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    if getattr(request.user, 'role', None) == 'AGENT':
        return JsonResponse({'ok': False, 'error': '고객만 요청할 수 있습니다.'}, status=403)
    import json
    quote_id = None
    message = ''
    if request.content_type and 'application/json' in (request.content_type or ''):
        try:
            data = json.loads(request.body or '{}')
            quote_id = data.get('quote_id')
            message = (data.get('message') or '').strip()
        except (ValueError, TypeError):
            pass
    else:
        quote_id = request.POST.get('quote_id')
        message = (request.POST.get('message') or '').strip()
    if not quote_id:
        return JsonResponse({'ok': False, 'error': 'quote_id가 필요합니다.'}, status=400)
    try:
        qid = int(quote_id)
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': '유효하지 않은 quote_id입니다.'}, status=400)
    quote = (
        SettlementQuote.objects.filter(
            id=qid,
            submission__user=request.user,
            status=SettlementQuote.Status.FINAL_SENT,
        )
        .select_related('submission')
        .first()
    )
    if not quote:
        return JsonResponse({'ok': False, 'error': '결제 대기 중인 견적만 수정 요청할 수 있습니다.'}, status=404)
    if not message:
        return JsonResponse({'ok': False, 'error': '수정 요청 내용을 입력해 주세요.'}, status=400)

    from customer_request_service import handle_customer_request_flow
    from .services_quote_change import serialize_change_request_for_response, serialize_analysis_for_response

    flow = handle_customer_request_flow(
        'customer_quote_revision',
        request.user,
        message,
        quote=quote,
    )
    if not flow or flow.error:
        return JsonResponse({'ok': False, 'error': (flow.error if flow else '요청을 접수할 수 없습니다.')}, status=400)

    ctx = flow.ctx
    policy = flow.policy
    if not ctx:
        return JsonResponse({'ok': False, 'error': '요청을 접수할 수 없습니다.'}, status=400)

    change_request = ctx.change_request
    analysis = ctx.extra.get('analysis') if ctx.extra else None
    base_message = (policy.customer_facing_summary or '').strip() if policy else ''
    if not base_message:
        lang = get_request_language(request)
        base_message = (
            get_display_text(
                '요청이 접수되었습니다. 관리자 검토 후 설문 수정 또는 견적 재작성 안내를 드릴게요.',
                lang,
            )
            or '요청이 접수되었습니다. 관리자 검토 후 설문 수정 또는 견적 재작성 안내를 드릴게요.'
        )
    if analysis and getattr(analysis, 'normalized_summary', None):
        summary = (analysis.normalized_summary or '')[:300]
        if summary:
            base_message += '\n\n[요청 요약] ' + summary
    if analysis and getattr(analysis, 'recommended_next_step', None):
        next_step = (analysis.recommended_next_step or '')[:200]
        if next_step:
            base_message += '\n\n[다음 단계] ' + next_step

    return JsonResponse({
        'ok': True,
        'change_request': serialize_change_request_for_response(change_request) if change_request else {},
        'analysis': serialize_analysis_for_response(analysis) if analysis else {},
        'policy': policy.as_dict() if policy else {},
        'message': base_message,
    })


@require_POST
@ensure_csrf_cookie
def api_action_offer_execute(request, offer_id):
    """
    고객 액션 제안(버튼) 실행. POST만 허용. 로그인 사용자 본인 제안만 실행 가능.
    - AJAX(X-Requested-With: XMLHttpRequest): JSON 반환 { ok: bool }.
    - 폼 직접 제출(스크립트 미동작 등): 성공 시 설문 편집 페이지로 리다이렉트.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    from django.http import HttpResponseRedirect
    from .models import CustomerActionOffer
    from customer_request_service import execute_confirmed_action

    offer = CustomerActionOffer.objects.filter(id=offer_id).select_related('submission', 'conversation').first()
    if not offer:
        return JsonResponse({'ok': False, 'error': '제안을 찾을 수 없습니다.'}, status=404)
    sub = getattr(offer, 'submission', None)
    if sub and getattr(sub, 'user_id', None) and sub.user_id != request.user.id:
        return JsonResponse({'ok': False, 'error': '권한이 없습니다.'}, status=403)
    if not sub and offer.conversation_id:
        from messaging.models import ConversationParticipant
        if not ConversationParticipant.objects.filter(conversation_id=offer.conversation_id, user=request.user).exists():
            return JsonResponse({'ok': False, 'error': '권한이 없습니다.'}, status=403)

    success, err = execute_confirmed_action(offer_id, request.user)
    if success:
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            survey_edit_url = reverse('survey:survey_start') + '?resume=1'
            return HttpResponseRedirect(survey_edit_url)
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False, 'error': err or '실행에 실패했습니다.'}, status=400)


@require_POST
@ensure_csrf_cookie
def api_proposal_confirm(request, proposal_id):
    """
    고객 제안 승인. POST /api/settlement/proposal/<id>/confirm/
    PROPOSED → CONFIRMED → 실행 → EXECUTED/FAILED. 로그인 사용자 본인 제안만.
    성공 시 customer_message(고객 안내 문구)를 포함하여 반환.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    from messaging.models import CustomerActionProposal
    from customer_request_service import confirm_proposal

    proposal = CustomerActionProposal.objects.filter(id=proposal_id).select_related('analysis').first()
    if not proposal:
        return JsonResponse({'ok': False, 'error': '제안을 찾을 수 없습니다.'}, status=404)
    if proposal.analysis and getattr(proposal.analysis, 'customer_id', None) != request.user.id:
        return JsonResponse({'ok': False, 'error': '권한이 없습니다.'}, status=403)

    success, err, customer_msg = confirm_proposal(proposal_id, request.user)
    if success:
        resp = {'ok': True}
        if customer_msg:
            resp['message'] = customer_msg
        return JsonResponse(resp)
    return JsonResponse({'ok': False, 'error': err or '실행에 실패했습니다.'}, status=400)


@require_POST
@ensure_csrf_cookie
def api_proposal_mark_shown(request, proposal_id):
    """
    프론트엔드에서 proposal 카드가 실제로 렌더링되었을 때 호출.
    PROPOSAL_VIEWED 이벤트를 CustomerActionFeedbackLog에 기록. 중복 호출 안전.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False}, status=403)
    from messaging.models import CustomerActionProposal
    from customer_request_service import _log_feedback

    proposal = CustomerActionProposal.objects.filter(id=proposal_id).first()
    if not proposal:
        return JsonResponse({'ok': False}, status=404)
    _log_feedback(proposal, "PROPOSAL_VIEWED", actor=request.user)
    return JsonResponse({'ok': True})


@require_POST
@ensure_csrf_cookie
def api_proposal_decline(request, proposal_id):
    """
    고객 제안 거절. POST /api/settlement/proposal/<id>/decline/
    PROPOSED → DECLINED.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    from messaging.models import CustomerActionProposal
    from customer_request_service import decline_proposal

    proposal = CustomerActionProposal.objects.filter(id=proposal_id).select_related('analysis').first()
    if not proposal:
        return JsonResponse({'ok': False, 'error': '제안을 찾을 수 없습니다.'}, status=404)
    if proposal.analysis and getattr(proposal.analysis, 'customer_id', None) != request.user.id:
        return JsonResponse({'ok': False, 'error': '권한이 없습니다.'}, status=403)

    success, err = decline_proposal(proposal_id, request.user)
    if success:
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False, 'error': err or '처리에 실패했습니다.'}, status=400)


@require_POST
@ensure_csrf_cookie
def api_complete_human_review(request, review_id):
    """
    담당자가 사람 검토 요청을 완료 처리. staff 전용.
    POST body (JSON): { "note": "...", "customer_message": "고객에게 보낼 메시지" }
    반환: { ok: bool, error?: str }
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    if not getattr(request.user, 'is_staff', False):
        return JsonResponse({'ok': False, 'error': '권한이 없습니다.'}, status=403)
    import json
    note = ''
    customer_message = ''
    if request.content_type and 'application/json' in (request.content_type or ''):
        try:
            data = json.loads(request.body or '{}')
            note = (data.get('note') or '').strip()
            customer_message = (data.get('customer_message') or '').strip()
        except (ValueError, TypeError):
            pass
    from .models import HumanReviewRequest
    from customer_request_service import complete_human_review
    success, err = complete_human_review(int(review_id), request.user, note=note, customer_message=customer_message or None)
    if success:
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False, 'error': err or '처리에 실패했습니다.'}, status=400)


def _is_form_post(request):
    """Content-Type이 form인지 (HTML form 제출)."""
    ct = (request.content_type or '').lower()
    return 'application/x-www-form-urlencoded' in ct or 'multipart/form-data' in ct


def _customer_quote_i18n(lang):
    """고객 견적 페이지 번역 키."""
    return {
        'title': get_display_text('내 견적', lang),
        'no_quote': get_display_text('아직 견적이 없습니다. 설문 제출 후 Admin이 견적을 보내면 여기에 표시됩니다.', lang),
        'quote_preparing': get_display_text('견적을 작성 중입니다. 송부 후 가격이 공개됩니다.', lang),
        'quote_sent': get_display_text('견적이 도착했습니다. 아래 내용을 확인해 주세요.', lang),
        'quote_paid': get_display_text('결제가 완료되었습니다.', lang),
        'total': get_display_text('합계', lang),
        'price_masked': get_display_text('견적 후 공개', lang),
        'pay': get_display_text('결제하기', lang),
        'go_dashboard': get_display_text('대시보드로', lang),
        'go_calendar': get_display_text('정착 플랜/달력', lang),
        'region': get_display_text('지역', lang),
        'request_revision': get_display_text('견적서 수정 요청', lang),
        'request_revision_help': get_display_text('금액·항목 등 수정이 필요하면 내용을 적어 보내주세요. Admin이 검토 후 수정된 견적을 보내드립니다.', lang),
        'request_revision_placeholder': get_display_text('예: OO 서비스 금액 조정 요청, 일정 변경 등', lang),
        'send_revision_request': get_display_text('수정 요청 보내기', lang),
    }


@require_GET
@ensure_csrf_cookie
def api_agents_for_service(request):
    """
    서비스·지역 기준 가능한 Agent 목록. 서비스별 수락률(accept rate) 포함.
    결제 전에는 Agent 목록/가격 노출 금지: 고객은 결제(PAID) 후에만 호출 가능.
    GET ?service_code=DRIVERS_LICENSE&state=CA
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Q, Count

    User = get_user_model()
    if request.user.is_authenticated and getattr(request.user, 'role', None) == 'CUSTOMER':
        if not customer_can_assign_agent(request.user):
            return JsonResponse({
                'agents': [],
                'error': '결제 후에만 Agent 목록을 볼 수 있습니다.',
                'require_payment': True,
            }, status=403)

    service_code = (request.GET.get('service_code') or '').strip()
    state = (request.GET.get('state') or '').strip()

    if not service_code:
        return JsonResponse({'agents': [], 'error': 'service_code가 필요합니다.'}, status=400)

    # service_code → SettlementService id
    from .models import SettlementService
    q = Q(code=service_code)
    if service_code.isdigit():
        q = q | Q(id=int(service_code))
    svc = SettlementService.objects.filter(q).first()
    if not svc:
        return JsonResponse({'agents': [], 'error': '유효하지 않은 서비스 코드입니다.'}, status=400)
    service_id = svc.id

    agents_qs = User.objects.filter(
        role=User.Role.AGENT,
        status=User.Status.ACTIVE,
        agent_services__contains=[service_id],
    )
    if state:
        agents_qs = agents_qs.filter(agent_states__contains=[state])

    # Agent별 이 서비스에 대한 약속 수락률 (CONFIRMED / (전체 - 취소)). 고객 취소는 수락률에서 제외.
    agent_ids = list(agents_qs[:20].values_list('id', flat=True))
    from .models import AgentAppointmentRequest
    accept_stats = {}
    if agent_ids:
        stats_qs = (
            AgentAppointmentRequest.objects.filter(agent_id__in=agent_ids, service_code=service_code)
            .values('agent_id')
            .annotate(
                total=Count('id'),
                confirmed=Count('id', filter=Q(status='CONFIRMED')),
                cancelled=Count('id', filter=Q(status='CANCELLED')),
            )
        )
        for row in stats_qs:
            total = row['total'] or 0
            cancelled = row['cancelled'] or 0
            total_effective = total - cancelled  # 취소 건 제외
            confirmed = row['confirmed'] or 0
            rate = (confirmed / total_effective) if total_effective else None
            accept_stats[row['agent_id']] = {
                'rate': round(rate, 2) if rate is not None else None,
                'display': f'{int(round(rate * 100))}%' if rate is not None else '-',
                'count': f'{confirmed}/{total_effective}' if total_effective else '-',
            }

    result = []
    for u in agents_qs[:20]:
        summary = u.get_agent_rating_summary() or {}
        service_names = []
        for sid in (u.agent_services or []):
            s = SettlementService.objects.filter(id=sid).first()
            if s:
                service_names.append(s.name)
        img_url = ''
        if u.profile_image:
            img_url = request.build_absolute_uri(u.profile_image.url)
        stat = accept_stats.get(u.id) or {}
        result.append({
            'id': u.id,
            'name': u.get_full_name() or u.username,
            'username': u.username,
            'rating_avg': round(summary.get('avg') or 0, 1),
            'rating_count': summary.get('count') or 0,
            'accept_rate': stat.get('rate'),
            'accept_rate_display': stat.get('display', '-'),
            'accept_rate_count': stat.get('count', '-'),
            'profile_image_url': img_url,
            'states': u.agent_states or [],
            'service_names': service_names,
        })
    return JsonResponse({'agents': result})


@require_GET
@ensure_csrf_cookie
def api_available_agents_for_plan(request):
    """
    결제 후 전담 Agent 선택용: 플랜의 서비스·지역을 커버할 수 있는 Agent 목록.
    customer_can_assign_agent가 True일 때만 호출 가능. 결제 전 노출 금지.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'agents': [], 'error': '로그인이 필요합니다.'}, status=403)
    if not customer_can_assign_agent(request.user):
        return JsonResponse({
            'agents': [],
            'error': '결제 후에만 Agent 목록을 볼 수 있습니다.',
            'require_payment': True,
        }, status=403)
    try:
        plan = UserSettlementPlan.objects.get(user=request.user)
    except UserSettlementPlan.DoesNotExist:
        return JsonResponse({'agents': [], 'error': '정착 플랜이 없습니다.'}, status=404)
    from .schedule_utils import get_schedule_for_display
    schedule = get_schedule_for_display(plan) or {}
    service_codes = set()
    for items in schedule.values():
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict) and (it.get('code') or '').strip():
                service_codes.add((it.get('code') or '').strip())
    state = (plan.state or '').strip()
    if not service_codes:
        return JsonResponse({'agents': []})
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    from functools import reduce
    import operator
    User = get_user_model()
    from .models import SettlementService
    service_ids = set()
    for code in service_codes:
        q = Q(code=code)
        if str(code).isdigit():
            q = q | Q(id=int(code))
        svc = SettlementService.objects.filter(q).first()
        if svc:
            service_ids.add(svc.id)
    if not service_ids:
        return JsonResponse({'agents': []})
    q_services = reduce(
        operator.or_,
        [Q(agent_services__contains=[sid]) for sid in list(service_ids)[:20]],
        Q(),
    )
    agents_qs = User.objects.filter(
        role=User.Role.AGENT,
        status=User.Status.ACTIVE,
    ).filter(q_services)
    if state:
        agents_qs = agents_qs.filter(agent_states__contains=[state])
    agents_qs = agents_qs.distinct()[:30]
    result = []
    for u in agents_qs:
        summary = u.get_agent_rating_summary() or {}
        result.append({
            'id': u.id,
            'name': u.get_full_name() or u.username,
            'username': u.username,
            'rating_avg': round(summary.get('avg') or 0, 1),
            'rating_count': summary.get('count') or 0,
        })
    return JsonResponse({'agents': result})


@require_POST
@ensure_csrf_cookie
def api_assign_dedicated_agent(request):
    """
    결제 후 전담 Agent 1명 배정. customer_can_assign_agent일 때만.
    POST JSON 또는 form: agent_id
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    if not customer_can_assign_agent(request.user):
        return JsonResponse({'ok': False, 'error': '결제 후에만 전담 Agent를 배정할 수 있습니다.', 'require_payment': True}, status=403)
    from django.contrib.auth import get_user_model
    User = get_user_model()
    import json
    agent_id = None
    if request.content_type and 'application/json' in request.content_type:
        try:
            body = json.loads(request.body or '{}')
            agent_id = body.get('agent_id')
        except (ValueError, TypeError):
            pass
    else:
        agent_id = request.POST.get('agent_id')
    if agent_id is None:
        return JsonResponse({'ok': False, 'error': 'agent_id가 필요합니다.'}, status=400)
    try:
        agent_id = int(agent_id)
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': '유효하지 않은 agent_id입니다.'}, status=400)
    try:
        agent = User.objects.get(id=agent_id, role=User.Role.AGENT, status=User.Status.ACTIVE)
    except User.DoesNotExist:
        return JsonResponse({'ok': False, 'error': '해당 Agent를 찾을 수 없습니다.'}, status=404)
    plan, _ = UserSettlementPlan.objects.get_or_create(
        user=request.user,
        defaults={'state': '', 'city': '', 'service_schedule': {}, 'checkout_total': 0},
    )
    plan.assigned_agent = agent
    plan.save(update_fields=['assigned_agent', 'updated_at'])
    from survey.models import SurveySubmission
    from survey.submission_state import mark_submission_service_in_progress
    paid_sub = SurveySubmission.objects.filter(
        user=request.user,
        settlement_quotes__status=SettlementQuote.Status.PAID,
    ).order_by('-submitted_at').distinct().first()
    mark_submission_service_in_progress(paid_sub)
    try:
        from .notifications import send_agent_assigned_notification
        from translations.utils import get_request_language
        send_agent_assigned_notification(plan, agent, request.user, language_code=get_request_language(request))
    except Exception:
        pass
    return JsonResponse({'ok': True, 'message': '전담 Agent가 배정되었습니다.', 'agent_id': agent.id, 'agent_name': agent.get_full_name() or agent.username})


@require_POST
@ensure_csrf_cookie
def api_appointment_request(request):
    """
    Agent 약속 신청 (무료 서비스만 즉시 생성).
    유료 서비스는 결제 완료(api_checkout) 후에만 에이전트에게 전달됨.
    POST agent_id, service_code, service_date, preferred_time, message
    비로그인 시 customer_name, customer_email 필수
    """
    from django.contrib.auth import get_user_model
    from billing.utils import get_user_free_agent_services

    User = get_user_model()
    agent_id = request.POST.get('agent_id')
    service_code = (request.POST.get('service_code') or '').strip()
    service_date_str = (request.POST.get('service_date') or '').strip()
    preferred_time = (request.POST.get('preferred_time') or '').strip()
    message = (request.POST.get('message') or '').strip()
    customer_name = (request.POST.get('customer_name') or '').strip()
    customer_email = (request.POST.get('customer_email') or '').strip()

    if not agent_id:
        return JsonResponse({'ok': False, 'error': 'agent_id가 필요합니다.'}, status=400)
    try:
        agent = User.objects.get(id=int(agent_id), role=User.Role.AGENT, status=User.Status.ACTIVE)
    except (ValueError, User.DoesNotExist):
        return JsonResponse({'ok': False, 'error': '유효하지 않은 Agent입니다.'}, status=400)

    if not service_code:
        return JsonResponse({'ok': False, 'error': '서비스 코드가 필요합니다.'}, status=400)

    if not service_date_str:
        return JsonResponse({'ok': False, 'error': '희망 일자를 선택해 주세요.'}, status=400)
    try:
        from datetime import datetime
        service_date = datetime.strptime(service_date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'ok': False, 'error': '날짜 형식이 올바르지 않습니다. (YYYY-MM-DD)'}, status=400)

    if not request.user.is_authenticated and (not customer_name or not customer_email):
        return JsonResponse({'ok': False, 'error': '이름과 이메일을 입력해 주세요.'}, status=400)

    # 유료 서비스: 결제 완료 후 checkout API에서만 약속 생성. 여기서는 생성하지 않음.
    free_codes = {c for c, _ in get_user_free_agent_services(request.user)} if request.user.is_authenticated else set()
    if service_code not in free_codes:
        if not request.user.is_authenticated:
            return JsonResponse({
                'ok': False,
                'error': '유료 서비스는 로그인 후 결제를 완료해 주세요.',
                'require_payment': True,
            }, status=400)
        return JsonResponse({
            'ok': False,
            'error': '이 서비스는 유료입니다. 아래 결제 버튼을 눌러 결제를 완료한 뒤 에이전트에게 전달됩니다.',
            'require_payment': True,
        }, status=400)

    req = AgentAppointmentRequest(
        agent=agent,
        customer=request.user if request.user.is_authenticated else None,
        service_code=service_code,
        service_date=service_date,
        preferred_time=preferred_time,
        message=message,
        customer_name=customer_name if not request.user.is_authenticated else '',
        customer_email=customer_email if not request.user.is_authenticated else '',
    )
    req.save()
    return JsonResponse({'ok': True, 'message': '약속 신청이 완료되었습니다. Agent가 연락드릴 예정입니다.'})


@require_POST
@ensure_csrf_cookie
def api_appointment_update(request, pk):
    """약속 수정 (희망 시간, 메시지). 고객 본인만. PENDING 또는 CONFIRMED일 때 가능. CONFIRMED에서 수정 시 PENDING으로 되돌려 에이전트 재확인 필요."""
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    try:
        req = AgentAppointmentRequest.objects.get(pk=pk, customer=request.user)
    except AgentAppointmentRequest.DoesNotExist:
        return JsonResponse({'ok': False, 'error': '약속을 찾을 수 없습니다.'}, status=404)
    if req.status not in ('PENDING', 'CONFIRMED'):
        return JsonResponse({'ok': False, 'error': '대기 중이거나 확정된 약속만 수정할 수 있습니다.'}, status=400)
    preferred_time = (request.POST.get('preferred_time') or '').strip()
    message = (request.POST.get('message') or '').strip()
    req.preferred_time = preferred_time
    req.message = message
    was_confirmed = req.status == 'CONFIRMED'
    if was_confirmed:
        req.status = 'PENDING'
        req.save(update_fields=['preferred_time', 'message', 'status'])
        from messaging.models import Conversation, Message
        conv = Conversation.objects.filter(appointment=req).first()
        if conv:
            Message.objects.create(
                conversation=conv,
                sender=request.user,
                body='고객이 약속을 수정했습니다. 다시 수락해 주세요.',
            )
            conv.updated_at = timezone.now()
            conv.save(update_fields=['updated_at'])
    else:
        req.save(update_fields=['preferred_time', 'message'])
    return JsonResponse({
        'ok': True,
        'message': '약속이 수정되었습니다.' + (' 에이전트가 다시 수락하면 확정됩니다.' if was_confirmed else ''),
    })


@require_POST
@ensure_csrf_cookie
def api_appointment_cancel(request, pk):
    """약속 취소. 고객(customer) 또는 해당 에이전트(agent)만 취소 가능. 취소 시 에이전트 달력에서 제외됨."""
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    try:
        req = AgentAppointmentRequest.objects.get(
            pk=pk
        )
    except AgentAppointmentRequest.DoesNotExist:
        return JsonResponse({'ok': False, 'error': '약속을 찾을 수 없습니다.'}, status=404)
    if req.customer_id and req.customer_id == request.user.id:
        req.cancellation_reason = '고객 취소'
    elif req.agent_id and req.agent_id == request.user.id:
        req.cancellation_reason = '에이전트 취소'
    else:
        return JsonResponse({'ok': False, 'error': '이 약속을 취소할 권한이 없습니다.'}, status=403)
    req.status = 'CANCELLED'
    req.save(update_fields=['status', 'cancellation_reason'])
    return JsonResponse({'ok': True, 'message': '약속이 취소되었습니다.'})


@require_POST
@ensure_csrf_cookie
def api_appointment_accept(request, pk):
    """에이전트가 약속 수락. 본인에게 온 요청만."""
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    try:
        req = AgentAppointmentRequest.objects.get(pk=pk, agent=request.user)
    except AgentAppointmentRequest.DoesNotExist:
        return JsonResponse({'ok': False, 'error': '약속을 찾을 수 없습니다.'}, status=404)
    if req.status == 'CANCELLED':
        return JsonResponse({'ok': False, 'error': '이미 취소된 약속입니다.'}, status=400)
    req.status = 'CONFIRMED'
    req.save(update_fields=['status'])

    # 해당 약속 대화에 고객에게 수락 메시지 전송
    from messaging.models import Conversation, Message
    conv = Conversation.objects.filter(appointment=req).first()
    if conv:
        Message.objects.create(
            conversation=conv,
            sender=request.user,
            body='약속을 수락했습니다.',
        )
        conv.updated_at = timezone.now()
        conv.save(update_fields=['updated_at'])

    return JsonResponse({'ok': True, 'message': '약속을 수락했습니다.'})


@require_GET
def api_rateable_appointments(request):
    """
    고객이 평가 가능한 약속 목록: CONFIRMED, customer=request.user, 아직 별점 없음.
    설문/결제 후 Agent 선택 UI 및 대시보드 "후기 작성"용.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    from accounts.models import AgentRating
    from .constants import get_service_label
    qs = (
        AgentAppointmentRequest.objects.filter(
            customer=request.user,
            status='CONFIRMED',
        )
        .exclude(id__in=AgentRating.objects.filter(appointment__isnull=False).values_list('appointment_id', flat=True))
        .select_related('agent')
        .order_by('-service_date', '-confirmed_at')
    )
    lang = get_request_language(request)
    items = []
    for req in qs[:20]:
        items.append({
            'id': req.id,
            'agent_id': req.agent_id,
            'agent_name': (req.agent.get_full_name() or req.agent.username) if req.agent else '',
            'service_code': req.service_code or '',
            'service_label': get_display_text(get_service_label(req.service_code or ''), lang) or get_service_label(req.service_code or ''),
            'service_date': req.service_date.isoformat() if hasattr(req.service_date, 'isoformat') else str(req.service_date),
            'confirmed_time_slot': req.confirmed_time_slot or '',
        })
    return JsonResponse({'ok': True, 'items': items})


def _validate_review_comment(comment: str, max_length: int = 500) -> tuple:
    """
    Moderation-safe: strip, length, reject empty or spammy (only whitespace/repeated chars).
    Returns (cleaned_comment, error_message). error_message is None if valid.
    """
    if comment is None:
        return '', None
    s = (comment or '').strip()[:max_length]
    if not s:
        return s, None  # empty is allowed (comment optional)
    if len(s) < 2 and s:
        return s, None  # 1 char is ok
    # Reject if all same character or mostly non-word
    import re
    if re.match(r'^(\s|.)\1*$', s):
        return s, 'invalid_comment'
    non_word = len(re.findall(r'[^\w\s\u3130-\u318f\uac00-\ud7af]', s))  # allow letters, digits, CJK
    if len(s) > 10 and non_word > len(s) * 0.8:
        return s, 'invalid_comment'
    return s, None


@require_POST
@ensure_csrf_cookie
def api_appointment_rate(request, pk):
    """
    고객이 확정된 약속에 대해 별점+한줄평 제출. 약속당 1건만 허용(AgentRating.appointment unique).
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    try:
        req = AgentAppointmentRequest.objects.get(pk=pk, customer=request.user, status='CONFIRMED')
    except AgentAppointmentRequest.DoesNotExist:
        return JsonResponse({'ok': False, 'error': '해당 약속을 찾을 수 없거나 평가할 수 없습니다.'}, status=404)
    from accounts.models import AgentRating
    if AgentRating.objects.filter(appointment=req).exists():
        return JsonResponse({'ok': False, 'error': '이미 평가하셨습니다.'}, status=400)
    score_val = request.POST.get('score')
    if request.content_type and 'application/json' in (request.content_type or ''):
        try:
            import json
            body = json.loads(request.body or '{}')
            score_val = score_val or body.get('score')
            comment = (body.get('comment') or request.POST.get('comment') or '').strip()
        except (ValueError, TypeError):
            comment = (request.POST.get('comment') or '').strip()
    else:
        comment = (request.POST.get('comment') or '').strip()
    try:
        score = int(score_val)
    except (TypeError, ValueError):
        score = None
    if score is None or score < 1 or score > 5:
        return JsonResponse({'ok': False, 'error': '별점은 1~5 사이로 입력해 주세요.'}, status=400)
    comment_clean, comment_err = _validate_review_comment(comment, max_length=500)
    if comment_err:
        return JsonResponse({'ok': False, 'error': '한줄평이 올바르지 않습니다.'}, status=400)
    AgentRating.objects.create(
        rater=request.user,
        agent=req.agent,
        appointment=req,
        score=score,
        comment=comment_clean[:500],
    )
    return JsonResponse({'ok': True, 'message': '평가가 등록되었습니다.'})


@require_POST
@ensure_csrf_cookie
def api_appointment_confirm(request, pk):
    """
    Agent가 일정 확정: confirmed_at, confirmed_time_slot 설정 후 고객에게 메시지 발송.
    번역 룰 유지(get_display_text). 확정 시 고객 달력 상태는 CONFIRMED로 이미 반영됨.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    try:
        req = AgentAppointmentRequest.objects.get(pk=pk, agent=request.user)
    except AgentAppointmentRequest.DoesNotExist:
        return JsonResponse({'ok': False, 'error': '약속을 찾을 수 없습니다.'}, status=404)
    if req.status == 'CANCELLED':
        return JsonResponse({'ok': False, 'error': '이미 취소된 약속입니다.'}, status=400)

    confirmed_time_slot = (request.POST.get('confirmed_time_slot') or '').strip()
    if request.content_type and 'application/json' in (request.content_type or ''):
        try:
            import json
            body = json.loads(request.body or '{}')
            confirmed_time_slot = (body.get('confirmed_time_slot') or '').strip() or confirmed_time_slot
        except (ValueError, TypeError):
            pass

    req.status = 'CONFIRMED'
    req.confirmed_at = timezone.now()
    req.confirmed_time_slot = confirmed_time_slot[:100] if confirmed_time_slot else ''
    req.save(update_fields=['status', 'confirmed_at', 'confirmed_time_slot'])

    lang = get_request_language(request)
    msg_parts = [get_display_text('일정이 확정되었습니다.', lang), str(req.service_date)]
    if req.confirmed_time_slot:
        msg_parts.append(req.confirmed_time_slot)
    msg_body = ' '.join(msg_parts)

    from messaging.models import Conversation, Message
    conv = Conversation.objects.filter(appointment=req).first()
    if not conv and req.customer_id:
        conv = Conversation.objects.create(appointment=req)
    if conv:
        Message.objects.create(
            conversation=conv,
            sender=request.user,
            body=msg_body,
        )
        conv.updated_at = timezone.now()
        conv.save(update_fields=['updated_at'])

    return JsonResponse({'ok': True, 'message': '일정이 확정되었습니다.', 'confirmed_at': req.confirmed_at.isoformat() if req.confirmed_at else None})


@require_POST
@ensure_csrf_cookie
def api_checkout(request):
    """
    결제 확정: 스케줄의 Agent 신청 항목에 대해 약속을 생성하고 agent 수락 대기(PENDING)로 둠.
    POST JSON: { "schedule": { "YYYY-MM-DD": [ { "code", "label", "agent_id", "agent_name"?, ... }, ... ], ... } }
    로그인 사용자만. 결제는 모킹(실제 PG 연동 없음).
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status=403)
    import json
    try:
        body = json.loads(request.body or '{}')
        schedule = body.get('schedule') or {}
    except (ValueError, TypeError):
        schedule = {}
    if not isinstance(schedule, dict):
        return JsonResponse({'ok': False, 'error': '스케줄 형식이 올바르지 않습니다.'}, status=400)
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if customer_can_assign_agent(request.user):
        try:
            p = UserSettlementPlan.objects.get(user=request.user)
            if not p.assigned_agent_id:
                return JsonResponse({'ok': False, 'error': '전담 Agent를 먼저 선택해 주세요.', 'require_assign_agent': True}, status=400)
        except UserSettlementPlan.DoesNotExist:
            pass

    try:
        plan = UserSettlementPlan.objects.get(user=request.user)
        from .schedule_utils import get_schedule_for_display
        current_schedule = get_schedule_for_display(plan) or {}
    except UserSettlementPlan.DoesNotExist:
        plan = None
        current_schedule = {}
    if not isinstance(current_schedule, dict):
        current_schedule = {}
    # 결제 후 전담 Agent: plan.assigned_agent가 있으면 서비스별 agent_id 없이 해당 Agent로 전체 약속 생성
    dedicated_agent_id = getattr(plan, 'assigned_agent_id', None) if plan else None
    if dedicated_agent_id:
        try:
            User.objects.get(id=dedicated_agent_id, role=User.Role.AGENT)
        except User.DoesNotExist:
            dedicated_agent_id = None

    current_slots = set()
    for _date, _items in (current_schedule or {}).items():
        if not isinstance(_items, list):
            continue
        for _item in _items:
            if isinstance(_item, dict):
                current_slots.add((str(_date), (_item.get('code') or '').strip()))

    created = 0
    for date_str, items in schedule.items():
        if not isinstance(items, list):
            continue
        try:
            from datetime import datetime
            service_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        for item in items or []:
            if not isinstance(item, dict):
                continue
            code = (item.get('code') or '').strip()
            agent_id = dedicated_agent_id or item.get('agent_id')
            if not code or not agent_id:
                continue
            if (date_str, code) not in current_slots:
                continue
            try:
                agent = User.objects.get(id=int(agent_id), role=User.Role.AGENT)
            except (ValueError, User.DoesNotExist):
                continue
            existing = AgentAppointmentRequest.objects.filter(
                customer=request.user,
                agent_id=agent_id,
                service_code=code,
                service_date=service_date,
            ).exclude(status='CANCELLED').exists()
            if not existing:
                req = AgentAppointmentRequest.objects.create(
                    agent=agent,
                    customer=request.user,
                    service_code=code,
                    service_date=service_date,
                    preferred_time=item.get('preferred_time') or '',
                    message=item.get('message') or '',
                    status='PENDING',
                )
                created += 1
                # 결제 후 생성된 PlanServiceTask에 약속 연결 (Admin 필요작업 현황 반영)
                try:
                    from .models import PlanServiceTask
                    plan = UserSettlementPlan.objects.get(user=request.user)
                    task = PlanServiceTask.objects.filter(
                        plan=plan, service_code=code, appointment__isnull=True
                    ).first()
                    if task:
                        task.appointment = req
                        task.save(update_fields=['appointment_id'])
                except (UserSettlementPlan.DoesNotExist, Exception):
                    pass

    # 저장 시 요청 스케줄을 그대로 덮어쓰지 않고, 현재 DB 스케줄과 합침.
    # 요청에만 있고 DB에는 없는 슬롯 중 agent_id가 있는 것은 admin 삭제로 제거된 것이므로 재추가하지 않음.
    merged_schedule = {}
    all_dates = set((current_schedule or {}).keys()) | set(schedule.keys())
    for date_str in all_dates:
        current_items = list((current_schedule or {}).get(date_str) or [])
        request_items = list(schedule.get(date_str) or [])
        merged_items = []
        for cur in current_items:
            if not isinstance(cur, dict):
                continue
            code = (cur.get('code') or '').strip()
            req_match = next((r for r in request_items if isinstance(r, dict) and (r.get('code') or '').strip() == code), None)
            merged_items.append(req_match if req_match is not None else cur)
        for req in request_items:
            if not isinstance(req, dict):
                continue
            code = (req.get('code') or '').strip()
            in_current = any(isinstance(c, dict) and (c.get('code') or '').strip() == code for c in current_items)
            if not in_current and req.get('agent_id'):
                continue  # DB에 없고 agent만 있는 슬롯 = 삭제된 슬롯이므로 재추가 안 함
            if not in_current:
                merged_items.append(req)
        merged_schedule[date_str] = merged_items

    free_codes = set(c for c, _ in get_user_free_agent_services(request.user))
    checkout_total, _ = calc_checkout_total(merged_schedule, free_agent_service_codes=free_codes)
    UserSettlementPlan.objects.update_or_create(
        user=request.user,
        defaults={
            'service_schedule': merged_schedule,
            'checkout_total': checkout_total,
        }
    )
    return JsonResponse({
        'ok': True,
        'message': '결제가 완료되었습니다. Agent 수락 대기 상태로 신청되었습니다.',
        'created': created,
    })


@require_GET
@ensure_csrf_cookie
def api_service_suggest(request):
    """
    LLM 기반 서비스 추천 API (Standard/Premium 전용)
    GET ?q=이사+직후+운전면허+은행+필요
    응답: {"suggested": ["DRIVERS_LICENSE", "BANK_ACCOUNT"]}
    """
    if not get_user_plan_policy(request.user).get('can_use_llm'):
        return JsonResponse({
            'suggested': [],
            'error': 'AI 서비스 추천은 스탠다드 이상 등급에서 이용 가능합니다.',
        }, status=403)

    query = (request.GET.get('q') or '').strip()
    if not query:
        return JsonResponse({'suggested': [], 'error': 'q 파라미터가 필요합니다.'}, status=400)

    suggested = _suggest_services_via_llm(query)
    return JsonResponse({'suggested': suggested})


def _suggest_services_via_llm(text: str) -> list:
    """
    사용자 입력을 LLM에 전달해 관련 서비스 코드 목록 반환.
    OPENAI_API_KEY 없으면 휴리스틱 매칭으로 폴백.
    """
    import os
    api_key = os.environ.get('OPENAI_API_KEY') or ''
    if not api_key:
        return _heuristic_match(text)

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        service_list = '\n'.join(
            f'- {code}: {get_service_label(code)}'
            for code in get_all_service_codes()
        )
        prompt = f"""다음은 미국 정착 관련 서비스 목록입니다.

{service_list}

사용자 요청: "{text}"

위 요청과 관련된 서비스 코드만 JSON 배열로 답하세요. 예: ["DRIVERS_LICENSE", "BANK_ACCOUNT"]
관련 없으면 빈 배열 []을 반환하세요. 코드 외 다른 텍스트는 넣지 마세요."""

        resp = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.1,
        )
        content = (resp.choices[0].message.content or '').strip()
        # JSON 파싱 (``` 제거)
        if content.startswith('```'):
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
        import json
        data = json.loads(content)
        valid = set(get_all_service_codes())
        return [s for s in (data if isinstance(data, list) else []) if s in valid]
    except Exception as e:
        return _heuristic_match(text)


@require_GET
@ensure_csrf_cookie
def api_schedule_generate(request):
    """
    선택된 서비스를 입국 날짜 기준 2주일 일정으로 배치 (Standard/Premium 전용)
    GET ?services=CODE1,CODE2&entry_date=YYYY-MM-DD
    응답: {"schedule": {"YYYY-MM-DD": [{"code": "X", "label": "Y"}, ...], ...}}
    """
    if not get_user_plan_policy(request.user).get('can_use_llm'):
        return JsonResponse({
            'schedule': {},
            'error': '스케줄 생성은 스탠다드 이상 등급에서 이용 가능합니다.',
        }, status=403)

    services_str = request.GET.get('services', '')
    entry_date_str = request.GET.get('entry_date', '')

    codes = [s.strip() for s in services_str.split(',') if s.strip()]
    valid = set(get_all_service_codes())
    codes = [c for c in codes if c in valid]
    if not codes:
        return JsonResponse({'schedule': {}, 'error': '선택된 서비스가 없습니다.'}, status=400)

    try:
        from datetime import datetime
        entry = datetime.strptime(entry_date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'schedule': {}, 'error': '입국 예정일을 YYYY-MM-DD 형식으로 입력해 주세요.'}, status=400)

    schedule = _generate_schedule(codes, entry, weeks=2)
    return JsonResponse({'schedule': schedule})


def _generate_schedule(codes: list, entry_date, weeks: int = 2) -> dict:
    """
    입국일 기준으로 서비스를 일정에 배치.
    LLM 있으면 사용, 없으면 휴리스틱(우선순위+날짜 분산).
    """
    import os
    from datetime import timedelta

    ordered = get_schedule_ordered_services(codes)
    api_key = os.environ.get('OPENAI_API_KEY') or ''
    schedule = {}

    if api_key:
        schedule = _schedule_via_llm(ordered, entry_date, weeks)
    if not schedule:
        schedule = _schedule_heuristic(ordered, entry_date, weeks)

    return schedule


def _schedule_via_llm(codes: list, entry_date, weeks: int) -> dict:
    """LLM으로 최적 일정 생성"""
    import json
    import os
    from datetime import timedelta

    service_list = ', '.join(f'{c}({get_service_label(c)})' for c in codes)
    entry_str = entry_date.strftime('%Y-%m-%d')
    end_date = entry_date + timedelta(days=weeks * 7)

    prompt = f"""미국 입국 후 정착 서비스 일정을 만들어 주세요.

입국일: {entry_str}
종료일: {end_date.strftime('%Y-%m-%d')} (약 {weeks}주)
서비스 목록: {service_list}

다음 규칙을 고려하세요:
- SSN은 가장 먼저 (은행 등에 필요)
- 공항픽업은 입국일
- 은행계좌는 SSN 이후
- 운전면허는 시간이 걸리므로 여유 있게
- 연관 서비스는 가깝게 배치
- 하루에 1~2개 서비스 권장

JSON으로만 답하세요. 형식: {{"YYYY-MM-DD": [["CODE1", "라벨1"], ["CODE2", "라벨2"]], ...}}
날짜는 입국일부터 {weeks}주 내로, 코드는 반드시 위 목록에서만 사용하세요."""

    try:
        import openai
        client = openai.OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        resp = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.2,
        )
        content = (resp.choices[0].message.content or '').strip()
        if content.startswith('```'):
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
        data = json.loads(content)
        valid = set(get_all_service_codes())
        result = {}
        for date_str, items in data.items():
            if not isinstance(items, list):
                continue
            lst = []
            for item in items:
                if isinstance(item, list) and len(item) >= 2:
                    code, label = item[0], item[1]
                elif isinstance(item, dict):
                    code = item.get('code') or item.get('CODE')
                    label = item.get('label') or get_service_label(str(code))
                else:
                    continue
                if code in valid:
                    lst.append({'code': code, 'label': label if label else get_service_label(code)})
            if lst:
                result[date_str] = lst
        return result
    except Exception:
        return {}


def _schedule_heuristic(codes: list, entry_date, weeks: int) -> dict:
    """휴리스틱: 우선순위 순으로 날짜에 분산 배치"""
    from datetime import timedelta

    ordered = get_schedule_ordered_services(codes)
    result = {}
    days_available = weeks * 7
    for i, code in enumerate(ordered):
        day_offset = min(i * 2, days_available - 1)  # 2일 간격, 남은 일수 초과 시 마지막 주
        d = entry_date + timedelta(days=day_offset)
        date_str = d.strftime('%Y-%m-%d')
        label = get_service_label(code)
        result.setdefault(date_str, []).append({'code': code, 'label': label})
    return result


def _heuristic_match(text: str) -> list:
    """한글 키워드로 서비스 매칭 (LLM 없을 때 폴백)"""
    text_lower = text.lower().replace(' ', '')
    result = []
    mapping = [
        ('주택투어', 'HOUSING_TOUR'), ('운전면허', 'DRIVERS_LICENSE'), ('병원', 'HOSPITAL_VISIT'),
        ('학교', 'SCHOOL_VISIT'), ('은행', 'BANK_ACCOUNT'), ('전화', 'PHONE_SETUP'),
        ('임대', 'RENTAL_SUPPORT'), ('유틸리티', 'UTILITY_SETUP'), ('이틸리티', 'UTILITY_SETUP'),
        ('가스', 'UTILITY_SETUP'), ('전기', 'UTILITY_SETUP'), ('수도', 'UTILITY_SETUP'),
        ('주택조사', 'HOUSING_RESEARCH'), ('조택조사', 'HOUSING_RESEARCH'), ('영상촬영', 'HOUSING_VIDEO'),
        ('차량', 'VEHICLE_PURCHASE'), ('차구매', 'VEHICLE_PURCHASE'), ('소셜', 'SSN_APPLICATION'),
        ('ssn', 'SSN_APPLICATION'), ('차등록', 'VEHICLE_REGISTRATION'), ('임대승인', 'RENTAL_APPROVAL'),
        ('임대계약', 'RENTAL_CONTRACT'), ('공항', 'AIRPORT_PICKUP'), ('픽업', 'AIRPORT_PICKUP'),
        ('렌트', 'VEHICLE_RENT'), ('차량렌트', 'VEHICLE_RENT'), ('지역투어', 'AREA_TOUR'),
        ('투어', 'AREA_TOUR'),
    ]
    for keyword, code in mapping:
        if keyword in text_lower and code not in result:
            result.append(code)
    return result
