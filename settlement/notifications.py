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


def send_survey_submitted_customer_email(submission, language_code='ko'):
    """
    설문 제출(SUBMITTED) 시 고객에게 확인 이메일 발송. 금액 미포함.
    """
    if not submission or submission.status != 'SUBMITTED':
        return False
    email = (getattr(submission, 'email', None) or '').strip()
    if not email or not _is_email_configured():
        logger.debug("Survey submitted customer email skipped: no email or email not configured.")
        return False
    subject = _get_display_text('설문이 제출되었습니다', language_code)
    body_lines = [
        _get_display_text('안녕하세요. 정착 서비스 설문이 정상적으로 제출되었습니다.', language_code),
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


def send_survey_submitted_customer_message(submission, language_code='ko'):
    """
    설문 제출(SUBMITTED) 시 고객 메시지함에 확인 메시지 추가. 로그인한 고객(submission.user)만 대상.
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
        from messaging.models import Conversation, ConversationParticipant, Message
        subject = _get_display_text('설문 제출 확인', language_code)
        body = '✨ ' + _get_display_text('정착 서비스 설문이 제출되었습니다. 😊 Admin 검토 후 견적을 보내드리겠습니다.', language_code)
        body += '\n\n💬 ' + _get_display_text('필요한 사항이 있으시면 메시지로 보내 주세요.', language_code)
        conv = Conversation.objects.create(type=Conversation.Type.NOTICE, subject=subject)
        ConversationParticipant.objects.create(conversation=conv, user=customer)
        msg = Message(conversation=conv, sender=system_sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Survey submitted customer message failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
        return False


def send_revision_requested_customer_message(submission, language_code='ko', section_titles=None, revision_message=None):
    """
    수정 요청(REVISION_REQUESTED) 시 고객 메시지함에 안내. 로그인한 고객만 대상.
    설문 화면에서 다시 수정할 수 있다는 안내 + (선택) 수정 요청 카드명·메시지.
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
        from messaging.models import Conversation, ConversationParticipant, Message
        subject = _get_display_text('설문 수정 요청', language_code)
        body = _get_display_text('설문 수정이 요청되었습니다.', language_code)
        body += '\n\n' + _get_display_text('정착 서비스 > 정착 설문 화면에서 다시 접속하여 요청된 내용을 수정해 주세요.', language_code)
        if section_titles:
            body += '\n\n' + _get_display_text('수정 요청된 카드', language_code) + ': ' + ', '.join(section_titles)
        extra = (revision_message or '').strip()
        if extra:
            body += '\n\n' + extra
        conv = Conversation.objects.create(type=Conversation.Type.NOTICE, subject=subject)
        ConversationParticipant.objects.create(conversation=conv, user=customer)
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Revision requested customer message failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
        return False


def send_survey_submitted_admin_message(submission, language_code='ko'):
    """
    설문 제출(SUBMITTED) 시 Admin 메시지함에 알림 메시지 추가.
    """
    if not submission or submission.status != 'SUBMITTED':
        return False
    admin_users = _get_admin_users()
    if not admin_users:
        logger.debug("Survey submitted admin message skipped: no staff users.")
        return False
    sender = getattr(submission, 'user', None) if getattr(submission, 'user_id', None) else None
    if not sender or not sender.is_authenticated:
        sender = _get_system_sender()
    if not sender:
        logger.warning("Survey submitted admin message skipped: no sender.")
        return False
    try:
        from messaging.models import Conversation, ConversationParticipant, Message
        customer = getattr(submission, 'user', None)
        if customer and getattr(customer, 'is_authenticated', True):
            customer_name = (customer.get_full_name() or getattr(customer, 'username', '') or getattr(customer, 'email', '') or '').strip() or (getattr(submission, 'email', None) or '-')
        else:
            customer_name = (getattr(submission, 'email', None) or '-').strip() or '-'
        subject_suffix = _get_display_text('새 설문 제출 알림', language_code)
        subject = f'[{customer_name}] {subject_suffix}'
        email = getattr(submission, 'email', None) or '-'
        submitted_at = str(getattr(submission, 'submitted_at', None) or '-')
        body = _get_display_text('고객이 정착 서비스 설문을 제출했습니다.', language_code)
        body += '\n' + _get_display_text('이메일', language_code) + ': ' + email
        body += '\n' + _get_display_text('제출 시각', language_code) + ': ' + submitted_at
        conv = Conversation.objects.create(
            type=Conversation.Type.NOTICE,
            subject=subject,
            survey_submission=submission,
        )
        for admin in admin_users:
            ConversationParticipant.objects.get_or_create(conversation=conv, user=admin)
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Survey submitted admin message failed: submission_id=%s error=%s", getattr(submission, 'id'), e, exc_info=True)
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
        from messaging.models import Conversation, ConversationParticipant, Message
        subject = _get_display_text('견적서를 보냈습니다', language_code)
        body = _get_display_text('견적서를 보냈습니다. 내 견적 페이지에서 확인해 주세요.', language_code)
        body += '\n\n' + _get_display_text('추가로 필요한 사항이 있으면 Admin에게 메시지를 보내 주세요.', language_code)
        conv = Conversation.objects.create(type=Conversation.Type.NOTICE, subject=subject)
        ConversationParticipant.objects.create(conversation=conv, user=customer)
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
        return True
    except Exception as e:
        logger.warning("Quote sent customer message failed: quote_id=%s error=%s", getattr(quote, 'id'), e, exc_info=True)
        return False


def send_payment_complete_notifications(quote, plan, language_code='ko'):
    """
    결제 완료(PAID) → 고객·Agent 알림. 가격 포함 가능(PAID).
    """
    if not quote or quote.status != 'PAID':
        return False
    if not message_may_include_price(quote):
        return False
    sent = False
    # 고객 알림 (이메일)
    customer_email = (quote.submission.email or '').strip() if quote.submission_id else ''
    if customer_email and _is_email_configured():
        subject = _get_display_text('결제가 완료되었습니다', language_code)
        lines = [
            _get_display_text('안녕하세요. 견적 결제가 완료되었습니다.', language_code),
            '',
            _get_display_text('합계', language_code) + ': ' + str(int(quote.total or 0)) + ' ' + _get_display_text('원', language_code),
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
            sent = True
        except Exception as e:
            logger.warning("Payment complete customer notification failed: quote_id=%s error=%s", quote.id, e, exc_info=True)
    # Agent 알림 (배정된 전담 Agent에게)
    agent = getattr(plan, 'assigned_agent', None) if plan else None
    if agent and getattr(agent, 'email', None) and (agent.email or '').strip() and _is_email_configured():
        agent_email = (agent.email or '').strip()
        subject = _get_display_text('고객 결제 완료 알림', language_code)
        sub = quote.submission
        customer_name = '-'
        if sub:
            if getattr(sub, 'user', None):
                customer_name = (sub.user.get_full_name() or sub.user.username or sub.email or '')
            else:
                customer_name = (sub.email or '')
        lines = [
            _get_display_text('배정된 고객이 견적 결제를 완료했습니다.', language_code),
            '',
            _get_display_text('고객', language_code) + ': ' + str(customer_name),
            _get_display_text('합계', language_code) + ': ' + str(int(quote.total or 0)) + ' ' + _get_display_text('원', language_code),
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
            logger.warning("Payment complete agent notification failed: quote_id=%s agent_id=%s error=%s", quote.id, getattr(agent, 'id'), e, exc_info=True)
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
        from messaging.models import Conversation, ConversationParticipant, Message
        sub = quote.submission
        customer_name = (getattr(sub, 'user', None) and sub.user.get_full_name()) or (sub.email or '-')
        subject_suffix = _get_display_text('견적서 도착', language_code)
        subject = f'[{customer_name}] {subject_suffix}'
        body = _get_display_text('새 견적서(초안)가 생성되었습니다. Admin 검토 페이지에서 확인해 주세요.', language_code)
        body += '\n' + _get_display_text('고객', language_code) + ': ' + (sub.email or '-')
        conv = Conversation.objects.create(
            type=Conversation.Type.NOTICE,
            subject=subject,
            survey_submission=sub,
        )
        for admin in admin_users:
            ConversationParticipant.objects.get_or_create(conversation=conv, user=admin)
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
