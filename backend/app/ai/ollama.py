"""Local Ollama LLM provider (https://ollama.ai/)."""
from __future__ import annotations

import logging
from typing import Dict

import httpx

from ..config import get_settings
from .prompts import DISCLAIMER, SYSTEM_PROMPT, user_prompt
from .template import TemplateProvider

log = logging.getLogger(__name__)


class OllamaProvider:
    name = "ollama"

    def __init__(self) -> None:
        s = get_settings()
        self.base_url = s.OLLAMA_URL.rstrip("/")
        self.model = s.OLLAMA_MODEL
        self.timeout = s.OLLAMA_TIMEOUT_SECONDS
        self._fallback = TemplateProvider()

    def explain(self, payload: Dict) -> str:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt(payload)},
                        ],
                        "options": {"temperature": 0.3},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "").strip()
                if not content:
                    raise ValueError("Empty response from Ollama")
                if DISCLAIMER not in content:
                    content = f"{content}\n\n{DISCLAIMER}"
                return content
        except Exception as exc:
            log.warning("Ollama call failed (%s); using template fallback.", exc)
            return self._fallback.explain(payload)
