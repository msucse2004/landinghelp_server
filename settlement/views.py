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
from .models import SettlementQuoteRequest, AgentAppointmentRequest, SettlementService, UserSettlementPlan
from .constants import (
    get_services_by_category,
    get_all_service_codes,
    get_service_label,
    get_schedule_ordered_services,
    SCHEDULE_PRIORITY,
    calc_checkout_total,
    enrich_schedule_with_appointment_status,
    CATEGORY_ORDER,
)


def settlement_quote(request):
    """서비스 견적 신청 (폼 표시 및 제출 처리). 에이전트 계정은 정착 플랜 대신 고객예약 달력으로 이동."""
    lang = get_request_language(request)
    if request.user.is_authenticated and getattr(request.user, 'role', None) == 'AGENT':
        return redirect(reverse('app_agent_appointments'))
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
            msg = get_display_text('스케줄이 저장되었습니다. 예상 Checkout: %(total)s원', lang) % {'total': f'{checkout_total:,.0f}'}  # 스케줄이 저장되었습니다. 예상 Checkout: %(total)s원
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
        except UserSettlementPlan.DoesNotExist:
            pass

    # 저장된 플랜의 checkout 합계 (표시용) — Agent가 하나라도 할당된 경우에만 표시
    saved_checkout = 0
    if request.user.is_authenticated:
        try:
            plan = request.user.settlement_plan
            if plan.checkout_total and plan.has_agent_assignment():
                saved_checkout = float(plan.checkout_total)
        except UserSettlementPlan.DoesNotExist:
            pass

    raw_free_agent_services = get_user_free_agent_services(request.user) if request.user.is_authenticated else []
    free_agent_services = [(code, get_display_text(label, lang)) for code, label in raw_free_agent_services]

    # 서비스별 가격 (플로팅 요약 패널용) code -> { name, price }
    service_prices = {}
    for s in SettlementService.objects.filter(is_active=True):
        key = s.code or str(s.id)
        service_prices[key] = {'name': s.name, 'price': float(s.customer_price or 0)}
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
        'won': get_display_text('원', lang),
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
        'relocation_info': get_display_text('이주 정보', lang),
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

    return render(request, 'services/settlement_quote.html', {
        'form': form,
        'services_by_category': services_by_category,
        'selected_services': selected_services,
        'tier_info': tier_info,
        'can_use_llm': can_use_llm_user,
        'initial_schedule_json': json.dumps(initial_schedule),
        'saved_checkout_total': saved_checkout,
        'free_agent_services': free_agent_services,
        'service_prices_json': service_prices_json,
        'free_agent_service_codes_json': free_agent_service_codes_json,
        'settlement_i18n': settlement_i18n,
    })


@require_GET
@ensure_csrf_cookie
def api_agents_for_service(request):
    """
    서비스·지역 기준 가능한 Agent 목록. 서비스별 수락률(accept rate) 포함.
    GET ?service_code=DRIVERS_LICENSE&state=CA
    응답: {"agents": [{"id": 1, "name": "...", "rating_avg": 4.5, "accept_rate": 0.85, "accept_rate_display": "85%"}, ...]}
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Q, Count

    User = get_user_model()
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

    # DB에 저장된 현재 스케줄을 기준으로 함. (admin에서 약속 삭제 시 해당 슬롯은 이미 제거된 상태)
    # 클라이언트가 새로고침 없이 보낸 스케줄에 삭제된 슬롯이 있으면 약속 재생성·슬롯 재추가를 막음.
    try:
        plan = UserSettlementPlan.objects.get(user=request.user)
        current_schedule = plan.service_schedule or {}
    except UserSettlementPlan.DoesNotExist:
        plan = None
        current_schedule = {}
    if not isinstance(current_schedule, dict):
        current_schedule = {}
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
            agent_id = item.get('agent_id')
            if not code or not agent_id:
                continue
            # DB 현재 스케줄에 없는 (date, code)는 admin에서 삭제된 슬롯일 수 있으므로 약속 생성하지 않음
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
                AgentAppointmentRequest.objects.create(
                    agent=agent,
                    customer=request.user,
                    service_code=code,
                    service_date=service_date,
                    preferred_time=item.get('preferred_time') or '',
                    message=item.get('message') or '',
                    status='PENDING',
                )
                created += 1

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
