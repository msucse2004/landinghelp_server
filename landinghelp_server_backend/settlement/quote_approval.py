"""
최종 견적 승인·송부 공통 로직.
Django Admin 저장과 검토 페이지 "승인 후 송부"에서 동일한 흐름을 사용해 로직 중복을 제거합니다.
송부 시: 고객 선호어/영어 2종 PDF 첨부 이메일 + 앱 메시지(요약·결제 링크). 이메일 실패해도 FINAL_SENT 유지.

무효화 정책: 기존 견적은 hard delete 하지 않음. 설문 재개 승인 시 이전 FINAL_SENT 견적에
revision_superseded_at 만 설정해 결제 대상에서 제외하며, 레코드·메시지·이력은 유지.
"""
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


def finalize_and_send_quote(quote, actor=None):
    """
    견적을 최종 승인하고 고객에게 송부합니다.
    - quote.status → FINAL_SENT, submission.status → AWAITING_PAYMENT, sent_at 기록
    - QUOTE_SENT 이벤트 로그
    - 이메일: localized subject/body + 결제 링크 + 견적서 PDF 2종(고객 선호어, 영어) 첨부. 실패 시에도 quote는 FINAL_SENT 유지, 로그만 남김.
    - 앱 메시지: 공유 대화에 견적 송부 안내 + 짧은 요약 + 결제 링크 (이메일 실패 여부와 무관하게 발송)

    quote: SettlementQuote (DRAFT 또는 NEGOTIATING 권장; 이미 FINAL_SENT/PAID여도 sent_at만 보완 가능)
    actor: 요청자 User (이벤트 로그용, None 가능)
    Returns: (success: bool, error_message: str | None)
    """
    if not quote:
        return False, '견적이 없습니다.'
    from .models import SettlementQuote
    from survey.models import SurveySubmission, SurveySubmissionEvent

    if quote.status not in (SettlementQuote.Status.FINAL_SENT, SettlementQuote.Status.PAID):
        quote.status = SettlementQuote.Status.FINAL_SENT
        quote.save(update_fields=['status', 'updated_at'])

    if quote.submission_id:
        sub = quote.submission
        if sub.status != SurveySubmission.Status.AWAITING_PAYMENT:
            sub.status = SurveySubmission.Status.AWAITING_PAYMENT
            sub.save(update_fields=['status'])
        try:
            sub.advance_case_stage(sub.CaseStage.QUOTE_SENT)
        except Exception:
            pass
        SurveySubmissionEvent.objects.create(
            submission=sub,
            event_type=SurveySubmissionEvent.EventType.QUOTE_SENT,
            created_by=actor,
        )

    # sent_at은 송부 시점으로 기록 (이메일 성공 여부와 무관)
    if not quote.sent_at:
        quote.sent_at = timezone.now()
        quote.save(update_fields=['sent_at'])

    # 이메일: PDF 2종 첨부 + 결제 링크. 실패해도 quote 상태는 이미 FINAL_SENT/sent_at 반영됨.
    lang = 'ko'
    try:
        if getattr(quote.submission, 'user_id', None) and quote.submission.user_id:
            lang = (getattr(quote.submission.user, 'preferred_language', None) or '').strip() or lang
    except Exception:
        pass
    try:
        from .quote_email import send_quote_release_email_with_attachments
        if not send_quote_release_email_with_attachments(quote, lang_preferred=lang):
            logger.warning("Quote %s: release email (with PDFs) failed or skipped; in-app message still sent.", quote.id)
    except Exception as e:
        logger.warning("Quote %s: release email exception: %s", quote.id, e, exc_info=True)

    # 앱 메시지: 항상 발송 (견적 송부 안내 + 요약 + 결제 링크)
    try:
        from .notifications import send_quote_release_message
        send_quote_release_message(quote, language_code=lang)
    except Exception as e:
        logger.warning("Quote %s: send_quote_release_message failed: %s", quote.id, e, exc_info=True)

    # 재견적 관계: 이 견적이 무효화된 이전 견적을 대체한 경우 supersedes 설정
    if quote.submission_id:
        try:
            from .models import SettlementQuote
            superseded = (
                SettlementQuote.objects.filter(
                    submission_id=quote.submission_id,
                    status=SettlementQuote.Status.FINAL_SENT,
                    revision_superseded_at__isnull=False,
                )
                .order_by('-revision_superseded_at')
                .first()
            )
            if superseded and not quote.supersedes_id:
                quote.supersedes = superseded
                quote.save(update_fields=['supersedes', 'updated_at'])
        except Exception as e:
            logger.warning("Quote %s: setting supersedes failed: %s", quote.id, e, exc_info=True)

    # 설문 재개·수정 후 새 견적 송부 시: 해당 submission의 미해결 change request → APPLIED
    if quote.submission_id:
        try:
            from .models import QuoteChangeRequest, QuoteChangeActionLog, HumanReviewRequest
            pending_statuses = (
                QuoteChangeRequest.Status.ANALYZED,
                QuoteChangeRequest.Status.IN_REVIEW,
                QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED,
                QuoteChangeRequest.Status.APPROVED,
            )
            for cr in QuoteChangeRequest.objects.filter(
                submission_id=quote.submission_id,
                status__in=pending_statuses,
            ):
                cr.status = QuoteChangeRequest.Status.APPLIED
                cr.save(update_fields=['status', 'updated_at'])
                QuoteChangeActionLog.objects.create(
                    change_request=cr,
                    actor=actor,
                    action_type=QuoteChangeActionLog.ActionType.ADMIN_APPROVED_QUOTE_REVISION,
                    detail={'sent_quote_id': quote.id},
                )
            # 같은 submission에 대한 미완료 HumanReviewRequest → COMPLETED (재견적 송부로 처리 완료)
            now = timezone.now()
            for rev in HumanReviewRequest.objects.filter(
                submission_id=quote.submission_id,
            ).exclude(status=HumanReviewRequest.Status.COMPLETED):
                rev.status = HumanReviewRequest.Status.COMPLETED
                rev.completed_at = now
                rev.completed_note = (rev.completed_note or '') + '\n재견적 송부로 완료 처리 (견적 #%s).' % quote.id
                rev.save(update_fields=['status', 'completed_at', 'completed_note', 'updated_at'])
        except Exception as e:
            logger.warning("Quote %s: marking change requests APPLIED failed: %s", quote.id, e, exc_info=True)

    return True, None
