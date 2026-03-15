"""
견적 변경 요청 워크플로우 진입점.

자유 텍스트 수정 요청 접수 → QuoteChangeRequest 생성 → LLM 분석 → status ANALYZED.
Admin 설문 재개 승인: approve_reopen_survey → submission 수정 가능 상태, 기존 견적 비활성(결제 제외).
"""
import logging
from typing import Any, Dict, Optional, Tuple

from django.db.models import F
from django.utils import timezone

from .models import QuoteChangeRequest, QuoteChangeActionLog, SettlementQuote
from .services_quote_change_llm import analyze_quote_change_request

logger = logging.getLogger(__name__)

# 설문 재개 시 고객에게 보낼 메시지 (revision_requested_message에 저장)
REOPEN_MESSAGE_KO = (
    '관리자가 수정 요청을 승인했습니다. 이전에 입력한 내용을 바탕으로 설문을 수정해 주세요.\n\n'
    '설문을 다시 제출하면 관리자가 수정된 내용을 검토한 뒤 새 견적을 보내드립니다.'
)
REOPEN_MESSAGE_EN = (
    'Your revision request has been approved. Please update your survey based on your previous answers.\n\n'
    'After you resubmit, we will review the changes and send you a new quotation.'
)


def submit_text_change_request(
    quote: SettlementQuote,
    user,
    message: str,
) -> Tuple[Optional[QuoteChangeRequest], Optional[Any], Optional[str]]:
    """
    고객 자유 텍스트 수정 요청을 접수하고 LLM 분석까지 수행.

    - QuoteChangeRequest 생성 (source_type=TEXT, status=OPEN)
    - analyze_quote_change_request(change_request) 실행
    - 분석 생성 시 status를 ANALYZED로 업데이트
    - 설문 재개/quote 삭제/quote 최종 상태 직접 변경은 하지 않음.

    Returns:
        (change_request, analysis, error_message)
        성공 시 error_message=None. 실패 시 change_request/analysis 중 하나만 있을 수 있고 error_message 설정.
    """
    if not quote or not message or not (str(message).strip()):
        return None, None, '수정 요청 내용을 입력해 주세요.'

    submission = getattr(quote, 'submission', None)
    if not submission:
        return None, None, '견적에 연결된 설문이 없습니다.'

    try:
        cr = QuoteChangeRequest(
            submission=submission,
            quote=quote,
            requested_by=user,
            source_type=QuoteChangeRequest.SourceType.TEXT,
            status=QuoteChangeRequest.Status.OPEN,
            customer_message=str(message).strip(),
        )
        cr.save()
    except Exception as e:
        logger.warning("QuoteChangeRequest create failed: %s", e, exc_info=True)
        return None, None, '요청 접수에 실패했습니다.'

    analysis = None
    try:
        analysis = analyze_quote_change_request(cr)
    except Exception as e:
        logger.warning("analyze_quote_change_request failed: %s", e, exc_info=True)
        # OPEN 유지, admin 검토 필요
        return cr, None, None  # 요청은 생성됐으므로 ok로 처리, analysis만 없음

    if analysis:
        cr.status = QuoteChangeRequest.Status.ANALYZED
        cr.save(update_fields=['status'])

    return cr, analysis, None


def serialize_change_request_for_response(cr: QuoteChangeRequest) -> Dict[str, Any]:
    """API 응답용 change_request 직렬화. 민감 필드 제외."""
    if not cr:
        return {}
    return {
        'id': cr.id,
        'status': cr.status,
        'created_at': cr.created_at.isoformat() if cr.created_at else None,
        'source_type': cr.source_type,
    }


def serialize_analysis_for_response(analysis) -> Dict[str, Any]:
    """API 응답용 analysis 직렬화. raw_llm_output·raw_customer_message 제외."""
    if not analysis:
        return {}
    return {
        'id': getattr(analysis, 'id', None),
        'summary': getattr(analysis, 'normalized_summary', '') or '',
        'detected_intent': getattr(analysis, 'detected_intent', ''),
        'confidence': float(getattr(analysis, 'confidence', 0)),
        'recommended_next_step': getattr(analysis, 'recommended_next_step', '') or '',
        'requires_admin_confirmation': bool(getattr(analysis, 'requires_admin_confirmation', True)),
    }


