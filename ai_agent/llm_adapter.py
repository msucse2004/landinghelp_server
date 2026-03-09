"""
LLM adapter interface. Production can swap in a real LLM (OpenAI, Ollama, etc.).
Web search can be added later as a separate tool adapter, not here.
"""
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def generate(
    system_prompt: str,
    user_prompt: str,
    *,
    language: str = 'ko',
    max_tokens: int = 800,
) -> Tuple[str, bool]:
    """
    Generate assistant response. Returns (response_text, uncertainty_flagged).
    Implementations should set uncertainty_flagged=True when the model expresses uncertainty
    or when a fallback/stub is used.
    """
    impl = get_adapter()
    return impl.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        language=language,
        max_tokens=max_tokens,
    )


def get_adapter():
    """Return the configured adapter. Default: stub when no production LLM is configured."""
    from django.conf import settings
    adapter = getattr(settings, 'AI_AGENT_LLM_ADAPTER', None)
    if adapter and adapter != 'stub':
        try:
            # Optional: load from dotted path, e.g. 'ai_agent.llm_ollama.Adapter'
            if isinstance(adapter, str) and '.' in adapter:
                from django.utils.module_loading import import_string
                return import_string(adapter)()
            return adapter
        except Exception as e:
            logger.warning("AI_AGENT_LLM_ADAPTER failed to load: %s", e, exc_info=True)
    return StubAdapter()


class StubAdapter:
    """
    Stub implementation when no production LLM is configured.
    Returns a safe, non-committal message and flags uncertainty.
    """

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        language: str = 'ko',
        max_tokens: int = 800,
    ) -> Tuple[str, bool]:
        del system_prompt, max_tokens  # unused in stub
        if not (user_prompt or '').strip():
            return _stub_message(language, empty=True), True
        # Stub: never promise anything; always suggest messaging support.
        return _stub_message(language, empty=False), True


def _stub_message(language: str, empty: bool) -> str:
    if language and language.startswith('en'):
        if empty:
            return "Please type your question about your relocation or services. I'll do my best to help based on your plan and our guides."
        return (
            "Thanks for your message. The AI assistant is not fully connected yet. "
            "For accurate answers, please use the message inbox to contact our team. "
            "We'll get back to you shortly."
        )
    if empty:
        return "이사·정착 서비스 관련 질문을 입력해 주세요. 플랜과 안내 자료를 바탕으로 도와드리겠습니다."
    return (
        "메시지 감사합니다. 현재 AI 어시스턴트가 완전히 연결되지 않았습니다. "
        "정확한 안내를 원하시면 메시지함에서 팀에게 문의해 주시면 빠르게 답변 드리겠습니다."
    )
