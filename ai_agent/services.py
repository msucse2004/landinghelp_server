"""
AI assistant service layer: context + prompts + LLM adapter + messaging + logging.
Guardrails: no unsupported promises, identify uncertainty, log interactions.
"""
import logging
from typing import Optional, Tuple

from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


def get_or_create_ai_conversation(user, survey_submission=None):
    """
    Get or create the AI assistant conversation for this user.
    Reuses messaging.Conversation with type=AI_ASSISTANT.
    """
    from messaging.models import Conversation, ConversationParticipant
    conv = (
        Conversation.objects.filter(
            type=Conversation.Type.AI_ASSISTANT,
            participants__user=user,
        )
        .order_by('-updated_at')
        .first()
    )
    if conv:
        return conv
    subject = _assistant_subject()
    conv = Conversation.objects.create(
        type=Conversation.Type.AI_ASSISTANT,
        survey_submission=survey_submission,
        subject=subject,
    )
    ConversationParticipant.objects.create(conversation=conv, user=user)
    return conv


def _assistant_subject():
    try:
        from translations.utils import get_display_text
        return get_display_text('AI 어시스턴트', 'ko') or 'AI 어시스턴트'
    except Exception:
        return 'AI 어시스턴트'


def get_assistant_sender():
    """User to use as sender for assistant messages (e.g. first staff or configured bot)."""
    from django.conf import settings
    user_id = getattr(settings, 'AI_AGENT_BOT_USER_ID', None)
    if user_id:
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            pass
    return User.objects.filter(is_staff=True, is_active=True).order_by('pk').first()


def respond(
    user,
    conversation,
    user_message_text: str,
    *,
    survey_submission=None,
) -> Tuple[str, Optional[object]]:
    """
    Build context, call LLM adapter, persist assistant reply as Message, log interaction.
    Returns (response_text, message_obj). message_obj is None if saving failed.
    """
    if not user or not user.is_authenticated:
        return _safe_fallback(user), None
    text = (user_message_text or '').strip()
    if not text:
        return _safe_fallback(user, empty=True), None

    from .context_builder import build_context
    from .prompts import system_prompt, user_prompt
    from .llm_adapter import generate
    from .models import AssistantInteractionLog

    context = build_context(user)
    sys = system_prompt(context)
    usr = user_prompt(text, context)
    language = (context.get('profile') or {}).get('language') or 'ko'

    try:
        response_text, uncertainty_flagged = generate(
            system_prompt=sys,
            user_prompt=usr,
            language=language,
        )
    except Exception as e:
        logger.warning("LLM generate failed: %s", e, exc_info=True)
        response_text = _safe_fallback(user)
        uncertainty_flagged = True

    response_text = (response_text or '').strip()[:4000]
    if not response_text:
        response_text = _safe_fallback(user)

    bot = get_assistant_sender()
    if not bot:
        logger.warning("No assistant bot user configured; response not saved to conversation.")
        AssistantInteractionLog.objects.create(
            user=user,
            conversation=conversation,
            role='assistant',
            input_text=text[:2000],
            output_text=response_text[:2000],
            model_used='stub',
            uncertainty_flagged=uncertainty_flagged,
        )
        return response_text, None

    from messaging.models import Message
    try:
        msg = Message.objects.create(
            conversation=conversation,
            sender=bot,
            body=response_text,
        )
    except Exception as e:
        logger.warning("Failed to save assistant message: %s", e, exc_info=True)
        msg = None

    AssistantInteractionLog.objects.create(
        user=user,
        conversation=conversation,
        message=msg,
        role='assistant',
        input_text=text[:2000],
        output_text=response_text[:2000],
        model_used=getattr(getattr(respond, '_last_adapter', None), '__class__.__name__', 'stub'),
        uncertainty_flagged=uncertainty_flagged,
    )
    return response_text, msg


def _safe_fallback(user, empty: bool = False) -> str:
    lang = getattr(user, 'preferred_language', None) or 'ko'
    if lang and lang.startswith('en'):
        if empty:
            return "Please type your question."
        return "Something went wrong. Please try the message inbox to contact our team."
    if empty:
        return "질문을 입력해 주세요."
    return "일시적인 오류가 있었습니다. 메시지함으로 문의해 주세요."
