"""Intraday VWAP - cumulative volume-weighted average price for the session.

Pure function. Takes a 1-minute OHLCV DataFrame and returns a Series of
the same length holding the running VWAP. Typical-price weighting:

    typical = (high + low + close) / 3
    vwap_t  = sum(typical * volume) / sum(volume)   for k in [0, t]

When volume is zero or missing for the whole window we fall back to a
simple cumulative mean of the close so callers always get a number.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def vwap(df: pd.DataFrame) -> pd.Series:
    """Return cumulative VWAP over the given 1-min OHLCV frame."""
    if df is None or df.empty:
        return pd.Series(dtype=float)

    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].astype(float).fillna(0.0)

    if (vol > 0).sum() == 0:
        # No volume at all - fall back to running mean of typical price.
        return typical.expanding().mean()

    pv = (typical * vol).cumsum()
    cum_vol = vol.cumsum().replace(0, np.nan)
    out = pv / cum_vol

    # Where cum_vol was zero (no trades yet), backfill with typical price
    # so the first sample isn't NaN.
    return out.fillna(typical)


def latest_vwap(df: pd.DataFrame) -> float | None:
    """Return the last VWAP value, or None when the input is empty."""
    if df is None or df.empty:
        return None
    s = vwap(df)
    if s.empty:
        return None
    val = s.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


__all__ = ["vwap", "latest_vwap"]
