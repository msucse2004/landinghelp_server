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


# ---------------------------------------------------------------------------
# 학습용 strongest label: 실제 저장된 페이지를 semantic page_key로 기록
# ---------------------------------------------------------------------------

# 설문 섹션 제목 → 학습/분석용 page_key (여러 수정 페이지를 명시적으로 구분)
SECTION_TITLE_TO_PAGE_KEY = {
    "신청자 정보": "applicant_info",
    "입국 인원": "household_info",
    "지역·현황": "region_status",
    "입국 목적·체류": "entry_purpose_stay",
    "희망 서비스": "service_selection",
    "서비스 진행 방식": "delivery_preferences",
    "기타 의뢰 내용": "other_requests",
}


def get_page_key_for_section(section, step):
    """
    현재 step의 섹션에 대한 semantic page_key 반환.
    학습 시 "실제로 어떤 페이지에서 저장했는가"를 strongest label로 쓸 때 사용.
    """
    if section and getattr(section, "title", None):
        key = SECTION_TITLE_TO_PAGE_KEY.get((section.title or "").strip())
        if key:
            return key
    return "step_%s" % (step or 1)


def _record_edit_saved(
    request_id,
    request,
    draft,
    step,
    step_keys,
    save_result,
    page_key=None,
):
    """
    저장 성공/실패 시 edit_saved 이벤트 기록 (공통).
    request_id가 없으면 기록하지 않음(graceful fallback).
    """
    if not request_id or not request_id.strip():
        return
    try:
        from messaging.feedback_events import log_edit_saved
        if page_key is None:
            current_section = _get_current_section_for_step(step, draft)
            page_key = get_page_key_for_section(current_section, step)
        log_edit_saved(
            request_id,
            user_id=getattr(request.user, "id", None) if request.user.is_authenticated else None,
            survey_submission_id=getattr(draft, "id", None),
            page_key=page_key,
            changed_fields=list(step_keys) if step_keys else [],
            save_result=save_result,
            entity_type="survey_submission",
            entity_id=str(getattr(draft, "id", "")),
            metadata_extra={
                "changed_entity_type": "survey_submission",
                "changed_entity_id": str(getattr(draft, "id", "")),
            },
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "survey: log_edit_saved failed (non-blocking) request_id=%s step=%s: %s",
            request_id, step, e,
            exc_info=True,
        )


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
    if getattr(user, 'birth_date', None):
        out['birth_date'] = str(user.birth_date)  # 'YYYY-MM-DD'
    if getattr(user, 'phone', None) and (user.phone or '').strip():
        out['phone'] = user.phone.strip()
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


def _ensure_section_requests_for_revision(draft):
    """
    REVISION_REQUESTED 상태인데 pending section requests가 없을 때,
    가장 최근 reopen_survey 제안의 분석 결과에서 section requests를 복구 생성.
    (이전 버전에서 생성 누락된 경우 대응)
    """
    if not draft or draft.status != SurveySubmission.Status.REVISION_REQUESTED:
        return
    existing = SurveySubmissionSectionRequest.objects.filter(
        submission=draft, resolved_at__isnull=True,
    ).exists()
    if existing:
        return
    try:
        from messaging.models import CustomerActionProposal
        from customer_request_service import _infer_target_section_ids_from_primary_page, _create_section_requests_for_submission
        prop = (
            CustomerActionProposal.objects
            .filter(submission=draft, action_code='reopen_survey')
            .select_related('analysis')
            .order_by('-created_at')
            .first()
        )
        if not prop or not prop.analysis:
            return
        # 1순위: action_payload
        target_ids = []
        ap = prop.action_payload or {}
        if isinstance(ap, dict):
            raw = ap.get('target_section_ids') or []
            if isinstance(raw, list):
                target_ids = [int(v) for v in raw if str(v).isdigit()]
        # 2순위: route_candidates.selected_primary_page
        if not target_ids:
            rc = prop.analysis.route_candidates or {}
            page = (rc.get('selected_primary_page') or '').strip()
            if page:
                inferred = _infer_target_section_ids_from_primary_page(page)
                if inferred:
                    target_ids = list(inferred)
        if target_ids:
            _create_section_requests_for_submission(
                draft, tuple(target_ids),
                requested_by=None,
                message='이전 요청 분석에서 자동 복구',
            )
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            'survey: _ensure_section_requests_for_revision failed submission=%s',
            getattr(draft, 'id', None), exc_info=True,
        )


