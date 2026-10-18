"""15-minute intraday scalp catalog for stock / commodity detail analysis.

Pure: no DB, no network. Caller supplies a 15m OHLCV frame (≥ 20 bars).
Every emitted plan carries an invalidation level (the stop).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from . import patterns
from .indicators import compute_all, rsi as rsi_series
from .intraday_range import RangeLevels, detect_range, session_vwap

HOLD_MINUTES = 45
STOP_ATR_MULT = 0.85
T1_ATR_MULT = 1.0
T2_ATR_MULT = 1.65

DISCLAIMER = "Research and decision-support only. Not financial advice."


@dataclass(frozen=True)
class IntradayScalpRecord:
    category: str
    direction: str
    score: float
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    invalidation: float
    hold_minutes: int = HOLD_MINUTES
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class IntradayAnalysisResult:
    regime: str
    patterns: List[str]
    support: Optional[float]
    resistance: Optional[float]
    vwap: Optional[float]
    atr: Optional[float]
    rsi: Optional[float]
    scalps: List[IntradayScalpRecord]
    aligned_with_signal: Optional[bool] = None


def _round(x: float) -> float:
    return round(float(x), 2)


def _score(reasons: List[str], cap: int = 4) -> float:
    if not reasons:
        return 0.0
    return min(100.0, (len(reasons) / cap) * 100.0)


def _long_plan(spot: float, atr: float, *, stop_anchor: float) -> tuple[float, float, float, float]:
    stop = min(stop_anchor, spot - STOP_ATR_MULT * atr)
    t1 = spot + T1_ATR_MULT * atr
    t2 = spot + T2_ATR_MULT * atr
    return _round(spot), _round(stop), _round(t1), _round(t2)


def _short_plan(spot: float, atr: float, *, stop_anchor: float) -> tuple[float, float, float, float]:
    stop = max(stop_anchor, spot + STOP_ATR_MULT * atr)
    t1 = spot - T1_ATR_MULT * atr
    t2 = spot - T2_ATR_MULT * atr
    return _round(spot), _round(stop), _round(t1), _round(t2)


def _classify_regime(df: pd.DataFrame, enriched: pd.DataFrame) -> str:
    if len(enriched) < 20:
        return "UNKNOWN"
    last = enriched.iloc[-1]
    adx_v = last.get("adx")
    ema20 = last.get("ema20")
    ema50 = last.get("ema50")
    close = float(last["close"])
    if any(pd.isna(x) for x in (adx_v, ema20, ema50)):
        return "RANGE_BOUND"
    adx_v = float(adx_v)
    ema20 = float(ema20)
    ema50 = float(ema50)
    if adx_v >= 20:
        if close > ema20 > ema50:
            return "TRENDING_UP"
        if close < ema20 < ema50:
            return "TRENDING_DOWN"
    return "RANGE_BOUND"


def _detect_patterns(enriched: pd.DataFrame) -> List[str]:
    pat = patterns.detect_all(enriched)
    labels: List[str] = []
    mapping = {
        "breakout_20d": "20-bar breakout",
        "breakout_55d": "55-bar breakout",
        "pullback": "EMA pullback",
        "bullish_engulfing": "Bullish engulfing",
        "bearish_engulfing": "Bearish engulfing",
        "hammer": "Hammer",
        "bearish_reversal": "Bearish reversal",
    }
    for key, label in mapping.items():
        if pat.get(key):
            labels.append(label)
    return labels


def evaluate_intraday(
    df_15m: pd.DataFrame,
    *,
    signal_direction: Optional[str] = None,
) -> IntradayAnalysisResult:
    """Run 15m pattern + scalp catalog on the supplied frame."""
    empty = IntradayAnalysisResult(
        regime="UNKNOWN",
        patterns=[],
        support=None,
        resistance=None,
        vwap=None,
        atr=None,
        rsi=None,
        scalps=[],
        aligned_with_signal=None,
    )
    if df_15m is None or len(df_15m) < 20:
        return empty

    enriched = compute_all(df_15m)
    last = enriched.iloc[-1]
    prev = enriched.iloc[-2]
    spot = float(last["close"])
    atr_v = last.get("atr14")
    if atr_v is None or pd.isna(atr_v) or float(atr_v) <= 0:
        return empty
    atr_v = float(atr_v)

    rsi_vals = rsi_series(enriched["close"], 14)
    rsi_v = float(rsi_vals.iloc[-1]) if not rsi_vals.empty else 50.0

    regime = _classify_regime(df_15m, enriched)
    pattern_labels = _detect_patterns(enriched)
    levels = detect_range(df_15m)
    vwap_v = session_vwap(df_15m)

    out: List[IntradayScalpRecord] = []
    last3 = df_15m.tail(3)

    if levels is not None:
        support_dist = (spot - levels.support) / spot
        resistance_dist = (levels.resistance - spot) / spot

        if 0 <= support_dist <= 0.0025 and last3["low"].min() >= levels.support * 0.999 and rsi_v < 52:
            reasons = [
                f"Within {support_dist * 100:.2f}% of 15m support {levels.support:.2f}",
                "Last 3 bars holding above support",
                f"RSI {rsi_v:.0f} below midline",
            ]
            entry, stop, t1, t2 = _long_plan(
                spot, atr_v, stop_anchor=levels.support - 0.15 * atr_v,
            )
            out.append(IntradayScalpRecord(
                category="RANGE_BOUNCE_LONG", direction="LONG", score=_score(reasons),
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                invalidation=stop, reasons=reasons,
            ))

        if 0 <= resistance_dist <= 0.0025 and last3["high"].max() <= levels.resistance * 1.001 and rsi_v > 48:
            reasons = [
                f"Within {resistance_dist * 100:.2f}% of 15m resistance {levels.resistance:.2f}",
                "Last 3 bars capped below resistance",
                f"RSI {rsi_v:.0f} above midline",
            ]
            entry, stop, t1, t2 = _short_plan(
                spot, atr_v, stop_anchor=levels.resistance + 0.15 * atr_v,
            )
            out.append(IntradayScalpRecord(
                category="RANGE_BOUNCE_SHORT", direction="SHORT", score=_score(reasons),
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                invalidation=stop, reasons=reasons,
            ))

        if (
            float(prev["low"]) < levels.support
            and float(last["close"]) > levels.support
            and float(last["close"]) > float(last["open"])
        ):
            reasons = [
                f"Whipsaw below support {levels.support:.2f}",
                f"Reclaimed with bullish 15m close {last['close']:.2f}",
            ]
            entry, stop, t1, t2 = _long_plan(
                spot, atr_v, stop_anchor=float(prev["low"]) - 0.1 * atr_v,
            )
            out.append(IntradayScalpRecord(
                category="FALSE_BREAKOUT_LONG", direction="LONG", score=_score(reasons),
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                invalidation=stop, reasons=reasons,
            ))

        if (
            float(prev["high"]) > levels.resistance
            and float(last["close"]) < levels.resistance
            and float(last["close"]) < float(last["open"])
        ):
            reasons = [
                f"Whipsaw above resistance {levels.resistance:.2f}",
                f"Rejected with bearish 15m close {last['close']:.2f}",
            ]
            entry, stop, t1, t2 = _short_plan(
                spot, atr_v, stop_anchor=float(prev["high"]) + 0.1 * atr_v,
            )
            out.append(IntradayScalpRecord(
                category="FALSE_BREAKOUT_SHORT", direction="SHORT", score=_score(reasons),
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                invalidation=stop, reasons=reasons,
            ))

    if vwap_v is not None and vwap_v > 0 and levels is not None:
        if (
            float(prev["close"]) < vwap_v
            and float(last["close"]) > vwap_v
            and float(last["close"]) > float(last["open"])
        ):
            reasons = [
                f"Reclaimed VWAP {vwap_v:.2f} from below",
                "Bullish 15m body on reclaim bar",
            ]
            entry, stop, t1, t2 = _long_plan(
                spot, atr_v, stop_anchor=float(prev["low"]) - 0.1 * atr_v,
            )
            out.append(IntradayScalpRecord(
                category="VWAP_RECLAIM_LONG", direction="LONG", score=_score(reasons),
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                invalidation=stop, reasons=reasons,
            ))
        if (
            float(prev["close"]) > vwap_v
            and float(last["close"]) < vwap_v
            and float(last["close"]) < float(last["open"])
        ):
            reasons = [
                f"Lost VWAP {vwap_v:.2f} from above",
                "Bearish 15m body on rejection bar",
            ]
            entry, stop, t1, t2 = _short_plan(
                spot, atr_v, stop_anchor=float(prev["high"]) + 0.1 * atr_v,
            )
            out.append(IntradayScalpRecord(
                category="VWAP_RECLAIM_SHORT", direction="SHORT", score=_score(reasons),
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                invalidation=stop, reasons=reasons,
            ))

    if regime == "TRENDING_UP":
        prior_high = float(df_15m["high"].iloc[-9:-1].max())
        ema20 = float(last.get("ema20") or spot)
        if spot > prior_high and 52 <= rsi_v <= 72:
            reasons = [
                "15m uptrend (close > EMA20 > EMA50)",
                f"Break of prior 8-bar high {prior_high:.2f}",
                f"RSI {rsi_v:.0f} in momentum zone",
            ]
            entry, stop, t1, t2 = _long_plan(spot, atr_v, stop_anchor=ema20 - 0.2 * atr_v)
            out.append(IntradayScalpRecord(
                category="MOMENTUM_BREAKOUT_LONG", direction="LONG", score=_score(reasons),
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                invalidation=stop, reasons=reasons,
            ))
        touched_ema = bool((df_15m["low"].tail(3) <= ema20 * 1.002).any())
        if touched_ema and spot > ema20 and float(last["close"]) > float(last["open"]):
            reasons = [
                "Pullback to EMA20 in 15m uptrend",
                "Bullish rejection candle",
            ]
            entry, stop, t1, t2 = _long_plan(spot, atr_v, stop_anchor=ema20 - 0.25 * atr_v)
            out.append(IntradayScalpRecord(
                category="EMA_PULLBACK_LONG", direction="LONG", score=_score(reasons, cap=3),
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                invalidation=stop, reasons=reasons,
            ))

    if regime == "TRENDING_DOWN":
        prior_low = float(df_15m["low"].iloc[-9:-1].min())
        ema20 = float(last.get("ema20") or spot)
        if spot < prior_low and 28 <= rsi_v <= 48:
            reasons = [
                "15m downtrend (close < EMA20 < EMA50)",
                f"Break of prior 8-bar low {prior_low:.2f}",
                f"RSI {rsi_v:.0f} weak",
            ]
            entry, stop, t1, t2 = _short_plan(spot, atr_v, stop_anchor=ema20 + 0.2 * atr_v)
            out.append(IntradayScalpRecord(
                category="MOMENTUM_BREAKDOWN_SHORT", direction="SHORT", score=_score(reasons),
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                invalidation=stop, reasons=reasons,
            ))
        touched_ema = bool((df_15m["high"].tail(3) >= ema20 * 0.998).any())
        if touched_ema and spot < ema20 and float(last["close"]) < float(last["open"]):
            reasons = [
                "Rally into EMA20 in 15m downtrend",
                "Bearish rejection candle",
            ]
            entry, stop, t1, t2 = _short_plan(spot, atr_v, stop_anchor=ema20 + 0.25 * atr_v)
            out.append(IntradayScalpRecord(
                category="EMA_PULLBACK_SHORT", direction="SHORT", score=_score(reasons, cap=3),
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                invalidation=stop, reasons=reasons,
            ))

    out.sort(key=lambda r: r.score, reverse=True)

    aligned: Optional[bool] = None
    if signal_direction and out:
        top = out[0]
        aligned = top.direction == signal_direction.upper()

    return IntradayAnalysisResult(
        regime=regime,
        patterns=pattern_labels,
        support=levels.support if levels else None,
        resistance=levels.resistance if levels else None,
        vwap=vwap_v,
        atr=round(atr_v, 2),
        rsi=round(rsi_v, 1),
        scalps=out,
        aligned_with_signal=aligned,
    )


__all__ = [
    "DISCLAIMER",
    "HOLD_MINUTES",
    "IntradayAnalysisResult",
    "IntradayScalpRecord",
    "evaluate_intraday",
]
