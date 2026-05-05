"""Index signal generator.

Three setup categories per index (LONG side):
  TREND_CONTINUATION   — uptrend + RSI healthy + MACD bullish
  BREAKOUT_RETEST      — closed above 20-day high with confirmation
  PULLBACK_TO_EMA      — pullback into EMA20 inside an uptrend

Plus the SHORT-side mirror (PE-buy direction):
  TREND_BREAKDOWN
  BREAKDOWN_RETEST
  RALLY_TO_RESISTANCE

For Nifty / Bank Nifty (where option chain is available) the signal is
biased by the option-chain summary: bullish chain bias adds points to LONG
setups and subtracts from SHORT, and vice versa. Sensex (no NSE chain) is
graded purely on price action.

Pure: no DB, no I/O. Returns dataclass `IndexSignalRecord`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from .indicators import compute_all, latest_indicator_dict
from .regime import classify
from . import patterns


CATEGORIES = (
    "TREND_CONTINUATION",
    "BREAKOUT_RETEST",
    "PULLBACK_TO_EMA",
    "TREND_BREAKDOWN",
    "BREAKDOWN_RETEST",
    "RALLY_TO_RESISTANCE",
)


@dataclass
class IndexTradePlan:
    """Spot-level plan. Option strike + premium-level plan are derived later."""
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    invalidation: float


@dataclass
class IndexSignalRecord:
    symbol: str
    code: str
    as_of_date: date
    category: str
    direction: str          # LONG | SHORT
    score: float
    confidence: float
    spot: float
    reasons: List[str] = field(default_factory=list)
    plan: Optional[IndexTradePlan] = None
    indicators: Dict = field(default_factory=dict)
    regime: str = "RANGE"
    option_chain_bias: Optional[str] = None
    option_chain_strength: float = 0.0


def _safe(val) -> Optional[float]:
    if val is None or pd.isna(val):
        return None
    return float(val)


def _long_plan(close: float, atr: float, *, stop_mult: float, rr1: float, rr2: float) -> IndexTradePlan:
    stop = close - stop_mult * atr
    risk = close - stop
    return IndexTradePlan(
        entry=round(close, 2),
        stop_loss=round(stop, 2),
        target_1=round(close + risk * rr1, 2),
        target_2=round(close + risk * rr2, 2),
        invalidation=round(stop, 2),
    )


def _short_plan(close: float, atr: float, *, stop_mult: float, rr1: float, rr2: float) -> IndexTradePlan:
    stop = close + stop_mult * atr
    risk = stop - close
    return IndexTradePlan(
        entry=round(close, 2),
        stop_loss=round(stop, 2),
        target_1=round(close - risk * rr1, 2),
        target_2=round(close - risk * rr2, 2),
        invalidation=round(stop, 2),
    )


def _score(reasons: List[str], cap: int = 5) -> float:
    if not reasons:
        return 0.0
    return min(100.0, (len(reasons) / cap) * 100.0)


def _confidence(reasons: List[str], required: int = 3) -> float:
    return round(min(1.0, len(reasons) / required), 2)


def _apply_chain_bias(
    score: float,
    direction: str,
    chain_bias: Optional[str],
    chain_strength: float,
) -> float:
    """Boost or penalise score by option-chain bias when available.

    Range: ±15 score points scaled by chain_strength (0..1).
    """
    if chain_bias is None or chain_strength <= 0:
        return score
    delta = 15.0 * chain_strength
    bullish = chain_bias == "Bullish"
    bearish = chain_bias == "Bearish"
    if direction == "LONG":
        if bullish:
            score += delta
        elif bearish:
            score -= delta
    else:
        if bearish:
            score += delta
        elif bullish:
            score -= delta
    return max(0.0, min(100.0, score))


def evaluate_index(
    symbol: str,
    code: str,
    df_raw: pd.DataFrame,
    *,
    chain_bias: Optional[str] = None,
    chain_strength: float = 0.0,
    chain_notes: Optional[List[str]] = None,
) -> List[IndexSignalRecord]:
    """Run all rules for one index's daily OHLCV. Returns matching records only."""
    if df_raw is None or df_raw.empty or len(df_raw) < 60:
        return []

    df = compute_all(df_raw)
    last = df.iloc[-1]
    as_of = pd.Timestamp(df.index[-1]).date()
    close = float(last["close"])
    atr_v = _safe(last.get("atr14"))
    atr_pct = _safe(last.get("atr_pct"))
    rsi_v = _safe(last.get("rsi14"))
    adx_v = _safe(last.get("adx"))
    macd_h = _safe(last.get("macd_hist"))
    ret20 = _safe(last.get("return_20d"))
    pct_from_high = _safe(last.get("pct_from_52w_high"))

    regime, _ = classify(df)
    pat = patterns.detect_all(df)
    indicators_dict = latest_indicator_dict(df)
    out: List[IndexSignalRecord] = []
    chain_notes = chain_notes or []

    # ----- LONG: TREND_CONTINUATION -----
    reasons: List[str] = []
    if regime in ("UPTREND", "STRONG_UPTREND"):
        reasons.append(f"Regime {regime}")
    if rsi_v is not None and 50 <= rsi_v <= 72:
        reasons.append(f"RSI {rsi_v:.0f} in momentum zone")
    if macd_h is not None and macd_h > 0:
        reasons.append("MACD histogram positive")
    if adx_v is not None and adx_v >= 22:
        reasons.append(f"ADX {adx_v:.0f} (trending)")
    if ret20 is not None and ret20 > 1.5:
        reasons.append(f"20-day return {ret20:.1f}%")
    if chain_bias == "Bullish" and chain_strength > 0.3:
        reasons.extend([f"Option chain bullish: {n}" for n in chain_notes[:1]])
    if len(reasons) >= 3 and atr_v is not None:
        score = _score(reasons, cap=5)
        score = _apply_chain_bias(score, "LONG", chain_bias, chain_strength)
        plan = _long_plan(close, atr_v, stop_mult=1.5, rr1=1.5, rr2=3.0)
        out.append(IndexSignalRecord(
            symbol=symbol, code=code, as_of_date=as_of, category="TREND_CONTINUATION",
            direction="LONG",
            score=round(score, 2), confidence=_confidence(reasons),
            spot=close, reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
            option_chain_bias=chain_bias, option_chain_strength=chain_strength,
        ))

    # ----- LONG: BREAKOUT_RETEST -----
    reasons = []
    if pat.get("breakout_20d"):
        reasons.append("Closed above 20-day high")
    if pat.get("breakout_55d"):
        reasons.append("Closed above 55-day high")
    if regime in ("UPTREND", "STRONG_UPTREND"):
        reasons.append(f"Uptrend regime {regime}")
    if macd_h is not None and macd_h > 0:
        reasons.append("MACD bullish")
    if pct_from_high is not None and pct_from_high > -2.0:
        reasons.append("At/near 52-week high")
    if chain_bias == "Bullish" and chain_strength > 0.4:
        reasons.append("Option chain reinforces breakout")
    if pat.get("breakout_20d") and len(reasons) >= 2 and atr_v is not None:
        score = _score(reasons, cap=5)
        score = _apply_chain_bias(score, "LONG", chain_bias, chain_strength)
        plan = _long_plan(close, atr_v, stop_mult=1.2, rr1=1.5, rr2=2.5)
        out.append(IndexSignalRecord(
            symbol=symbol, code=code, as_of_date=as_of, category="BREAKOUT_RETEST",
            direction="LONG",
            score=round(score, 2), confidence=_confidence(reasons),
            spot=close, reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
            option_chain_bias=chain_bias, option_chain_strength=chain_strength,
        ))

    # ----- LONG: PULLBACK_TO_EMA -----
    reasons = []
    if pat.get("pullback"):
        reasons.append("Pullback to EMA20/EMA50 in uptrend")
    if rsi_v is not None and 42 <= rsi_v <= 58:
        reasons.append(f"RSI {rsi_v:.0f} cooled off")
    if pat.get("bullish_engulfing") or pat.get("hammer"):
        reasons.append("Bullish reversal candle")
    if regime in ("UPTREND", "STRONG_UPTREND"):
        reasons.append("Uptrend intact")
    if pat.get("pullback") and len(reasons) >= 2 and atr_v is not None:
        score = _score(reasons, cap=4)
        score = _apply_chain_bias(score, "LONG", chain_bias, chain_strength)
        plan = _long_plan(close, atr_v, stop_mult=1.3, rr1=1.5, rr2=3.0)
        out.append(IndexSignalRecord(
            symbol=symbol, code=code, as_of_date=as_of, category="PULLBACK_TO_EMA",
            direction="LONG",
            score=round(score, 2), confidence=_confidence(reasons),
            spot=close, reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
            option_chain_bias=chain_bias, option_chain_strength=chain_strength,
        ))

    # ----- SHORT: TREND_BREAKDOWN -----
    reasons = []
    if regime in ("DOWNTREND", "STRONG_DOWNTREND"):
        reasons.append(f"Regime {regime}")
    if rsi_v is not None and 28 <= rsi_v <= 50:
        reasons.append(f"RSI {rsi_v:.0f} weak")
    if macd_h is not None and macd_h < 0:
        reasons.append("MACD histogram negative")
    if adx_v is not None and adx_v >= 22:
        reasons.append(f"ADX {adx_v:.0f} (trending)")
    if ret20 is not None and ret20 < -1.5:
        reasons.append(f"20-day return {ret20:.1f}%")
    if chain_bias == "Bearish" and chain_strength > 0.3:
        reasons.extend([f"Option chain bearish: {n}" for n in chain_notes[:1]])
    if len(reasons) >= 3 and atr_v is not None:
        score = _score(reasons, cap=5)
        score = _apply_chain_bias(score, "SHORT", chain_bias, chain_strength)
        plan = _short_plan(close, atr_v, stop_mult=1.5, rr1=1.5, rr2=3.0)
        out.append(IndexSignalRecord(
            symbol=symbol, code=code, as_of_date=as_of, category="TREND_BREAKDOWN",
            direction="SHORT",
            score=round(score, 2), confidence=_confidence(reasons),
            spot=close, reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
            option_chain_bias=chain_bias, option_chain_strength=chain_strength,
        ))

    # ----- SHORT: BREAKDOWN_RETEST -----
    reasons = []
    if pat.get("bearish_reversal"):
        reasons.append("Lower-highs + RSI rolling over")
    if pat.get("bearish_engulfing"):
        reasons.append("Bearish engulfing candle")
    if regime in ("DOWNTREND", "STRONG_DOWNTREND"):
        reasons.append(f"Downtrend regime {regime}")
    if macd_h is not None and macd_h < 0:
        reasons.append("MACD bearish")
    if chain_bias == "Bearish" and chain_strength > 0.4:
        reasons.append("Option chain reinforces breakdown")
    if (pat.get("bearish_reversal") or pat.get("bearish_engulfing")) and len(reasons) >= 2 and atr_v is not None:
        score = _score(reasons, cap=5)
        score = _apply_chain_bias(score, "SHORT", chain_bias, chain_strength)
        plan = _short_plan(close, atr_v, stop_mult=1.2, rr1=1.5, rr2=2.5)
        out.append(IndexSignalRecord(
            symbol=symbol, code=code, as_of_date=as_of, category="BREAKDOWN_RETEST",
            direction="SHORT",
            score=round(score, 2), confidence=_confidence(reasons),
            spot=close, reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
            option_chain_bias=chain_bias, option_chain_strength=chain_strength,
        ))

    # ----- SHORT: RALLY_TO_RESISTANCE -----
    reasons = []
    if regime in ("DOWNTREND", "STRONG_DOWNTREND"):
        reasons.append(f"Regime {regime}")
    if rsi_v is not None and 55 <= rsi_v <= 68:
        reasons.append(f"RSI {rsi_v:.0f} bouncing into resistance")
    if pat.get("bearish_engulfing") or pat.get("bearish_reversal"):
        reasons.append("Bearish reversal at the level")
    if len(reasons) >= 2 and atr_v is not None:
        score = _score(reasons, cap=4)
        score = _apply_chain_bias(score, "SHORT", chain_bias, chain_strength)
        plan = _short_plan(close, atr_v, stop_mult=1.3, rr1=1.5, rr2=3.0)
        out.append(IndexSignalRecord(
            symbol=symbol, code=code, as_of_date=as_of, category="RALLY_TO_RESISTANCE",
            direction="SHORT",
            score=round(score, 2), confidence=_confidence(reasons),
            spot=close, reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
            option_chain_bias=chain_bias, option_chain_strength=chain_strength,
        ))

    return out


def signal_to_dict(rec: IndexSignalRecord) -> dict:
    plan = rec.plan
    return {
        "symbol": rec.symbol,
        "as_of_date": rec.as_of_date,
        "category": rec.category,
        "direction": rec.direction,
        "score": rec.score,
        "confidence": rec.confidence,
        "spot": rec.spot,
        "entry": plan.entry if plan else None,
        "stop_loss": plan.stop_loss if plan else None,
        "target_1": plan.target_1 if plan else None,
        "target_2": plan.target_2 if plan else None,
        "invalidation": plan.invalidation if plan else None,
        "reasons_json": rec.reasons,
        "option_chain_bias": rec.option_chain_bias,
    }
