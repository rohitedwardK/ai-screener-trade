"""Intraday support / resistance on 15-minute bars.

Median of recent swing extremes — same idea as the live-market range
detector but tuned for coarser bars (fewer false swings).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RangeLevels:
    support: float
    resistance: float
    mid: float
    width_pct: float
    samples_used: int


def _swing_highs(df: pd.DataFrame, *, window: int) -> pd.Series:
    rolling_max = df["high"].rolling(window=window, min_periods=window, center=True).max()
    mask = df["high"] >= rolling_max
    return df["high"].where(mask).dropna()


def _swing_lows(df: pd.DataFrame, *, window: int) -> pd.Series:
    rolling_min = df["low"].rolling(window=window, min_periods=window, center=True).min()
    mask = df["low"] <= rolling_min
    return df["low"].where(mask).dropna()


def detect_range(
    df: pd.DataFrame,
    *,
    swing_window: int = 3,
    take_recent: int = 8,
) -> Optional[RangeLevels]:
    """Support/resistance from recent 15m swing points."""
    if df is None or len(df) < swing_window * 2 + 1:
        return None

    highs = _swing_highs(df, window=swing_window)
    lows = _swing_lows(df, window=swing_window)
    if highs.empty or lows.empty:
        return None

    recent_highs = highs.tail(take_recent)
    recent_lows = lows.tail(take_recent)
    resistance = float(np.median(recent_highs.values))
    support = float(np.median(recent_lows.values))
    if resistance <= support:
        last_close = float(df["close"].iloc[-1])
        resistance = last_close * 1.002
        support = last_close * 0.998

    mid = (resistance + support) / 2.0
    width_pct = (resistance - support) / mid if mid > 0 else 0.0
    return RangeLevels(
        support=round(support, 2),
        resistance=round(resistance, 2),
        mid=round(mid, 2),
        width_pct=float(width_pct),
        samples_used=int(min(len(recent_highs), len(recent_lows))),
    )


def session_vwap(df: pd.DataFrame) -> Optional[float]:
    """Volume-weighted average price for the loaded intraday window."""
    if df is None or df.empty or "volume" not in df.columns:
        return None
    vol = df["volume"].astype(float)
    if vol.sum() <= 0:
        return float(df["close"].iloc[-1])
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    return round(float((typical * vol).sum() / vol.sum()), 2)


__all__ = ["RangeLevels", "detect_range", "session_vwap"]
