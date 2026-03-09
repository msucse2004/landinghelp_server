"""
when2meet 스타일 Agent 가용 시간 수집.
대면(IN_PERSON_AGENT) 서비스 항목이 있는 경우 해당 Agent에게 가용 창 입력 링크를 보냄.
"""
import logging
from urllib.parse import urlencode

from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)

# 토큰 유효 기간 (초): 7일
AVAILABILITY_TOKEN_MAX_AGE = 7 * 24 * 3600


def _get_signer():
    return TimestampSigner(key=settings.SECRET_KEY)


def build_availability_token(plan_id, agent_id):
    """plan_id + agent_id 서명. URL 안전하게 전달."""
    signer = _get_signer()
    return signer.sign(f"{plan_id}:{agent_id}")


def verify_availability_token(token):
    """토큰 검증. 성공 시 (plan_id: int, agent_id: int), 실패 시 None."""
    signer = _get_signer()
    try:
        value = signer.unsign(token, max_age=AVAILABILITY_TOKEN_MAX_AGE)
        parts = value.split(":", 1)
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except (SignatureExpired, BadSignature):
        pass
    return None


def build_availability_link(plan_id, agent_id, request=None):
    """Agent 가용 입력 페이지 URL (서명된 token 포함)."""
    token = build_availability_token(plan_id, agent_id)
    path = reverse('agent_availability_input', kwargs={'plan_id': plan_id})
    url = path + '?' + urlencode({'token': token})
    if request and getattr(settings, 'SITE_URL', None):
        base = (settings.SITE_URL or '').strip().rstrip('/')
        if base:
            return base + url
    return url


def get_agents_needing_availability(schedule_plan):
    """
    플랜에서 대면 Agent 서비스로 배정된 Agent ID 목록 (중복 제거).
    """
    if not schedule_plan:
        return []
    from .models import ServiceScheduleItem
    agent_ids = list(
        schedule_plan.items.filter(
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            assigned_agent_id__isnull=False,
        )
        .values_list('assigned_agent_id', flat=True)
        .distinct()
    )
    return agent_ids


def send_availability_request_to_agent(schedule_plan, agent, language_code='ko'):
    """
    해당 Agent에게 가용 시간 입력 요청: 공유 대화에 메시지 + 이메일(설정 시).
    submission 연결 대화에 agent를 참여자로 추가하고, 메시지 본문에 입력 링크 포함.
    """
    from messaging.models import Conversation, ConversationParticipant, Message
    from .notifications import _get_or_create_shared_conversation, _get_display_text, _get_system_sender, _is_email_configured
    from django.utils import timezone

    if not schedule_plan or not agent:
        return False
    submission = getattr(schedule_plan, 'submission', None)
    if not submission:
        return False
    subject = _get_display_text('가용 시간 입력 요청', language_code)
    link = build_availability_link(schedule_plan.id, agent.id)
    body_lines = [
        _get_display_text('고객 일정 편집을 위해 가용 시간을 알려주세요.', language_code),
        '',
        _get_display_text('아래 링크에서 가능한 시간대를 선택해 제출해 주세요.', language_code),
        link,
        '',
        _get_display_text('여러 번 수정하여 제출할 수 있으며, 일정 확정 전까지 반영됩니다.', language_code),
    ]
    body = '\n'.join(body_lines)
    conv = _get_or_create_shared_conversation(submission, subject_fallback=subject)
    ConversationParticipant.objects.get_or_create(conversation=conv, user=agent)
    sender = _get_system_sender()
    if not sender:
        logger.warning("No system sender for availability request")
        return False
    try:
        msg = Message(conversation=conv, sender=sender, body=body)
        msg.save()
    except Exception as e:
        logger.warning("Availability request message failed: plan=%s agent=%s error=%s", schedule_plan.id, agent.id, e, exc_info=True)
        return False
    if _is_email_configured() and getattr(agent, 'email', None) and (agent.email or '').strip():
        try:
            from django.core.mail import send_mail
            send_mail(
                subject,
                body,
                getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                [agent.email.strip()],
                fail_silently=True,
            )
        except Exception as e:
            logger.warning("Availability request email failed: agent=%s error=%s", agent.id, e, exc_info=True)
    return True
