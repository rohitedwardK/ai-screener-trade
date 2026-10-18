"""Minimal Ollama client for briefing synthesis and bounded research actions.

We deliberately don't use a heavyweight agent framework (CrewAI / LangGraph)
because briefings and research tool selection use small, grounded payloads.
Research validates model actions separately and never accepts model-generated
price levels. A direct call to Ollama via the existing `httpx` client keeps
the dependency surface minimal.

If Ollama is unreachable the orchestrator falls back to the deterministic
markdown stitcher in `orchestrator._fallback_summary_md`.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


class AgenticUnavailable(RuntimeError):
    """Raised when Ollama cannot be reached, so the orchestrator falls back
    to the deterministic stitcher."""


def _strip_openai_prefix(model: str) -> str:
    """Ollama's /api/chat expects the bare model name (e.g. `llama3.2:latest`).
    The settings keep the `openai/` prefix for symmetry with other providers
    but we drop it here before talking to the native endpoint."""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _ollama_base(base_url: str) -> str:
    """Convert `http://host:port/v1` (OpenAI-compat) to the native Ollama
    base `http://host:port`. Accepts either form."""
    if base_url.endswith("/v1") or base_url.endswith("/v1/"):
        return base_url.rstrip("/").rsplit("/v1", 1)[0]
    return base_url.rstrip("/")


def chat(prompt: str, *, system: Optional[str] = None, temperature: float = 0.2, timeout_sec: Optional[float] = None) -> str:
    """Send a single-turn prompt to Ollama and return the assistant text.

    Raises `AgenticUnavailable` on connection / timeout errors so the
    caller can fall back. JSON parse / 5xx errors are also surfaced.
    """
    settings = get_settings()
    base = _ollama_base(settings.AGENTIC_LLM_BASE_URL)
    model = _strip_openai_prefix(settings.AGENTIC_LLM_MODEL)
    timeout = float(settings.AGENTIC_LLM_TIMEOUT_SEC) if timeout_sec is None else timeout_sec

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": float(temperature)},
    }

    url = f"{base}/api/chat"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        log.warning("Ollama unreachable: %s", exc)
        raise AgenticUnavailable(f"ollama transport error: {exc}") from exc

    if resp.status_code >= 500:
        raise AgenticUnavailable(f"ollama 5xx ({resp.status_code}): {resp.text[:200]}")
    if resp.status_code >= 400:
        # 4xx is a deterministic problem (bad model name, etc.) — surface it
        # so the caller logs it; don't pretend Ollama is unreachable.
        raise RuntimeError(f"ollama error {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise AgenticUnavailable(f"ollama returned non-JSON: {exc}") from exc

    content = (data.get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise AgenticUnavailable("ollama returned empty content")
    return content.strip()


def is_available() -> bool:
    """Check that Ollama responds and the configured local model is installed."""
    settings = get_settings()
    base = _ollama_base(settings.AGENTIC_LLM_BASE_URL)
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{base}/api/tags")
        if resp.status_code >= 400:
            return False
        model = _strip_openai_prefix(settings.AGENTIC_LLM_MODEL)
        return any(row.get("name") == model for row in resp.json().get("models", []))
    except Exception:  # noqa: BLE001
        return False


__all__ = ["AgenticUnavailable", "chat", "is_available"]
