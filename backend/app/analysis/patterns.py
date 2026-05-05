"""Price-action pattern detection.

All functions take a DataFrame already enriched by `indicators.compute_all`
(so columns like ema20/ema50/rsi14/atr14/vol_avg20 exist).

Each detector returns a bool flag (latest bar) plus a small detail dict.
"""
from __future__ import annotations

from typing import Dict, Tuple

import pandas as pd


def _last(df: pd.DataFrame, col: str, lookback: int = 0) -> float:
    if df.empty or col not in df.columns:
        return float("nan")
    idx = -1 - lookback
    if abs(idx) > len(df):
        return float("nan")
    return float(df[col].iloc[idx])


def detect_breakout(df: pd.DataFrame, lookback: int = 20) -> Tuple[bool, Dict]:
    """Close above prior `lookback`-day high with volume surge."""
    if len(df) < lookback + 2:
        return False, {}
    prior_high = df["high"].iloc[-(lookback + 1):-1].max()
    close = float(df["close"].iloc[-1])
    vol_ratio = float(df["vol_ratio"].iloc[-1]) if "vol_ratio" in df.columns else 1.0
    is_breakout = bool(close > prior_high and vol_ratio >= 1.3)
    return is_breakout, {
        "prior_high": float(prior_high),
        "close": close,
        "vol_ratio": vol_ratio,
    }


def detect_pullback(df: pd.DataFrame) -> Tuple[bool, Dict]:
    """In an uptrend (ema20>ema50>ema200), price pulls back near ema20/ema50."""
    if len(df) < 200:
        return False, {}
    close = _last(df, "close")
    ema20 = _last(df, "ema20")
    ema50 = _last(df, "ema50")
    ema200 = _last(df, "ema200")
    rsi14 = _last(df, "rsi14")
    if any(pd.isna(x) for x in (close, ema20, ema50, ema200, rsi14)):
        return False, {}
    uptrend = ema20 > ema50 > ema200
    near_support = close <= ema20 * 1.02 or close <= ema50 * 1.02
    cooled_off = 35 < rsi14 < 60
    return bool(uptrend and near_support and cooled_off), {
        "ema20": ema20,
        "ema50": ema50,
        "rsi14": rsi14,
    }


def detect_oversold_bounce(df: pd.DataFrame) -> Tuple[bool, Dict]:
    """RSI dipped below 30 in last 5 bars and is now turning up."""
    if "rsi14" not in df.columns or len(df) < 6:
        return False, {}
    rsi_recent = df["rsi14"].iloc[-6:]
    last = float(rsi_recent.iloc[-1])
    prev = float(rsi_recent.iloc[-2])
    dipped = bool((rsi_recent.iloc[:-1] < 30).any())
    turning_up = last > prev
    return bool(dipped and turning_up and last < 50), {"rsi_now": last, "rsi_prev": prev}


def detect_bearish_reversal(df: pd.DataFrame) -> Tuple[bool, Dict]:
    """Lower-highs in last 10 bars + RSI rolling over below 50 in a downtrend."""
    if len(df) < 50 or "rsi14" not in df.columns:
        return False, {}
    rsi_now = _last(df, "rsi14")
    rsi_prev = _last(df, "rsi14", 1)
    ema20 = _last(df, "ema20")
    ema50 = _last(df, "ema50")
    close = _last(df, "close")
    if any(pd.isna(x) for x in (rsi_now, rsi_prev, ema20, ema50, close)):
        return False, {}
    bearish_stack = ema20 < ema50 and close < ema20
    rolling_over = rsi_now < rsi_prev and rsi_now < 50
    return bool(bearish_stack and rolling_over), {"rsi": rsi_now}


def detect_bullish_engulfing(df: pd.DataFrame) -> Tuple[bool, Dict]:
    if len(df) < 2:
        return False, {}
    prev = df.iloc[-2]
    cur = df.iloc[-1]
    prev_red = prev["close"] < prev["open"]
    cur_green = cur["close"] > cur["open"]
    engulf = cur["open"] <= prev["close"] and cur["close"] >= prev["open"]
    return bool(prev_red and cur_green and engulf), {}


def detect_bearish_engulfing(df: pd.DataFrame) -> Tuple[bool, Dict]:
    if len(df) < 2:
        return False, {}
    prev = df.iloc[-2]
    cur = df.iloc[-1]
    prev_green = prev["close"] > prev["open"]
    cur_red = cur["close"] < cur["open"]
    engulf = cur["open"] >= prev["close"] and cur["close"] <= prev["open"]
    return bool(prev_green and cur_red and engulf), {}


def detect_hammer(df: pd.DataFrame) -> Tuple[bool, Dict]:
    if df.empty:
        return False, {}
    cur = df.iloc[-1]
    body = abs(cur["close"] - cur["open"])
    if body == 0:
        return False, {}
    lower_wick = min(cur["open"], cur["close"]) - cur["low"]
    upper_wick = cur["high"] - max(cur["open"], cur["close"])
    is_hammer = lower_wick >= 2 * body and upper_wick <= body
    return bool(is_hammer), {}


def detect_volume_surge(df: pd.DataFrame, mult: float = 2.0) -> Tuple[bool, Dict]:
    if "vol_ratio" not in df.columns or df.empty:
        return False, {}
    ratio = float(df["vol_ratio"].iloc[-1])
    return bool(ratio >= mult), {"vol_ratio": ratio}


def detect_all(df: pd.DataFrame) -> Dict[str, bool]:
    return {
        "breakout_20d": detect_breakout(df, 20)[0],
        "breakout_55d": detect_breakout(df, 55)[0],
        "pullback": detect_pullback(df)[0],
        "oversold_bounce": detect_oversold_bounce(df)[0],
        "bearish_reversal": detect_bearish_reversal(df)[0],
        "bullish_engulfing": detect_bullish_engulfing(df)[0],
        "bearish_engulfing": detect_bearish_engulfing(df)[0],
        "hammer": detect_hammer(df)[0],
        "volume_surge": detect_volume_surge(df)[0],
    }
