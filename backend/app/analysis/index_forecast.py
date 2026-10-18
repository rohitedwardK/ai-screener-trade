"""Deterministic multi-timeframe index forecast for the read-only dashboard."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd


@dataclass
class IndexForecast:
    weekly_bias: str = "Neutral"
    hourly_bias: str = "Neutral"
    fifteen_minute_bias: str = "Neutral"
    next_5m_bias: str = "WAIT"
    setup: str = "NO_TRADE"
    breakout_state: str = "INSIDE_RANGE"
    breakout_level: Optional[float] = None
    breakdown_level: Optional[float] = None
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    invalidation: Optional[float] = None
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)
    as_of: Optional[str] = None


def _bias(close: pd.Series, fast: int, slow: int) -> str:
    values = close.dropna()
    if len(values) < slow:
        return "Neutral"
    fast_ema = float(values.ewm(span=fast, adjust=False).mean().iloc[-1])
    slow_ema = float(values.ewm(span=slow, adjust=False).mean().iloc[-1])
    last = float(values.iloc[-1])
    if last > fast_ema > slow_ema:
        return "Bullish"
    if last < fast_ema < slow_ema:
        return "Bearish"
    return "Neutral"


def evaluate(daily: pd.DataFrame, intraday: pd.DataFrame) -> IndexForecast:
    """Combine completed daily and 5-minute bars without claiming certainty."""
    if daily is None or daily.empty:
        return IndexForecast(cautions=["Daily history is unavailable."])
    daily = daily.sort_index()
    weekly = daily.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    out = IndexForecast(weekly_bias=_bias(weekly["close"], 4, 10))
    if intraday is None or len(intraday.dropna(subset=["close"])) < 8:
        out.cautions.append("Not enough recent 5-minute bars; scalp forecast is withheld.")
        return out

    bars = intraday.sort_index().dropna(subset=["open", "high", "low", "close"])
    hourly = bars.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    out.hourly_bias = _bias(hourly["close"], 3, 8)
    last = float(bars["close"].iloc[-1])
    close_15m_ago = float(bars["close"].iloc[-4]) if len(bars) >= 4 else float(bars["close"].iloc[0])
    move_15m = (last / close_15m_ago - 1.0) * 100.0 if close_15m_ago else 0.0
    out.fifteen_minute_bias = "Bullish" if move_15m > 0.08 else "Bearish" if move_15m < -0.08 else "Flat"
    prior = bars.iloc[-21:-1] if len(bars) >= 21 else bars.iloc[:-1]
    out.breakout_level = round(float(prior["high"].max()), 2)
    out.breakdown_level = round(float(prior["low"].min()), 2)
    atr5 = float((bars["high"] - bars["low"]).tail(14).mean())
    volume_ok = not ("volume" in bars and float(bars["volume"].tail(20).sum()) > 0) or float(bars["volume"].iloc[-1]) >= float(bars["volume"].tail(20).median())
    bullish = last > out.breakout_level and out.hourly_bias == "Bullish" and move_15m > 0
    bearish = last < out.breakdown_level and out.hourly_bias == "Bearish" and move_15m < 0
    aligned = sum((out.weekly_bias == ("Bullish" if bullish else "Bearish"), out.hourly_bias == ("Bullish" if bullish else "Bearish"), (move_15m > 0 if bullish else move_15m < 0)))
    if bullish or bearish:
        direction = "LONG" if bullish else "SHORT"
        sign = 1.0 if bullish else -1.0
        out.setup = f"{direction}_BREAKOUT_SCALP"
        out.breakout_state = "BREAKOUT_CONFIRMED" if volume_ok else "BREAKOUT_UNCONFIRMED"
        out.next_5m_bias = "UP" if bullish else "DOWN"
        out.entry = round(last, 2)
        out.stop_loss = round(last - sign * max(atr5, last * 0.0008), 2)
        out.invalidation = out.stop_loss
        risk = abs(out.entry - out.stop_loss)
        out.target_1 = round(out.entry + sign * risk * 1.2, 2)
        out.target_2 = round(out.entry + sign * risk * 1.8, 2)
        out.confidence = min(90.0, 52.0 + aligned * 10.0 + (8.0 if volume_ok else 0.0))
        out.reasons = [
            f"Price crossed the prior {len(prior)}-bar {'high' if bullish else 'low'} at {out.breakout_level if bullish else out.breakdown_level:.2f}.",
            f"Hourly structure is {out.hourly_bias.lower()} and the last 15-minute move is {move_15m:+.2f}%.",
            "Breakout participation is supported by recent volume." if volume_ok else "Volume has not confirmed the break; wait for follow-through.",
        ]
    else:
        out.reasons = [f"Price remains between {out.breakdown_level:.2f} support and {out.breakout_level:.2f} resistance.", f"Hourly bias is {out.hourly_bias.lower()}; the last 15-minute move is {move_15m:+.2f}%." ]
        out.cautions.append("No confirmed break with timeframe alignment; avoid forcing a scalp.")
    out.as_of = bars.index[-1].isoformat()
    return out


__all__ = ["IndexForecast", "evaluate"]
