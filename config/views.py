from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as AuthLoginView
from django.views.decorators.http import require_POST, require_GET
from django.utils import translation
from billing.utils import get_user_grade_display
from billing.models import Plan
from content.models import CarouselSlide
from translations.utils import (
    get_valid_language_codes,
    get_request_language,
    get_calendar_month_year_display,
    get_calendar_month_display,
    get_calendar_weekday_display,
)


class LoginView(AuthLoginView):
    """로그인 성공 시 DB 선호 언어로 세션·쿠키를 뷰에서 직접 설정 (시그널/미들웨어 의존 제거)."""

    def form_valid(self, form):
        user = form.get_user()
        try:
            user.refresh_from_db(fields=['preferred_language'])
        except Exception:
            pass
        login(self.request, user)
        valid = get_valid_language_codes()
        lang = (getattr(user, 'preferred_language', None) or '').strip()
        if not lang or lang not in valid:
            lang = 'en'
        self.request.session.pop('language_explicitly_set', None)
        self.request.session['django_language'] = lang
        self.request.session.modified = True
        translation.activate(lang)
        self.request.LANGUAGE_CODE = lang
        response = redirect(self.get_success_url())
        response.set_cookie('django_language', lang, max_age=365 * 24 * 60 * 60, path='/')
        return response


@require_POST
def set_language(request):
    """
    헤더 드롭다운 언어 변경 시: 세션·쿠키 저장 후 next로 리다이렉트(즉시 화면 리프레시).
    로그인 사용자는 선호 언어도 DB에 반영.
    """
    lang = (request.POST.get('language') or '').strip()
    next_url = request.POST.get('next') or request.GET.get('next') or '/'
    valid = get_valid_language_codes()
    if lang and lang in valid:
        request.session['django_language'] = lang
        request.session['language_explicitly_set'] = True
        request.session.modified = True
        translation.activate(lang)
        if getattr(request, 'user', None) and request.user.is_authenticated:
            if getattr(request.user, 'preferred_language', None) != lang:
                request.user.preferred_language = lang
                request.user.save(update_fields=['preferred_language'])
    response = redirect(next_url)
    if lang and lang in valid:
        response.set_cookie('django_language', lang, max_age=365 * 24 * 60 * 60, path='/')
    return response


@require_GET
def api_i18n(request, lang):
    """
    선택한 언어의 고정 번역 전체를 JSON으로 반환. 키 → 번역문.
    새로고침 없이 언어 전환 시 클라이언트에서 DOM 갱신용.
    """
    valid = get_valid_language_codes()
    if lang not in valid:
        return JsonResponse({}, status=400)
    from translations.models import StaticTranslation, LANG_CODE_TO_FIELD
    field_name = LANG_CODE_TO_FIELD.get(lang)
    if not field_name:
        return JsonResponse({})
    out = {}
    for row in StaticTranslation.objects.all().only('key', field_name):
        val = getattr(row, field_name, None)
        if val and str(val).strip():
            out[row.key] = str(val).strip()
        else:
            out[row.key] = (row.key or '').strip()
    return JsonResponse(out)


