"""
제출(submission) 및 견적 초안에 대한 자동 검증·체크 포인트.
운영자 수동 확인 최소화: 누락 정보, 불일치, 미해결 수정 요청, 견적 검토 필요 항목을 규칙 기반으로 판단.
"""

# 체크 결과에 쓰는 상수
READINESS_READY = 'ready_for_approval'
READINESS_WAITING_CUSTOMER = 'waiting_on_customer'
READINESS_NEEDS_ADMIN_PRICING = 'needs_admin_pricing'
READINESS_INCOMPLETE = 'incomplete_request'

CATEGORY_COMPLETENESS = 'completeness'
CATEGORY_CONSISTENCY = 'consistency'
CATEGORY_CUSTOMER_UPDATE = 'customer_update'
CATEGORY_QUOTE_REVIEW = 'quote_review'
CATEGORY_DRAFT_FRESHNESS = 'draft_freshness'


def run_submission_checks(submission, quote_draft=None):
    """
    제출·견적 초안에 대해 결정론적 검사 수행.
    submission: SurveySubmission
    quote_draft: SettlementQuote | None (DRAFT 견적)
    Returns: {
        "readiness": READINESS_*,
        "readiness_label": "승인 가능" | "고객 입력 대기" | "Admin 가격 검토 필요" | "요청 불완전",
        "checks": [{"id": str, "passed": bool, "message": str, "category": str}, ...],
        "blocking_ids": [str, ...],  # 실패한 체크 중 블로킹 id
    }
    """
    if not submission:
        return _result(READINESS_INCOMPLETE, [], blocking=['has_submission'])

    checks = []
    blocking = []

    # --- 필수 정보 (completeness) ---
    email_ok = bool((submission.email or '').strip())
    checks.append({
        'id': 'has_email',
        'passed': email_ok,
        'message': '이메일 있음' if email_ok else '이메일 없음',
        'category': CATEGORY_COMPLETENESS,
    })
    if not email_ok:
        blocking.append('has_email')

    from .quote_input import get_quote_input_data
    data = get_quote_input_data(submission)
    service_codes = list(data.get('service_codes') or [])
    add_on_codes = list(data.get('add_on_codes') or [])
    has_services = bool(service_codes or add_on_codes)
    checks.append({
        'id': 'has_services',
        'passed': has_services,
        'message': '서비스 선택됨' if has_services else '선택된 서비스 없음',
        'category': CATEGORY_COMPLETENESS,
    })
    if not has_services:
        blocking.append('has_services')

    # --- 서비스 코드 일관성 (consistency): 미등록 코드 여부 ---
    unknown = _unknown_service_codes(service_codes + add_on_codes)
    known_codes_ok = len(unknown) == 0
    checks.append({
        'id': 'known_service_codes',
        'passed': known_codes_ok,
        'message': '모든 서비스 코드 등록됨' if known_codes_ok else f'미등록 코드: {", ".join(unknown[:5])}{" …" if len(unknown) > 5 else ""}',
        'category': CATEGORY_CONSISTENCY,
    })
    if not known_codes_ok:
        blocking.append('known_service_codes')

    # --- 고객 수정 대기 (customer_update) ---
    from .models import SurveySubmissionSectionRequest
    pending_sections = SurveySubmissionSectionRequest.objects.filter(
        submission=submission,
        resolved_at__isnull=True,
    ).exists()
    is_revision_requested = submission.status == submission.Status.REVISION_REQUESTED
    waiting_customer = is_revision_requested or pending_sections
    checks.append({
        'id': 'not_waiting_customer',
        'passed': not waiting_customer,
        'message': '고객 수정 대기 중' if waiting_customer else '고객 입력 완료',
        'category': CATEGORY_CUSTOMER_UPDATE,
    })
    if waiting_customer:
        blocking.append('not_waiting_customer')

    # --- 견적 초안 갱신 시점 (draft_freshness): 제출이 초안 생성 이후 수정됐으면 경고 ---
    draft_stale = False
    try:
        if quote_draft and getattr(quote_draft, 'auto_generated_at', None) and submission.updated_at:
            if submission.updated_at > quote_draft.auto_generated_at:
                draft_stale = True
    except (TypeError, ValueError):
        pass
    checks.append({
        'id': 'draft_fresh',
        'passed': not draft_stale,
        'message': '답변 변경됨 — 초안 재생성 권장' if draft_stale else '초안 이후 답변 변경 없음',
        'category': CATEGORY_DRAFT_FRESHNESS,
    })
    if draft_stale:
        blocking.append('draft_fresh')

    # --- 견적 항목 중 Admin 검토 필요 (_needs_review) ---
    quote_needs_review = False
    if quote_draft and quote_draft.items:
        for it in quote_draft.items:
            if isinstance(it, dict) and it.get('_needs_review'):
                quote_needs_review = True
                break
    checks.append({
        'id': 'quote_no_review_needed',
        'passed': not quote_needs_review,
        'message': '일부 항목 가격/코드 검토 필요' if quote_needs_review else '견적 항목 검토 불필요',
        'category': CATEGORY_QUOTE_REVIEW,
    })
    if quote_needs_review:
        blocking.append('quote_no_review_needed')

    # --- 견적 초안 존재 (승인 가능 여부에 영향) ---
    has_draft = quote_draft is not None
    checks.append({
        'id': 'has_draft',
        'passed': has_draft,
        'message': '견적 초안 있음' if has_draft else '견적 초안 없음',
        'category': CATEGORY_COMPLETENESS,
    })
    if not has_draft and submission.status == submission.Status.SUBMITTED:
        blocking.append('has_draft')

    # --- 종합 준비도 ---
    readiness = _compute_readiness(checks, blocking, submission)
    label = {
        READINESS_READY: '승인 가능',
        READINESS_WAITING_CUSTOMER: '고객 입력 대기',
        READINESS_NEEDS_ADMIN_PRICING: 'Admin 가격 검토 필요',
        READINESS_INCOMPLETE: '요청 불완전',
    }.get(readiness, readiness)

    return {
        'readiness': readiness,
        'readiness_label': label,
        'checks': checks,
        'blocking_ids': blocking,
    }


