# 약속 신청 생성 시 대화 자동 생성, 로그인 시 새 메시지 팝업 플래그
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in
from django.utils import translation

from settlement.models import AgentAppointmentRequest
from .models import Conversation, ConversationParticipant, Message, MessageRead
from translations.utils import get_valid_language_codes


@receiver(user_logged_in)
def set_show_new_message_popup_on_login(sender, request, user, **kwargs):
    """로그인 성공 시 세션에 플래그 설정 + DB 선호 언어를 읽어 세션·요청에 적용."""
    if not request:
        return
    request.session.pop('popup_dismissed', None)  # 로그인 시 초기화하여 미읽음 있으면 팝업 표시
    request.session['show_new_message_popup'] = True
    # DB에서 선호 언어를 읽어서 세팅 (최신 값 보장)
    try:
        user.refresh_from_db(fields=['preferred_language'])
    except Exception:
        pass
    lang = (getattr(user, 'preferred_language', None) or '').strip()
    request.session.pop('language_explicitly_set', None)  # 로그인 시 DB 선호어가 적용되도록
    valid = get_valid_language_codes()
    if not lang or lang not in valid:
        lang = 'en'
    request.session['django_language'] = lang
    request.session.modified = True
    try:
        request.session.save()
    except Exception:
        pass
    translation.activate(lang)
    if hasattr(request, 'LANGUAGE_CODE'):
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
        workspace_type=Conversation.WorkspaceType.APPOINTMENT,
        appointment=instance,
    )
    ConversationParticipant.objects.create(conversation=conv, user=instance.agent)
    if instance.customer_id:
        ConversationParticipant.objects.create(conversation=conv, user=instance.customer)

    from .views import _detect_and_translate_to_en

    def _create_first_message(sender, body):
        msg = Message(conversation=conv, sender=sender, body=body)
        try:
            msg.detected_lang, msg.body_en = _detect_and_translate_to_en(body)
        except Exception:
            pass
        msg.save()
        return msg

    # 로그인한 고객이 보낸 예약 요청: 첫 메시지를 만들고 에이전트에게만 미읽음으로 표시
    if instance.customer_id:
        first_body = (
            f'[약속 신청 메시지]\n{instance.message.strip()}'
            if instance.message and instance.message.strip()
            else '[예약 요청] 새로운 예약 요청이 접수되었습니다.'
        )
        msg = _create_first_message(instance.customer, first_body)
        MessageRead.objects.get_or_create(message=msg, user=instance.customer)
        # 에이전트는 읽음 처리하지 않음 → 배지 +1
    elif instance.message and instance.message.strip():
        # 비로그인(게스트) 요청 + 메시지 있음: 에이전트가 발신자로 넣고 본인 읽음 처리 (기존 동작 유지)
        first_body = f'[약속 신청 메시지]\n{instance.message.strip()}'
        msg = _create_first_message(instance.agent, first_body)
        MessageRead.objects.get_or_create(message=msg, user=instance.agent)
