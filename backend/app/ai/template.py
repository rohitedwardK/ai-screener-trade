"""Deterministic fallback explanation - uses no LLM."""
from __future__ import annotations

from typing import Dict

from .prompts import DISCLAIMER


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


class TemplateProvider:
    name = "template"

    def explain(self, payload: Dict) -> str:
        symbol = payload.get("symbol", "?")
        category = payload.get("category", "")
        regime = payload.get("regime", "?")
        score = payload.get("score", 0)
        confidence = payload.get("confidence", 0)
        reasons = payload.get("reasons", [])
        ind = payload.get("indicators", {}) or {}
        plan = payload.get("plan", {}) or {}

        intro = _CATEGORY_INTRO.get(category, f"{symbol} matched the {category} setup.").format(
            symbol=symbol
        )

        rsi = ind.get("rsi14")
        adx = ind.get("adx")
        atr_pct = ind.get("atr_pct")
        ema20 = ind.get("ema20")
        ema50 = ind.get("ema50")
        vol_ratio = ind.get("vol_ratio")

        body_bits = []
        if rsi is not None:
            body_bits.append(f"RSI is {rsi:.0f}")
        if adx is not None:
            body_bits.append(f"ADX is {adx:.0f}")
        if atr_pct is not None:
            body_bits.append(f"ATR is {atr_pct:.1f}% of price")
        if vol_ratio is not None:
            body_bits.append(f"volume is {vol_ratio:.1f}x its 20-day average")
        if ema20 and ema50:
            stacked = "above" if ema20 > ema50 else "below"
            body_bits.append(f"EMA20 is {stacked} EMA50")

        body = (
            "The current regime is "
            f"{regime}. " + ", ".join(body_bits) + "."
            if body_bits
            else f"The current regime is {regime}."
        )

        reasons_block = ""
        if reasons:
            reasons_block = "\nKey rules satisfied:\n" + "\n".join(f"- {r}" for r in reasons)

        plan_block = ""
        if plan and plan.get("entry") is not None:
            plan_block = (
                f"\nPlan: entry near {plan['entry']}, stop at {plan.get('stop_loss')}, "
                f"target1 {plan.get('target_1')}, target2 {plan.get('target_2')}."
            )

        invalidation = plan.get("invalidation") if plan else None
        risk_line = f"Invalidation: {invalidation}." if invalidation else "Invalidation: see stop loss."
        confidence_line = f"Confidence: {confidence:.0%}. Score: {score:.0f}/100."

        return (
            f"{intro}\n\n"
            f"{body}{reasons_block}{plan_block}\n\n"
            f"{risk_line}\n{confidence_line}\n\n{DISCLAIMER}"
        )