def _unknown_service_codes(codes):
    """등록되지 않은 서비스 코드 목록 반환."""
    if not codes:
        return []
    from settlement.models import SettlementService
    codes = [str(c).strip() for c in codes if str(c).strip()]
    if not codes:
        return []
    existing = set()
    for s in SettlementService.objects.filter(is_active=True):
        if s.code:
            existing.add(s.code.strip())
        existing.add(str(s.id))
    return [c for c in codes if c not in existing]


def _compute_readiness(checks, blocking, submission):
    """체크 결과와 블로킹 목록으로 최종 readiness 결정."""
    check_by_id = {c['id']: c for c in checks}

    if 'has_email' in blocking or 'has_services' in blocking:
        return READINESS_INCOMPLETE
    if submission.status == submission.Status.REVISION_REQUESTED or 'not_waiting_customer' in blocking:
        return READINESS_WAITING_CUSTOMER
    if 'known_service_codes' in blocking or 'quote_no_review_needed' in blocking:
        return READINESS_NEEDS_ADMIN_PRICING
    if 'has_draft' in blocking:
        return READINESS_INCOMPLETE
    if 'draft_fresh' in blocking:
        return READINESS_NEEDS_ADMIN_PRICING
    return READINESS_READY


def _result(readiness, checks, blocking=None):
    label = {
        READINESS_READY: '승인 가능',
        READINESS_WAITING_CUSTOMER: '고객 입력 대기',
        READINESS_NEEDS_ADMIN_PRICING: 'Admin 가격 검토 필요',
        READINESS_INCOMPLETE: '요청 불완전',
    }.get(readiness, readiness)
    return {
        'readiness': readiness,
        'readiness_label': label,
        'checks': checks,
        'blocking_ids': blocking or [],
    }
