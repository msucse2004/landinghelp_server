"""
설문 Wizard: GET/POST step, 중간 저장(DRAFT), 최종 제출(SUBMITTED).
가격 노출 금지: 서비스 목록은 이름만 표시, "견적 후 공개" 마스킹.
로그인 시 계정(User)에 있는 신청자 정보는 자동으로 폼에 채움.
"""
import json
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse
from django.utils import timezone

from .models import SurveyQuestion, SurveySection, SurveySubmission, SurveySubmissionSectionRequest


def _get_applicant_answers_from_user(user):
    """계정(User)에 있는 신청자 정보만 추출. 설문 키 → 값."""
    if not user or not user.is_authenticated:
        return {}
    out = {}
    if getattr(user, 'first_name', None):
        out['first_name'] = (user.first_name or '').strip()
    if getattr(user, 'last_name', None):
        out['last_name'] = (user.last_name or '').strip()
    if getattr(user, 'email', None):
        out['email'] = (user.email or '').strip()
    if getattr(user, 'gender', None) and user.gender in ('M', 'F'):
        out['gender'] = user.gender
    return {k: v for k, v in out.items() if v}


def _get_sections_with_questions(customer_visible=True):
    """
    카드(섹션) 단위 설문 구조. 고객 설문 카드 UI용.
    customer_visible=True면 is_internal=False인 카드만.
    반환: [{"section": SurveySection, "questions": [SurveyQuestion, ...]}, ...]
    문항이 하나 이상인 카드만 포함.
    """
    qs = SurveySection.objects.filter(is_active=True).order_by('display_order', 'id')
    if customer_visible:
        qs = qs.filter(is_internal=False)
    sections = list(qs)
    result = []
    for sec in sections:
        questions = list(
            SurveyQuestion.objects.filter(section=sec, is_active=True).order_by('order_in_section', 'order')
        )
        if questions:
            result.append({'section': sec, 'questions': questions})
    return result


def _get_pending_section_requests(submission):
    """
    제출에 대한 미해결 카드별 수정 요청. 반환: [SurveySubmissionSectionRequest, ...] (section display_order 순).
    """
    if not submission:
        return []
    return list(
        SurveySubmissionSectionRequest.objects.filter(
            submission=submission,
            resolved_at__isnull=True,
        ).select_related('section').order_by('section__display_order', 'id')
    )


def _get_sections_for_draft(draft):
    """
    고객이 이번에 편집할 카드 목록.
    REVISION_REQUESTED이고 카드별 수정 요청이 있으면 → 요청된 카드만 (순서 유지).
    그 외 → 전체 고객 노출 카드.
    반환: [{"section": SurveySection, "questions": [SurveyQuestion, ...]}, ...]
    """
    full_sections = _get_sections_with_questions(customer_visible=True)
    if not draft or draft.status != SurveySubmission.Status.REVISION_REQUESTED:
        return full_sections
    pending = _get_pending_section_requests(draft)
    if not pending:
        return full_sections
    # 요청된 section_id 순서대로, 해당 section+questions만
    section_ids_ordered = [r.section_id for r in pending]
    result = []
    for sec_id in section_ids_ordered:
        for item in full_sections:
            if item['section'].id == sec_id:
                result.append(item)
                break
    return result


def _get_step_list(draft=None):
    """
    설문 단계 목록. draft가 있고 카드별 수정 요청이 있으면 해당 카드만, 아니면 전체.
    """
    sections = _get_sections_for_draft(draft) if draft else _get_sections_with_questions(customer_visible=True)
    if sections:
        return list(range(1, len(sections) + 1))
    steps = list(
        SurveyQuestion.objects.filter(is_active=True)
        .values_list('step', flat=True)
        .distinct()
        .order_by('step')
    )
    return steps if steps else [1]


def _get_questions_for_step(step, draft=None):
    """해당 단계의 활성 문항 목록. draft 있으면 _get_sections_for_draft 기준."""
    sections = _get_sections_for_draft(draft) if draft else _get_sections_with_questions(customer_visible=True)
    if sections and 1 <= step <= len(sections):
        return sections[step - 1]['questions']
    if not sections:
        return list(SurveyQuestion.objects.filter(step=step, is_active=True).order_by('order'))
    return list(SurveyQuestion.objects.filter(step=step, is_active=True).order_by('order'))


