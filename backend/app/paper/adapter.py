"""ScreenerSignal adapter.

Maps the existing screener output (Signal + Snapshot rows from the screener
DB) into the canonical paper-bot input format described in the spec.

This is intentionally an *adapter* (not a refactor of the screener):
existing code can keep returning the rich `Signal` + `Snapshot` shape;
paper-trading consumes only this normalized view.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Iterable, List, Optional

from ..models.orm import Signal, Snapshot
from ..models.paper_schemas import ScreenerSignal


# --- Mapping tables (spec) ---

REGIME_TO_TREND = {
    "STRONG_UPTREND": "Strong Uptrend",
    "UPTREND": "Uptrend",
    "RANGE": "Sideways",
    "VOLATILE": "Volatile",
    "DOWNTREND": "Downtrend",
    "STRONG_DOWNTREND": "Strong Downtrend",
}

CATEGORY_TO_SETUP = {
    "FRESH_BREAKOUT": "Breakout Retest",
    "PULLBACK_ENTRY": "Pullback to EMA20",
    "MOMENTUM_LEADER": "Momentum Continuation",
    "OVERSOLD_RECOVERING": "Oversold Recovery",
    "SWING_NEXT_WEEK": "Pullback to SMA20",
    "INTRADAY_WATCH_TOMORROW": "Momentum Continuation",
}

# Setups the bot actually trades (others are diagnostic only).
ALLOWED_SETUPS = {
    "Breakout Retest",
    "Pullback to EMA20",
    "Pullback to SMA20",
    "Momentum Continuation",
    "Oversold Recovery",
}


def confidence_bucket(conf: Optional[float]) -> str:
    """0..1 confidence -> Low | Medium | High."""
    if conf is None:
        return "Low"
    if conf < 0.5:
        return "Low"
    if conf <= 0.8:
        return "Medium"
    return "High"


def risk_level_from_atr_pct(atr_pct: Optional[float]) -> str:
    if atr_pct is None:
        return "Medium"
    if atr_pct < 2.5:
        return "Low"
    if atr_pct <= 4.5:
        return "Medium"
    return "High"


def risk_reward(entry: Optional[float], stop: Optional[float], target_1: Optional[float]) -> Optional[float]:
    if entry is None or stop is None or target_1 is None:
        return None
    risk = entry - stop
    reward = target_1 - entry
    if risk <= 0 or reward <= 0:
        return None
    return round(reward / risk, 2)


def _entry_zone(entry: Optional[float], atr14: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    if entry is None:
        return None, None
    band = (atr14 * 0.3) if (atr14 is not None and atr14 > 0) else (entry * 0.005)
    return round(entry - band, 2), round(entry + band, 2)


def from_signal(
    signal: Signal,
    snapshot: Optional[Snapshot],
    *,
    market_regime: Optional[str] = None,
    ai_summary: Optional[str] = None,
) -> ScreenerSignal:
    """Build a ScreenerSignal from a Signal row + (optional) latest Snapshot."""
    indicators = (snapshot.indicators_json or {}) if snapshot else {}
    regime = snapshot.regime if snapshot else "RANGE"
    trend = REGIME_TO_TREND.get(regime, "Sideways")
    setup_type = CATEGORY_TO_SETUP.get(signal.category, signal.category)
    close = float(snapshot.close) if snapshot else (float(signal.entry) if signal.entry else 0.0)
    atr14 = indicators.get("atr14")
    rsi = indicators.get("rsi14")
    vol_ratio = indicators.get("vol_ratio")
    atr_pct = (snapshot.atr_pct if snapshot else None) or indicators.get("atr_pct")

    entry = float(signal.entry) if signal.entry is not None else None
    stop_loss = float(signal.stop_loss) if signal.stop_loss is not None else None
    target_1 = float(signal.target_1) if signal.target_1 is not None else None
    target_2 = float(signal.target_2) if signal.target_2 is not None else None

    entry_low, entry_high = _entry_zone(entry, atr14)
    rr = risk_reward(entry, stop_loss, target_1)

    return ScreenerSignal(
        symbol=signal.symbol,
        date=signal.as_of_date,
        close=close,
        trend=trend,
        setup_type=setup_type,
        score=float(signal.score),
        confidence=confidence_bucket(float(signal.confidence)),
        risk_level=risk_level_from_atr_pct(atr_pct),
        risk_reward=rr,
        entry=entry,
        entry_zone_low=entry_low,
        entry_zone_high=entry_high,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        rsi=float(rsi) if rsi is not None else None,
        volume_ratio=float(vol_ratio) if vol_ratio is not None else None,
        atr_percent=float(atr_pct) if atr_pct is not None else None,
        market_regime=market_regime,
        ai_summary=ai_summary,
    )


def from_signals(
    pairs: Iterable[tuple[Signal, Optional[Snapshot]]],
    *,
    market_regime: Optional[str] = None,
) -> List[ScreenerSignal]:
    return [
        from_signal(sig, snap, market_regime=market_regime) for sig, snap in pairs
    ]


def is_actionable_setup(setup_type: str) -> bool:
    return setup_type in ALLOWED_SETUPS
