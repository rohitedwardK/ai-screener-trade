"""Pluggable LLM provider interface."""
from __future__ import annotations

from typing import Dict, Protocol

from ..config import get_settings


class BaseLLMProvider(Protocol):
    name: str

    def explain(self, payload: Dict) -> str: ...


def get_provider() -> BaseLLMProvider:
    """Resolve the configured provider; fall back to template on any import error."""
    settings = get_settings()
    kind = (settings.LLM_PROVIDER or "template").lower()

    if kind == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider()

    if kind == "openai":
        from .openai_compat import OpenAIProvider

        if not settings.OPENAI_API_KEY:
            from .template import TemplateProvider

            return TemplateProvider()
        return OpenAIProvider()

    from .template import TemplateProvider

    return TemplateProvider()
