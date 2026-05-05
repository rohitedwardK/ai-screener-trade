"""Adapter: IndexSignal + IndexSnapshot -> IndexScreenerSignal.

Mirrors `app.paper.adapter` but for indices and option-aware setups.
"""
from __future__ import annotations

from typing import List, Optional

from ..analysis.index_signals import IndexSignalRecord
from ..models.index_orm import IndexSignal, IndexSnapshot
from ..models.index_schemas import IndexScreenerSignal


REGIME_TO_TREND = {
    "STRONG_UPTREND": "Strong Uptrend",
    "UPTREND": "Uptrend",
    "RANGE": "Sideways",
    "VOLATILE": "Volatile",
    "DOWNTREND": "Downtrend",
    "STRONG_DOWNTREND": "Strong Downtrend",
}

CATEGORY_TO_SETUP = {
    "TREND_CONTINUATION": "Trend Continuation",
    "BREAKOUT_RETEST": "Breakout Retest",
    "PULLBACK_TO_EMA": "Pullback to EMA",
    "TREND_BREAKDOWN": "Trend Breakdown",
    "BREAKDOWN_RETEST": "Breakdown Retest",
    "RALLY_TO_RESISTANCE": "Rally to Resistance",
}

ALLOWED_SETUPS = set(CATEGORY_TO_SETUP.values())


def confidence_bucket(conf: Optional[float]) -> str:
    if conf is None:
        return "Low"
    if conf < 0.5:
        return "Low"
    if conf <= 0.8:
        return "Medium"
    return "High"


def risk_level_from_atr_pct(atr_pct: Optional[float]) -> str:
    """Indices have lower ATR%; thresholds adjusted accordingly."""
    if atr_pct is None:
        return "Medium"
    if atr_pct < 1.0:
        return "Low"
    if atr_pct <= 2.5:
        return "Medium"
    return "High"


def risk_reward(direction: str, entry: Optional[float], stop: Optional[float], target_1: Optional[float]) -> Optional[float]:
    if entry is None or stop is None or target_1 is None:
        return None
    if direction == "LONG":
        risk = entry - stop
        reward = target_1 - entry
    else:
        risk = stop - entry
        reward = entry - target_1
    if risk <= 0 or reward <= 0:
        return None
    return round(reward / risk, 2)


def from_signal_row(
    signal: IndexSignal,
    snapshot: Optional[IndexSnapshot],
    *,
    code: str,
    market_regime: Optional[str] = None,
    ai_summary: Optional[str] = None,
) -> IndexScreenerSignal:
    indicators = (snapshot.indicators_json or {}) if snapshot else {}
    regime = snapshot.regime if snapshot else "RANGE"
    trend = REGIME_TO_TREND.get(regime, "Sideways")
    setup = CATEGORY_TO_SETUP.get(signal.category, signal.category)
    chain_bias = signal.option_chain_bias

    spot = float(snapshot.close) if snapshot else float(signal.spot or 0.0)
    rsi = indicators.get("rsi14")
    atr_pct = (snapshot.atr_pct if snapshot else None) or indicators.get("atr_pct")

    entry = float(signal.entry) if signal.entry is not None else spot
    stop = float(signal.stop_loss) if signal.stop_loss is not None else None
    t1 = float(signal.target_1) if signal.target_1 is not None else None
    t2 = float(signal.target_2) if signal.target_2 is not None else None
    invalidation = float(signal.invalidation) if signal.invalidation is not None else stop

    direction = signal.direction or "LONG"
    option_type = "CE" if direction == "LONG" else "PE"
    rr = risk_reward(direction, entry, stop, t1)

    chain_summary = (snapshot.option_chain_summary_json or {}) if snapshot else {}
    pcr = chain_summary.get("pcr") if isinstance(chain_summary, dict) else None
    max_pain = chain_summary.get("max_pain") if isinstance(chain_summary, dict) else None

    return IndexScreenerSignal(
        symbol=signal.symbol,
        code=code,
        date=signal.as_of_date,
        spot=spot,
        direction=direction,
        option_type=option_type,
        setup_type=setup,
        score=float(signal.score),
        confidence=confidence_bucket(float(signal.confidence)),
        risk_level=risk_level_from_atr_pct(atr_pct),
        risk_reward=rr,
        spot_entry=entry,
        spot_stop_loss=stop,
        spot_target_1=t1,
        spot_target_2=t2,
        spot_invalidation=invalidation,
        rsi=float(rsi) if rsi is not None else None,
        atr_percent=float(atr_pct) if atr_pct is not None else None,
        market_regime=market_regime,
        option_chain_bias=chain_bias,
        pcr=float(pcr) if pcr is not None else None,
        max_pain=float(max_pain) if max_pain is not None else None,
        ai_summary=ai_summary,
    )


def from_signal_record(
    rec: IndexSignalRecord,
    *,
    code: str,
    market_regime: Optional[str],
    chain_bias: Optional[str],
    pcr: Optional[float],
    max_pain: Optional[float],
    atr_pct: Optional[float],
    rsi: Optional[float],
) -> IndexScreenerSignal:
    """Replay-mode adapter that doesn't need DB rows."""
    setup = CATEGORY_TO_SETUP.get(rec.category, rec.category)
    plan = rec.plan
    direction = rec.direction
    option_type = "CE" if direction == "LONG" else "PE"
    entry = plan.entry if plan else rec.spot
    stop = plan.stop_loss if plan else None
    t1 = plan.target_1 if plan else None
    t2 = plan.target_2 if plan else None
    invalidation = plan.invalidation if plan else stop
    rr = risk_reward(direction, entry, stop, t1)

    return IndexScreenerSignal(
        symbol=rec.symbol,
        code=code,
        date=rec.as_of_date,
        spot=rec.spot,
        direction=direction,
        option_type=option_type,
        setup_type=setup,
        score=float(rec.score),
        confidence=confidence_bucket(float(rec.confidence)),
        risk_level=risk_level_from_atr_pct(atr_pct),
        risk_reward=rr,
        spot_entry=entry,
        spot_stop_loss=stop,
        spot_target_1=t1,
        spot_target_2=t2,
        spot_invalidation=invalidation,
        rsi=rsi,
        atr_percent=atr_pct,
        market_regime=market_regime,
        option_chain_bias=chain_bias,
        pcr=pcr,
        max_pain=max_pain,
    )


def is_actionable_setup(setup_type: str) -> bool:
    return setup_type in ALLOWED_SETUPS
