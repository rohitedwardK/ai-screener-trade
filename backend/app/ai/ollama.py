"""Local Ollama LLM provider (https://ollama.ai/)."""
from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from ..config import get_settings
from .prompts import SYSTEM_PROMPT, parse_structured_explanation, user_prompt
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

    def explain(self, payload: Dict) -> Dict[str, Any]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "format": "json",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt(payload)},
                        ],
                        "options": {"temperature": 0.2},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "").strip()
                if not content:
                    raise ValueError("Empty response from Ollama")
                sections = parse_structured_explanation(content)
                if sections is None:
                    raise ValueError("Ollama reply was not structured JSON")
                return sections
        except Exception as exc:
            log.warning("Ollama call failed (%s); using template fallback.", exc)
            return self._fallback.explain(payload)
