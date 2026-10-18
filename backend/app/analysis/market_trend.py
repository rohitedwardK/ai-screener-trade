"""Price-action market trend classifier for dashboard briefings."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd


@dataclass(frozen=True)
class MarketTrendResult:
    trend: str
    label: str
    daily_state: str
    weekly_state: str
    basis: List[str] = field(default_factory=list)
    symbol: str = "^NSEI"
    close: Optional[float] = None
    previous_high: Optional[float] = None
    previous_low: Optional[float] = None


def _clean_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    out = df.copy()
    out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    return out.dropna(subset=["high", "low", "close"])


def _daily_state(latest: pd.Series, previous: pd.Series) -> str:
    broke_high = float(latest["high"]) > float(previous["high"])
    broke_low = float(latest["low"]) < float(previous["low"])

    if broke_high and not broke_low:
        return "UP_BREAKOUT"
    if broke_low and not broke_high:
        return "DOWN_BREAKDOWN"
    if not broke_high and not broke_low:
        return "INSIDE_RANGE"
    close = float(latest["close"])
    if close > float(previous["high"]):
        return "BULLISH_EXPANSION"
    if close < float(previous["low"]):
        return "BEARISH_EXPANSION"
    return "TWO_WAY_VOLATILE"


def _weekly_state(df: pd.DataFrame, lookback: int = 3) -> str:
    weekly = (
        df[["open", "high", "low", "close"]]
        .resample("W-FRI")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
    )
    if len(weekly) < lookback + 1:
        return "MIXED"

    recent = weekly.tail(lookback + 1)
    up = 0
    down = 0
    for i in range(1, len(recent)):
        prev = recent.iloc[i - 1]
        cur = recent.iloc[i]
        if float(cur["high"]) > float(prev["high"]) and float(cur["low"]) >= float(prev["low"]):
            up += 1
        elif float(cur["low"]) < float(prev["low"]) and float(cur["high"]) <= float(prev["high"]):
            down += 1

    required = max(2, lookback - 1)
    if up >= required and up > down:
        return "UP"
    if down >= required and down > up:
        return "DOWN"
    return "MIXED"


def classify_market_trend(df: pd.DataFrame, *, symbol: str = "^NSEI") -> MarketTrendResult:
    """Classify trend from prior-day breakout plus multi-week structure.

    The daily rule captures whether price is breaking yesterday's high/low.
    The weekly rule prevents one noisy candle from flipping the dashboard.
    """
    clean = _clean_ohlc(df)
    if len(clean) < 2:
        return MarketTrendResult(
            trend="UNKNOWN",
            label="Unclear",
            daily_state="UNKNOWN",
            weekly_state="MIXED",
            basis=["Need at least two daily candles."],
            symbol=symbol,
        )

    latest = clean.iloc[-1]
    previous = clean.iloc[-2]
    daily = _daily_state(latest, previous)
    weekly = _weekly_state(clean)

    basis = [
        f"Latest high {float(latest['high']):.2f} vs previous high {float(previous['high']):.2f}.",
        f"Latest low {float(latest['low']):.2f} vs previous low {float(previous['low']):.2f}.",
        f"Weekly structure is {weekly.lower()}.",
    ]

    bullish_daily = daily in ("UP_BREAKOUT", "BULLISH_EXPANSION")
    bearish_daily = daily in ("DOWN_BREAKDOWN", "BEARISH_EXPANSION")

    if weekly == "UP" and bullish_daily:
        trend = "UP"
        label = "Uptrend"
    elif weekly == "DOWN" and bearish_daily:
        trend = "DOWN"
        label = "Downtrend"
    elif daily == "TWO_WAY_VOLATILE":
        trend = "VOLATILE"
        label = "Volatile"
    elif daily == "INSIDE_RANGE":
        trend = "MIXED"
        label = "Mixed"
    elif weekly == "UP" and bearish_daily:
        trend = "MIXED"
        label = "Mixed pullback"
    elif weekly == "DOWN" and bullish_daily:
        trend = "MIXED"
        label = "Mixed bounce"
    else:
        trend = "MIXED"
        label = "Mixed"

    return MarketTrendResult(
        trend=trend,
        label=label,
        daily_state=daily,
        weekly_state=weekly,
        basis=basis,
        symbol=symbol,
        close=float(latest["close"]),
        previous_high=float(previous["high"]),
        previous_low=float(previous["low"]),
    )


__all__ = ["MarketTrendResult", "classify_market_trend"]