def _do_approve_reopen_survey(submission, cr, actor, request=None):
    """설문 재개 실행 로직. 호출 전에 cr.can_be_reopened_for_survey_edit() 검증 완료 가정."""
    from survey.models import SurveySubmission, SurveySubmissionEvent

    now = timezone.now()
    lang = 'ko'
    if getattr(submission, 'user_id', None) and submission.user_id:
        try:
            pref = (getattr(submission.user, 'preferred_language', None) or '').strip().lower()
            if pref and pref.startswith('en'):
                lang = 'en'
        except Exception:
            pass
    reopen_message = REOPEN_MESSAGE_EN if lang == 'en' else REOPEN_MESSAGE_KO

    submission.status = SurveySubmission.Status.REVISION_REQUESTED
    submission.revision_requested_at = now
    submission.revision_requested_message = reopen_message
    submission.reopened_at = now
    submission.save(update_fields=['status', 'revision_requested_at', 'revision_requested_message', 'reopened_at', 'updated_at'])
    SurveySubmission.objects.filter(pk=submission.pk).update(revision_count=F('revision_count') + 1)
    submission.refresh_from_db(fields=['revision_count'])

    SurveySubmissionEvent.objects.create(
        submission=submission,
        event_type=SurveySubmissionEvent.EventType.REOPENED,
        created_by=actor,
        meta={'change_request_id': cr.id},
    )

    cr.status = QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED
    cr.save(update_fields=['status'])

    QuoteChangeActionLog.objects.create(
        change_request=cr,
        actor=actor,
        action_type=QuoteChangeActionLog.ActionType.ADMIN_APPROVED_REOPEN,
        detail={'submission_id': submission.id},
    )
    QuoteChangeActionLog.objects.create(
        change_request=cr,
        actor=actor,
        action_type=QuoteChangeActionLog.ActionType.SURVEY_REOPENED,
        detail={'submission_id': submission.id},
    )

    sent_quote = (
        SettlementQuote.objects.filter(
            submission=submission,
            status=SettlementQuote.Status.FINAL_SENT,
        ).order_by('-sent_at', '-updated_at').first()
    )
    if sent_quote:
        sent_quote.revision_superseded_at = now
        sent_quote.save(update_fields=['revision_superseded_at'])

    try:
        from translations.utils import get_request_language
        from .notifications import send_survey_reopened_customer_message
        req_lang = get_request_language(request) if request else lang
        send_survey_reopened_customer_message(submission, language_code=req_lang or lang, request=request)
    except Exception as e:
        logger.warning("send_survey_reopened_customer_message failed: %s", e, exc_info=True)


def approve_reopen_survey(change_request, admin_user, request=None) -> Tuple[bool, Optional[str]]:
    """
    Admin 설문 재개 승인 (change_request 기준). LLM 추천은 참고이며, Admin 승인 시에만 실행.

    - change_request 유효성 검증, linked quote 무효화, submission 편집 가능 전환, 고객 메시지 발송.
    - Idempotent: 이미 CUSTOMER_ACTION_REQUIRED 이면 재실행 없이 성공 반환.
    Returns: (success, error_message)
    """
    if not change_request:
        return False, '변경 요청이 없습니다.'
    if change_request.status == QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED:
        return True, None
    if not change_request.can_be_reopened_for_survey_edit():
        return False, '현재 상태에서는 설문 재개를 할 수 없습니다. (제출/결제대기 상태이고 변경요청이 분석완료/검토중/승인일 때만 가능)'
    submission = getattr(change_request, 'submission', None)
    if not submission:
        return False, '해당 설문 제출을 찾을 수 없습니다.'
    _do_approve_reopen_survey(submission, change_request, admin_user, request)
    return True, None


def approve_reopen_survey_by_ids(
    submission_id: int,
    change_request_id: int,
    actor,
    request=None,
) -> Tuple[bool, Optional[str]]:
    """
    Admin 설문 재개 승인 (submission_id, change_request_id 기준). 뷰에서 호출용.
    내부적으로 change_request를 조회한 뒤 approve_reopen_survey(change_request, actor, request) 호출.
    """
    from survey.models import SurveySubmission

    submission = SurveySubmission.objects.filter(id=submission_id).first()
    if not submission:
        return False, '해당 설문 제출을 찾을 수 없습니다.'
    cr = QuoteChangeRequest.objects.filter(
        id=change_request_id,
        submission_id=submission_id,
    ).first()
    if not cr:
        return False, '해당 변경 요청을 찾을 수 없습니다.'
    return approve_reopen_survey(cr, actor, request)


