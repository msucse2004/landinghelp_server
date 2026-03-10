"""
LLM adapter interface with fallback chain: Gemini (1순위) → Ollama (2순위) → Stub.
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
    Tries Gemini first, then Ollama, then falls back to Stub.
    """
    adapter = get_adapter()
    return adapter.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        language=language,
        max_tokens=max_tokens,
    )


def get_adapter():
    """Return a ChainAdapter that tries Gemini → Ollama → Stub in order."""
    from django.conf import settings
    explicit = getattr(settings, 'AI_AGENT_LLM_ADAPTER', None)
    if explicit and explicit != 'stub' and explicit != 'chain':
        try:
            if isinstance(explicit, str) and '.' in explicit:
                from django.utils.module_loading import import_string
                return import_string(explicit)()
            return explicit
        except Exception as e:
            logger.warning("AI_AGENT_LLM_ADAPTER failed to load: %s", e, exc_info=True)
    return ChainAdapter()


class ChainAdapter:
    """Gemini(1순위) → Ollama(2순위) → Stub 순서로 시도."""

    def __init__(self):
        self._gemini: Optional[object] = None
        self._ollama: Optional[object] = None

    def _get_gemini(self):
        if self._gemini is not None:
            return self._gemini
        try:
            from django.conf import settings
            if getattr(settings, 'GEMINI_API_KEY', ''):
                from ai_agent.llm_gemini import GeminiAdapter
                self._gemini = GeminiAdapter()
                return self._gemini
        except Exception as e:
            logger.warning("Failed to init Gemini adapter: %s", e)
        return None

    def _get_ollama(self):
        if self._ollama is not None:
            return self._ollama
        try:
            from ai_agent.llm_ollama import OllamaAdapter
            self._ollama = OllamaAdapter()
            return self._ollama
        except Exception as e:
            logger.warning("Failed to init Ollama adapter: %s", e)
        return None

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        language: str = 'ko',
        max_tokens: int = 800,
    ) -> Tuple[str, bool]:
        gemini = self._get_gemini()
        if gemini:
            try:
                text, uncertainty = gemini.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    language=language,
                    max_tokens=max_tokens,
                )
                if text and text.strip():
                    logger.info("LLM response from Gemini (len=%d)", len(text))
                    return text, uncertainty
                logger.warning("Gemini returned empty, falling back to Ollama")
            except Exception as e:
                logger.warning("Gemini failed (%s), falling back to Ollama", e)

        ollama = self._get_ollama()
        if ollama:
            try:
                text, uncertainty = ollama.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    language=language,
                    max_tokens=max_tokens,
                )
                if text and text.strip():
                    logger.info("LLM response from Ollama (len=%d)", len(text))
                    return text, uncertainty
                logger.warning("Ollama returned empty, falling back to Stub")
            except Exception as e:
                logger.warning("Ollama failed (%s), falling back to Stub", e)

        logger.info("All LLM adapters failed, using Stub")
        return StubAdapter().generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            language=language,
            max_tokens=max_tokens,
        )


class StubAdapter:
    """
    Stub implementation when no production LLM is available.
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
        del system_prompt, max_tokens
        if not (user_prompt or '').strip():
            return _stub_message(language, empty=True), True
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