def home(request):
    from settlement.models import UserSettlementPlan

    slides = list(CarouselSlide.objects.filter(
        placement=CarouselSlide.Placement.HOME_INTRO,
        is_active=True
    ).order_by('order', 'id'))
    lang = get_request_language(request)
    try:
        from translations.utils import enrich_objects_for_display
        enrich_objects_for_display(slides, ['title', 'subtitle'], language_code=lang)
    except Exception:
        for s in slides:
            s.title_display = getattr(s, 'title', '') or ''
            s.subtitle_display = getattr(s, 'subtitle', '') or ''

    user_plan = None
    plan_schedule_json = '{}'
    if request.user.is_authenticated and request.user.role == 'CUSTOMER':
        try:
            plan = request.user.settlement_plan
            if plan.has_schedule():
                user_plan = plan
                import json
                from settlement.constants import enrich_schedule_with_appointment_status
                enriched = enrich_schedule_with_appointment_status(request.user, plan.service_schedule or {})
                plan_schedule_json = json.dumps(enriched)
        except UserSettlementPlan.DoesNotExist:
            pass

    # 달력 + 홈 플랜 카드 문구: StaticTranslation으로 지원 언어 동작
    plan_calendar_i18n = {}
    calendar_weekdays = []
    home_plan_i18n = {}
    plan_calendar_year_suffix = ''
    plan_calendar_month_suffix = ''
    if user_plan:
        from translations.utils import get_display_text
        lang = get_request_language(request)
        plan_calendar_i18n = {'lang': lang, 'year': get_display_text('년', lang), 'month': get_display_text('월', lang)}
        for i in range(1, 13):
            plan_calendar_i18n[f'month_{i}'] = get_calendar_month_display(i, lang)
        for i in range(7):
            plan_calendar_i18n[['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'][i]] = get_calendar_weekday_display(i, lang)
        calendar_weekdays = [get_calendar_weekday_display(i, lang) for i in range(7)]
        plan_calendar_year_suffix = get_display_text('년', lang)
        plan_calendar_month_suffix = get_display_text('월', lang)
        home_plan_i18n = {
            'my_plan_title': get_display_text('내 정착 플랜', lang),
            'estimated_checkout': get_display_text('예상 Checkout', lang),
            'won': get_display_text('원', lang),
            'entry_planned': get_display_text('입국 예정', lang),
            'saved_schedule': get_display_text('저장된 일정이 있습니다', lang),
            'edit_plan': get_display_text('정착 플랜 수정', lang),
        }

    return render(request, 'home.html', {
        'carousel_slides': slides,
        'user_plan': user_plan,
        'plan_schedule_json': plan_schedule_json,
        'plan_calendar_i18n': plan_calendar_i18n,
        'calendar_weekdays': calendar_weekdays,
        'plan_calendar_year_suffix': plan_calendar_year_suffix,
        'plan_calendar_month_suffix': plan_calendar_month_suffix,
        'home_plan_i18n': home_plan_i18n,
    })


def settlement_services(request):
    """정착서비스 메인 페이지"""
    return render(request, 'services/settlement.html')


def settlement_intro(request):
    """정착 서비스 소개"""
    return render(request, 'services/settlement_intro.html')


def settlement_quote(request):
    """서비스 견적 신청"""
    return render(request, 'services/settlement_quote.html')


def settlement_reviews(request):
    """고객 후기"""
    return render(request, 'services/settlement_reviews.html')


def settlement_cost_estimate(request):
    """셀프 정착 비용 예상"""
    return render(request, 'services/settlement_cost_estimate.html')


def corporate_services(request):
    """기업서비스 페이지"""
    return render(request, 'services/corporate.html')


def corporate_ad_register(request):
    """기업 광고 등록 신청"""
    from content.forms import CorporateAdRequestForm

    if request.method == 'POST':
        form = CorporateAdRequestForm(request.POST)
        if form.is_valid():
            form.save()
            from django.contrib import messages
            messages.success(request, '광고 등록 신청이 접수되었습니다. 검토 후 연락드리겠습니다.')
            return redirect('corporate_ad_register')
    else:
        form = CorporateAdRequestForm()
    return render(request, 'services/corporate_ad_register.html', {'form': form})


@login_required
def app_entry(request):
    """/app/ 진입점 - role별 대시보드 리다이렉트"""
    role = request.user.role
    if role == 'ADMIN':
        return redirect('app_admin_dashboard')
    if role == 'AGENT':
        return redirect('app_agent_dashboard')
    return redirect('app_customer_dashboard')


@login_required
def admin_dashboard(request):
    from translations.utils import get_display_text
    lang = get_request_language(request)
    admin_i18n = {
        'welcome_suffix': get_display_text('님, 환영합니다', lang),
        'admin_account': get_display_text('관리자 계정입니다.', lang),
        'my_plan': get_display_text('내 플랜:', lang),
        'view_content': get_display_text('컨텐츠 보기', lang),
    }
    return render(request, 'app/admin_dashboard.html', {
        'tier_label': get_user_grade_display(request.user, lang),
        'admin_i18n': admin_i18n,
    })


@login_required
def agent_dashboard(request):
    from translations.utils import get_display_text
    lang = get_request_language(request)
    agent_i18n = {
        'welcome_suffix': get_display_text('님, 환영합니다', lang),
        'agent_account': get_display_text('에이전트 계정입니다.', lang),
        'my_plan': get_display_text('내 플랜:', lang),
        'agent_calendar': get_display_text('고객 예약 달력', lang),
        'message_inbox': get_display_text('메시지 함', lang),
        'view_content': get_display_text('컨텐츠 보기', lang),
    }
    return render(request, 'app/agent_dashboard.html', {
        'tier_label': get_user_grade_display(request.user, lang),
        'agent_i18n': agent_i18n,
    })


