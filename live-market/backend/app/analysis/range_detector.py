"""Intraday support / resistance detection.

Pure function. Given a 1-min OHLCV frame for the current session, returns:

    RangeLevels(support, resistance, mid, width_pct, samples_used)

Approach
--------
We use a simple swing-extreme aggregation rather than a clustering model:

  * Compute the rolling N-bar high (`high.rolling(window).max()`) and the
    rolling N-bar low. Where the current bar equals that local extreme,
    mark it as a swing point. Default window = 5.
  * Take the median of the recent K swing highs as resistance, K swing
    lows as support. Median (instead of max/min) is more robust to one
    rogue print at the open.
  * Width = (resistance - support) / mid; useful as a regime gate.

This is intentionally lightweight: range scalps fire many times a session
and need a deterministic, recomputable level - not a full S/R clustering
model that might change its answer on an unrelated bar update.
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
    samples_used: int   # how many swing points contributed


def _swing_highs(df: pd.DataFrame, *, window: int) -> pd.Series:
    """Where each bar's high == the rolling-window max, that bar is a swing high."""
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
    swing_window: int = 5,
    take_recent: int = 10,
) -> Optional[RangeLevels]:
    """Compute current intraday support/resistance.

    Args:
        df            : 1-min OHLCV for the current session, ascending time.
        swing_window  : Bars on each side that the swing must dominate.
        take_recent   : How many of the most recent swings to median-aggregate.

    Returns None when the frame is too short to detect any swing pair.
    """
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
        # Pathological case (e.g. completely flat first hour): force a tiny
        # band around the last close so callers don't have to defensively
        # check NaN/zero everywhere.
        last_close = float(df["close"].iloc[-1])
        resistance = last_close * 1.001
        support = last_close * 0.999

    mid = (resistance + support) / 2.0
    width_pct = (resistance - support) / mid if mid > 0 else 0.0

    return RangeLevels(
        support=round(support, 2),
        resistance=round(resistance, 2),
        mid=round(mid, 2),
        width_pct=float(width_pct),
        samples_used=int(min(len(recent_highs), len(recent_lows))),
    )


def distance_to_edge(price: float, levels: RangeLevels) -> tuple[float, float]:
    """Return (distance_to_support_pct, distance_to_resistance_pct).

    Both expressed as a fraction of `price`. Negative when price has
    already crossed the level - useful to detect false breakouts.
    """
    if price <= 0:
        return 0.0, 0.0
    return (
        (price - levels.support) / price,
        (levels.resistance - price) / price,
    )


__all__ = ["RangeLevels", "detect_range", "distance_to_edge"]
