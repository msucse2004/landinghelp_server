"""
이벤트별 알림(이메일). 번역 룰(get_display_text) 유지.
규칙: status < FINAL_SENT인 메시지에는 금액/총액/checkout을 절대 포함하지 않는다.
"""
import logging
from django.core.mail import send_mail
from django.conf import settings

from .constants import message_may_include_price

logger = logging.getLogger(__name__)


def _get_display_text(key, lang='ko'):
    try:
        from translations.utils import get_display_text
        return get_display_text(key, lang) or key
    except ImportError:
        return key


def _get_admin_emails():
    """Admin 알림 수신 이메일 목록. settings.ADMINS 또는 staff 사용자."""
    emails = []
    for name, email in getattr(settings, 'ADMINS', []):
        if email:
            emails.append(email)
    if not emails:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        emails = list(User.objects.filter(is_staff=True, is_active=True).exclude(email='').values_list('email', flat=True)[:10])
    return emails


def _get_admin_users():
    """메시지함 알림용 Admin(스태프) 사용자 목록."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return list(User.objects.filter(is_staff=True, is_active=True)[:20])


def _get_system_sender():
    """시스템 알림 메시지의 발신자로 쓸 사용자(첫 superuser 또는 첫 staff)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    u = User.objects.filter(is_superuser=True, is_active=True).first()
    if u:
        return u
    return User.objects.filter(is_staff=True, is_active=True).first()


def _is_email_configured():
    """실제 발송 가능 여부 (console 백엔드가 아니고 계정 설정됨)."""
    if getattr(settings, 'EMAIL_BACKEND', '') == 'django.core.mail.backends.console.EmailBackend':
        return False
    if not getattr(settings, 'EMAIL_HOST_USER', None) or not getattr(settings, 'EMAIL_HOST_PASSWORD', None):
        return False
    return True


def _get_or_create_shared_conversation(submission, subject_fallback=''):
    """
    submission 에 연결된 공유 대화를 찾거나 새로 생성.
    모든 알림은 같은 submission 대화를 공유하여 고객↔Admin이 한 thread에서 소통.
    """
    from messaging.models import Conversation, ConversationParticipant
    conv = Conversation.objects.filter(survey_submission=submission).first()
    if not conv:
        conv = Conversation.objects.create(
            type=Conversation.Type.NOTICE,
            subject=subject_fallback,
            survey_submission=submission,
        )
    customer = getattr(submission, 'user', None)
    if customer and getattr(customer, 'is_authenticated', True):
        ConversationParticipant.objects.get_or_create(conversation=conv, user=customer)
    for admin in _get_admin_users():
        ConversationParticipant.objects.get_or_create(conversation=conv, user=admin)
    return conv