@login_required
def agent_appointment_calendar(request):
    """에이전트용: 고객 예약 달력 (날짜별 예약 목록, 클릭 시 수락/메시지)."""
    from accounts.models import User
    from settlement.models import AgentAppointmentRequest
    from settlement.constants import get_service_label
    from messaging.models import Conversation
    import json
    from datetime import date
    from calendar import monthrange

    if request.user.role != User.Role.AGENT:
        return redirect('app_agent_dashboard')

    appointments = AgentAppointmentRequest.objects.filter(
        agent=request.user
    ).exclude(status='CANCELLED').select_related('customer').order_by('service_date', 'created_at')

    from translations.utils import get_display_text
    lang = get_request_language(request)

    # date_str -> [ { id, service_code, service_label, customer_display, status, conversation_id, ... } ]
    by_date = {}
    conv_by_appointment = {}
    for req in appointments:
        date_str = req.service_date.isoformat() if hasattr(req.service_date, 'isoformat') else str(req.service_date)
        raw_label = get_service_label(req.service_code)
        by_date.setdefault(date_str, []).append({
            'id': req.id,
            'service_code': req.service_code,
            'service_label': get_display_text(raw_label, lang) or raw_label,
            'customer_display': (req.customer.get_full_name() or req.customer.username) if req.customer_id else (req.customer_name or req.customer_email or '비로그인'),
            'customer_username': req.customer.username if req.customer_id else None,
            'status': req.status,
            'preferred_time': req.preferred_time or '',
            'message': (req.message or '')[:200],
            'created_at': req.created_at.isoformat() if req.created_at else None,
        })
        conv = Conversation.objects.filter(appointment=req).first()
        if conv:
            conv_by_appointment[req.id] = conv.id

    for date_str, items in by_date.items():
        for it in items:
            it['conversation_id'] = conv_by_appointment.get(it['id'])

    today = date.today()
    try:
        y = int(request.GET.get('year', today.year))
        m = int(request.GET.get('month', today.month))
        if m < 1 or m > 12:
            y, m = today.year, today.month
        first = date(y, m, 1)
    except (ValueError, TypeError):
        y, m = today.year, today.month
        first = date(y, m, 1)
    last_day = monthrange(y, m)[1]
    start_blank = (first.weekday() + 1) % 7
    calendar_days = []
    for _ in range(start_blank):
        calendar_days.append({'day': None, 'date_str': None, 'items': []})
    for d in range(1, last_day + 1):
        date_str = f'{y}-{m:02d}-{d:02d}'
        calendar_days.append({
            'day': d,
            'date_str': date_str,
            'items': by_date.get(date_str, []),
        })

    prev_m, prev_y = (m - 1, y) if m > 1 else (12, y - 1)
    next_m, next_y = (m + 1, y) if m < 12 else (1, y + 1)

    # 달력 제목 + 요일: 설정 언어에 맞게 (es 등 포함)
    cal_title = get_calendar_month_year_display(y, m, lang)
    calendar_weekdays = [get_calendar_weekday_display(i, lang) for i in range(7)]

    calendar_title_i18n = get_display_text('고객 예약 달력', lang)
    calendar_desc_i18n = get_display_text('고객이 신청한 약속을 날짜별로 확인하고, 수락하거나 메시지를 보낼 수 있습니다.', lang)
    prev_month_i18n = get_display_text('이전', lang)
    next_month_i18n = get_display_text('다음', lang)
    return render(request, 'app/agent_appointment_calendar.html', {
        'tier_label': get_user_grade_display(request.user, lang),
        'appointments_by_date_json': json.dumps(by_date),
        'calendar_days': calendar_days,
        'cal_year': y,
        'cal_month': m,
        'cal_title': cal_title,
        'calendar_weekdays': calendar_weekdays,
        'calendar_title_i18n': calendar_title_i18n,
        'calendar_desc_i18n': calendar_desc_i18n,
        'prev_month_i18n': prev_month_i18n,
        'next_month_i18n': next_month_i18n,
        'prev_year': prev_y,
        'prev_month': prev_m,
        'next_year': next_y,
        'next_month': next_m,
    })