def _get_current_section_for_step(step, draft=None):
    """현재 단계가 카드일 때 해당 SurveySection 반환. draft 있으면 _get_sections_for_draft 기준."""
    sections = _get_sections_for_draft(draft) if draft else _get_sections_with_questions(customer_visible=True)
    if sections and 1 <= step <= len(sections):
        return sections[step - 1]['section']
    return None


def _get_or_create_draft(request):
    """
    편집 가능한 요청 1건 반환. DRAFT 또는 REVISION_REQUESTED(Admin 수정 요청) 시 이어쓰기.
    - 로그인: user 기준 최신 DRAFT 또는 REVISION_REQUESTED 1건.
    - 비로그인: session의 survey_submission_id로 DRAFT만 조회.
    """
    if request.user.is_authenticated:
        sub = SurveySubmission.objects.filter(
            user=request.user,
            status__in=(SurveySubmission.Status.DRAFT, SurveySubmission.Status.REVISION_REQUESTED),
        ).order_by('-updated_at').first()
        if sub:
            return sub
    sid = request.session.get('survey_submission_id')
    if sid:
        sub = SurveySubmission.objects.filter(
            id=sid, status=SurveySubmission.Status.DRAFT
        ).first()
        if sub:
            return sub
    return None


def _services_for_survey_display():
    """설문용 서비스 목록: 이름만, 가격 없음(견적 후 공개)."""
    try:
        from settlement.constants import get_services_by_category
        return get_services_by_category()
    except Exception:
        return {}
    # 템플릿에서 가격 대신 "견적 후 공개" 표시


def _has_submitted_survey(user):
    """로그인 사용자가 제출 완료 상태인 설문이 있는지. DRAFT·REVISION_REQUESTED는 편집 중이므로 제외."""
    if not user or not user.is_authenticated:
        return False
    return SurveySubmission.objects.filter(user=user).exclude(
        status__in=(SurveySubmission.Status.DRAFT, SurveySubmission.Status.REVISION_REQUESTED)
    ).exists()


def _build_selected_services_with_delivery(selected_required, answers, code_to_name):
    """
    선택된 필수 서비스 코드에 대해 (code, name, current_delivery_value) 리스트 반환.
    answers 에서 service_delivery_per_service 또는 service_delivery_preference 반영.
    """
    per_svc = answers.get('service_delivery_per_service') or {}
    if not isinstance(per_svc, dict):
        per_svc = {}
    return [
        (code, code_to_name.get(code, code), per_svc.get(code, ''))
        for code in (selected_required or [])
    ]


def _compute_agent_selection_context(answers, selected_required, current_section):
    """
    answers + selected_required + current_section 으로 Agent 선택 영역 표시 여부·코드·state 계산.
    반환: dict with show_agent_selection, state_for_agent, agent_direct_service_codes,
          agent_direct_service_codes_str, preferred_agent_id, on_delivery_step.
    survey_step 와 fragment view 에서 동일한 로직으로 사용.
    """
    from settlement.constants import _normalize_state_code
    result = {
        'show_agent_selection': False,
        'state_for_agent': '',
        'agent_direct_service_codes': [],
        'agent_direct_service_codes_str': '',
        'preferred_agent_id': (answers.get('preferred_agent_id') or '').strip(),
        'on_delivery_step': bool(
            current_section
            and getattr(current_section, 'title', '') == '서비스 진행 방식'
            and (selected_required or [])
        ),
    }
    if not selected_required:
        return result
    try:
        class _FakeSubmission:
            pass
        fake = _FakeSubmission()
        fake.answers = answers or {}
        fake.requested_required_services = list(selected_required or [])
        fake.requested_optional_services = []
        from survey.quote_input import get_quote_input_data
        data = get_quote_input_data(fake)
        result['state_for_agent'] = _normalize_state_code(
            data.get('settlement_state') or data.get('region') or ''
        )
    except Exception:
        pass
    mode = (answers.get('service_delivery_mode') or 'bulk').strip()
    bulk_pref = (answers.get('service_delivery_preference') or '').strip()
    per_svc = answers.get('service_delivery_per_service') or {}
    if not isinstance(per_svc, dict):
        per_svc = {}
    if mode == 'per_service':
        result['agent_direct_service_codes'] = [
            c for c in (selected_required or [])
            if per_svc.get(c) == 'agent_direct'
        ]
    elif bulk_pref == 'agent_direct':
        result['agent_direct_service_codes'] = list(selected_required or [])
    else:
        result['agent_direct_service_codes'] = []
    result['show_agent_selection'] = bool(result['agent_direct_service_codes'])
    result['agent_direct_service_codes_str'] = ','.join(result['agent_direct_service_codes'])
    return result