def approve_quote_revision(change_request, admin_user) -> Tuple[bool, Optional[Any], Optional[str]]:
    """
    Admin 견적 수정 승인: 서비스 추가/제거/변경 중심이면 기존 sent quote 기반으로 draft 생성(또는 기존 draft 재사용),
    change_request를 IN_REVIEW로 두어 Admin이 검토 후 송부할 수 있게 함. LLM 분석은 참고이며 Admin 승인 시에만 실행.

    Idempotent: 이미 APPLIED 이면 성공 반환. 이미 IN_REVIEW이고 draft가 있으면 재생성 없이 성공.
    Returns: (success, draft_quote or None, error_message)
    """
    if not change_request:
        return False, None, '변경 요청이 없습니다.'
    if change_request.status == QuoteChangeRequest.Status.APPLIED:
        draft = (
            SettlementQuote.objects.filter(
                submission_id=change_request.submission_id,
                status=SettlementQuote.Status.DRAFT,
            ).order_by('-updated_at').first()
        )
        return True, draft, None

    if change_request.status not in (
        QuoteChangeRequest.Status.ANALYZED,
        QuoteChangeRequest.Status.IN_REVIEW,
        QuoteChangeRequest.Status.APPROVED,
    ):
        return False, None, '현재 상태에서는 견적 수정 프로세스를 시작할 수 없습니다.'
    submission = getattr(change_request, 'submission', None)
    if not submission:
        return False, None, '해당 설문 제출을 찾을 수 없습니다.'

    from .quote_draft import create_draft_from_sent_quote
    draft, created = create_draft_from_sent_quote(submission)
    if not draft:
        return False, None, '송부된 견적이 없습니다. 견적을 먼저 고객에게 송부한 뒤 수정 프로세스를 진행하세요.'

    change_request.status = QuoteChangeRequest.Status.IN_REVIEW
    change_request.save(update_fields=['status'])

    QuoteChangeActionLog.objects.create(
        change_request=change_request,
        actor=admin_user,
        action_type=QuoteChangeActionLog.ActionType.ADMIN_APPROVED_QUOTE_REVISION,
        detail={'draft_id': draft.id, 'created': created},
    )
    return True, draft, None


def reject_change_request(change_request, admin_user, note: str = '') -> Tuple[bool, Optional[str]]:
    """
    Admin이 변경 요청을 반려. Idempotent: 이미 REJECTED 이면 재실행 없이 성공 반환.
    Returns: (success, error_message)
    """
    if not change_request:
        return False, '변경 요청이 없습니다.'
    if change_request.status == QuoteChangeRequest.Status.REJECTED:
        return True, None
    now = timezone.now()
    change_request.status = QuoteChangeRequest.Status.REJECTED
    change_request.reviewed_at = now
    update_fields = ['status', 'reviewed_at']
    if note is not None and note != '':
        change_request.admin_note = (change_request.admin_note or '') + ('\n[반려] ' + note.strip())
        update_fields.append('admin_note')
    change_request.save(update_fields=update_fields)
    QuoteChangeActionLog.objects.create(
        change_request=change_request,
        actor=admin_user,
        action_type=QuoteChangeActionLog.ActionType.ADMIN_REJECTED,
        detail={'note': (note or '')[:500]},
    )
    return True, None


def mark_change_request_applied(change_request, admin_user) -> Tuple[bool, Optional[str]]:
    """
    Admin이 변경 요청을 수동으로 '적용 완료' 처리. Idempotent: 이미 APPLIED 이면 재실행 없이 성공 반환.
    Returns: (success, error_message)
    """
    if not change_request:
        return False, '변경 요청이 없습니다.'
    if change_request.status == QuoteChangeRequest.Status.APPLIED:
        return True, None
    now = timezone.now()
    change_request.status = QuoteChangeRequest.Status.APPLIED
    change_request.resolved_at = now
    change_request.save(update_fields=['status', 'resolved_at'])
    QuoteChangeActionLog.objects.create(
        change_request=change_request,
        actor=admin_user,
        action_type=QuoteChangeActionLog.ActionType.ADMIN_APPROVED_QUOTE_REVISION,
        detail={'marked_applied': True},
    )
    return True, None
