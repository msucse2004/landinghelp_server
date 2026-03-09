"""견적 수정/송부(FINAL_SENT) 시 고객 알림. 기존 번역(get_display_text) 사용. status < FINAL_SENT인 메시지에는 금액/총액 미포함 규칙 적용."""
import logging
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from django.urls import reverse

from .constants import message_may_include_price

logger = logging.getLogger(__name__)


def get_quote_payment_link(quote=None):
    """
    고객 견적/결제 페이지 URL. 로그인한 고객만 접근 가능(뷰에서 검증).
    quote: SettlementQuote 또는 None. 지정하면 ?quote_id=<id> 로 해당 견적 페이지로 직행.
    이메일/앱 메시지/고객 견적 페이지에서 동일 헬퍼 사용.
    """
    path = reverse('customer_quote')
    if quote is not None and getattr(quote, 'id', None):
        path += '?quote_id=' + str(quote.id)
    base = (getattr(settings, 'SITE_URL', None) or '').strip().rstrip('/')
    if base:
        return base + path
    return path


def build_quote_release_payload(quote):
    """
    견적 송부 시 이메일/메시지에 쓸 페이로드.
    Returns: dict with payment_link, subject_preferred, body_preferred, customer_email, lang_preferred,
             total_display, item_count. message_may_include_price(quote) True일 때만 가격 포함.
    """
    if not quote or not quote.submission_id:
        return None
    if not message_may_include_price(quote):
        return None
    submission = quote.submission
    lang = 'ko'
    if getattr(submission, 'user_id', None) and submission.user_id:
        lang = (getattr(submission.user, 'preferred_language', None) or '').strip() or lang
    subject, body = build_quote_email_body(quote, lang, include_price=True)
    body = body.strip()
    payment_link = get_quote_payment_link(quote)
    # 본문 끝에 결제 링크 추가 (이메일용)
    if payment_link:
        try:
            from translations.utils import get_display_text
            link_label = get_display_text('결제 링크', lang) or (get_display_text('결제하기', lang) or 'Payment')
        except Exception:
            link_label = 'Payment / 결제'
        body_with_link = body + '\n\n' + link_label + ': ' + payment_link
    else:
        body_with_link = body
    total_val = int(quote.total or 0)
    items = quote.items or []
    item_count = sum(1 for i in items if isinstance(i, dict))
    return {
        'payment_link': payment_link,
        'subject_preferred': subject,
        'body_preferred': body_with_link,
        'customer_email': (submission.email or '').strip(),
        'lang_preferred': lang,
        'total_display': total_val,
        'item_count': item_count,
    }


def send_quote_release_email_with_attachments(quote, lang_preferred='ko'):
    """
    견적 송부 이메일: 고객 선호어 + 영어 2종 PDF 첨부, localized subject/body, 결제 링크 포함.
    quote.status는 호출 전에 이미 FINAL_SENT로 설정되어 있어야 함.
    실패 시 로그만 남기고 False 반환. quote 상태는 변경하지 않음.
    """
    if not quote or not quote.submission_id:
        return False
    if not message_may_include_price(quote):
        return False
    payload = build_quote_release_payload(quote)
    if not payload or not payload['customer_email']:
        logger.warning("Quote %s: no payload or customer email, skip release email.", quote.id)
        return False
    from .quote_pdf import build_quote_pdf_bytes
    pdf_ko = build_quote_pdf_bytes(quote, 'ko')
    pdf_en = build_quote_pdf_bytes(quote, 'en')
    attachments = []
    if pdf_ko:
        attachments.append(('quotation_ko.pdf', pdf_ko, 'application/pdf'))
    if pdf_en:
        attachments.append(('quotation_en.pdf', pdf_en, 'application/pdf'))
    email = EmailMessage(
        subject=payload['subject_preferred'],
        body=payload['body_preferred'],
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
        to=[payload['customer_email']],
        attachments=attachments,
    )
    try:
        email.send(fail_silently=False)
        return True
    except Exception as e:
        logger.warning("Quote release email with attachments failed: quote_id=%s to=%s error=%s", quote.id, payload['customer_email'], e, exc_info=True)
        return False


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
