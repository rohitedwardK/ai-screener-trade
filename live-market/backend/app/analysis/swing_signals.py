"""Swing setup catalog (TRENDING_UP / TRENDING_DOWN regime, 2-3 day hold).

Reuses the daily OHLCV CSV cache populated by the parent app's daily
refresh job (env `INDEX_DATA_DIR`). The intraday regime is the gate:
we only emit when the daily setup direction matches the live intraday
regime, so the operator never gets a "buy the dip" plan during a clear
intraday breakdown.

Categories:

  TREND_CONTINUATION     daily uptrend + intraday TRENDING_UP
  BREAKOUT_PULLBACK      breakout to new 20-day highs + intraday up
  TREND_BREAKDOWN        daily downtrend + intraday TRENDING_DOWN
  BREAKDOWN_PULLBACK     breakdown to new 20-day lows + intraday down

Plan sizing for the 2-3 day horizon:

  stop = SWING_STOP_ATR_MULT * daily_ATR
  T1   = SWING_T1_ATR_MULT   * daily_ATR
  T2   = SWING_TARGET_ATR_MULT * daily_ATR

Each record includes `days_to_expiry` so the strike picker can size the
option leg appropriately.

Pure: no DB, no I/O. The daily DataFrame is supplied by `daily_loader`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from ..config import get_settings
from . import indicators
from .market_regime import REGIME_TRENDING_DOWN, REGIME_TRENDING_UP


@dataclass(frozen=True)
class SwingSetupRecord:
    symbol: str
    category: str
    direction: str          # LONG | SHORT
    score: float
    spot_entry: float
    spot_stop: float
    spot_t1: float
    spot_t2: float
    spot_invalidation: float
    days_to_expiry: int
    reasons: List[str] = field(default_factory=list)


def _round(x: float) -> float:
    return round(float(x), 2)


def _long_plan(spot: float, atr_d: float) -> tuple[float, float, float, float]:
    cfg = get_settings()
    stop = spot - cfg.SWING_STOP_ATR_MULT * atr_d
    t1 = spot + cfg.SWING_T1_ATR_MULT * atr_d
    t2 = spot + cfg.SWING_TARGET_ATR_MULT * atr_d
    return _round(spot), _round(stop), _round(t1), _round(t2)


def _short_plan(spot: float, atr_d: float) -> tuple[float, float, float, float]:
    cfg = get_settings()
    stop = spot + cfg.SWING_STOP_ATR_MULT * atr_d
    t1 = spot - cfg.SWING_T1_ATR_MULT * atr_d
    t2 = spot - cfg.SWING_TARGET_ATR_MULT * atr_d
    return _round(spot), _round(stop), _round(t1), _round(t2)


def _score(reasons: List[str], cap: int = 5) -> float:
    if not reasons:
        return 0.0
    return min(100.0, (len(reasons) / cap) * 100.0)


def _enrich_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Add the indicator columns we need without pulling in the parent
    `compute_all` (which depends on pivots).
    """
    out = df.copy()
    out["ema20"] = indicators.ema(df["close"], 20)
    out["ema50"] = indicators.ema(df["close"], 50)
    out["rsi14"] = indicators.rsi(df["close"], 14)
    macd_df = indicators.macd(df["close"])
    out["macd_hist"] = macd_df["hist"]
    adx_df = indicators.adx(df, 14)
    out["adx"] = adx_df["adx"]
    out["+di"] = adx_df["+di"]
    out["-di"] = adx_df["-di"]
    out["atr14"] = indicators.atr(df, 14)
    out["high_20"] = df["high"].rolling(window=20, min_periods=20).max()
    out["low_20"] = df["low"].rolling(window=20, min_periods=20).min()
    return out