def _get_sections_for_draft(draft):
    """
    고객이 이번에 편집할 카드 목록.
    REVISION_REQUESTED여도 설문 전체 카드를 열어 둔다.
    다만 survey_start에서 요청된 카드로 우선 진입시켜 탐색 시작점만 맞춘다.
    반환: [{"section": SurveySection, "questions": [SurveyQuestion, ...]}, ...]
    """
    full_sections = _get_sections_with_questions(customer_visible=True)
    return full_sections


def _get_revision_focus_step(draft):
    """
    REVISION_REQUESTED 설문 진입 시 우선 보여줄 단계 계산.
    pending section request가 있으면 해당 section이 위치한 전체 step 번호를 반환.
    """
    steps = _get_step_list(draft)
    if not draft or draft.status != SurveySubmission.Status.REVISION_REQUESTED:
        return steps[0] if steps else 1
    pending = _get_pending_section_requests(draft)
    if not pending:
        return steps[0] if steps else 1
    target_section_ids = {req.section_id for req in pending}
    sections = _get_sections_for_draft(draft)
    for index, item in enumerate(sections, start=1):
        if item['section'].id in target_section_ids:
            return index
    return steps[0] if steps else 1


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
    if result['show_agent_selection']:
        result['preferred_agent_id'] = 'admin_assign'
    elif result.get('preferred_agent_id') == 'admin_assign':
        result['preferred_agent_id'] = ''
    return result


def _get_request_id_from_request(request):
    """
    request_id를 GET → POST → session 순으로 조회.
    프론트: 설문 수정하기 클릭 시 redirect URL에 ?request_id=xxx 포함 권장.
    저장/제출 시 POST body에 request_id 넣거나, 진입 시 이미 session에 있으면 유지.
    """
    rid = (request.GET.get("request_id") or request.POST.get("request_id") or "").strip()
    if rid:
        return rid
    return request.session.get("survey_request_id") or ""


@require_GET
@ensure_csrf_cookie
def survey_start(request):
    """
    GET /settlement/survey/
    우선순위: (1) 로그인 user의 DRAFT/REVISION_REQUESTED가 있으면 resume (2) 없으면 제출 이력 있으면 이미 제출 페이지 (3) 새 설문 step 1.
    ?resume=1: 메시지/대시보드 진입점; 비로그인 시 로그인 후 이 URL로 복귀.
    ?request_id=xxx: 수정 요청 세션 ID (같은 request_id로 추천 클릭·저장·피드백 이벤트 묶음).
    ?from=suggestion|manual_navigation|deep_link: 진입 경로 (page_viewed source).
    """
    # 메시지/대시보드의 "설문 다시 수정하기" 링크로 진입 시: 비로그인이면 로그인 유도
    if request.GET.get('resume') and not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path(), login_url=None)

    request_id = _get_request_id_from_request(request)
    if request_id:
        request.session["survey_request_id"] = request_id

    from_param = (request.GET.get("from") or "").strip() or None
    if from_param in ("suggestion", "manual_navigation", "deep_link"):
        request.session["survey_view_source"] = from_param
    elif from_param:
        request.session["survey_view_source"] = "deep_link"

    draft = _get_or_create_draft(request)
    if draft and draft.status == SurveySubmission.Status.REVISION_REQUESTED:
        _ensure_section_requests_for_revision(draft)
    steps = _get_step_list(draft)

    if draft:
        # 소유권 검증: 로그인 사용자인데 draft가 다른 사용자 소유면 접근 차단
        if request.user.is_authenticated and getattr(draft, 'user_id', None) is not None and draft.user_id != request.user.pk:
            return render(request, 'survey/survey_message.html', {
                'message_title': '접근 제한',
                'message_body': '해당 설문은 본인만 수정할 수 있습니다. 로그인한 계정을 확인해 주세요.',
            })
        # 편집 가능 상태만 허용 (DRAFT, REVISION_REQUESTED)
        if draft.status not in (SurveySubmission.Status.DRAFT, SurveySubmission.Status.REVISION_REQUESTED):
            return render(request, 'survey/survey_message.html', {
                'message_title': '수정 불가',
                'message_body': '현재 이 설문은 수정할 수 없는 상태입니다. 이미 제출되었거나 관리자 검토 중일 수 있습니다. 문의 사항은 메시지함으로 연락해 주세요.',
            })
        if draft.status == SurveySubmission.Status.REVISION_REQUESTED:
            step = _get_revision_focus_step(draft)
        else:
            step = min(max(1, draft.current_step), steps[-1] if steps else 1)
            step = step if step in steps else (steps[0] if steps else 1)
        url = reverse('survey:survey_step', kwargs={'step': step})
        q = []
        if request_id:
            q.append("request_id=" + request_id)
        if from_param:
            q.append("from=" + from_param)
        if q:
            url += "?" + "&".join(q)
        return redirect(url)

    # DRAFT 없음: 로그인 사용자면 제출 이력 확인
    if request.user.is_authenticated and _has_submitted_survey(request.user):
        return render(request, 'survey/survey_already_submitted.html')

    # 새 설문: step 1부터 (제출은 첫 저장 시 생성)
    step = steps[0] if steps else 1
    url = reverse('survey:survey_step', kwargs={'step': step})
    q = []
    if request_id:
        q.append("request_id=" + request_id)
    if from_param:
        q.append("from=" + from_param)
    if q:
        url += "?" + "&".join(q)
    return redirect(url)