@require_GET
@ensure_csrf_cookie
def survey_start(request):
    """
    GET /settlement/survey/
    우선순위: (1) 로그인 user의 DRAFT가 있으면 resume (2) 없으면 제출 이력 있으면 이미 제출 페이지 (3) 새 설문 step 1.
    """
    draft = _get_or_create_draft(request)
    steps = _get_step_list(draft)

    if draft:
        # 이어쓰기: 마지막 진행 단계로 이동
        step = min(max(1, draft.current_step), steps[-1] if steps else 1)
        step = step if step in steps else (steps[0] if steps else 1)
        return redirect(reverse('survey:survey_step', kwargs={'step': step}))

    # DRAFT 없음: 로그인 사용자면 제출 이력 확인
    if request.user.is_authenticated and _has_submitted_survey(request.user):
        return render(request, 'survey/survey_already_submitted.html')

    # 새 설문: step 1부터 (제출은 첫 저장 시 생성)
    step = steps[0] if steps else 1
    return redirect(reverse('survey:survey_step', kwargs={'step': step}))


@require_GET
@ensure_csrf_cookie
def survey_step(request, step):
    """GET /settlement/survey/step/<n>/ → n단계 폼. 재접속 시 이 단계부터 이어쓰기되도록 current_step 갱신."""
    draft = _get_or_create_draft(request)
    # 로그인 사용자: 초안 없이 이미 제출한 이력만 있으면 새 설문 불가 → 이미 제출 페이지로
    if not draft and request.user.is_authenticated and _has_submitted_survey(request.user):
        return redirect(reverse('survey:survey_start'))
    steps = _get_step_list(draft)
    if step not in steps:
        step = steps[0] if steps else 1
        return redirect(reverse('survey:survey_step', kwargs={'step': step}))

    # 로그인/세션 초안이 있으면, 이번에 열어 본 단계까지 진행으로 기록 (재접속 시 이 단계에서 재개)
    if draft and step > getattr(draft, 'current_step', 0):
        draft.current_step = step
        draft.save(update_fields=['current_step', 'updated_at'])

    questions = _get_questions_for_step(step, draft)
    step_index = steps.index(step) if step in steps else 0
    prev_step = steps[step_index - 1] if step_index > 0 else None
    next_step = steps[step_index + 1] if step_index < len(steps) - 1 else None
    current_section = _get_current_section_for_step(step, draft)
    use_cards = current_section is not None

    # 카드별 수정 요청 시: 수정할 카드 목록 / 잠긴 카드 목록 (고객 안내용)
    sections_need_update_titles = []
    locked_section_titles = []
    if draft and draft.status == SurveySubmission.Status.REVISION_REQUESTED:
        pending = _get_pending_section_requests(draft)
        if pending:
            full_sections = _get_sections_with_questions(customer_visible=True)
            need_ids = {r.section_id for r in pending}
            for item in full_sections:
                title = item['section'].title
                if item['section'].id in need_ids:
                    sections_need_update_titles.append(title)
                else:
                    locked_section_titles.append(title)

    services_by_category = _services_for_survey_display()
    selected_required = list(draft.requested_required_services) if draft else []
    selected_optional = list(draft.requested_optional_services) if draft else []
    code_to_name = {}
    for _cat, items in services_by_category.items():
        for code, name in items:
            code_to_name[code] = name
    selected_services_display = [(code, code_to_name.get(code, code)) for code in selected_required]
    answers = dict(draft.answers or {}) if draft else {}
    if request.user.is_authenticated:
        from_user = _get_applicant_answers_from_user(request.user)
        for key, val in from_user.items():
            if key not in answers or not (answers[key] or '').strip():
                answers[key] = val
    answers = {k: v for k, v in answers.items() if v is not None}

    selected_services_with_delivery = _build_selected_services_with_delivery(
        selected_required, answers, code_to_name
    )
    on_delivery_step = bool(
        current_section
        and getattr(current_section, 'title', '') == '서비스 진행 방식'
        and (selected_required or [])
    )
    on_agent_selection_step = bool(
        current_section and getattr(current_section, 'title', '') == '기타 의뢰 내용'
    )
    agent_ctx = _compute_agent_selection_context(answers, selected_required, current_section)
    show_agent_selection = agent_ctx['show_agent_selection'] if on_agent_selection_step else False
    state_for_agent = agent_ctx['state_for_agent'] if on_agent_selection_step else ''
    agent_direct_service_codes = agent_ctx['agent_direct_service_codes'] if on_agent_selection_step else []
    preferred_agent_id = agent_ctx['preferred_agent_id'] if on_agent_selection_step else ''
    agents = []
    if on_agent_selection_step and agent_ctx['show_agent_selection'] and agent_ctx['agent_direct_service_codes']:
        from settlement.views import get_agents_for_survey_fragment
        agents = get_agents_for_survey_fragment(
            agent_ctx['state_for_agent'],
            agent_ctx['agent_direct_service_codes'],
            request,
        )

    revision_message = getattr(draft, 'revision_requested_message', '') if draft else ''
    progress_pct = round(100 * step / len(steps)) if steps else 0
    return render(request, 'survey/survey_wizard.html', {
        'step': step,
        'steps': steps,
        'progress_pct': progress_pct,
        'questions': questions,
        'submission': draft,
        'answers': answers,
        'prev_step': prev_step,
        'next_step': next_step,
        'current_section': current_section,
        'use_cards': use_cards,
        'revision_requested_message': revision_message,
        'is_revision_requested': draft and draft.status == SurveySubmission.Status.REVISION_REQUESTED,
        'sections_need_update_titles': sections_need_update_titles,
        'locked_section_titles': locked_section_titles,
        'services_by_category': services_by_category,
        'price_masked_label': '견적 후 공개',
        'selected_required_services': selected_required,
        'selected_optional_services': selected_optional,
        'selected_services_display': selected_services_display,
        'selected_services_with_delivery': selected_services_with_delivery,
        'show_agent_selection': show_agent_selection,
        'state_for_agent': state_for_agent,
        'agent_direct_service_codes': agent_direct_service_codes,
        'agent_direct_service_codes_str': ','.join(agent_direct_service_codes),
        'preferred_agent_id': preferred_agent_id,
        'on_delivery_step': on_delivery_step,
        'on_agent_selection_step': on_agent_selection_step,
        'agents': agents,
        'agents_json': json.dumps(agents) if agents else '[]',
    })


