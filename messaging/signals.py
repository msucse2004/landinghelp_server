# 약속 신청 생성 시 대화 자동 생성, 로그인 시 새 메시지 팝업 플래그
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in
from django.utils import translation
from django.conf import settings

from settlement.models import AgentAppointmentRequest
from .models import Conversation, ConversationParticipant, Message, MessageRead

# 선호 언어로 세션/현재 요청 언어 설정 시 허용할 언어 코드
VALID_LANGUAGE_CODES = {code for code, _ in getattr(settings, 'LANGUAGES', [])}


@receiver(user_logged_in)
def set_show_new_message_popup_on_login(sender, request, user, **kwargs):
    """로그인 성공 시 세션에 플래그 설정 + 선호 언어를 세션 및 현재 요청에 적용."""
    if not request:
        return
    request.session['show_new_message_popup'] = True
    lang = getattr(user, 'preferred_language', None) or ''
    lang = (lang or '').strip()
    if lang and lang in VALID_LANGUAGE_CODES:
        request.session['django_language'] = lang
        translation.activate(lang)
        request.LANGUAGE_CODE = lang


@receiver(post_save, sender=AgentAppointmentRequest)
def create_conversation_for_appointment(sender, instance, created, **kwargs):
    """약속 신청이 생성되면 해당 약속용 대화를 만들고, 첫 메시지를 에이전트 미읽음으로 둠."""
    if not created:
        return
    if Conversation.objects.filter(appointment=instance).exists():
        return
    conv = Conversation.objects.create(
        type=Conversation.Type.APPOINTMENT,
        appointment=instance,
    )
    ConversationParticipant.objects.create(conversation=conv, user=instance.agent)
    if instance.customer_id:
        ConversationParticipant.objects.create(conversation=conv, user=instance.customer)

    # 로그인한 고객이 보낸 예약 요청: 첫 메시지를 만들고 에이전트에게만 미읽음으로 표시
    if instance.customer_id:
        first_body = (
            f'[약속 신청 메시지]\n{instance.message.strip()}'
            if instance.message and instance.message.strip()
            else '[예약 요청] 새로운 예약 요청이 접수되었습니다.'
        )
        msg = Message.objects.create(
            conversation=conv,
            sender=instance.customer,
            body=first_body,
        )
        MessageRead.objects.get_or_create(message=msg, user=instance.customer)
        # 에이전트는 읽음 처리하지 않음 → 배지 +1
    elif instance.message and instance.message.strip():
        # 비로그인(게스트) 요청 + 메시지 있음: 에이전트가 발신자로 넣고 본인 읽음 처리 (기존 동작 유지)
        first_body = f'[약속 신청 메시지]\n{instance.message.strip()}'
        msg = Message.objects.create(conversation=conv, sender=instance.agent, body=first_body)
        MessageRead.objects.get_or_create(message=msg, user=instance.agent)
