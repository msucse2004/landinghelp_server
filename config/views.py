from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView as AuthLoginView
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import translation, timezone
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


@ensure_csrf_cookie
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
            from settlement.schedule_utils import get_schedule_for_display
            schedule_data = get_schedule_for_display(plan) or {}
            if isinstance(schedule_data, dict) and schedule_data:
                user_plan = plan
                import json
                from settlement.constants import enrich_schedule_with_appointment_status
                enriched = enrich_schedule_with_appointment_status(request.user, schedule_data)
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
            'entry_planned': get_display_text('입국 예정', lang),
            'saved_schedule': get_display_text('저장된 일정이 있습니다', lang),
            'edit_plan': get_display_text('정착 플랜 수정', lang),
            'price_masked': get_display_text('견적 후 공개', lang),
        }
    can_show_plan_prices = True
    if request.user.is_authenticated:
        try:
            from settlement.constants import has_pending_survey_quote
            can_show_plan_prices = not has_pending_survey_quote(request.user)
        except Exception:
            pass
    is_customer = request.user.is_authenticated and getattr(request.user, 'role', None) == 'CUSTOMER'
    if is_customer and home_plan_i18n:
        from translations.utils import get_display_text
        lang = get_request_language(request)
        home_plan_i18n = dict(home_plan_i18n)
        home_plan_i18n['survey_link'] = get_display_text('설문 작성', lang)

    return render(request, 'home.html', {
        'carousel_slides': slides,
        'user_plan': user_plan,
        'plan_schedule_json': plan_schedule_json,
        'plan_calendar_i18n': plan_calendar_i18n,
        'calendar_weekdays': calendar_weekdays,
        'plan_calendar_year_suffix': plan_calendar_year_suffix,
        'plan_calendar_month_suffix': plan_calendar_month_suffix,
        'home_plan_i18n': home_plan_i18n,
        'can_show_plan_prices': can_show_plan_prices,
        'is_customer': is_customer,
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
@ensure_csrf_cookie
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
    schedule_data = {}
    try:
        plan = request.user.settlement_plan
        user_plan = plan
        from settlement.schedule_utils import (
            get_schedule_for_display,
            get_paid_service_codes_for_user,
            filter_schedule_to_paid_services,
        )
        schedule_data = get_schedule_for_display(plan) or {}
        paid_codes = get_paid_service_codes_for_user(request.user)
        if paid_codes and isinstance(schedule_data, dict):
            schedule_data = filter_schedule_to_paid_services(schedule_data, paid_codes)
        if isinstance(schedule_data, dict) and schedule_data:
            from settlement.constants import enrich_schedule_with_appointment_status
            enriched = enrich_schedule_with_appointment_status(request.user, schedule_data)
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
    dashboard_calendar_i18n['detail_title'] = get_display_text('서비스 상세', lang)
    dashboard_calendar_i18n['detail_service_name'] = get_display_text('서비스', lang)
    dashboard_calendar_i18n['detail_time'] = get_display_text('시간', lang)
    dashboard_calendar_i18n['detail_type'] = get_display_text('유형', lang)
    dashboard_calendar_i18n['detail_agent'] = get_display_text('담당 Agent', lang)
    dashboard_calendar_i18n['detail_location'] = get_display_text('장소 / 미팅 안내', lang)
    dashboard_calendar_i18n['detail_notes'] = get_display_text('메모 / 준비사항', lang)
    dashboard_calendar_i18n['detail_message_shortcut'] = get_display_text('메시지 보내기', lang)
    dashboard_calendar_i18n['close'] = get_display_text('닫기', lang)
    dashboard_calendar_i18n['type_self_search'] = get_display_text('직접 진행', lang)
    dashboard_calendar_i18n['type_ai'] = get_display_text('AI 지원', lang)
    dashboard_calendar_i18n['type_in_person'] = get_display_text('Agent 대면', lang)
    dashboard_calendar_i18n['no_time'] = get_display_text('—', lang)
    dashboard_calendar_i18n['no_location'] = get_display_text('—', lang)
    dashboard_calendar_i18n['no_notes'] = get_display_text('—', lang)
    dashboard_calendar_i18n['todays_services'] = get_display_text('오늘의 서비스', lang)
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
        'entry_planned': get_display_text('입국 예정', lang),
        'prev': get_display_text('이전', lang),
        'next': get_display_text('다음', lang),
        'edit_plan': get_display_text('정착 플랜 수정', lang),
        'my_quote': get_display_text('내 견적', lang),
        'create_plan': get_display_text('정착 플랜 만들기', lang),
        'survey_link': get_display_text('설문 작성', lang),
        'survey_title': get_display_text('서비스 이용을 위해 설문을 작성해 주세요', lang),
        'survey_desc': get_display_text('설문 제출 후 견적을 받으실 수 있습니다.', lang),
        'view_content': get_display_text('컨텐츠 보기', lang),
        'edit_appointment': get_display_text('예약 수정', lang),
        'preferred_time': get_display_text('희망 시간대', lang),
        'example_time': get_display_text('예: 오전 10시', lang),
        'message': get_display_text('메시지', lang),
        'message_placeholder': get_display_text('에이전트에게 전달할 메시지', lang),
        'save': get_display_text('저장', lang),
        'detail_title': get_display_text('서비스 상세', lang),
        'close': get_display_text('닫기', lang),
    }

    # 무료 Agent 서비스 라벨 번역
    free_agent_services_display = [
        (code, get_display_text(label, lang)) for code, label in free_agent_services
    ] if free_agent_services else []

    can_show_plan_prices = True
    try:
        from settlement.constants import has_pending_survey_quote
        can_show_plan_prices = not has_pending_survey_quote(request.user)
    except Exception:
        pass
    dashboard_i18n['price_masked'] = get_display_text('견적 후 공개', lang)

    submission_status_label = ''
    show_reopen_survey = False
    pending_reopen_offer = None
    try:
        from survey.models import SurveySubmission
        from settlement.models import CustomerActionOffer
        sub = SurveySubmission.objects.filter(user=request.user).exclude(
            status=SurveySubmission.Status.DRAFT
        ).order_by('-submitted_at').first()
        if sub:
            submission_status_label = get_display_text(sub.get_status_display(), lang) or sub.get_status_display()
            if sub.status == SurveySubmission.Status.SERVICE_IN_PROGRESS:
                completed, total = sub.get_service_progress()
                if total:
                    submission_status_label += f' ({completed}/{total} ' + (get_display_text('완료', lang) or '완료') + ')'
            show_reopen_survey = sub.status == SurveySubmission.Status.REVISION_REQUESTED
            if not show_reopen_survey:
                offer = CustomerActionOffer.objects.filter(
                    submission=sub,
                    button_action_key='reopen_survey',
                    status=CustomerActionOffer.Status.PENDING,
                    can_execute=True,
                ).order_by('-created_at').first()
                if offer:
                    pending_reopen_offer = {'id': offer.id, 'button_label': offer.button_label or get_display_text('설문 수정 시작', lang) or '설문 수정 시작'}
                    show_reopen_survey = True
    except Exception:
        pass

    schedule_has_items = bool(user_plan and isinstance(schedule_data, dict) and schedule_data)
    dashboard_i18n['schedule_empty'] = get_display_text('아직 확정된 일정이 없습니다.', lang)
    dashboard_i18n['assistant_link'] = get_display_text('AI 어시스턴트', lang)
    dashboard_i18n['rateable_title'] = get_display_text('완료된 서비스 평가', lang)
    dashboard_i18n['rateable_desc'] = get_display_text('서비스가 완료된 Agent에 대해 별점과 한줄평을 남겨 주세요.', lang)
    dashboard_i18n['rate_modal_title'] = get_display_text('서비스 평가', lang)
    dashboard_i18n['rate_stars'] = get_display_text('별점', lang)
    dashboard_i18n['rate_comment'] = get_display_text('한줄평 (선택)', lang)
    dashboard_i18n['rate_comment_placeholder'] = get_display_text('서비스에 대한 짧은 후기를 남겨 주세요.', lang)
    dashboard_i18n['rate_submit'] = get_display_text('제출', lang)
    dashboard_i18n['task_self_search'] = get_display_text('직접 진행', lang)
    dashboard_i18n['task_ai'] = get_display_text('AI 지원', lang)
    dashboard_i18n['meeting_agent'] = get_display_text('Agent 대면', lang)
    dashboard_i18n['survey_reopen_label'] = get_display_text('설문 다시 수정하기', lang) or '설문 다시 수정하기'

    # 설문 수정 재개 링크 (메시지함 링크와 동일; resume=1로 진입 시 비로그인 사용자 로그인 유도)
    from django.urls import reverse
    survey_resume_url = reverse('survey:survey_start') + '?resume=1'

    customer_ui_payload = {}
    try:
        from customer_request_service import build_customer_ui_payload
        customer_ui_payload = build_customer_ui_payload(request.user)
    except Exception:
        pass

    return render(request, 'app/customer_dashboard.html', {
        'tier_label': get_user_grade_display(request.user, lang),
        'user_plan': user_plan,
        'plan_schedule_json': plan_schedule_json,
        'schedule_has_items': schedule_has_items,
        'free_agent_services': free_agent_services_display,
        'pending_appointments': pending_appointments,
        'dashboard_calendar_i18n': dashboard_calendar_i18n,
        'calendar_weekdays': calendar_weekdays,
        'calendar_year_suffix': get_display_text('년', lang),
        'calendar_month_suffix': get_display_text('월', lang),
        'dashboard_i18n': dashboard_i18n,
        'can_show_plan_prices': can_show_plan_prices,
        'submission_status_label': submission_status_label,
        'show_reopen_survey': show_reopen_survey,
        'survey_resume_url': survey_resume_url,
        'pending_reopen_offer': pending_reopen_offer,
        'customer_ui_payload': customer_ui_payload,
    })


def _staff_required(user):
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_list(request):
    """Staff: 설문 제출 목록 (검토용). DRAFT 제외, 최신순."""
    from survey.models import SurveySubmission
    from django.core.paginator import Paginator

    qs = SurveySubmission.objects.exclude(
        status=SurveySubmission.Status.DRAFT
    ).select_related('user').order_by('-updated_at')
    paginator = Paginator(qs, 20)
    page = request.GET.get('page', 1)
    try:
        page_num = int(page)
    except (ValueError, TypeError):
        page_num = 1
    submissions = paginator.get_page(page_num)
    return render(request, 'app/submission_review_list.html', {
        'submissions': submissions,
        'page_obj': submissions,
    })


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def reset_survey_and_messaging_for_test(request):
    """
    Staff 전용: 견적서/설문 테스트를 위해 대화 DB와 설문 제출 DB를 전부 삭제.
    - messaging: MessageRead, MessageTranslation, Message, ConversationParticipant, Conversation
    - survey: SurveySubmission (CASCADE로 견적·변경요청·이벤트·카드별요청 등 함께 삭제)
    """
    from messaging.models import MessageRead, MessageTranslation, Message, ConversationParticipant, Conversation
    from survey.models import SurveySubmission
    from django.contrib import messages

    # 삭제 순서: 메시지 읽음/번역 → 메시지 → 참여자 → 대화 → 설문 제출(CASCADE로 견적·변경요청 등 제거)
    deleted = {}
    try:
        r = MessageRead.objects.all().delete()
        deleted['message_read'] = r[0]
        t = MessageTranslation.objects.all().delete()
        deleted['message_translation'] = t[0]
        m = Message.objects.all().delete()
        deleted['message'] = m[0]
        p = ConversationParticipant.objects.all().delete()
        deleted['conversation_participant'] = p[0]
        c = Conversation.objects.all().delete()
        deleted['conversation'] = c[0]
        s = SurveySubmission.objects.all().delete()
        deleted['survey_submission'] = s[0]
    except Exception as e:
        messages.error(request, f'리셋 중 오류: {e}')
        return redirect('app_submission_review_list')

    total = sum(deleted.values())
    messages.success(
        request,
        f'테스트 리셋 완료: 대화 {deleted.get("conversation", 0)}건, 설문 제출 {deleted.get("survey_submission", 0)}건 등 총 {total}건 삭제됨. '
        '새로 설문을 작성하고 견적서 플로우를 테스트할 수 있습니다.'
    )
    return redirect('app_submission_review_list')


def _format_answer_value(raw, question_dict):
    """설문 문항 정의(choices 등)에 따라 답변 표시 문자열 반환."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ''
    choices = question_dict.get('choices') or []
    if isinstance(raw, list):
        if not raw:
            return ''
        # 선택지가 있으면 value -> label 매핑
        choice_map = {str(c.get('value', '')).strip(): (c.get('label') or c.get('value') or '') for c in choices if c}
        labels = [choice_map.get(str(v).strip(), str(v)) for v in raw if v is not None]
        return ', '.join(labels) if labels else ', '.join(str(v) for v in raw)
    raw_str = str(raw).strip()
    for c in choices:
        if not c:
            continue
        v = c.get('value')
        if v is not None and str(v).strip() == raw_str:
            return (c.get('label') or c.get('value') or raw_str)
    return raw_str


def _build_customer_answers_by_section(submission):
    """
    Admin 검토용: 고객이 입력한 설문 전체를 섹션(카드)별로 묶어 반환.
    설문지에서 숨겨진 항목(내부 전용 섹션, 숨김 처리된 문항 키)은 검토 화면에서도 제외.
    반환: [ { 'section_title': str, 'section_id': int, 'items': [ {'key', 'label', 'value_display'} ] }, ... ]
    """
    from survey.models import SurveySection, SurveyQuestion
    from survey.constants import SURVEY_KEYS_HIDDEN_ON_FORM
    answers = getattr(submission, 'answers', None) or {}
    # 고객 설문에 노출되는 섹션만 (is_internal=False)
    sections = list(
        SurveySection.objects.filter(is_active=True, is_internal=False)
        .order_by('display_order', 'id')
        .prefetch_related('questions')
    )
    out = []
    for section in sections:
        questions = sorted(
            [q for q in section.questions.all() if q.is_active and q.key not in SURVEY_KEYS_HIDDEN_ON_FORM],
            key=lambda q: (q.order_in_section, q.order, q.id),
        )
        items = []
        for q in questions:
            raw = answers.get(q.key)
            value_display = _format_answer_value(raw, {
                'choices': q.choices or [],
                'field_type': q.field_type,
            })
            items.append({
                'key': q.key,
                'label': q.label,
                'value_display': value_display,
                'value_raw': raw,
            })
        if items:
            out.append({
                'section_title': section.title,
                'section_id': section.id,
                'items': items,
            })
    # 섹션에 묶이지 않은 문항(step만 있는 구 문항 등): answers에만 있는 키, 숨김 키 제외
    section_keys = set()
    for s in sections:
        for q in s.questions.all():
            if q.is_active:
                section_keys.add(q.key)

    def _has_value(v):
        if v is None:
            return False
        if isinstance(v, list):
            return len(v) > 0
        return str(v).strip() != ''

    orphan_keys = [
        k for k in answers.keys()
        if k not in section_keys and k not in SURVEY_KEYS_HIDDEN_ON_FORM and _has_value(answers.get(k))
    ]
    if orphan_keys:
        from survey.models import SurveyQuestion
        orphan_qs = SurveyQuestion.objects.filter(key__in=orphan_keys, is_active=True).order_by('step', 'order')
        q_map = {q.key: q for q in orphan_qs}
        items = []
        for key in orphan_keys:
            q = q_map.get(key)
            label = q.label if q else key
            raw = answers.get(key)
            value_display = _format_answer_value(raw, {'choices': (q.choices or []) if q else [], 'field_type': (q.field_type if q else 'text')})
            items.append({'key': key, 'label': label, 'value_display': value_display, 'value_raw': raw})
        if items:
            out.append({'section_title': '기타', 'section_id': None, 'items': items})
    return out


@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review(request, submission_id):
    """Staff: 제출 단건 검토 — 요청 요약, 견적 초안, 워크플로우, 결제/일정 요약, 조치 버튼."""
    from survey.models import SurveySubmission
    from survey.quote_input import get_quote_input_data
    from settlement.models import SettlementQuote, UserSettlementPlan, AgentAppointmentRequest
    from settlement.constants import get_service_label
    from django.shortcuts import get_object_or_404

    submission = get_object_or_404(SurveySubmission, id=submission_id)
    lang = get_request_language(request)

    # 고객 요약
    customer_name = ''
    if submission.user_id:
        u = submission.user
        customer_name = (u.get_full_name() or u.username or u.email or '').strip() or submission.email
    else:
        customer_name = submission.email
    customer_summary = {
        'name': customer_name,
        'email': submission.email,
        'user_id': submission.user_id,
        'username': submission.user.username if submission.user_id else None,
    }

    # 요청 요약 (정규화된 답변)
    request_data = get_quote_input_data(submission)
    service_codes = request_data.get('service_codes') or []
    add_on_codes = request_data.get('add_on_codes') or []
    request_summary = {
        'service_codes': service_codes,
        'add_on_codes': add_on_codes,
        'region': request_data.get('region') or '',
        'entry_date': request_data.get('entry_date') or '',
        'household_size': request_data.get('household_size'),
        'special_requirements': (request_data.get('special_requirements') or '').strip(),
        'raw': request_data,
    }
    # 선택 서비스 라벨 (표시용)
    request_summary['service_labels'] = [(c, get_service_label(c)) for c in service_codes]
    request_summary['add_on_labels'] = [(c, get_service_label(c)) for c in add_on_codes]

    # 견적 초안 (DRAFT)
    quote_draft = (
        SettlementQuote.objects.filter(
            submission=submission,
            status=SettlementQuote.Status.DRAFT,
        ).order_by('-updated_at').first()
    )
    if not quote_draft:
        latest_revision_base_quote = (
            SettlementQuote.objects.filter(submission=submission)
            .exclude(status=SettlementQuote.Status.DRAFT)
            .order_by('-created_at', '-updated_at')
            .first()
        )
        if latest_revision_base_quote and latest_revision_base_quote.items:
            cloned_items = []
            for it in (latest_revision_base_quote.items or []):
                if not isinstance(it, dict):
                    continue
                cloned_items.append({k: v for k, v in it.items() if k not in ('_auto', '_needs_review')})
            if cloned_items:
                quote_draft = SettlementQuote.objects.create(
                    submission=submission,
                    status=SettlementQuote.Status.DRAFT,
                    version=(latest_revision_base_quote.version or 1) + 1,
                    region=latest_revision_base_quote.region or '',
                    items=cloned_items,
                    total=latest_revision_base_quote.total or 0,
                    draft_source='auto',
                    auto_generated_at=timezone.now(),
                )
    # 고객 요청 서비스 형태 라벨 (직접 검색 / AI 서비스 / Agent 직접 도움)
    _delivery_labels = {
        'direct_search': '직접 검색',
        'ai_service': 'AI 서비스',
        'agent_direct': 'Agent 직접 도움',
    }
    answers = getattr(submission, 'answers', None) or {}
    per_service = answers.get('service_delivery_per_service') or {}
    bulk_preference = (answers.get('service_delivery_preference') or '').strip()

    items_with_flags = []
    if quote_draft and quote_draft.items:
        for it in quote_draft.items:
            if not isinstance(it, dict):
                continue
            item = dict(it)
            needs_review = item.pop('_needs_review', False)
            is_auto = item.pop('_auto', False)
            code = item.get('code', '')
            delivery_key = per_service.get(code) or bulk_preference
            delivery_label = _delivery_labels.get(delivery_key, '') if delivery_key else ''
            items_with_flags.append({
                **item,
                'needs_review': needs_review,
                'is_auto': is_auto,
                'delivery_label': delivery_label,
            })
    quote_draft_display = None
    if quote_draft:
        quote_draft_display = {
            'id': quote_draft.id,
            'region': quote_draft.region or '',
            'total': int(quote_draft.total or 0),
            'items': items_with_flags,
            'draft_source': quote_draft.draft_source or '',
            'auto_generated_at': quote_draft.auto_generated_at,
            'version': quote_draft.version,
        }
    needs_quote_review = any(i.get('needs_review') for i in items_with_flags)

    def _quote_item_codes(quote_obj):
        out = []
        if not quote_obj:
            return out
        for it in (getattr(quote_obj, 'items', None) or []):
            if not isinstance(it, dict):
                continue
            code = str(it.get('code') or '').strip()
            if code and code not in out:
                out.append(code)
        return out

    # 워크플로우 상태
    workflow_status = {
        'status': submission.status,
        'label': submission.get_status_display(),
        'submitted_at': submission.submitted_at,
        'revision_requested_at': submission.revision_requested_at,
        'revision_message': (submission.revision_requested_message or '').strip(),
    }
    if submission.status == SurveySubmission.Status.SERVICE_IN_PROGRESS:
        completed, total = submission.get_service_progress()
        workflow_status['service_progress_completed'] = completed
        workflow_status['service_progress_total'] = total

    # 결제 요약 (FINAL_SENT / PAID 견적)
    payment_quote = (
        SettlementQuote.objects.filter(
            submission=submission,
            status__in=(SettlementQuote.Status.FINAL_SENT, SettlementQuote.Status.PAID),
        ).order_by('-updated_at').first()
    )
    payment_summary = None
    if payment_quote:
        payment_summary = {
            'status': payment_quote.status,
            'status_label': payment_quote.get_status_display(),
            'total': int(payment_quote.total or 0),
            'sent_at': payment_quote.sent_at,
            'superseded': bool(getattr(payment_quote, 'revision_superseded_at', None)),
        }

    # DRAFT 없고 송부/결제된 견적만 있을 때: 해당 견적을 읽기 전용으로 견적서 카드에 표시(기존 견적서 유지)
    quotation_read_only = False
    if not quote_draft_display and payment_quote and payment_quote.items:
        sent_items = []
        for it in payment_quote.items:
            if not isinstance(it, dict):
                continue
            item = dict(it).copy()
            item.pop('_needs_review', None)
            item.pop('_auto', None)
            code = item.get('code', '')
            delivery_key = per_service.get(code) or bulk_preference
            delivery_label = _delivery_labels.get(delivery_key, '') if delivery_key else ''
            sent_items.append({**item, 'delivery_label': delivery_label})
        quote_draft_display = {
            'id': payment_quote.id,
            'region': payment_quote.region or '',
            'total': int(payment_quote.total or 0),
            'items': sent_items,
            'draft_source': '',
            'auto_generated_at': None,
            'version': payment_quote.version,
        }
        quotation_read_only = True

    survey_service_codes = list(dict.fromkeys(list(getattr(submission, 'requested_required_services', None) or []) + list(getattr(submission, 'requested_optional_services', None) or [])))
    if not survey_service_codes:
        survey_service_codes = list(request_summary.get('service_codes') or [])
    compare_quote = quote_draft or payment_quote
    quote_service_codes = _quote_item_codes(compare_quote)
    missing_in_survey = [c for c in quote_service_codes if c not in set(survey_service_codes)]
    missing_in_quote = [c for c in survey_service_codes if c not in set(quote_service_codes)]
    service_mismatch = {
        'has_mismatch': bool(missing_in_survey or missing_in_quote),
        'survey_codes': survey_service_codes,
        'quote_codes': quote_service_codes,
        'missing_in_survey': missing_in_survey,
        'missing_in_quote': missing_in_quote,
        'missing_in_survey_labels': [get_service_label(c) for c in missing_in_survey],
        'missing_in_quote_labels': [get_service_label(c) for c in missing_in_quote],
    }

    # 일정 준비도 및 필요 작업 (결제 후)
    scheduling_summary = None
    required_tasks = []
    if submission.user_id and payment_quote and payment_quote.status == SettlementQuote.Status.PAID:
        try:
            from settlement.models import PlanServiceTask
            plan = UserSettlementPlan.objects.get(user_id=submission.user_id)
            appointments = list(
                AgentAppointmentRequest.objects.filter(
                    customer_id=submission.user_id,
                ).exclude(status='CANCELLED').select_related('agent').order_by('service_date')
            )
            assigned = plan.assigned_agent_id
            pending = sum(1 for a in appointments if a.status == 'PENDING')
            confirmed = sum(1 for a in appointments if a.status == 'CONFIRMED')
            scheduling_summary = {
                'has_plan': True,
                'assigned_agent': plan.assigned_agent,
                'assigned_agent_name': (plan.assigned_agent.get_full_name() or plan.assigned_agent.username) if assigned else None,
                'total_appointments': len(appointments),
                'pending': pending,
                'confirmed': confirmed,
            }
            # 견적 기준 필요 작업(PlanServiceTask) 목록 — Admin 확인·에이전트 배정 현황
            tasks_qs = PlanServiceTask.objects.filter(plan=plan).order_by('display_order').select_related('appointment')
            for t in tasks_qs:
                if t.appointment_id:
                    status_key = t.appointment.status if t.appointment else 'PENDING'
                    status_label = {'PENDING': '수락 대기', 'CONFIRMED': '확정', 'CANCELLED': '취소'}.get(status_key, status_key)
                else:
                    status_key = 'NOT_SCHEDULED'
                    status_label = '미배정'
                required_tasks.append({
                    'service_code': t.service_code,
                    'label': t.label or t.service_code,
                    'status': status_key,
                    'status_label': status_label,
                    'appointment_id': t.appointment_id,
                })
        except UserSettlementPlan.DoesNotExist:
            scheduling_summary = {'has_plan': False, 'total_appointments': 0, 'pending': 0, 'confirmed': 0}

    # Admin 조치 필요 영역
    needs_admin_decision = []
    if submission.status == SurveySubmission.Status.SUBMITTED:
        if not quote_draft:
            needs_admin_decision.append('견적 초안 없음 — 생성 또는 수동 작성 필요')
        elif needs_quote_review:
            needs_admin_decision.append('일부 항목 가격/코드 검토 필요 (_needs_review)')
        if not request_summary['service_codes'] and not request_summary['add_on_codes']:
            needs_admin_decision.append('선택된 서비스 없음 — 확인 필요')
    if submission.status == SurveySubmission.Status.REVISION_REQUESTED:
        needs_admin_decision.append('고객 수정 대기 중')

    # 자동 체크 포인트 (운영자 수동 확인 최소화)
    from survey.submission_checks import run_submission_checks
    submission_readiness = run_submission_checks(submission, quote_draft)

    # 카드별 수정 요청: 고객 노출 카드 목록, 현재 미해결 수정 요청 카드
    from survey.models import SurveySection, SurveySubmissionSectionRequest
    available_sections = list(
        SurveySection.objects.filter(is_active=True, is_internal=False)
        .order_by('display_order').values('id', 'title')
    )
    pending_section_requests = list(
        SurveySubmissionSectionRequest.objects.filter(
            submission=submission, resolved_at__isnull=True
        ).values_list('section_id', flat=True)
    )

    # 견적서 공식 포맷용 컨텍스트 (견적 번호: Q-YYYY-MM-DD-{그날 견적서 순번}, 유효기간 견적일자 기준 10일)
    from datetime import timedelta
    _now = timezone.now()
    _company = getattr(settings, 'QUOTATION_COMPANY_NAME', 'LifeAI US')
    _valid_days = 10  # 견적일자 기준 10일
    display_quote = quote_draft or payment_quote
    if display_quote:
        _qdate = display_quote.created_at.date()
        _daily_seq = SettlementQuote.objects.filter(
            created_at__date=_qdate, id__lte=display_quote.id
        ).count()
        _quotation_number = f'Q-{_qdate:%Y-%m-%d}-{_daily_seq}'
        _quotation_date = _qdate.strftime('%Y-%m-%d')
    else:
        _qdate = _now.date()
        _daily_seq = SettlementQuote.objects.filter(created_at__date=_qdate).count() + 1
        _quotation_number = f'Q-{_qdate:%Y-%m-%d}-{_daily_seq}'
        _quotation_date = _now.strftime('%Y-%m-%d')
    _quote_lang = 'en'
    if getattr(submission, 'user_id', None) and submission.user_id:
        try:
            _pref = (getattr(submission.user, 'preferred_language', None) or '').strip().lower()
            if _pref and _pref[:2] == 'ko':
                _quote_lang = 'ko'
            elif _pref:
                _quote_lang = _pref[:2]
        except Exception:
            pass
    _QUOTE_TERMS = {
        'ko': '결제는 수락 시에 이루어집니다. 본 견적서는 위에 명시된 날짜까지 유효합니다. 서비스 및 가격은 주문 시 합의된 범위에 따릅니다.',
        'en': 'Payment due upon acceptance. This quotation is valid until the date stated above. Services and pricing are subject to the scope agreed at the time of order.',
    }
    _QUOTE_CONTACT = {
        'ko': '문의 사항은 메시지 또는 이메일로 연락 주세요.',
        'en': 'For questions, please contact us via message or email.',
    }
    _terms_text = _QUOTE_TERMS.get(_quote_lang) or _QUOTE_TERMS['en']
    _contact_text = _QUOTE_CONTACT.get(_quote_lang) or _QUOTE_CONTACT['en']
    _valid_until_date = (_qdate + timedelta(days=_valid_days)).strftime('%Y-%m-%d')
    quotation_context = {
        'company_name': _company,
        'quotation_number': _quotation_number,
        'quotation_date': _quotation_date,
        'valid_until': _valid_until_date,
        'terms': _terms_text,
        'contact_footer': _contact_text,
    }

    customer_answers_by_section = _build_customer_answers_by_section(submission)

    # 고객 수정 요청(자유 텍스트) + LLM 해석 결과
    from settlement.models import QuoteChangeRequest
    latest_change_request = (
        QuoteChangeRequest.objects.filter(submission=submission)
        .order_by('-created_at')
        .select_related('quote')
        .first()
    )
    latest_change_analysis = None
    suggested_actions = []
    latest_customer_revision = None
    if latest_change_request:
        latest_change_analysis = latest_change_request.latest_analysis()
        if latest_change_analysis and getattr(latest_change_analysis, 'extracted_actions', None):
            for a in latest_change_analysis.extracted_actions:
                if isinstance(a, dict):
                    sc = a.get('service_code') or ''
                    suggested_actions.append({
                        'action_type': a.get('action_type', ''),
                        'service_code': sc,
                        'service_label': get_service_label(sc) if sc else '',
                        'reason': (a.get('reason') or '')[:300],
                    })
        changed_items = []
        ignore_action_codes = {
            'ROUTE_TO_ADMIN_REVIEW', 'ROUTE_TO_AGENT_REVIEW', 'ROUTE_TO_ADMIN_THEN_AGENT',
            'REPLY_WITH_INFORMATION', 'REPLY_WITH_STATUS',
        }
        action_label_map = {
            'PROPOSE_ADD_SERVICE': '서비스 추가',
            'PROPOSE_REMOVE_SERVICE': '서비스 제거',
            'PROPOSE_CHANGE_SERVICE': '서비스 변경',
            'OFFER_SURVEY_REOPEN': '설문 항목 수정',
            'OFFER_SURVEY_RESUME': '설문 재개',
            'OFFER_QUOTE_REVISION_REQUEST': '견적 항목 수정',
            'ADD': '서비스 추가',
            'REMOVE': '서비스 제거',
            'CHANGE': '서비스 변경',
        }
        for a in suggested_actions:
            raw_action = (a.get('action_type') or '').strip().upper()
            if not raw_action or raw_action in ignore_action_codes:
                continue
            action_text = action_label_map.get(raw_action, '')
            label = (a.get('service_label') or a.get('service_code') or '').strip()
            if action_text and label:
                text = f"{action_text}: {label}"
            elif action_text:
                text = action_text
            else:
                text = label
            if text and text not in changed_items:
                changed_items.append(text)

        hint_texts = [
            (latest_change_request.customer_message or ''),
            (getattr(latest_change_analysis, 'normalized_summary', '') if latest_change_analysis else ''),
            (getattr(latest_change_analysis, 'recommended_next_step', '') if latest_change_analysis else ''),
        ]
        merged_hint_text = ' '.join([str(t or '').lower() for t in hint_texts])
        field_hints = [
            ('서비스 항목', ('서비스', '희망 서비스', '추가', '삭제', '제거', '변경', 'option')),
            ('입국 날짜', ('입국', '입국일', 'entry', 'arrival date')),
            ('출국 날짜', ('출국', '출국일', 'departure date', 'return date')),
            ('체류 기간', ('체류', '기간', 'stay period', 'duration')),
            ('인원 수', ('인원', '가구', '동반', 'household')),
            ('비자 정보', ('비자', 'visa')),
            ('이름 정보', ('이름', '성명', 'first name', 'last name', '한글 이름')),
            ('연락처 정보', ('휴대폰', '전화', '이메일', '채팅앱', '카톡', 'whatsapp', 'telegram')),
            ('거주 국가/도시', ('현재 거주', '국가', '도시', 'state', 'city', 'address')),
            ('입국 목적/체류 신분', ('입국 목적', '체류 신분', 'purpose', 'status')),
            ('주거 정보', ('거주 형태', 'housing', 'house', '아파트', '콘도')),
            ('공항/항공편 정보', ('공항', '항공편', '비행편', '도착 시간', '도착시간', 'flight')),
            ('픽업 일정', ('픽업', 'pickup', 'pick up')),
            ('서비스 진행 방식', ('진행 방식', '서비스 방식', 'delivery mode', 'preference')),
            ('기타 요청 내용', ('기타 요청', 'other request', '추가 요청', '메모')),
        ]
        for label, keywords in field_hints:
            if any(str(k).lower() in merged_hint_text for k in keywords):
                if label not in changed_items:
                    changed_items.append(label)

        if not changed_items and latest_change_analysis and getattr(latest_change_analysis, 'extracted_service_codes', None):
            for code in (latest_change_analysis.extracted_service_codes or []):
                sc = str(code or '').strip()
                if not sc:
                    continue
                label = get_service_label(sc) or sc
                if label not in changed_items:
                    changed_items.append(label)
        if not changed_items and (latest_change_request.customer_message or '').strip():
            changed_items.append('고객 원문 기반 수동 확인 필요')
        latest_customer_revision = {
            'changed_at': latest_change_request.created_at,
            'status_label': latest_change_request.get_status_display(),
            'changed_items': changed_items[:8],
            'raw_message': (latest_change_request.customer_message or '').strip(),
        }
    can_reopen_survey = bool(
        latest_change_request and getattr(latest_change_request, 'can_be_reopened_for_survey_edit', lambda: False)()
    )
    from customer_request_service import get_submission_reopen_status
    reopen_status = get_submission_reopen_status(submission)
    can_start_quote_revision = bool(
        (quote_draft or payment_quote)
        and submission.status in (SurveySubmission.Status.SUBMITTED, SurveySubmission.Status.AWAITING_PAYMENT)
    )
    # 설문 재제출 후: change request가 IN_REVIEW이면 Admin에게 새 견적 작성·송부 안내
    if (
        submission.status == SurveySubmission.Status.SUBMITTED
        and latest_change_request
        and latest_change_request.status == QuoteChangeRequest.Status.IN_REVIEW
    ):
        needs_admin_decision.append('고객이 수정을 재제출했습니다. 변경된 설문을 반영해 새 견적 초안을 검토한 뒤 송부하세요.')

    # 재견적 흐름 추적: 이 submission의 견적 이력 + 각 견적이 반영한 변경 요청
    from settlement.models import QuoteChangeActionLog
    quotes_for_submission = list(
        SettlementQuote.objects.filter(submission=submission).order_by('-created_at').values(
            'id', 'status', 'sent_at', 'revision_superseded_at', 'supersedes_id', 'version', 'created_at'
        )
    )
    quote_trail = []
    for q in quotes_for_submission:
        applied_cr_ids = list(
            QuoteChangeActionLog.objects.filter(
                action_type=QuoteChangeActionLog.ActionType.ADMIN_APPROVED_QUOTE_REVISION,
                detail__sent_quote_id=q['id'],
            ).values_list('change_request_id', flat=True).distinct()
        )
        superseded_quote_id = q.get('supersedes_id')
        quote_trail.append({
            'id': q['id'],
            'status': q['status'],
            'status_display': dict(SettlementQuote.Status.choices).get(q['status'], q['status']),
            'sent_at': q['sent_at'],
            'revision_superseded_at': q['revision_superseded_at'],
            'supersedes_id': superseded_quote_id,
            'version': q.get('version'),
            'created_at': q['created_at'],
            'applied_change_request_ids': applied_cr_ids,
        })
    submission_revision_info = {
        'revision_count': getattr(submission, 'revision_count', None) or 0,
        'reopened_at': getattr(submission, 'reopened_at', None),
    }

    return render(request, 'app/submission_review.html', {
        'submission': submission,
        'customer_summary': customer_summary,
        'customer_answers_by_section': customer_answers_by_section,
        'request_summary': request_summary,
        'quote_draft': quote_draft,
        'quote_draft_display': quote_draft_display,
        'needs_quote_review': needs_quote_review,
        'workflow_status': workflow_status,
        'payment_summary': payment_summary,
        'scheduling_summary': scheduling_summary,
        'needs_admin_decision': needs_admin_decision,
        'available_sections': available_sections,
        'pending_section_requests': pending_section_requests,
        'required_tasks': required_tasks,
        'submission_readiness': submission_readiness,
        'quotation_context': quotation_context,
        'quotation_read_only': quotation_read_only,
        'latest_change_request': latest_change_request,
        'latest_change_analysis': latest_change_analysis,
        'latest_customer_revision': latest_customer_revision,
        'suggested_actions': suggested_actions,
        'can_reopen_survey': can_reopen_survey,
        'can_start_quote_revision': can_start_quote_revision,
        'reopen_status': reopen_status,
        'quote_trail': quote_trail,
        'submission_revision_info': submission_revision_info,
        'service_mismatch': service_mismatch,
    })


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_request_revision(request, submission_id):
    """
    Staff: 고객에게 수정 요청 (REVISION_REQUESTED).
    상태·revision_requested_at/message 갱신, 이벤트 로그, 공유 대화에 메시지 + 이메일(설정 시) 발송.
    """
    from survey.models import SurveySubmission, SurveySubmissionEvent
    from django.shortcuts import get_object_or_404
    from django.contrib import messages

    submission = get_object_or_404(SurveySubmission, id=submission_id)
    if submission.status != SurveySubmission.Status.SUBMITTED:
        messages.warning(request, '수정 요청은 제출(SUBMITTED) 상태에서만 가능합니다.')
        return redirect('app_submission_review', submission_id=submission_id)
    message = (request.POST.get('revision_message') or '').strip()
    submission.status = SurveySubmission.Status.REVISION_REQUESTED
    submission.revision_requested_at = timezone.now()
    submission.revision_requested_message = message
    submission.save(update_fields=['status', 'revision_requested_at', 'revision_requested_message'])
    SurveySubmissionEvent.objects.create(
        submission=submission,
        event_type=SurveySubmissionEvent.EventType.REVISION_REQUESTED,
        created_by=request.user,
        meta={'message': message[:500]},
    )
    lang = 'ko'
    if getattr(submission, 'user_id', None) and submission.user_id:
        lang = (getattr(submission.user, 'preferred_language', None) or '').strip() or lang
    try:
        from settlement.notifications import send_revision_requested_customer_message, send_revision_requested_customer_email
        send_revision_requested_customer_message(submission, language_code=lang, revision_message=message)
        send_revision_requested_customer_email(submission, language_code=lang, revision_message=message)
    except Exception:
        pass
    messages.success(request, '고객에게 수정 요청을 보냈습니다. (앱 메시지함 + 이메일 발송됨)')
    return redirect('app_submission_review', submission_id=submission_id)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_request_section_updates(request, submission_id):
    """
    Staff: 특정 카드(섹션)만 고객에게 수정 요청. 구조화된 재입력 유도.
    SurveySubmissionSectionRequest 생성, REVISION_REQUESTED 설정, 이벤트 로그, 메시지+이메일 발송.
    """
    from survey.models import SurveySubmission, SurveySection, SurveySubmissionSectionRequest, SurveySubmissionEvent
    from django.shortcuts import get_object_or_404
    from django.contrib import messages

    submission = get_object_or_404(SurveySubmission, id=submission_id)
    if submission.status != SurveySubmission.Status.SUBMITTED:
        messages.warning(request, '카드별 수정 요청은 제출(SUBMITTED) 상태에서만 가능합니다.')
        return redirect('app_submission_review', submission_id=submission_id)

    section_ids = request.POST.getlist('section_ids')
    section_ids = [int(x) for x in section_ids if str(x).isdigit()]
    message = (request.POST.get('section_update_message') or '').strip()

    valid_section_ids = set(
        SurveySection.objects.filter(
            is_active=True, is_internal=False, id__in=section_ids
        ).values_list('id', flat=True)
    )
    section_ids = [i for i in section_ids if i in valid_section_ids]
    if not section_ids:
        messages.warning(request, '수정 요청할 카드를 하나 이상 선택해 주세요.')
        return redirect('app_submission_review', submission_id=submission_id)

    existing = set(
        SurveySubmissionSectionRequest.objects.filter(
            submission=submission, section_id__in=section_ids, resolved_at__isnull=True
        ).values_list('section_id', flat=True)
    )
    for sid in section_ids:
        if sid not in existing:
            SurveySubmissionSectionRequest.objects.create(
                submission=submission,
                section_id=sid,
                message=message,
                requested_by=request.user,
            )
            existing.add(sid)

    sections = list(SurveySection.objects.filter(id__in=section_ids).order_by('display_order').values_list('title', flat=True))
    revision_message = '다음 카드를 수정해 주세요: ' + ', '.join(sections)
    if message:
        revision_message += '\n\n' + message
    submission.status = SurveySubmission.Status.REVISION_REQUESTED
    submission.revision_requested_at = timezone.now()
    submission.revision_requested_message = revision_message
    submission.save(update_fields=['status', 'revision_requested_at', 'revision_requested_message'])

    SurveySubmissionEvent.objects.create(
        submission=submission,
        event_type=SurveySubmissionEvent.EventType.SECTIONS_UPDATE_REQUESTED,
        created_by=request.user,
        meta={'section_ids': section_ids, 'section_titles': list(sections), 'message': message[:500]},
    )
    lang = 'ko'
    if getattr(submission, 'user_id', None) and submission.user_id:
        lang = (getattr(submission.user, 'preferred_language', None) or '').strip() or lang
    try:
        from settlement.notifications import send_revision_requested_customer_message, send_revision_requested_customer_email
        send_revision_requested_customer_message(
            submission,
            language_code=lang,
            section_titles=list(sections),
            revision_message=message,
        )
        send_revision_requested_customer_email(
            submission,
            language_code=lang,
            section_titles=list(sections),
            revision_message=message,
        )
    except Exception:
        pass
    messages.success(request, '선택한 카드에 대한 수정 요청을 고객에게 보냈습니다. (앱 메시지함 + 이메일)')
    return redirect('app_submission_review', submission_id=submission_id)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_generate_draft(request, submission_id):
    """Staff: 견적 초안 자동 생성/갱신."""
    from survey.models import SurveySubmission
    from settlement.quote_draft import generate_quote_draft_from_submission
    from django.shortcuts import get_object_or_404
    from django.contrib import messages

    submission = get_object_or_404(SurveySubmission, id=submission_id)
    generate_quote_draft_from_submission(submission, actor=request.user)
    messages.success(request, '견적 초안을 생성·갱신했습니다.')
    return redirect('app_submission_review', submission_id=submission_id)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_update_quote_prices(request, submission_id):
    """Staff: 견적 초안 항목 가격을 USD로 수정 저장."""
    from survey.models import SurveySubmission
    from settlement.models import SettlementQuote
    from django.shortcuts import get_object_or_404
    from django.contrib import messages
    from decimal import Decimal

    submission = get_object_or_404(SurveySubmission, id=submission_id)
    quote = (
        SettlementQuote.objects.filter(
            submission=submission,
            status=SettlementQuote.Status.DRAFT,
        ).order_by('-updated_at').first()
    )
    if not quote or not quote.items:
        messages.error(request, '수정할 견적 초안이 없습니다.')
        return redirect('app_submission_review', submission_id=submission_id)
    items = list(quote.items)
    total = Decimal('0')
    for i in range(len(items)):
        if not isinstance(items[i], dict):
            continue
        key = 'price_%d' % i
        val = request.POST.get(key)
        try:
            price = int(Decimal(str(val or 0)))
        except Exception:
            price = int(items[i].get('price') or 0)
        items[i]['price'] = price
        total += price
    quote.items = items
    quote.total = total
    quote.save(update_fields=['items', 'total', 'updated_at'])
    messages.success(request, '견적 가격(USD)을 저장했습니다.')
    return redirect('app_submission_review', submission_id=submission_id)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_approve_quote(request, submission_id):
    """Staff: 초안 견적을 최종 승인하고 고객에게 송부. POST에 price_N 있으면 먼저 반영 후 승인."""
    from survey.models import SurveySubmission
    from settlement.models import SettlementQuote
    from settlement.quote_approval import finalize_and_send_quote
    from django.shortcuts import get_object_or_404
    from django.contrib import messages
    from decimal import Decimal

    submission = get_object_or_404(SurveySubmission, id=submission_id)
    quote = (
        SettlementQuote.objects.filter(
            submission=submission,
            status=SettlementQuote.Status.DRAFT,
        ).order_by('-updated_at').first()
    )
    if not quote:
        messages.error(request, '이 제출에 대한 견적 초안이 없습니다. 먼저 초안을 생성하세요.')
        return redirect('app_submission_review', submission_id=submission_id)

    survey_service_codes = list(dict.fromkeys(
        list(getattr(submission, 'requested_required_services', None) or [])
        + list(getattr(submission, 'requested_optional_services', None) or [])
    ))
    quote_service_codes = []
    for it in (quote.items or []):
        if not isinstance(it, dict):
            continue
        code = str(it.get('code') or '').strip()
        if code and code not in quote_service_codes:
            quote_service_codes.append(code)
    missing_in_survey = [c for c in quote_service_codes if c not in set(survey_service_codes)]
    missing_in_quote = [c for c in survey_service_codes if c not in set(quote_service_codes)]
    if missing_in_survey or missing_in_quote:
        messages.error(request, '설문 서비스 필드와 견적 서비스 항목이 불일치합니다. 불일치를 해소한 뒤 송부해 주세요.')
        return redirect('app_submission_review', submission_id=submission_id)
    # 견적서 폼에서 넘어온 가격(price_0, price_1, ...)이 있으면 먼저 저장
    if quote.items:
        items = list(quote.items)
        total = Decimal('0')
        for i in range(len(items)):
            if not isinstance(items[i], dict):
                continue
            key = 'price_%d' % i
            val = request.POST.get(key)
            try:
                price = int(Decimal(str(val or 0)))
            except Exception:
                price = int(items[i].get('price') or 0)
            items[i]['price'] = price
            total += price
        quote.items = items
        quote.total = total
        quote.save(update_fields=['items', 'total', 'updated_at'])
    success, err = finalize_and_send_quote(quote, actor=request.user)
    if success:
        messages.success(request, '견적을 최종 승인하고 고객에게 송부했습니다. 고객은 내 견적 페이지에서 확인할 수 있습니다.')
    else:
        messages.error(request, err or '송부 처리 중 오류가 발생했습니다.')
    return redirect('app_submission_review', submission_id=submission_id)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_create_draft_from_sent(request, submission_id):
    """Staff: 송부된 견적(FINAL_SENT/PAID)을 복사해 수정용 DRAFT 생성. 이후 견적서 수정 후 '승인 후 고객에게 송부'로 재송부 가능."""
    from survey.models import SurveySubmission
    from settlement.models import SettlementQuote
    from django.shortcuts import get_object_or_404
    from django.contrib import messages
    from decimal import Decimal

    submission = get_object_or_404(SurveySubmission, id=submission_id)
    sent_quote = (
        SettlementQuote.objects.filter(
            submission=submission,
            status__in=(SettlementQuote.Status.FINAL_SENT, SettlementQuote.Status.PAID),
        ).order_by('-sent_at', '-updated_at').first()
    )
    if not sent_quote:
        messages.error(request, '송부된 견적이 없습니다.')
        return redirect('app_submission_review', submission_id=submission_id)
    # 기존 DRAFT가 있으면 그대로 수정 화면으로 (중복 생성 방지)
    existing_draft = (
        SettlementQuote.objects.filter(
            submission=submission,
            status=SettlementQuote.Status.DRAFT,
        ).order_by('-updated_at').first()
    )
    if existing_draft:
        messages.info(request, '이미 수정용 초안이 있습니다. 아래에서 금액을 수정한 뒤 "승인 후 고객에게 송부"를 누르세요.')
        return redirect('app_submission_review', submission_id=submission_id)
    # 송부된 견적의 items 복사 (메타 키 제거)
    items = []
    for it in (sent_quote.items or []):
        if not isinstance(it, dict):
            continue
        item = {k: v for k, v in it.items() if k not in ('_auto', '_needs_review')}
        items.append(item)
    next_version = (sent_quote.version or 1) + 1
    new_draft = SettlementQuote(
        submission=submission,
        status=SettlementQuote.Status.DRAFT,
        version=next_version,
        region=sent_quote.region or '',
        items=items,
        total=sent_quote.total or Decimal('0'),
        draft_source='admin',
    )
    new_draft.save()
    messages.success(request, '송부된 견적을 바탕으로 수정용 초안을 만들었습니다. 금액을 수정한 뒤 "승인 후 고객에게 송부"를 눌러 보내세요.')
    return redirect('app_submission_review', submission_id=submission_id)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_resend_quote(request, submission_id):
    """Staff: 이미 송부된 견적(FINAL_SENT)을 고객에게 이메일·앱 메시지로 다시 보냄."""
    from survey.models import SurveySubmission
    from settlement.models import SettlementQuote
    from settlement.quote_approval import finalize_and_send_quote
    from django.shortcuts import get_object_or_404
    from django.contrib import messages

    submission = get_object_or_404(SurveySubmission, id=submission_id)
    sent_quote = (
        SettlementQuote.objects.filter(
            submission=submission,
            status=SettlementQuote.Status.FINAL_SENT,
        ).order_by('-sent_at', '-updated_at').first()
    )
    if not sent_quote:
        messages.error(request, '재송부할 견적(FINAL_SENT)이 없습니다.')
        return redirect('app_submission_review', submission_id=submission_id)
    success, err = finalize_and_send_quote(sent_quote, actor=request.user)
    if success:
        messages.success(request, '동일 견적을 고객에게 다시 보냈습니다(이메일·메시지).')
    else:
        messages.error(request, err or '재송부 처리 중 오류가 발생했습니다.')
    return redirect('app_submission_review', submission_id=submission_id)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_approve_reopen_survey(request, submission_id, change_request_id):
    """Staff: 고객 수정 요청에 대해 설문 재개 승인. submission → REVISION_REQUESTED, 기존 견적 결제 제외."""
    from django.shortcuts import get_object_or_404
    from survey.models import SurveySubmission
    from settlement.services_quote_change import approve_reopen_survey_by_ids
    from django.contrib import messages

    get_object_or_404(SurveySubmission, id=submission_id)
    success, err = approve_reopen_survey_by_ids(
        submission_id=int(submission_id),
        change_request_id=int(change_request_id),
        actor=request.user,
        request=request,
    )
    if success:
        messages.success(request, '설문 재개를 승인했습니다. 고객이 이전 내용을 바탕으로 설문을 수정할 수 있습니다.')
    else:
        messages.error(request, err or '설문 재개 처리에 실패했습니다.')
    return redirect('app_submission_review', submission_id=submission_id)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_reopen_survey(request, submission_id):
    """
    Staff: 고객 요청 없이 설문 수정 허용(CTA) 발송. Action offer 생성 + 고객에게 메시지 발송.
    고객이 '설문 수정 시작' 버튼을 눌러야 실제 상태 전이. Idempotent.
    """
    from django.shortcuts import get_object_or_404
    from survey.models import SurveySubmission
    from settlement.models import QuoteChangeRequest
    from customer_request_service import admin_initiated_reopen_submission
    from django.contrib import messages

    get_object_or_404(SurveySubmission, id=submission_id)
    change_request_id = request.POST.get('change_request_id')
    change_request = None
    if change_request_id and str(change_request_id).isdigit():
        change_request = QuoteChangeRequest.objects.filter(
            id=int(change_request_id), submission_id=submission_id
        ).first()
    success, offer, err = admin_initiated_reopen_submission(
        int(submission_id), request.user,
        change_request=change_request, request=request,
    )
    if success:
        if offer:
            messages.success(
                request,
                '고객에게 설문 수정 허용 메시지를 보냈습니다. 고객이 "설문 수정 시작" 버튼을 누르면 수정 가능 상태로 전환됩니다.',
            )
        else:
            messages.info(request, '이미 고객 수정 가능 상태이거나 CTA가 대기 중입니다.')
    else:
        messages.error(request, err or '설문 수정 허용 처리에 실패했습니다.')
    return redirect('app_submission_review', submission_id=submission_id)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_approve_quote_revision(request, submission_id, change_request_id):
    """Staff: LLM 추천 견적 수정 승인 → sent quote 기반 draft 생성, change_request IN_REVIEW. 서비스 레이어 approve_quote_revision 사용."""
    from django.shortcuts import get_object_or_404
    from survey.models import SurveySubmission
    from settlement.models import QuoteChangeRequest
    from settlement.services_quote_change import approve_quote_revision
    from django.contrib import messages

    get_object_or_404(SurveySubmission, id=submission_id)
    cr = get_object_or_404(QuoteChangeRequest, id=change_request_id, submission_id=submission_id)
    success, draft, err = approve_quote_revision(cr, request.user)
    if success:
        if draft:
            messages.success(request, '수정용 견적 초안을 생성했습니다. 아래 견적서에서 금액을 수정한 뒤 "승인 후 고객에게 송부"를 눌러 보내세요.')
        else:
            messages.success(request, '이미 수정 프로세스가 진행 중입니다. 아래 견적서를 확인하세요.')
        from django.urls import reverse
        return redirect(reverse('app_submission_review', kwargs={'submission_id': submission_id}) + '#quotation-card')
    messages.error(request, err or '견적 수정 프로세스 시작에 실패했습니다.')
    return redirect('app_submission_review', submission_id=submission_id)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
def submission_review_reject_change_request(request, submission_id):
    """Staff: 고객 수정 요청(QuoteChangeRequest)을 반려. 서비스 레이어 reject_change_request 사용."""
    from survey.models import SurveySubmission
    from settlement.models import QuoteChangeRequest
    from settlement.services_quote_change import reject_change_request
    from django.shortcuts import get_object_or_404
    from django.contrib import messages

    submission = get_object_or_404(SurveySubmission, id=submission_id)
    cr_id = request.POST.get('change_request_id')
    if not cr_id:
        messages.error(request, 'change_request_id가 필요합니다.')
        return redirect('app_submission_review', submission_id=submission_id)
    try:
        cr = QuoteChangeRequest.objects.get(id=int(cr_id), submission=submission)
    except (ValueError, QuoteChangeRequest.DoesNotExist):
        messages.error(request, '해당 변경 요청을 찾을 수 없습니다.')
        return redirect('app_submission_review', submission_id=submission_id)
    note = (request.POST.get('reject_note') or '').strip()
    success, err = reject_change_request(cr, request.user, note=note)
    if success:
        messages.success(request, '변경 요청을 반려했습니다.')
    else:
        messages.error(request, err or '반려 처리에 실패했습니다.')
    return redirect('app_submission_review', submission_id=submission_id)