@require_POST
@ensure_csrf_cookie
def survey_agent_selection_fragment(request, step):
    """
    POST: 현재 폼 상태를 받아 Agent selection partial HTML 반환.
    DB 저장 없이 request.POST 기준으로 show_agent_selection / agent_codes 등을 계산하고
    동일한 helper(_compute_agent_selection_context)를 사용해 fragment 렌더.
    """
    import logging
    logger = logging.getLogger(__name__)

    selected_required = []
    raw = request.POST.get('requested_required_services')
    if raw:
        try:
            selected_required = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (ValueError, TypeError):
            selected_required = []
    if not isinstance(selected_required, list):
        selected_required = []

    answers = {}
    for key in request.POST:
        if key == 'csrfmiddlewaretoken':
            continue
        answers[key] = request.POST.get(key)
    if request.POST.get('service_delivery_mode') == 'per_service' and selected_required:
        per_service = {}
        for code in selected_required:
            v = (request.POST.get('service_delivery_%s' % code) or '').strip()
            if v:
                per_service[code] = v
        answers['service_delivery_per_service'] = per_service

    current_section = _get_current_section_for_step(step, None)
    agent_ctx = _compute_agent_selection_context(answers, selected_required, current_section)
    show_agent_selection = agent_ctx['show_agent_selection']
    state_for_agent = agent_ctx['state_for_agent']
    agent_direct_service_codes = agent_ctx['agent_direct_service_codes']
    preferred_agent_id = agent_ctx['preferred_agent_id']
    on_delivery_step = agent_ctx['on_delivery_step']

    mode = (answers.get('service_delivery_mode') or '').strip()
    bulk_pref = (answers.get('service_delivery_preference') or '').strip()
    per_svc = answers.get('service_delivery_per_service') or {}
    logger.info(
        '[agent-fragment] mode=%s, bulk_pref=%s, per_service=%s, selected_required=%s, agent_codes=%s, show=%s',
        mode, bulk_pref, per_svc, selected_required, agent_direct_service_codes, show_agent_selection,
    )

    agents = []
    if show_agent_selection and agent_direct_service_codes:
        from settlement.views import get_agents_for_survey_fragment
        agents = get_agents_for_survey_fragment(
            state_for_agent, agent_direct_service_codes, request
        )

    agents_json = json.dumps(agents) if agents else '[]'

    return render(request, 'survey/_agent_selection_fragment.html', {
        'show_agent_selection': show_agent_selection,
        'state_for_agent': state_for_agent,
        'agent_direct_service_codes': agent_direct_service_codes,
        'agent_direct_service_codes_str': agent_ctx['agent_direct_service_codes_str'],
        'preferred_agent_id': preferred_agent_id,
        'on_delivery_step': on_delivery_step,
        'agents': agents,
        'agents_json': agents_json,
        'request': request,
    })


