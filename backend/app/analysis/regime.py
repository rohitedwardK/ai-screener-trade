"""Stock regime classification using EMA stack, ADX, and ATR%."""
from __future__ import annotations

from typing import Tuple

import pandas as pd


REGIMES = (
    "STRONG_UPTREND",
    "UPTREND",
    "RANGE",
    "DOWNTREND",
    "STRONG_DOWNTREND",
    "VOLATILE",
)


def classify(df: pd.DataFrame) -> Tuple[str, dict]:
    """Return (regime_label, detail_dict) using the latest bar."""
    if df.empty or len(df) < 200:
        return "RANGE", {"reason": "insufficient_history"}

    row = df.iloc[-1]
    close = float(row["close"])
    ema20 = float(row.get("ema20", float("nan")))
    ema50 = float(row.get("ema50", float("nan")))
    ema200 = float(row.get("ema200", float("nan")))
    adx = float(row.get("adx", 0.0) or 0.0)
    atr_pct = float(row.get("atr_pct", 0.0) or 0.0)

    detail = {
        "close": close,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "adx": adx,
        "atr_pct": atr_pct,
    }

    # High volatility overrides directional bucket if ADX is weak.
    if atr_pct >= 5.0 and adx < 20:
        return "VOLATILE", detail

    bullish_stack = ema20 > ema50 > ema200 and close > ema20
    bearish_stack = ema20 < ema50 < ema200 and close < ema20

    if bullish_stack and adx >= 25:
        return "STRONG_UPTREND", detail
    if bullish_stack:
        return "UPTREND", detail
    if bearish_stack and adx >= 25:
        return "STRONG_DOWNTREND", detail
    if bearish_stack:
        return "DOWNTREND", detail
    if adx < 18:
        return "RANGE", detail
    if close > ema50:
        return "UPTREND", detail
    return "DOWNTREND", detail
