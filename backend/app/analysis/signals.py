"""Rule-based signal generator.

Maps technical state -> categories that answer the user's 10 questions:
  MOMENTUM_LEADER         -> Q1
  FRESH_BREAKOUT          -> Q2
  PULLBACK_ENTRY          -> Q3
  OVERSOLD_RECOVERING     -> Q4
  OVERBOUGHT_AVOID        -> Q5
  WEAK_AVOID              -> Q6
  HIGH_RISK               -> Q7
  SWING_NEXT_WEEK         -> Q8
  INTRADAY_WATCH_TOMORROW -> Q9
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from . import patterns
from .indicators import compute_all, latest_indicator_dict
from .regime import classify
from .risk import TradePlan, long_plan, short_plan


CATEGORIES = [
    "MOMENTUM_LEADER",
    "FRESH_BREAKOUT",
    "PULLBACK_ENTRY",
    "OVERSOLD_RECOVERING",
    "OVERBOUGHT_AVOID",
    "WEAK_AVOID",
    "HIGH_RISK",
    "SWING_NEXT_WEEK",
    "INTRADAY_WATCH_TOMORROW",
]


@dataclass
class SignalRecord:
    symbol: str
    as_of_date: date
    category: str
    score: float
    confidence: float
    reasons: List[str] = field(default_factory=list)
    plan: Optional[TradePlan] = None
    indicators: Dict = field(default_factory=dict)
    regime: str = "RANGE"


def _safe(val) -> Optional[float]:
    if val is None or pd.isna(val):
        return None
    return float(val)


def _score_from_reasons(reasons: List[str], cap: int = 5) -> float:
    """Convert N supporting rules into a 0..100 score."""
    if not reasons:
        return 0.0
    return min(100.0, (len(reasons) / cap) * 100.0)


def _confidence(reasons: List[str], required: int = 3) -> float:
    """Confidence = min(1, supporting_rules / required)."""
    return round(min(1.0, len(reasons) / required), 2)


def evaluate_symbol(
    symbol: str,
    df_raw: pd.DataFrame,
    df_enriched: pd.DataFrame | None = None,
) -> List[SignalRecord]:
    """Run all rules for a single symbol's OHLCV history.

    If `df_enriched` is supplied it is used as-is (saves a second pass over
    the indicator pipeline). Otherwise indicators are computed from `df_raw`.
    """
    if df_raw is None or df_raw.empty or len(df_raw) < 60:
        return []

    df = df_enriched if df_enriched is not None else compute_all(df_raw)
    last = df.iloc[-1]
    as_of = pd.Timestamp(df.index[-1]).date()
    close = float(last["close"])
    atr_v = _safe(last.get("atr14"))
    atr_pct = _safe(last.get("atr_pct"))
    rsi_v = _safe(last.get("rsi14"))
    adx_v = _safe(last.get("adx"))
    macd_h = _safe(last.get("macd_hist"))
    ret20 = _safe(last.get("return_20d"))
    ret60 = _safe(last.get("return_60d"))
    pct_from_high = _safe(last.get("pct_from_52w_high"))
    vol_ratio = _safe(last.get("vol_ratio"))

    regime, _detail = classify(df)
    pat = patterns.detect_all(df)
    indicators_dict = latest_indicator_dict(df)
    out: List[SignalRecord] = []

    # ----- MOMENTUM_LEADER -----
    reasons: List[str] = []
    if regime in ("STRONG_UPTREND", "UPTREND"):
        reasons.append(f"Regime is {regime}")
    if ret20 is not None and ret20 > 5:
        reasons.append(f"20-day return {ret20:.1f}%")
    if ret60 is not None and ret60 > 10:
        reasons.append(f"60-day return {ret60:.1f}%")
    if rsi_v is not None and 55 <= rsi_v <= 75:
        reasons.append(f"RSI {rsi_v:.0f} in momentum zone")
    if adx_v is not None and adx_v >= 25:
        reasons.append(f"Strong trend (ADX {adx_v:.0f})")
    if pct_from_high is not None and pct_from_high > -5:
        reasons.append("Within 5% of 52-week high")
    if len(reasons) >= 3 and atr_v is not None:
        plan = long_plan(close, atr_v, stop_mult=2.0)
        out.append(SignalRecord(
            symbol=symbol, as_of_date=as_of, category="MOMENTUM_LEADER",
            score=_score_from_reasons(reasons, cap=5),
            confidence=_confidence(reasons),
            reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
        ))

    # ----- FRESH_BREAKOUT -----
    reasons = []
    if pat["breakout_20d"]:
        reasons.append("Closed above 20-day high")
    if pat["breakout_55d"]:
        reasons.append("Closed above 55-day high")
    if pat["volume_surge"]:
        reasons.append("Volume surge >=2x")
    elif vol_ratio is not None and vol_ratio >= 1.3:
        reasons.append(f"Volume {vol_ratio:.1f}x average")
    if regime in ("UPTREND", "STRONG_UPTREND"):
        reasons.append("In uptrend regime")
    if macd_h is not None and macd_h > 0:
        reasons.append("MACD histogram positive")
    if (pat["breakout_20d"] or pat["breakout_55d"]) and len(reasons) >= 2 and atr_v is not None:
        plan = long_plan(close, atr_v, stop_mult=1.5)
        out.append(SignalRecord(
            symbol=symbol, as_of_date=as_of, category="FRESH_BREAKOUT",
            score=_score_from_reasons(reasons, cap=5),
            confidence=_confidence(reasons),
            reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
        ))

    # ----- PULLBACK_ENTRY -----
    reasons = []
    if pat["pullback"]:
        reasons.append("Pullback to EMA20/EMA50 in uptrend")
    if rsi_v is not None and 40 <= rsi_v <= 55:
        reasons.append(f"RSI {rsi_v:.0f} cooled off")
    if pat["bullish_engulfing"] or pat["hammer"]:
        reasons.append("Bullish reversal candle")
    if regime in ("UPTREND", "STRONG_UPTREND"):
        reasons.append("Uptrend intact")
    if pat["pullback"] and len(reasons) >= 2 and atr_v is not None:
        plan = long_plan(close, atr_v, stop_mult=1.5)
        out.append(SignalRecord(
            symbol=symbol, as_of_date=as_of, category="PULLBACK_ENTRY",
            score=_score_from_reasons(reasons, cap=4),
            confidence=_confidence(reasons),
            reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
        ))

    # ----- OVERSOLD_RECOVERING -----
    reasons = []
    if pat["oversold_bounce"]:
        reasons.append("RSI bounced from <30")
    if pat["bullish_engulfing"] or pat["hammer"]:
        reasons.append("Reversal candle")
    if regime not in ("STRONG_DOWNTREND",):
        reasons.append(f"Regime {regime} (not strong downtrend)")
    if vol_ratio is not None and vol_ratio >= 1.2:
        reasons.append(f"Volume confirmation {vol_ratio:.1f}x")
    if pat["oversold_bounce"] and len(reasons) >= 2 and atr_v is not None:
        plan = long_plan(close, atr_v, stop_mult=1.5)
        out.append(SignalRecord(
            symbol=symbol, as_of_date=as_of, category="OVERSOLD_RECOVERING",
            score=_score_from_reasons(reasons, cap=4),
            confidence=_confidence(reasons),
            reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
        ))

    # ----- OVERBOUGHT_AVOID -----
    reasons = []
    if rsi_v is not None and rsi_v >= 75:
        reasons.append(f"RSI overheated at {rsi_v:.0f}")
    if pct_from_high is not None and pct_from_high > -1 and ret20 is not None and ret20 > 15:
        reasons.append("Vertical move into 52w-high")
    if last.get("bb_upper") is not None and close > float(last.get("bb_upper", close)):
        reasons.append("Closed above upper Bollinger band")
    if ret60 is not None and ret60 > 40:
        reasons.append(f"60-day return very high ({ret60:.0f}%)")
    if len(reasons) >= 2:
        out.append(SignalRecord(
            symbol=symbol, as_of_date=as_of, category="OVERBOUGHT_AVOID",
            score=_score_from_reasons(reasons, cap=3),
            confidence=_confidence(reasons, required=2),
            reasons=reasons, plan=None,
            indicators=indicators_dict, regime=regime,
        ))

    # ----- WEAK_AVOID -----
    reasons = []
    if regime in ("DOWNTREND", "STRONG_DOWNTREND"):
        reasons.append(f"Regime {regime}")
    if rsi_v is not None and rsi_v < 40:
        reasons.append(f"RSI weak {rsi_v:.0f}")
    if ret20 is not None and ret20 < -5:
        reasons.append(f"20-day return {ret20:.1f}%")
    if pat["bearish_reversal"] or pat["bearish_engulfing"]:
        reasons.append("Bearish reversal pattern")
    if len(reasons) >= 2 and atr_v is not None:
        plan = short_plan(close, atr_v)
        out.append(SignalRecord(
            symbol=symbol, as_of_date=as_of, category="WEAK_AVOID",
            score=_score_from_reasons(reasons, cap=4),
            confidence=_confidence(reasons),
            reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
        ))

    # ----- HIGH_RISK -----
    reasons = []
    if atr_pct is not None and atr_pct >= 4.5:
        reasons.append(f"ATR% {atr_pct:.1f} (elevated volatility)")
    if regime == "VOLATILE":
        reasons.append("Volatile regime")
    if vol_ratio is not None and vol_ratio < 0.5:
        reasons.append("Volume drying up")
    if last.get("bb_width") is not None and float(last["bb_width"]) > 0.20:
        reasons.append("Bollinger band width wide")
    if reasons:
        out.append(SignalRecord(
            symbol=symbol, as_of_date=as_of, category="HIGH_RISK",
            score=_score_from_reasons(reasons, cap=3),
            confidence=_confidence(reasons, required=2),
            reasons=reasons, plan=None,
            indicators=indicators_dict, regime=regime,
        ))

    # ----- SWING_NEXT_WEEK -----
    reasons = []
    if regime in ("UPTREND", "STRONG_UPTREND"):
        reasons.append(f"Regime {regime}")
    if rsi_v is not None and 45 <= rsi_v <= 65:
        reasons.append(f"RSI {rsi_v:.0f} healthy")
    if macd_h is not None and macd_h > 0:
        reasons.append("MACD bullish")
    if atr_pct is not None and 1.5 <= atr_pct <= 4.0:
        reasons.append(f"ATR% {atr_pct:.1f} actionable")
    if pat["pullback"] or pat["breakout_20d"] or pat["bullish_engulfing"]:
        reasons.append("Setup present (pullback / breakout / engulfing)")
    if len(reasons) >= 3 and atr_v is not None:
        plan = long_plan(close, atr_v, stop_mult=1.5)
        out.append(SignalRecord(
            symbol=symbol, as_of_date=as_of, category="SWING_NEXT_WEEK",
            score=_score_from_reasons(reasons, cap=5),
            confidence=_confidence(reasons),
            reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
        ))

    # ----- INTRADAY_WATCH_TOMORROW -----
    reasons = []
    if vol_ratio is not None and vol_ratio >= 1.5:
        reasons.append(f"High volume {vol_ratio:.1f}x")
    if atr_pct is not None and atr_pct >= 1.5:
        reasons.append(f"Sufficient range (ATR% {atr_pct:.1f})")
    if pat["breakout_20d"] or pat["bullish_engulfing"] or pat["bearish_engulfing"]:
        reasons.append("Pattern primed")
    if regime in ("STRONG_UPTREND", "UPTREND", "STRONG_DOWNTREND", "DOWNTREND"):
        reasons.append(f"Directional regime {regime}")
    if len(reasons) >= 3 and atr_v is not None:
        plan = long_plan(close, atr_v, stop_mult=1.0, rr1=1.0, rr2=2.0)
        out.append(SignalRecord(
            symbol=symbol, as_of_date=as_of, category="INTRADAY_WATCH_TOMORROW",
            score=_score_from_reasons(reasons, cap=4),
            confidence=_confidence(reasons),
            reasons=reasons, plan=plan,
            indicators=indicators_dict, regime=regime,
        ))

    return out


def signal_to_dict(rec: SignalRecord) -> dict:
    """Convert SignalRecord -> ORM-ready dict for repository.save_signals()."""
    plan = rec.plan
    return {
        "symbol": rec.symbol,
        "as_of_date": rec.as_of_date,
        "category": rec.category,
        "score": rec.score,
        "confidence": rec.confidence,
        "entry": plan.entry if plan else None,
        "stop_loss": plan.stop_loss if plan else None,
        "target_1": plan.target_1 if plan else None,
        "target_2": plan.target_2 if plan else None,
        "invalidation": plan.invalidation if plan else None,
        "reasons_json": rec.reasons,
    }
