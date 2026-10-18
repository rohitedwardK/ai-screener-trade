"""Direction-aware evidence for rule-based signals.

Unsigned features (ATR%, volume) measure activity only. Signed votes come from
regime labels and pattern polarity. Conflicting bullish vs bearish votes resolve
to WAIT — never a category-default LONG.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .signal_decision import DIRECTION_LONG, DIRECTION_SHORT, DIRECTION_WAIT

BULLISH_REGIMES = frozenset({"UPTREND", "STRONG_UPTREND"})
BEARISH_REGIMES = frozenset({"DOWNTREND", "STRONG_DOWNTREND"})

_DIRECTIONAL_PATTERN_KEYS = (
    "breakout_20d",
    "breakout_55d",
    "bullish_engulfing",
    "bearish_engulfing",
    "hammer",
    "bearish_reversal",
)


def has_directional_pattern(pat: Dict[str, bool]) -> bool:
    return any(pat.get(k) for k in _DIRECTIONAL_PATTERN_KEYS)


def regime_signed_vote(regime: str) -> Tuple[int, int, Optional[str]]:
    if regime in BULLISH_REGIMES:
        return 1, 0, f"Regime {regime} (bullish)"
    if regime in BEARISH_REGIMES:
        return 0, 1, f"Regime {regime} (bearish)"
    return 0, 0, None


def pattern_signed_votes(pat: Dict[str, bool]) -> Tuple[int, int, List[str]]:
    bull, bear = 0, 0
    reasons: List[str] = []
    if pat.get("breakout_20d"):
        bull += 1
        reasons.append("Closed above 20-day high (bullish)")
    if pat.get("breakout_55d"):
        bull += 1
        reasons.append("Closed above 55-day high (bullish)")
    if pat.get("bullish_engulfing"):
        bull += 1
        reasons.append("Bullish engulfing")
    if pat.get("hammer"):
        bull += 1
        reasons.append("Hammer (bullish)")
    if pat.get("bearish_engulfing"):
        bear += 1
        reasons.append("Bearish engulfing")
    if pat.get("bearish_reversal"):
        bear += 1
        reasons.append("Bearish reversal pattern")
    return bull, bear, reasons


def combine_signed_votes(
    *parts: Tuple[int, int],
) -> Tuple[int, int]:
    bull = sum(p[0] for p in parts)
    bear = sum(p[1] for p in parts)
    return bull, bear


def direction_from_signed_votes(bull: int, bear: int) -> Tuple[str, Optional[str]]:
    if bull == 0 and bear == 0:
        return DIRECTION_WAIT, "No directional evidence"
    if bull > 0 and bear > 0:
        return DIRECTION_WAIT, "Conflicting directional evidence (bullish vs bearish)"
    if bull > 0:
        return DIRECTION_LONG, None
    return DIRECTION_SHORT, None


def direction_confidence(bull: int, bear: int) -> float:
    """One-sided signed margin in [0, 1]. Zero when no votes or when votes conflict."""
    if bull > 0 and bear > 0:
        return 0.0
    total = bull + bear
    if total == 0:
        return 0.0
    return round(abs(bull - bear) / total, 2)
