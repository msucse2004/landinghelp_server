"""
Ollama LLM adapter.
로컬 Ollama 서버(http://localhost:11434)에 요청.
외부 패키지 없이 stdlib urllib만 사용.
"""
import json
import logging
import urllib.request
import urllib.error
from typing import Tuple

logger = logging.getLogger(__name__)


class OllamaAdapter:
    DEFAULT_URL = "http://localhost:11434"
    DEFAULT_MODEL = "llama3.1:8b"

    def __init__(self, *, base_url: str = "", model: str = ""):
        import os
        self._base_url = (
            base_url
            or os.environ.get("OLLAMA_URL", "")
            or self.DEFAULT_URL
        ).rstrip("/")
        self._model = (
            model
            or os.environ.get("OLLAMA_MODEL", "")
            or self.DEFAULT_MODEL
        )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        language: str = "ko",
        max_tokens: int = 800,
    ) -> Tuple[str, bool]:
        url = self._base_url + "/api/chat"
        payload = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.2,
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            text = (body.get("message") or {}).get("content", "").strip()
            if not text:
                logger.warning("Ollama returned empty content")
                return "", True
            return text, False
        except Exception as e:
            logger.warning("Ollama adapter error: %s", e, exc_info=True)
            raise
