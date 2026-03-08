"""
최종 견적 승인·송부 공통 로직.
Django Admin 저장과 검토 페이지 "승인 후 송부"에서 동일한 흐름을 사용해 로직 중복을 제거합니다.
"""
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


def finalize_and_send_quote(quote, actor=None):
    """
    견적을 최종 승인하고 고객에게 송부합니다.
    - quote.status를 FINAL_SENT로 설정(아직이면)
    - submission 상태를 고객 결재 대기중(AWAITING_PAYMENT)으로 변경
    - QUOTE_SENT 이벤트 로그
    - 이메일 발송 및 sent_at 갱신(아직 미송부인 경우만)

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
        SurveySubmissionEvent.objects.create(
            submission=sub,
            event_type=SurveySubmissionEvent.EventType.QUOTE_SENT,
            created_by=actor,
        )

    if not quote.sent_at:
        from .quote_email import send_quote_to_customer
        try:
            lang = 'ko'
            if getattr(quote.submission, 'user_id', None) and quote.submission.user_id:
                u = quote.submission.user
                lang = (getattr(u, 'preferred_language', None) or '').strip() or lang
        except Exception:
            lang = 'ko'
        if send_quote_to_customer(quote, language_code=lang):
            quote.sent_at = timezone.now()
            quote.save(update_fields=['sent_at'])
        else:
            logger.warning("Quote %s: send_quote_to_customer returned False.", quote.id)
        # 고객 메시지함에 견적 송부 안내 + 추가 필요 시 Admin에게 메시지 보내라는 안내
        try:
            from .notifications import send_quote_sent_customer_message
            send_quote_sent_customer_message(quote, language_code=lang)
        except Exception as e:
            logger.warning("Quote %s: send_quote_sent_customer_message failed: %s", quote.id, e, exc_info=True)

    return True, None