def evaluate(
    symbol: str,
    daily_df: pd.DataFrame,
    *,
    intraday_regime: str,
    live_spot: Optional[float] = None,
) -> List[SwingSetupRecord]:
    """Run the swing catalog.

    Args:
        symbol           - yahoo ticker like ^NSEI
        daily_df         - daily OHLCV from INDEX_DATA_DIR; ASC time, lowercase cols
        intraday_regime  - current intraday regime label (gate)
        live_spot        - optional override for the entry price; if None we
                           use the latest daily close. Operators want plans
                           anchored on the live price, not the previous close.

    Returns matching records only. Empty list on insufficient data or
    when intraday/daily directions disagree.
    """
    out: List[SwingSetupRecord] = []
    if daily_df is None or daily_df.empty or len(daily_df) < 50:
        return out
    if intraday_regime not in (REGIME_TRENDING_UP, REGIME_TRENDING_DOWN):
        return out

    df = _enrich_daily(daily_df)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    atr_d = float(last["atr14"]) if pd.notna(last["atr14"]) else 0.0
    if atr_d <= 0:
        return out

    spot = float(live_spot) if live_spot and live_spot > 0 else float(last["close"])
    rsi_v = float(last["rsi14"]) if pd.notna(last["rsi14"]) else 50.0
    adx_v = float(last["adx"]) if pd.notna(last["adx"]) else 0.0
    macd_h = float(last["macd_hist"]) if pd.notna(last["macd_hist"]) else 0.0
    ema20 = float(last["ema20"]) if pd.notna(last["ema20"]) else spot
    ema50 = float(last["ema50"]) if pd.notna(last["ema50"]) else spot
    high_20_prev = float(prev["high_20"]) if pd.notna(prev["high_20"]) else float("inf")
    low_20_prev = float(prev["low_20"]) if pd.notna(prev["low_20"]) else float("-inf")

    cfg = get_settings()
    dte = max(int(cfg.SWING_HORIZON_DAYS), 1)

    # ---- LONG side (only when intraday is trending up) ----
    if intraday_regime == REGIME_TRENDING_UP:
        # TREND_CONTINUATION
        if ema20 > ema50 and 50 <= rsi_v <= 72 and macd_h > 0 and adx_v >= 22:
            reasons = [
                "daily EMA20 > EMA50 (uptrend)",
                f"RSI {rsi_v:.0f} in momentum zone",
                "MACD histogram positive",
                f"ADX {adx_v:.0f} (trending)",
                "intraday regime TRENDING_UP confirms direction",
            ]
            entry, stop, t1, t2 = _long_plan(spot, atr_d)
            out.append(SwingSetupRecord(
                symbol=symbol, category="TREND_CONTINUATION", direction="LONG",
                score=_score(reasons),
                spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
                spot_invalidation=stop, days_to_expiry=dte, reasons=reasons,
            ))
        # BREAKOUT_PULLBACK
        if (
            float(last["close"]) > high_20_prev
            and ema20 > ema50
            and macd_h > 0
        ):
            reasons = [
                f"closed above 20-day high {high_20_prev:.2f}",
                "daily EMA20 > EMA50",
                "MACD histogram positive",
                "intraday regime TRENDING_UP",
            ]
            entry, stop, t1, t2 = _long_plan(spot, atr_d)
            out.append(SwingSetupRecord(
                symbol=symbol, category="BREAKOUT_PULLBACK", direction="LONG",
                score=_score(reasons),
                spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
                spot_invalidation=stop, days_to_expiry=dte, reasons=reasons,
            ))

    # ---- SHORT side (only when intraday is trending down) ----
    if intraday_regime == REGIME_TRENDING_DOWN:
        # TREND_BREAKDOWN
        if ema20 < ema50 and 28 <= rsi_v <= 50 and macd_h < 0 and adx_v >= 22:
            reasons = [
                "daily EMA20 < EMA50 (downtrend)",
                f"RSI {rsi_v:.0f} weak",
                "MACD histogram negative",
                f"ADX {adx_v:.0f} (trending)",
                "intraday regime TRENDING_DOWN confirms direction",
            ]
            entry, stop, t1, t2 = _short_plan(spot, atr_d)
            out.append(SwingSetupRecord(
                symbol=symbol, category="TREND_BREAKDOWN", direction="SHORT",
                score=_score(reasons),
                spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
                spot_invalidation=stop, days_to_expiry=dte, reasons=reasons,
            ))
        # BREAKDOWN_PULLBACK
        if (
            float(last["close"]) < low_20_prev
            and ema20 < ema50
            and macd_h < 0
        ):
            reasons = [
                f"closed below 20-day low {low_20_prev:.2f}",
                "daily EMA20 < EMA50",
                "MACD histogram negative",
                "intraday regime TRENDING_DOWN",
            ]
            entry, stop, t1, t2 = _short_plan(spot, atr_d)
            out.append(SwingSetupRecord(
                symbol=symbol, category="BREAKDOWN_PULLBACK", direction="SHORT",
                score=_score(reasons),
                spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
                spot_invalidation=stop, days_to_expiry=dte, reasons=reasons,
            ))

    return out


__all__ = ["SwingSetupRecord", "evaluate"]