@require_POST
@ensure_csrf_cookie
def survey_step_save(request, step):
    """POST /settlement/survey/step/<n>/save/ → 해당 step answers 저장(DRAFT), current_step 갱신."""
    draft = _get_or_create_draft(request)
    steps = _get_step_list(draft)
    if step not in steps:
        return JsonResponse({'ok': False, 'error': 'invalid step'}, status=400)
    email = (request.POST.get('email') or '').strip()
    if request.user.is_authenticated and not email:
        email = (request.user.email or '').strip()

    # 새 초안 생성: step 1 저장 시 email 필수. 로그인 사용자는 계정당 1건만 허용.
    if not draft:
        if not email:
            return JsonResponse({'ok': False, 'error': 'email required'}, status=400)
        if request.user.is_authenticated:
            existing = SurveySubmission.objects.filter(user=request.user).order_by('-updated_at').first()
            if existing:
                if existing.status in (SurveySubmission.Status.DRAFT, SurveySubmission.Status.REVISION_REQUESTED):
                    draft = existing
                    request.session['survey_submission_id'] = draft.id
                else:
                    return JsonResponse({'ok': False, 'error': 'already_submitted'}, status=400)
        if not draft:
            draft = SurveySubmission(
                user=request.user if request.user.is_authenticated else None,
                email=email,
                status=SurveySubmission.Status.DRAFT,
                current_step=step,
                answers={},
            )
            draft.save()
            request.session['survey_submission_id'] = draft.id

    # 이 단계 문항 키만 추출해 answers 병합 (DRAFT는 부분 저장 허용)
    questions = _get_questions_for_step(step, draft)
    step_keys = {q.key for q in questions}
    for key in step_keys:
        if key not in request.POST:
            continue
        val = request.POST.get(key)
        if key == 'email' and val:
            draft.email = val.strip()
        if key == 'requested_required_services':
            try:
                draft.requested_required_services = json.loads(val) if isinstance(val, str) else (val or [])
            except (ValueError, TypeError):
                draft.requested_required_services = []
            draft.answers[key] = draft.requested_required_services
            continue
        if key == 'requested_optional_services':
            try:
                draft.requested_optional_services = json.loads(val) if isinstance(val, str) else (val or [])
            except (ValueError, TypeError):
                draft.requested_optional_services = []
            draft.answers[key] = draft.requested_optional_services
            continue
        if key == 'preferred_support_mode':
            draft.preferred_support_mode = (val or '')[:100]
        draft.answers[key] = val
    # 서비스 진행 방식: 모드에 따라 per_service 데이터 관리
    delivery_mode = request.POST.get('service_delivery_mode', '')
    if delivery_mode == 'per_service' and draft.requested_required_services:
        per_service = {}
        for code in draft.requested_required_services:
            v = (request.POST.get('service_delivery_%s' % code) or '').strip()
            if v:
                per_service[code] = v
        draft.answers['service_delivery_per_service'] = per_service
    elif delivery_mode == 'bulk':
        draft.answers['service_delivery_per_service'] = {}
    # 설문에서 선호 Agent 선택 시 저장
    preferred_agent_id = (request.POST.get('preferred_agent_id') or '').strip()
    if preferred_agent_id:
        try:
            int(preferred_agent_id)
            draft.answers['preferred_agent_id'] = preferred_agent_id
        except (ValueError, TypeError):
            pass
    if email:
        draft.email = email.strip()
    draft.current_step = step
    draft.save(update_fields=['email', 'answers', 'current_step', 'updated_at', 'preferred_support_mode', 'requested_required_services', 'requested_optional_services'])

    return JsonResponse({'ok': True, 'submission_id': draft.id, 'current_step': draft.current_step})


