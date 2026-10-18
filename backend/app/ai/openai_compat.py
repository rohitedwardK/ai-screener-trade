"""OpenAI / OpenAI-compatible provider (works with OpenAI, Gemini, Groq, etc.)."""
from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from ..config import get_settings
from .prompts import SYSTEM_PROMPT, parse_structured_explanation, user_prompt
from .template import TemplateProvider

log = logging.getLogger(__name__)


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        s = get_settings()
        self.base_url = s.OPENAI_BASE_URL.rstrip("/")
        self.model = s.OPENAI_MODEL
        self.api_key = s.OPENAI_API_KEY
        self.timeout = s.OPENAI_TIMEOUT_SECONDS
        self._fallback = TemplateProvider()

    def explain(self, payload: Dict) -> Dict[str, Any]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt(payload)},
                        ],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                if not content:
                    raise ValueError("Empty response from OpenAI-compatible API")
                sections = parse_structured_explanation(content)
                if sections is None:
                    raise ValueError("OpenAI-compatible reply was not structured JSON")
                return sections
        except Exception as exc:
            log.warning("OpenAI-compatible call failed (%s); using template fallback.", exc)
            return self._fallback.explain(payload)