@login_required
def customer_dashboard(request):
    from settlement.models import UserSettlementPlan, AgentAppointmentRequest
    from settlement.constants import get_service_label
    from billing.utils import get_user_free_agent_services
    from translations.utils import get_display_text, get_request_language
    import json

    lang = get_request_language(request)
    user_plan = None
    plan_schedule_json = '{}'
    try:
        plan = request.user.settlement_plan
        if plan.has_schedule():
            user_plan = plan
            from settlement.constants import enrich_schedule_with_appointment_status
            enriched = enrich_schedule_with_appointment_status(request.user, plan.service_schedule or {})
            # 달력에 표시할 서비스명·상태 라벨을 현재 언어로 번역
            for date_str, items in enriched.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    code = item.get('code') or ''
                    raw_label = item.get('label') or get_service_label(code)
                    item['label'] = get_display_text(raw_label, lang) or raw_label
                    if item.get('appointment_status_label'):
                        item['appointment_status_label'] = get_display_text(item['appointment_status_label'], lang) or item['appointment_status_label']
            plan_schedule_json = json.dumps(enriched)
    except UserSettlementPlan.DoesNotExist:
        pass

    free_agent_services = get_user_free_agent_services(request.user) if request.user.role == 'CUSTOMER' else []

    # 에이전트에게 할당되었고 아직 수락 전인 예약 목록 (고객 본인 것만), 서비스명 번역
    _pending_qs = []
    if request.user.is_authenticated:
        _pending_qs = list(
            AgentAppointmentRequest.objects.filter(
                customer=request.user,
                status='PENDING',
            ).exclude(agent_id__isnull=True).select_related('agent').order_by('service_date', 'created_at')
        )
    pending_appointments = [
        {
            'id': r.id,
            'service_label': get_display_text(get_service_label(r.service_code or ''), lang) or get_service_label(r.service_code or ''),
            'service_date': r.service_date.isoformat() if hasattr(r.service_date, 'isoformat') else str(r.service_date),
            'service_code': r.service_code or '',
            'preferred_time': r.preferred_time or '',
            'message': (r.message or '')[:200],
            'message_attr': ((r.message or '')[:200]).replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;'),
        }
        for r in _pending_qs
    ]

    # 달력 및 전체 대시보드 문구: 설정 언어에 맞게 (es 등 포함)
    dashboard_calendar_i18n = {'lang': lang, 'year': get_display_text('년', lang), 'month': get_display_text('월', lang)}
    for i in range(1, 13):
        dashboard_calendar_i18n[f'month_{i}'] = get_calendar_month_display(i, lang)
    for i in range(7):
        dashboard_calendar_i18n[['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'][i]] = get_calendar_weekday_display(i, lang)
    calendar_weekdays = [get_calendar_weekday_display(i, lang) for i in range(7)]

    # 대시보드 문구 전체 StaticTranslation
    dashboard_i18n = {
        'page_title': get_display_text('고객 대시보드', lang),
        'welcome_suffix': get_display_text('님, 환영합니다', lang),
        'customer_account': get_display_text('고객 계정입니다.', lang),
        'my_plan': get_display_text('내 플랜:', lang),
        'free_agent_services_label': get_display_text('무료 Agent 서비스:', lang),
        'pending_appointments': get_display_text('수락 대기 중인 예약', lang),
        'edit': get_display_text('수정', lang),
        'cancel': get_display_text('취소', lang),
        'my_schedule': get_display_text('내 정착 일정', lang),
        'estimated_checkout': get_display_text('예상 Checkout', lang),
        'won': get_display_text('원', lang),
        'entry_planned': get_display_text('입국 예정', lang),
        'prev': get_display_text('이전', lang),
        'next': get_display_text('다음', lang),
        'edit_plan': get_display_text('정착 플랜 수정', lang),
        'create_plan': get_display_text('정착 플랜 만들기', lang),
        'view_content': get_display_text('컨텐츠 보기', lang),
        'edit_appointment': get_display_text('예약 수정', lang),
        'preferred_time': get_display_text('희망 시간대', lang),
        'example_time': get_display_text('예: 오전 10시', lang),
        'message': get_display_text('메시지', lang),
        'message_placeholder': get_display_text('에이전트에게 전달할 메시지', lang),
        'save': get_display_text('저장', lang),
    }

    # 무료 Agent 서비스 라벨 번역
    free_agent_services_display = [
        (code, get_display_text(label, lang)) for code, label in free_agent_services
    ] if free_agent_services else []

    return render(request, 'app/customer_dashboard.html', {
        'tier_label': get_user_grade_display(request.user, lang),
        'user_plan': user_plan,
        'plan_schedule_json': plan_schedule_json,
        'free_agent_services': free_agent_services_display,
        'pending_appointments': pending_appointments,
        'dashboard_calendar_i18n': dashboard_calendar_i18n,
        'calendar_weekdays': calendar_weekdays,
        'calendar_year_suffix': get_display_text('년', lang),
        'calendar_month_suffix': get_display_text('월', lang),
        'dashboard_i18n': dashboard_i18n,
    })