def _log_submission_event(submission, event_type, created_by=None, meta=None):
    """요청 서류 이벤트 기록 (감사 로그)."""
    from .models import SurveySubmissionEvent
    SurveySubmissionEvent.objects.create(
        submission=submission,
        event_type=event_type,
        created_by=created_by,
        meta=meta or {},
    )


@require_POST
@ensure_csrf_cookie
def survey_submit(request):
    """POST /settlement/survey/submit/ → 제출(SUBMITTED). DRAFT 또는 REVISION_REQUESTED에서 재제출 가능."""
    draft = _get_or_create_draft(request)
    if not draft:
        return redirect(reverse('survey:survey_start'))

    was_revision = draft.status == SurveySubmission.Status.REVISION_REQUESTED
    resolved_section_ids = []
    if was_revision:
        pending = _get_pending_section_requests(draft)
        if pending:
            now = timezone.now()
            for req in pending:
                req.resolved_at = now
                req.save(update_fields=['resolved_at'])
                resolved_section_ids.append(req.section_id)

    draft.status = SurveySubmission.Status.SUBMITTED
    draft.submitted_at = timezone.now()
    draft.save(update_fields=['status', 'submitted_at'])
    request.session.pop('survey_submission_id', None)

    event_type = 'resubmitted' if was_revision else 'submitted'
    event_meta = {'resolved_section_ids': resolved_section_ids} if resolved_section_ids else {}
    _log_submission_event(
        draft,
        event_type,
        created_by=request.user if request.user.is_authenticated else None,
        meta=event_meta,
    )

    # 재제출 시 견적 초안 갱신; 최초 제출 시 DRAFT 없을 때만 생성.
    try:
        from settlement.models import SettlementQuote
        from settlement.quote_draft import generate_quote_draft_from_submission
        if was_revision:
            generate_quote_draft_from_submission(draft, actor=request.user if request.user.is_authenticated else None)
        elif not SettlementQuote.objects.filter(submission=draft, status=SettlementQuote.Status.DRAFT).exists():
            generate_quote_draft_from_submission(draft, actor=request.user if request.user.is_authenticated else None)
    except Exception:
        pass

    try:
        from settlement.notifications import (
            send_survey_submitted_admin_notification,
            send_survey_submitted_customer_email,
            send_survey_submitted_customer_message,
            send_survey_submitted_admin_message,
        )
        from translations.utils import get_request_language
        lang = get_request_language(request)
        send_survey_submitted_admin_notification(draft, language_code=lang)
        send_survey_submitted_customer_email(draft, language_code=lang)
        send_survey_submitted_customer_message(draft, language_code=lang)
        send_survey_submitted_admin_message(draft, language_code=lang)
    except Exception:
        pass

    return redirect(reverse('survey:survey_thankyou'))


@require_GET
@ensure_csrf_cookie
def survey_thankyou(request):
    """제출 완료 안내 (submit 후 redirect 대상)."""
    return render(request, 'survey/survey_thankyou.html')