@require_GET
@ensure_csrf_cookie
def survey_step(request, step):
    """GET /settlement/survey/step/<n>/ → n단계 폼. 재접속 시 이 단계부터 이어쓰기되도록 current_step 갱신. ?request_id= 있으면 세션에 저장·학습 이벤트(page_viewed) 기록."""
    request_id = _get_request_id_from_request(request)
    if request_id:
        request.session["survey_request_id"] = request_id

    draft = _get_or_create_draft(request)
    # 로그인 사용자: 초안 없이 이미 제출한 이력만 있으면 새 설문 불가 → 이미 제출 페이지로
    if not draft and request.user.is_authenticated and _has_submitted_survey(request.user):
        return redirect(reverse('survey:survey_start'))
    steps = _get_step_list(draft)
    if step not in steps:
        step = steps[0] if steps else 1
        url = reverse('survey:survey_step', kwargs={'step': step})
        if request_id:
            url += '?request_id=' + request_id
        return redirect(url)

    # 로그인/세션 초안이 있으면, 이번에 열어 본 단계까지 진행으로 기록 (재접속 시 이 단계에서 재개)
    if draft and step > getattr(draft, 'current_step', 0):
        draft.current_step = step
        draft.save(update_fields=['current_step', 'updated_at'])

    # 학습용: 페이지 진입 이벤트 (request_id 있을 때만). source로 추천 진입 vs 직접 이동 구분
    view_source = (request.GET.get("from") or "").strip() or request.session.get("survey_view_source") or "manual_navigation"
    if request_id and draft:
        try:
            from messaging.feedback_events import log_page_viewed
            current_section = _get_current_section_for_step(step, draft)
            page_key = get_page_key_for_section(current_section, step)
            log_page_viewed(
                request_id,
                user_id=getattr(request.user, "id", None) if request.user.is_authenticated else None,
                survey_submission_id=getattr(draft, "id", None),
                page_key=page_key,
                source=view_source,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "survey: log_page_viewed failed (non-blocking) request_id=%s step=%s: %s",
                request_id, step, e,
                exc_info=True,
            )
    request.session["survey_view_source"] = "manual_navigation"

    questions = _get_questions_for_step(step, draft)
    step_index = steps.index(step) if step in steps else 0
    prev_step = steps[step_index - 1] if step_index > 0 else None
    next_step = steps[step_index + 1] if step_index < len(steps) - 1 else None
    current_section = _get_current_section_for_step(step, draft)
    use_cards = current_section is not None

    # 카드별 수정 요청 시: 우선 확인이 필요한 카드 목록만 안내
    sections_need_update_titles = []
    locked_section_titles = []
    if draft and draft.status == SurveySubmission.Status.REVISION_REQUESTED:
        pending = _get_pending_section_requests(draft)
        if pending:
            need_ids = {r.section_id for r in pending}
            for item in _get_sections_with_questions(customer_visible=True):
                title = item['section'].title
                if item['section'].id in need_ids:
                    sections_need_update_titles.append(title)

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
    on_agent_selection_step = on_delivery_step
    agent_ctx = _compute_agent_selection_context(answers, selected_required, current_section)
    show_agent_selection = agent_ctx['show_agent_selection'] if on_delivery_step else False
    state_for_agent = agent_ctx.get('state_for_agent', '') if on_delivery_step else ''
    agent_direct_service_codes = agent_ctx.get('agent_direct_service_codes', []) if on_delivery_step else []
    preferred_agent_id = agent_ctx.get('preferred_agent_id', '') if on_delivery_step else ''
    agents = []

    revision_message = getattr(draft, 'revision_requested_message', '') if draft else ''
    progress_pct = round(100 * step / len(steps)) if steps else 0
    revision_feedback_page_key = get_page_key_for_section(current_section, step) if current_section else ''
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
        'request_id': request_id or '',
        'revision_feedback_page_key': revision_feedback_page_key,
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
    agent_ctx = _compute_agent_selection_context(
        draft.answers,
        list(draft.requested_required_services or []),
        _get_current_section_for_step(step, draft),
    )
    if agent_ctx.get('show_agent_selection'):
        draft.answers['preferred_agent_id'] = 'admin_assign'
    else:
        draft.answers.pop('preferred_agent_id', None)
    if email:
        draft.email = email.strip()
    draft.current_step = step

    request_id = _get_request_id_from_request(request)
    try:
        draft.save(update_fields=['email', 'answers', 'current_step', 'updated_at', 'preferred_support_mode', 'requested_required_services', 'requested_optional_services'])
        _record_edit_saved(request_id, request, draft, step, step_keys, "success")
        return JsonResponse({'ok': True, 'submission_id': draft.id, 'current_step': draft.current_step})
    except Exception as e:
        _record_edit_saved(request_id, request, draft, step, step_keys, "failure")
        return JsonResponse({'ok': False, 'error': str(e)[:500]}, status=500)


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
    """
    POST /settlement/survey/submit/ → 제출(SUBMITTED). DRAFT 또는 REVISION_REQUESTED에서 재제출 가능.
    설문 제출/재제출에 따른 상태 전이는 이 뷰에서만 수행. 고객 메시지·견적 수정 요청 분류/실행은 customer_request_service.
    """
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
    # 제출 시점에 로그인한 사용자가 있으면 submission에 연결 (고객 메시지함 알림용)
    update_fields = ['status', 'submitted_at']
    if request.user.is_authenticated and draft.user_id is None:
        draft.user = request.user
        update_fields.append('user')
    draft.save(update_fields=update_fields)
    request.session.pop('survey_submission_id', None)
    request_id = _get_request_id_from_request(request)
    if request_id:
        request.session.pop("survey_request_id", None)

    # reopen 후 재제출: 해당 submission의 CUSTOMER_ACTION_REQUIRED change request → IN_REVIEW (Admin 검토 대기)
    change_request_ids_moved = []
    if was_revision:
        try:
            from settlement.models import QuoteChangeRequest
            crs = list(
                QuoteChangeRequest.objects.filter(
                    submission=draft,
                    status=QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED,
                ).values_list('id', flat=True)
            )
            change_request_ids_moved = crs
            QuoteChangeRequest.objects.filter(
                submission=draft,
                status=QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED,
            ).update(status=QuoteChangeRequest.Status.IN_REVIEW)
        except Exception:
            pass

    event_type = 'resubmitted' if was_revision else 'submitted'
    event_meta = {'resolved_section_ids': resolved_section_ids} if resolved_section_ids else {}
    if was_revision:
        event_meta['resubmitted_after_reopen'] = True
        if change_request_ids_moved:
            event_meta['change_request_ids_moved_to_in_review'] = change_request_ids_moved
    _log_submission_event(
        draft,
        event_type,
        created_by=request.user if request.user.is_authenticated else None,
        meta=event_meta,
    )

    if was_revision:
        try:
            from customer_request_service import record_followup_success
            record_followup_success(draft, event_meta=event_meta)
        except Exception:
            pass

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

    # 설문 제출 직후(Admin 검토용) 일정 초안 생성: 결제 전 단계에서 대면 Agent 서비스 우선 제안.
    # idempotent 보장: 동일 submission의 DRAFT/REVIEWING 플랜이 있으면 재생성하지 않음.
    try:
        from settlement.models import ServiceScheduleItem
        from settlement.scheduling_engine import ensure_submission_schedule_draft
        ensure_submission_schedule_draft(
            draft,
            actor=request.user if request.user.is_authenticated else None,
            service_type_whitelist={ServiceScheduleItem.ServiceType.IN_PERSON_AGENT},
        )
    except Exception:
        pass

    # Notify customer (inbox + email) and admin (email + inbox). Same flow for first submit and resubmit.
    try:
        from settlement.notifications import (
            send_survey_submitted_admin_notification,
            send_survey_submitted_customer_email,
            send_survey_submitted_customer_message,
            send_survey_submitted_admin_message,
        )
        from translations.utils import get_request_language
        import logging
        logger = logging.getLogger(__name__)
        lang = get_request_language(request)
        send_survey_submitted_admin_notification(draft, language_code=lang)
        send_survey_submitted_customer_email(draft, language_code=lang, is_revision_resubmit=was_revision)
        if not send_survey_submitted_customer_message(draft, language_code=lang, is_revision_resubmit=was_revision):
            logger.warning(
                "Survey submitted customer message skipped: submission_id=%s user_id=%s (login and link user for inbox message).",
                getattr(draft, 'id', None), getattr(draft, 'user_id', None),
            )
        send_survey_submitted_admin_message(draft, language_code=lang)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Survey submit notifications failed: %s", e, exc_info=True)

    return redirect(reverse('survey:survey_thankyou'))


