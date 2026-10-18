"""Prompt templates for the AI explanation layer."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


DISCLAIMER = (
    "Research and decision-support only. Not financial advice. "
    "Always validate against your own plan, confirm with price action, "
    "and respect the invalidation level."
)

SYSTEM_PROMPT = """You are an experienced market analyst writing for retail traders.
You ONLY explain rule-based and statistical findings supplied to you in the payload.
You DO NOT predict prices, you DO NOT promise outcomes, and you NEVER recommend leverage.

Return ONLY valid JSON with these keys:
- setup: 1-2 sentences. Category, direction (LONG/SHORT/WAIT), and regime. WAIT is not a trade.
- indicators: 1-2 sentences citing only supplied RSI, ADX, EMA stack, ATR%, volume.
- rules: array of short strings copied/paraphrased from payload.reasons. Empty array if none.
- plan: one sentence with entry, stop, target_1, target_2 from payload.plan, or "" if WAIT / missing.
- risks: 1-2 sentences on what invalidates the setup. Do not invent numbers.

Rules:
- Do not invent numbers that are not in the payload.
- Do not flip direction or invent signals.
- No markdown, no extra keys, no prose outside JSON.
"""


def user_prompt(payload: Dict) -> str:
    return (
        "Produce the JSON explanation for this Indian-stock screener payload. "
        "Use the supplied numbers, do not invent any.\n\n"
        f"PAYLOAD:\n```json\n{json.dumps(payload, indent=2, default=str)}\n```\n"
    )


def empty_sections() -> Dict[str, Any]:
    return {
        "setup": "",
        "indicators": "",
        "rules": [],
        "plan": "",
        "risks": "",
    }


def normalize_sections(data: Dict[str, Any]) -> Dict[str, Any]:
    rules = data.get("rules") or []
    if isinstance(rules, str):
        rules = [rules]
    return {
        "setup": str(data.get("setup") or "").strip(),
        "indicators": str(data.get("indicators") or "").strip(),
        "rules": [str(r).strip() for r in rules if str(r).strip()],
        "plan": str(data.get("plan") or "").strip(),
        "risks": str(data.get("risks") or "").strip(),
    }


def parse_structured_explanation(raw: str) -> Optional[Dict[str, Any]]:
    """Extract the JSON section object from an LLM reply; None if unusable."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    sections = normalize_sections(data)
    if not sections["setup"]:
        return None
    return sections


def sections_to_text(sections: Dict[str, Any]) -> str:
    parts: List[str] = []
    setup = (sections.get("setup") or "").strip()
    if setup:
        parts.append(setup)
    indicators = (sections.get("indicators") or "").strip()
    if indicators:
        parts.append(indicators)
    rules = sections.get("rules") or []
    if rules:
        parts.append("Key rules satisfied:\n" + "\n".join(f"- {r}" for r in rules))
    plan = (sections.get("plan") or "").strip()
    if plan:
        parts.append(plan)
    risks = (sections.get("risks") or "").strip()
    if risks:
        parts.append(risks)
    return "\n\n".join(parts)
