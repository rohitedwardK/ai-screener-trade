"""Recent close/SMA20 crossings and observed follow-through, in both directions."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import sma


def recent_ma20_crossing(raw: pd.DataFrame, lookback: int = 3) -> dict | None:
    if not 1 <= lookback <= 10:
        raise ValueError("lookback must be between 1 and 10 sessions")
    if len(raw) < 20 + lookback or raw.index.has_duplicates:
        return None
    frame = raw.sort_index()
    recent = frame.iloc[-(20 + lookback):]
    values = recent[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (recent[["open", "high", "low", "close"]] <= 0).any().any() or (recent["volume"] < 0).any():
        return None
    close = frame["close"]
    average = sma(close, 20)
    difference = close - average
    for age in range(lookback):
        i = len(frame) - 1 - age
        current, previous = difference.iloc[i], difference.iloc[i - 1]
        sign = 1 if current > 0 and previous <= 0 else -1 if current < 0 and previous >= 0 else 0
        if not sign:
            continue
        # A touch or recross cancels this setup, even if the last candle recovered.
        if not (sign * difference.iloc[i:] > 0).all():
            return None
        cross_close, latest_close = float(close.iloc[i]), float(close.iloc[-1])
        continued = bool(age > 0 and sign * (latest_close - cross_close) > 0
                         and sign * (latest_close - close.iloc[-2]) > 0)
        volume_mean = float(frame["volume"].iloc[-20:].mean())
        return {
            "direction": "UP" if sign > 0 else "DOWN",
            "crossed_at": frame.index[i].date().isoformat(),
            "as_of": frame.index[-1].date().isoformat(),
            "sessions_since_cross": age,
            "status": "CONTINUING" if continued else "AWAITING_FOLLOW_THROUGH",
            "close": latest_close, "cross_close": cross_close,
            "ma20": float(average.iloc[-1]),
            "invalidation": float(average.iloc[-1]),
            "distance_pct": (latest_close / average.iloc[-1] - 1) * 100,
            "since_cross_pct": (latest_close / cross_close - 1) * 100,
            "daily_return_pct": (latest_close / close.iloc[-2] - 1) * 100,
            "relative_volume": float(frame["volume"].iloc[-1] / volume_mean) if volume_mean > 0 else None,
        }
    return None
