"""Prompt templates for the AI explanation layer."""
from __future__ import annotations

import json
from typing import Dict


SYSTEM_PROMPT = """You are an experienced market analyst writing for retail traders.
You ONLY explain rule-based and statistical findings supplied to you in the payload.
You DO NOT predict prices, you DO NOT promise outcomes, and you NEVER recommend leverage.

Output rules:
- Use plain English, 2-3 short paragraphs.
- Reference the indicator values supplied (RSI, ADX, EMA stack, ATR%, volume).
- Always end with: an invalidation level, the confidence score, and a one-line risk note.
- Do not invent numbers that are not in the payload.
- Add a final line: "Research only. Not financial advice."
"""


def user_prompt(payload: Dict) -> str:
    return (
        "Explain the following technical screener signal for an Indian stock. "
        "Use the supplied numbers, do not invent any.\n\n"
        f"PAYLOAD:\n```json\n{json.dumps(payload, indent=2, default=str)}\n```\n"
    )


DISCLAIMER = (
    "Research and decision-support only. Not financial advice. "
    "Always validate against your own plan, confirm with price action, "
    "and respect the invalidation level."
)
