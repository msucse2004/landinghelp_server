"""
Gemini LLM adapter.
google-generativeai 패키지를 사용하여 Gemini API 호출.
settings.GEMINI_API_KEY 가 설정되어 있어야 동작.
"""
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class GeminiAdapter:
    MODEL = "gemini-2.0-flash"

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        from django.conf import settings
        import google.generativeai as genai

        api_key = getattr(settings, "GEMINI_API_KEY", "") or ""
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")
        genai.configure(api_key=api_key)
        self._client = genai.GenerativeModel(self.MODEL)
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        language: str = "ko",
        max_tokens: int = 800,
    ) -> Tuple[str, bool]:
        try:
            model = self._get_client()
            combined = system_prompt.strip() + "\n\n" + user_prompt.strip()
            response = model.generate_content(
                combined,
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": 0.2,
                },
            )
            text = ""
            if response and response.text:
                text = response.text.strip()
            if not text:
                logger.warning("Gemini returned empty response")
                return "", True
            return text, False
        except Exception as e:
            logger.warning("Gemini adapter error: %s", e, exc_info=True)
            raise
