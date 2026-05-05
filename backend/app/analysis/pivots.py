"""Classical floor-trader pivot levels.

Pure, deterministic helpers used by the index analysis layer to surface
intraday support / resistance levels derived from the *previous* trading
day's high / low / close.

Formulas (classical / floor-trader):
    P  = (H + L + C) / 3
    R1 = 2P - L
    S1 = 2P - H
    R2 = P + (H - L)
    S2 = P - (H - L)
    R3 = H + 2*(P - L)
    S3 = L - 2*(H - P)

The previous-day values are sourced from `df["high"].shift(1)` etc. inside
`indicators.compute_all`, so the latest row of the enriched frame already
represents the levels valid for *today* (no look-ahead).
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd


def compute_classical(
    prev_high: float, prev_low: float, prev_close: float,
) -> Dict[str, float]:
    """Return P / R1-R3 / S1-S3 from a single prior-day H/L/C triplet."""
    h, l, c = float(prev_high), float(prev_low), float(prev_close)
    p = (h + l + c) / 3.0
    r1 = 2.0 * p - l
    s1 = 2.0 * p - h
    r2 = p + (h - l)
    s2 = p - (h - l)
    r3 = h + 2.0 * (p - l)
    s3 = l - 2.0 * (h - p)
    return {
        "pivot_p": p,
        "pivot_r1": r1,
        "pivot_r2": r2,
        "pivot_r3": r3,
        "pivot_s1": s1,
        "pivot_s2": s2,
        "pivot_s3": s3,
    }


def compute_pivot_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised version of `compute_classical` over a daily OHLC frame.

    Returns a DataFrame with the same index as `df` whose row N holds the
    pivot levels valid for day N, derived from day N-1's H/L/C. Row 0 is
    NaN by construction.
    """
    if df is None or df.empty:
        return pd.DataFrame(index=df.index if df is not None else None)

    h = df["high"].shift(1)
    l = df["low"].shift(1)
    c = df["close"].shift(1)
    p = (h + l + c) / 3.0
    return pd.DataFrame({
        "pivot_p": p,
        "pivot_r1": 2.0 * p - l,
        "pivot_r2": p + (h - l),
        "pivot_r3": h + 2.0 * (p - l),
        "pivot_s1": 2.0 * p - h,
        "pivot_s2": p - (h - l),
        "pivot_s3": l - 2.0 * (h - p),
    }, index=df.index)


def distance_pct(close: float, pivot: Optional[float]) -> Optional[float]:
    """Signed % distance of `close` from `pivot`. None when pivot is missing/zero."""
    if pivot is None or pd.isna(pivot) or pivot == 0:
        return None
    return float((close / float(pivot) - 1.0) * 100.0)


def nearest_level(close: float, levels: Dict[str, Optional[float]]) -> Optional[str]:
    """Return the key of the pivot level closest to `close`, ignoring None.

    Useful for surfacing "near R1" / "near S2" annotations. Returns None
    when no levels are populated.
    """
    best_key: Optional[str] = None
    best_dist = float("inf")
    for k, v in levels.items():
        if v is None or pd.isna(v):
            continue
        d = abs(float(close) - float(v))
        if d < best_dist:
            best_dist = d
            best_key = k
    return best_key


__all__ = [
    "compute_classical",
    "compute_pivot_columns",
    "distance_pct",
    "nearest_level",
]