# ---------------------------------------------------------------------------
# Explicit feedback (수정 관련 사용자 피드백 버튼)
# ---------------------------------------------------------------------------

FEEDBACK_VALUES = frozenset({"corrected_here", "used_other_page", "could_not_find"})


@require_POST
@ensure_csrf_cookie
def survey_revision_feedback(request):
    """
    POST: 수정 안내 화면에서 사용자가 클릭한 피드백 저장 (feedback_clicked).
    Body (JSON 또는 form): request_id, value (corrected_here | used_other_page | could_not_find), page_key(선택).
    """
    try:
        if request.content_type and "application/json" in request.content_type:
            body = json.loads(request.body or "{}")
        else:
            body = request.POST.dict()
        request_id = (body.get("request_id") or "").strip()
        value = (body.get("value") or "").strip().lower()
        page_key = (body.get("page_key") or "").strip() or None
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "invalid body"}, status=400)

    if not request_id:
        return JsonResponse({"ok": False, "error": "request_id required"}, status=400)
    if value not in FEEDBACK_VALUES:
        return JsonResponse({"ok": False, "error": "value must be one of: corrected_here, used_other_page, could_not_find"}, status=400)

    draft = _get_or_create_draft(request)
    survey_submission_id = getattr(draft, "id", None) if draft else None
    user_id = getattr(request.user, "id", None) if request.user.is_authenticated else None

    try:
        from messaging.feedback_events import log_feedback_clicked
        log_feedback_clicked(
            request_id,
            value=value,
            user_id=user_id,
            survey_submission_id=survey_submission_id,
            page_key=page_key,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "survey_revision_feedback: log_feedback_clicked failed (non-blocking) request_id=%s: %s",
            request_id, e,
            exc_info=True,
        )
        # 로그 저장 실패가 본 기능(피드백 수신)을 막지 않도록 200 반환
    return JsonResponse({"ok": True})


@require_GET
@ensure_csrf_cookie
def survey_thankyou(request):
    """제출 완료 안내 (submit 후 redirect 대상)."""
    return render(request, 'survey/survey_thankyou.html')
