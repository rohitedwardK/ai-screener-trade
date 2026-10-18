"""Deterministic fallback explanation - uses no LLM."""
from __future__ import annotations

from typing import Any, Dict

from .prompts import empty_sections, normalize_sections


_CATEGORY_INTRO = {
    "MOMENTUM_LEADER": "{symbol} is showing strong momentum.",
    "FRESH_BREAKOUT": "{symbol} has just broken out.",
    "PULLBACK_ENTRY": "{symbol} is offering a pullback entry inside an established uptrend.",
    "OVERSOLD_RECOVERING": "{symbol} appears oversold and is starting to recover.",
    "OVERBOUGHT_AVOID": "{symbol} looks overextended; chasing here is risky.",
    "WEAK_AVOID": "{symbol} is technically weak.",
    "HIGH_RISK": "{symbol} carries elevated risk right now.",
    "SWING_NEXT_WEEK": "{symbol} is a swing-trade candidate for the coming week.",
    "INTRADAY_WATCH_TOMORROW": "{symbol} deserves an intraday watch for tomorrow.",
}


def _fmt(value: Any, spec: str) -> str | None:
    if value is None:
        return None
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return None


class TemplateProvider:
    name = "template"

    def explain(self, payload: Dict) -> Dict[str, Any]:
        symbol = payload.get("symbol", "?")
        category = payload.get("category", "")
        direction = (payload.get("direction") or "WAIT").upper()
        regime = payload.get("regime", "?")
        score = payload.get("score", 0)
        confidence = payload.get("confidence", 0)
        reasons = [str(r).strip() for r in (payload.get("reasons") or []) if str(r).strip()]
        ind = payload.get("indicators", {}) or {}
        plan = payload.get("plan", {}) or {}

        if direction == "WAIT":
            setup = f"{symbol} is a WAIT — the setup is not an actionable long or short."
        else:
            setup = _CATEGORY_INTRO.get(category, f"{symbol} matched the {category} setup.").format(
                symbol=symbol
            )
        setup = f"{setup} Direction is {direction}; regime is {regime}."

        body_bits = []
        rsi = _fmt(ind.get("rsi14"), ".0f")
        adx = _fmt(ind.get("adx"), ".0f")
        atr_pct = _fmt(ind.get("atr_pct"), ".1f")
        vol_ratio = _fmt(ind.get("vol_ratio"), ".1f")
        ema20 = ind.get("ema20")
        ema50 = ind.get("ema50")
        if rsi is not None:
            body_bits.append(f"RSI is {rsi}")
        if adx is not None:
            body_bits.append(f"ADX is {adx}")
        if atr_pct is not None:
            body_bits.append(f"ATR is {atr_pct}% of price")
        if vol_ratio is not None:
            body_bits.append(f"volume is {vol_ratio}x its 20-day average")
        if ema20 and ema50:
            stacked = "above" if ema20 > ema50 else "below"
            body_bits.append(f"EMA20 is {stacked} EMA50")
        indicators = (
            ", ".join(body_bits) + "."
            if body_bits
            else "No indicator values were supplied on this snapshot."
        )

        plan_text = ""
        if plan and plan.get("entry") is not None:
            plan_text = (
                f"Plan: entry near {plan['entry']}, stop at {plan.get('stop_loss')}, "
                f"target1 {plan.get('target_1')}, target2 {plan.get('target_2')}."
            )

        invalidation = plan.get("invalidation") if plan else None
        if direction == "WAIT":
            risks = "No trade plan applies until the setup becomes LONG or SHORT."
        elif invalidation is not None:
            risks = f"Treat a move through {invalidation} as invalidation of this setup."
        else:
            risks = "Treat a move through the stop loss as invalidation of this setup."
        try:
            conf_pct = f"{float(confidence):.0%}"
            score_txt = f"{float(score):.0f}"
        except (TypeError, ValueError):
            conf_pct, score_txt = "—", "—"
        risks = f"{risks} Confidence {conf_pct}; score {score_txt}/100."

        return normalize_sections(
            {
                **empty_sections(),
                "setup": setup,
                "indicators": indicators,
                "rules": reasons,
                "plan": plan_text,
                "risks": risks,
            }
        )
