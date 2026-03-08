"""견적 수정/송부(FINAL_SENT) 시 고객 알림. 기존 번역(get_display_text) 사용. status < FINAL_SENT인 메시지에는 금액/총액 미포함 규칙 적용."""
import logging
from django.core.mail import send_mail
from django.conf import settings

from .constants import message_may_include_price

logger = logging.getLogger(__name__)


def build_quote_email_body(quote, language_code='ko', include_price=True):
    """
    견적 이메일 본문 생성. 규칙: include_price가 False면 금액/총액/checkout 절대 포함하지 않음.
    status < FINAL_SENT인 메시지에는 항상 include_price=False로 호출해야 함.
    """
    try:
        from translations.utils import get_display_text
    except ImportError:
        get_display_text = lambda k, lang: k

    subject = get_display_text('견적 안내', language_code) or '견적 안내'
    lines = [
        get_display_text('안녕하세요. 요청하신 정착 서비스 견적을 보내드립니다.', language_code) or '안녕하세요. 요청하신 정착 서비스 견적을 보내드립니다.',
        '',
    ]
    for item in (quote.items or []):
        if isinstance(item, dict):
            label = item.get('label') or item.get('code') or '-'
            if include_price and item.get('price') is not None:
                lines.append(f"  · {label}: ${int(item['price']):,.2f} USD")
            else:
                lines.append(f"  · {label}")
    lines.append('')
    if include_price:
        total_line = (get_display_text('합계', language_code) or '합계') + f": ${int(quote.total or 0):,.2f} USD"
        lines.append(total_line)
        lines.append('')
    lines.append(get_display_text('문의 사항은 회신으로 부탁드립니다.', language_code) or '문의 사항은 회신으로 부탁드립니다.')
    body = '\n'.join(lines)
    return subject, body


def send_quote_to_customer(quote, language_code='ko'):
    """
    견적 송부(FINAL_SENT) → 고객 알림. 이 시점부터 가격 포함 가능.
    규칙: status < FINAL_SENT이면 금액/총액/checkout 절대 포함하지 않음 → 이 함수는 FINAL_SENT/PAID일 때만 호출.
    """
    if not quote or not quote.submission_id:
        return False
    if not message_may_include_price(quote):
        return False
    if quote.status != quote.Status.FINAL_SENT and quote.status != quote.Status.PAID:
        return False
    email = (quote.submission.email or '').strip()
    if not email:
        logger.warning("Quote %s: submission has no email, skip send.", quote.id)
        return False

    include_price = message_may_include_price(quote)
    subject, body = build_quote_email_body(quote, language_code, include_price=include_price)

    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.warning("Quote email send failed: quote_id=%s email=%s error=%s", quote.id, email, e, exc_info=True)
        return False