def send_survey_submitted_admin_notification(submission, language_code='ko'):
    """
    설문 제출(SUBMITTED) 시 Admin 알림. 금액/총액/checkout 포함 금지(status < FINAL_SENT).
    """
    if not submission or submission.status != 'SUBMITTED':
        return False
    emails = _get_admin_emails()
    if not emails or not _is_email_configured():
        logger.debug("Survey submitted admin notification skipped: no admin emails or email not configured.")
        return False
    subject = _get_display_text('새 설문 제출 알림', language_code)
    body_lines = [
        _get_display_text('고객이 정착 서비스 설문을 제출했습니다.', language_code),
        '',
        _get_display_text('이메일', language_code) + ': ' + (submission.email or '-'),
        _get_display_text('제출 시각', language_code) + ': ' + (str(submission.submitted_at) if getattr(submission, 'submitted_at', None) else '-'),
    ]
    if getattr(submission, 'preferred_support_mode', None):
        body_lines.append(_get_display_text('선호 지원 방식', language_code) + ': ' + (submission.preferred_support_mode or '-'))
    body_lines.append('')
    body_lines.append(_get_display_text('Admin에서 설문 제출 목록을 확인하고 견적을 작성해 주세요.', language_code))
    body = '\n'.join(body_lines)
    try:
        send_mail(
            subject,
            body,
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            emails,
            fail_silently=True,
        )
        return True
    except Exception as e:
        logger.warning("Survey submitted admin notification failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
        return False


def send_survey_submitted_customer_email(submission, language_code='ko', is_revision_resubmit=False):
    """
    설문 제출(SUBMITTED) 시 고객에게 확인 이메일 발송. 금액 미포함.
    is_revision_resubmit=True면 수정 제출용 문구 사용.
    """
    if not submission or submission.status != 'SUBMITTED':
        return False
    email = (getattr(submission, 'email', None) or '').strip()
    if not email or not _is_email_configured():
        logger.debug("Survey submitted customer email skipped: no email or email not configured.")
        return False
    if is_revision_resubmit:
        subject = _get_display_text('설문 수정이 제출되었습니다', language_code)
        intro = _get_display_text('안녕하세요. 정착 서비스 설문 수정이 정상적으로 제출되었습니다.', language_code)
    else:
        subject = _get_display_text('설문이 제출되었습니다', language_code)
        intro = _get_display_text('안녕하세요. 정착 서비스 설문이 정상적으로 제출되었습니다.', language_code)
    body_lines = [
        intro,
        '',
        _get_display_text('제출 시각', language_code) + ': ' + (str(submission.submitted_at) if getattr(submission, 'submitted_at', None) else '-'),
        '',
        _get_display_text('Admin에서 검토 후 견적을 보내드리겠습니다. 내 견적 페이지에서 확인하실 수 있습니다.', language_code),
    ]
    body = '\n'.join(body_lines)
    try:
        send_mail(
            subject,
            body,
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            [email],
            fail_silently=True,
        )
        return True
    except Exception as e:
        logger.warning("Survey submitted customer email failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
        return False


def _customer_name_for_conversation(submission):
    """대화 제목용 고객 이름 (submission.user 또는 email)."""
    customer = getattr(submission, 'user', None)
    if customer and getattr(customer, 'is_authenticated', True):
        return (getattr(customer, 'get_full_name', lambda: '')() or getattr(customer, 'username', '') or getattr(customer, 'email', '') or '').strip()
    return (getattr(submission, 'email', None) or '-').strip() or '-'


def send_survey_submitted_customer_message(submission, language_code='ko', is_revision_resubmit=False):
    """
    설문 제출(SUBMITTED) 시 고객 메시지함에 확인 메시지 추가. 로그인한 고객(submission.user)만 대상.
    is_revision_resubmit=True면 수정 제출용 문구 사용.
    고객 + Admin 모두 참여자로 추가하여 같은 thread에서 대화 가능.
    대화 제목: [이름] 정착 서비스 (상태는 메시지함 API에서 표시).
    """
    if not submission or submission.status != 'SUBMITTED':
        return False
    customer = getattr(submission, 'user', None)
    if not customer or not customer.is_authenticated:
        logger.debug("Survey submitted customer message skipped: no linked user.")
        return False
    system_sender = _get_system_sender()
    if not system_sender:
        logger.warning("Survey submitted customer message skipped: no system sender (staff/superuser).")
        return False
    try:
        from messaging.models import Message
        base_subject = _get_display_text('정착 서비스', language_code)
        customer_name = _customer_name_for_conversation(submission)
        subject = f'[{customer_name}] {base_subject}'
        if is_revision_resubmit:
            body = '✨ ' + _get_display_text('정착 서비스 설문 수정이 제출되었습니다. 😊 Admin 검토 후 견적을 보내드리겠습니다.', language_code)
        else:
            body = '✨ ' + _get_display_text('정착 서비스 설문이 제출되었습니다. 😊 Admin 검토 후 견적을 보내드리겠습니다.', language_code)
        body += '\n\n💬 ' + _get_display_text('필요한 사항이 있으시면 메시지로 보내 주세요.', language_code)
        conv = _get_or_create_shared_conversation(submission, subject_fallback=subject)
        msg = Message(conversation=conv, sender=system_sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Survey submitted customer message failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
        return False


def _build_revision_requested_body(language_code, section_titles=None, revision_message=None):
    """수정 요청 시 고객에게 보낼 본문 텍스트 (메시지/이메일 공통)."""
    body = _get_display_text('설문 수정이 요청되었습니다.', language_code)
    body += '\n\n' + _get_display_text('정착 서비스 > 정착 설문 화면에서 다시 접속하여 요청된 내용을 수정해 주세요.', language_code)
    if section_titles:
        body += '\n\n' + _get_display_text('수정 요청된 카드', language_code) + ': ' + ', '.join(section_titles)
    extra = (revision_message or '').strip()
    if extra:
        body += '\n\n' + extra
    return body


def send_revision_requested_customer_email(submission, language_code='ko', section_titles=None, revision_message=None):
    """
    수정 요청(REVISION_REQUESTED) 시 고객에게 이메일 발송. 이메일 설정이 되어 있을 때만.
    메시지함과 동일한 요약 본문 사용. 금액/총액 미포함.
    """
    from survey.models import SurveySubmission
    if not submission or submission.status != SurveySubmission.Status.REVISION_REQUESTED:
        return False
    email = (getattr(submission, 'email', None) or '').strip()
    if not email and getattr(submission, 'user', None) and getattr(submission.user, 'email', None):
        email = (submission.user.email or '').strip()
    if not email:
        logger.debug("Revision requested customer email skipped: no email for submission_id=%s", getattr(submission, 'id'))
        return False
    if not _is_email_configured():
        logger.debug("Revision requested customer email skipped: email not configured.")
        return False
    subject = _get_display_text('설문 수정 요청', language_code)
    body = _build_revision_requested_body(language_code, section_titles=section_titles, revision_message=revision_message)
    try:
        send_mail(
            subject,
            body,
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            [email],
            fail_silently=True,
        )
        return True
    except Exception as e:
        logger.warning("Revision requested customer email failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
        return False


def send_survey_reopened_customer_message(submission, language_code='ko', request=None):
    """
    Admin이 설문 재개를 승인한 뒤 고객 메시지함에 안내.
    메시지 예시: 관리자 승인 안내 + 아래 링크로 이전 설문 수정 + 재제출 후 새 견적 안내 + resume 링크.
    """
    from survey.models import SurveySubmission
    if not submission or submission.status != SurveySubmission.Status.REVISION_REQUESTED:
        return False
    customer = getattr(submission, 'user', None)
    if not customer or not getattr(customer, 'is_authenticated', True):
        logger.debug("Survey reopened customer message skipped: no linked user.")
        return False
    sender = _get_system_sender()
    if not sender:
        logger.warning("Survey reopened customer message skipped: no system sender.")
        return False
    try:
        from django.urls import reverse
        from messaging.models import Message
        # resume=1: 설문 수정 재개 진입점; 로그인 필요 시 로그인 페이지로 보낸 뒤 이 URL로 복귀
        survey_resume_path = reverse('survey:survey_start') + '?resume=1'
        if request:
            survey_url = request.build_absolute_uri(survey_resume_path)
        else:
            site = (getattr(settings, 'SITE_URL', None) or '').rstrip('/')
            survey_url = (site + survey_resume_path) if site else survey_resume_path
        subject = _get_display_text('설문 수정 승인', language_code)
        line1 = _get_display_text('관리자가 수정 요청을 승인했습니다.', language_code)
        line2 = _get_display_text('아래 링크를 통해 이전에 제출한 설문을 수정해 주세요.', language_code)
        line3 = _get_display_text('설문 재제출 후 새 견적을 보내드리겠습니다.', language_code)
        link_label = _get_display_text('설문 수정하기', language_code)
        body = line1 + '\n\n' + line2 + '\n\n' + line3 + '\n\n' + link_label + '\n' + survey_url
        conv = _get_or_create_shared_conversation(submission, subject_fallback=subject)
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Survey reopened customer message failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
        return False


def send_revision_requested_customer_message(submission, language_code='ko', section_titles=None, revision_message=None):
    """
    수정 요청(REVISION_REQUESTED) 시 고객 메시지함에 안내. 로그인한 고객만 대상.
    설문 화면에서 다시 수정할 수 있다는 안내 + (선택) 수정 요청 카드명·메시지.
    공유 대화(submission 연결) 생성/재사용 후 메시지 추가.
    """
    from survey.models import SurveySubmission
    if not submission or submission.status != SurveySubmission.Status.REVISION_REQUESTED:
        return False
    customer = getattr(submission, 'user', None)
    if not customer or not getattr(customer, 'is_authenticated', True):
        logger.debug("Revision requested customer message skipped: no linked user.")
        return False
    sender = _get_system_sender()
    if not sender:
        logger.warning("Revision requested customer message skipped: no system sender.")
        return False
    try:
        from messaging.models import Message
        subject = _get_display_text('설문 수정 요청', language_code)
        body = _build_revision_requested_body(language_code, section_titles=section_titles, revision_message=revision_message)
        # Reuse shared conversation so customer and admin see the same thread
        conv = _get_or_create_shared_conversation(submission, subject_fallback=subject)
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Revision requested customer message failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
        return False


def send_survey_submitted_admin_message(submission, language_code='ko'):
    """
    설문 제출(SUBMITTED) 시 Admin 메시지함 알림.
    고객 가독성을 위해 공유 대화에는 메시지를 추가하지 않음(고객은 '설문 제출됨' 안내 메시지만 보게 함).
    Admin은 이메일(send_survey_submitted_admin_notification)으로 상세 안내를 받음.
    """
    if not submission or submission.status != 'SUBMITTED':
        return False
    # 공유 대화가 있으면 제목만 [이름] 정착 서비스로 맞춤(이미 customer_message에서 생성된 경우)
    try:
        from messaging.models import Conversation
        conv = Conversation.objects.filter(survey_submission=submission).first()
        if conv:
            base_subject = _get_display_text('정착 서비스', language_code)
            customer_name = _customer_name_for_conversation(submission)
            new_subject = f'[{customer_name}] {base_subject}'
            if conv.subject != new_subject:
                conv.subject = new_subject
                conv.save(update_fields=['subject'])
        return True
    except Exception as e:
        logger.warning("Survey submitted admin message (subject sync) failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
        return False


def send_quote_sent_customer_notification(quote, language_code='ko'):
    """
    견적 수정/송부(FINAL_SENT) → 고객 알림. 이 시점부터 가격 포함 가능.
    실제 발송은 quote_email.send_quote_to_customer 사용. 여기서는 규칙만 문서화.
    """
    if not message_may_include_price(quote):
        return False
    from .quote_email import send_quote_to_customer
    return send_quote_to_customer(quote, language_code)


def send_quote_sent_customer_message(quote, language_code='ko'):
    """
    견적 송부(FINAL_SENT) 시 고객 메시지함에 안내 메시지 추가.
    로그인한 고객(submission.user)만 대상. 견적서를 보냈다는 안내 + 추가 필요 시 Admin에게 메시지 보내라는 안내.
    (결제 링크 포함 메시지는 send_quote_release_message 사용.)
    """
    if not quote or not quote.submission_id:
        return False
    if not message_may_include_price(quote):
        return False
    customer = getattr(quote.submission, 'user', None)
    if not customer or not getattr(customer, 'is_authenticated', True):
        logger.debug("Quote sent customer message skipped: no linked user.")
        return False
    sender = _get_system_sender()
    if not sender:
        logger.warning("Quote sent customer message skipped: no system sender.")
        return False
    try:
        from messaging.models import Message
        subject = _get_display_text('견적서를 보냈습니다', language_code)
        body = _get_display_text('견적서를 보냈습니다. 내 견적 페이지에서 확인해 주세요.', language_code)
        body += '\n\n' + _get_display_text('추가로 필요한 사항이 있으면 Admin에게 메시지를 보내 주세요.', language_code)
        submission = quote.submission
        conv = _get_or_create_shared_conversation(submission, subject_fallback=subject)
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Quote sent customer message failed: quote_id=%s error=%s", getattr(quote, 'id'), e, exc_info=True)
        return False


def send_schedule_sent_to_customer(submission, language_code='ko'):
    """
    Admin이 일정 확정·송부 시 고객에게 앱 메시지 + 이메일 발송.
    submission에 연결된 공유 대화에 메시지 추가, 고객 이메일로 요약 발송(설정 시).
    """
    if not submission:
        return False
    customer = getattr(submission, 'user', None)
    if not customer or not getattr(customer, 'is_authenticated', True):
        logger.debug("Schedule sent customer notification skipped: no linked user.")
        return False
    sender = _get_system_sender()
    if not sender:
        logger.warning("Schedule sent customer notification skipped: no system sender.")
        return False
    subject = _get_display_text('일정이 확정되었습니다', language_code)
    body_msg = '📅 ' + _get_display_text('정착 서비스 일정이 확정되어 전달되었습니다.', language_code)
    body_msg += '\n\n' + _get_display_text('대시보드 > 내 정착 일정에서 확인하실 수 있습니다.', language_code)
    try:
        from messaging.models import Message
        conv = _get_or_create_shared_conversation(submission, subject_fallback=subject)
        msg = Message(conversation=conv, sender=sender, body=body_msg)
        msg.save()
    except Exception as e:
        logger.warning("Schedule sent customer message failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
    email = (getattr(customer, 'email', None) or getattr(submission, 'email', None) or '').strip()
    if email and _is_email_configured():
        try:
            send_mail(
                subject,
                body_msg,
                getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                [email],
                fail_silently=True,
            )
        except Exception as e:
            logger.warning("Schedule sent customer email failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
    return True


def send_quote_release_message(quote, language_code='ko'):
    """
    견적 송부(FINAL_SENT) 시 공유 대화에 메시지 추가: 견적 송부 안내 + 짧은 요약 + 결제 링크.
    고객·Admin 모두 대화에서 확인 가능. message_may_include_price(quote) True일 때만.
    """
    if not quote or not quote.submission_id:
        return False
    if not message_may_include_price(quote):
        return False
    from .quote_email import build_quote_release_payload
    payload = build_quote_release_payload(quote)
    if not payload:
        return False
    sender = _get_system_sender()
    if not sender:
        logger.warning("Quote release message skipped: no system sender.")
        return False
    try:
        from messaging.models import Message
        lang = payload.get('lang_preferred') or language_code
        subject = _get_display_text('견적서를 보냈습니다', lang)
        # UCD copy: 핵심 안내만 간결히. 링크는 메시지 본문에 노출하지 않고 UI 버튼으로 제공.
        body = _get_display_text('요청하신 정착 서비스 견적이 도착했습니다.', lang)

        item_labels = []
        for item in (getattr(quote, 'items', None) or []):
            if not isinstance(item, dict):
                continue
            label = (item.get('label') or item.get('name') or item.get('code') or '').strip()
            if label and label not in item_labels:
                item_labels.append(label)
        item_preview = ''
        if item_labels:
            preview_labels = item_labels[:4]
            item_preview = ', '.join(preview_labels)
            if len(item_labels) > len(preview_labels):
                item_preview += ' +' + str(len(item_labels) - len(preview_labels))

        body += '\n\n'
        if item_preview:
            body += (_get_display_text('항목', lang) or '항목') + ': ' + item_preview
            body += '\n'
        body += (_get_display_text('항목 수', lang) or '항목 수') + ': ' + str(payload.get('item_count', 0))
        body += '  |  ' + (_get_display_text('합계', lang) or '합계') + ': $' + f"{payload.get('total_display', 0):,.2f}" + ' USD'
        body += '\n\n' + _get_display_text('추가 요청이 있으면 메시지로 남겨 주세요.', lang)
        submission = quote.submission
        conv = _get_or_create_shared_conversation(submission, subject_fallback=subject)
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Quote release message failed: quote_id=%s error=%s", getattr(quote, 'id'), e, exc_info=True)
        return False


def send_payment_complete_customer_message(quote, language_code='ko'):
    """
    결제 완료(PAID) → 고객 앱 메시지. submission 공유 대화에 추가.
    "결제가 완료되었습니다. Admin이 확인 후 일정을 보내드립니다."
    """
    if not quote or quote.status != 'PAID' or not quote.submission_id:
        return False
    if not message_may_include_price(quote):
        return False
    sender = _get_system_sender()
    if not sender:
        return False
    try:
        from messaging.models import Message
        subject = _get_display_text('결제가 완료되었습니다', language_code)
        body = _get_display_text('결제가 완료되었습니다. Admin이 확인 후 일정을 보내드립니다.', language_code)
        body += '\n\n' + (_get_display_text('내 견적/정착 플랜에서 일정을 확인하실 수 있습니다.', language_code) or '내 견적/정착 플랜에서 일정을 확인하실 수 있습니다.')
        submission = quote.submission
        conv = _get_or_create_shared_conversation(submission, subject_fallback=subject)
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Payment complete customer message failed: quote_id=%s error=%s", quote.id, e, exc_info=True)
        return False


def send_payment_complete_admin_message(quote, language_code='ko'):
    """
    결제 완료(PAID) → Admin 앱 메시지. submission 공유 대화에 추가.
    "고객이 결제를 완료했습니다. 서비스 일정을 생성·확정해 주세요."
    """
    if not quote or quote.status != 'PAID' or not quote.submission_id:
        return False
    if not message_may_include_price(quote):
        return False
    sender = _get_system_sender()
    if not sender:
        return False
    try:
        from messaging.models import Message
        submission = quote.submission
        customer_name = (getattr(submission, 'user', None) and submission.user and (submission.user.get_full_name() or submission.user.username or submission.email)) or (submission.email or '-')
        subject = _get_display_text('고객 결제 완료', language_code)
        body = _get_display_text('고객이 결제를 완료했습니다. 서비스 일정을 생성·확정해 주세요.', language_code)
        body += '\n\n' + (_get_display_text('고객', language_code) or '고객') + ': ' + str(customer_name)
        body += '\n' + (_get_display_text('합계', language_code) or '합계') + ': $' + f"{int(quote.total or 0):,}" + ' USD'
        conv = _get_or_create_shared_conversation(submission, subject_fallback=subject)
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Payment complete admin message failed: quote_id=%s error=%s", quote.id, e, exc_info=True)
        return False


def send_payment_complete_customer_email(quote, language_code='ko'):
    """결제 완료(PAID) → 고객 이메일. 설정 시에만 발송. 일정 안내 문구 포함."""
    if not quote or quote.status != 'PAID' or not quote.submission_id:
        return False
    if not message_may_include_price(quote):
        return False
    customer_email = (quote.submission.email or '').strip()
    if not customer_email or not _is_email_configured():
        return False
    subject = _get_display_text('결제가 완료되었습니다', language_code)
    lines = [
        _get_display_text('안녕하세요. 견적 결제가 완료되었습니다.', language_code),
        '',
        _get_display_text('결제가 완료되었습니다. Admin이 확인 후 일정을 보내드립니다.', language_code),
        '',
        (_get_display_text('합계', language_code) or '합계') + ': $' + f"{int(quote.total or 0):,}" + ' USD',
        '',
        _get_display_text('내 견적/정착 플랜에서 일정을 확인하실 수 있습니다.', language_code),
    ]
    try:
        send_mail(
            subject,
            '\n'.join(lines),
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            [customer_email],
            fail_silently=True,
        )
        return True
    except Exception as e:
        logger.warning("Payment complete customer email failed: quote_id=%s error=%s", quote.id, e, exc_info=True)
        return False


def send_payment_complete_admin_email(quote, language_code='ko'):
    """결제 완료(PAID) → Admin 이메일. 고객 결제 완료 안내 및 일정 생성 요청."""
    if not quote or quote.status != 'PAID' or not quote.submission_id:
        return False
    if not message_may_include_price(quote):
        return False
    emails = _get_admin_emails()
    if not emails or not _is_email_configured():
        return False
    submission = quote.submission
    customer_name = (getattr(submission, 'user', None) and submission.user and (submission.user.get_full_name() or submission.user.username or submission.email)) or (submission.email or '-')
    subject = _get_display_text('고객 결제 완료 알림', language_code)
    lines = [
        _get_display_text('고객이 결제를 완료했습니다. 서비스 일정을 생성·확정해 주세요.', language_code),
        '',
        (_get_display_text('고객', language_code) or '고객') + ': ' + str(customer_name),
        (_get_display_text('합계', language_code) or '합계') + ': $' + f"{int(quote.total or 0):,}" + ' USD',
        '',
        _get_display_text('Admin 검토 페이지에서 해당 제출 건의 일정을 확인·확정할 수 있습니다.', language_code),
    ]
    try:
        send_mail(
            subject,
            '\n'.join(lines),
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            emails,
            fail_silently=True,
        )
        return True
    except Exception as e:
        logger.warning("Payment complete admin email failed: quote_id=%s error=%s", quote.id, e, exc_info=True)
        return False


def send_payment_complete_notifications(quote, plan, language_code='ko'):
    """
    결제 완료(PAID) → 고객·Admin·Agent 알림 자동화.
    - 고객: 앱 메시지(공유 대화) + 이메일(설정 시). "결제 완료, Admin이 일정 보내드림"
    - Admin: 앱 메시지(공유 대화) + 이메일(설정 시). "고객 결제 완료, 일정 생성·확정 요청"
    - Agent: 이메일(배정된 전담 Agent, 설정 시). 기존 동일.
    모두 submission 공유 대화 재사용. language_code는 고객 기준(선호어) 권장.
    """
    if not quote or quote.status != 'PAID':
        return False
    if not message_may_include_price(quote):
        return False
    sent = False
    send_payment_complete_customer_message(quote, language_code=language_code)
    send_payment_complete_admin_message(quote, language_code=language_code)
    if send_payment_complete_customer_email(quote, language_code=language_code):
        sent = True
    if send_payment_complete_admin_email(quote, language_code=language_code):
        sent = True
    # Agent 알림 (배정된 전담 Agent에게 이메일)
    agent = getattr(plan, 'assigned_agent', None) if plan else None
    if agent and getattr(agent, 'email', None) and (agent.email or '').strip() and _is_email_configured():
        agent_email = (agent.email or '').strip()
        sub = quote.submission
        customer_name = (getattr(sub, 'user', None) and sub.user and (sub.user.get_full_name() or sub.user.username or sub.email)) or (sub.email or '')
        subject = _get_display_text('고객 결제 완료 알림', language_code)
        lines = [
            _get_display_text('배정된 고객이 견적 결제를 완료했습니다.', language_code),
            '',
            (_get_display_text('고객', language_code) or '고객') + ': ' + str(customer_name),
            (_get_display_text('합계', language_code) or '합계') + ': $' + f"{int(quote.total or 0):,}" + ' USD',
            '',
            _get_display_text('고객 예약 달력에서 일정을 확인해 주세요.', language_code),
        ]
        try:
            send_mail(
                subject,
                '\n'.join(lines),
                getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                [agent_email],
                fail_silently=True,
            )
            sent = True
        except Exception as e:
            logger.warning("Payment complete agent email failed: quote_id=%s agent_id=%s error=%s", quote.id, getattr(agent, 'id'), e, exc_info=True)
    return sent


def send_quote_arrived_admin_notification(quote, language_code='ko'):
    """
    견적서(초안) 도착 시 Admin 이메일 알림.
    """
    if not quote or not quote.submission_id:
        return False
    emails = _get_admin_emails()
    if not emails or not _is_email_configured():
        logger.debug("Quote arrived admin notification skipped: no admin emails or email not configured.")
        return False
    sub = quote.submission
    customer_name = (getattr(sub, 'user', None) and sub.user.get_full_name()) or getattr(sub, 'email', '-') or '-'
    subject = _get_display_text('견적서가 도착했습니다', language_code)
    body_lines = [
        _get_display_text('새 견적서(초안)가 생성되었습니다. 검토해 주세요.', language_code),
        '',
        _get_display_text('고객', language_code) + ': ' + (sub.email or '-'),
        _get_display_text('제출 ID', language_code) + ': ' + str(sub.id),
        '',
        _get_display_text('Admin 검토 페이지에서 확인해 주세요.', language_code),
    ]
    body = '\n'.join(body_lines)
    try:
        send_mail(
            subject,
            body,
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            emails,
            fail_silently=True,
        )
        return True
    except Exception as e:
        logger.warning("Quote arrived admin notification failed: quote_id=%s error=%s", getattr(quote, 'id'), e, exc_info=True)
        return False


def send_quote_arrived_admin_message(quote, language_code='ko'):
    """
    견적서(초안) 도착 시 Admin 메시지함 알림.
    """
    if not quote or not quote.submission_id:
        return False
    admin_users = _get_admin_users()
    if not admin_users:
        logger.debug("Quote arrived admin message skipped: no staff users.")
        return False
    sender = _get_system_sender()
    if not sender:
        logger.warning("Quote arrived admin message skipped: no system sender.")
        return False
    try:
        from messaging.models import Message
        sub = quote.submission
        customer_name = (getattr(sub, 'user', None) and sub.user.get_full_name()) or (sub.email or '-')
        subject_suffix = _get_display_text('견적서 도착', language_code)
        subject = f'[{customer_name}] {subject_suffix}'
        body = _get_display_text('새 견적서(초안)가 생성되었습니다. Admin 검토 페이지에서 확인해 주세요.', language_code)
        body += '\n' + _get_display_text('고객', language_code) + ': ' + (sub.email or '-')
        conv = _get_or_create_shared_conversation(sub, subject_fallback=subject)
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Quote arrived admin message failed: quote_id=%s error=%s", getattr(quote, 'id'), e, exc_info=True)
        return False


def send_agent_assigned_notification(plan, agent, customer, language_code='ko'):
    """
    Agent 배정 시 해당 Agent 알림. 금액/총액/checkout 포함 금지.
    """
    if not plan or not agent or not getattr(agent, 'email', None):
        return False
    email = (agent.email or '').strip()
    if not email or not _is_email_configured():
        return False
    subject = _get_display_text('전담 Agent로 배정되었습니다', language_code)
    customer_display = (customer.get_full_name() or customer.username or getattr(customer, 'email', '')) if customer else '-'
    body_lines = [
        _get_display_text('고객이 당신을 전담 Agent로 배정했습니다.', language_code),
        '',
        _get_display_text('고객', language_code) + ': ' + str(customer_display),
        _get_display_text('지역', language_code) + ': ' + (plan.state or '') + (' ' + (plan.city or '') if getattr(plan, 'city', None) else ''),
        '',
        _get_display_text('고객 예약 달력에서 일정을 확인해 주세요.', language_code),
    ]
    body = '\n'.join(body_lines)
    try:
        send_mail(
            subject,
            body,
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            [email],
            fail_silently=True,
        )
        return True
    except Exception as e:
        logger.warning("Agent assigned notification failed: plan user=%s agent_id=%s error=%s", getattr(plan, 'user_id'), getattr(agent, 'id'), e, exc_info=True)
        return False
