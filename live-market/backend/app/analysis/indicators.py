"""Hand-rolled technical indicators (deterministic, no third-party TA libs).

Adapted from the parent app's `backend/app/analysis/indicators.py` but
stripped to the subset the live-market service actually uses (EMA, SMA,
RSI, MACD, ATR, ADX, Bollinger). No pivots, no `compute_all` - those
belong to the EOD daily pipeline upstream.

All functions take a DataFrame with lowercase columns:
    open, high, low, close, volume
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length, min_periods=length).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder smoothing == EMA with alpha=1/length.
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss > 0, 100.0)
    out = out.where((avg_gain > 0) | (avg_loss > 0), 50.0)
    return out.fillna(50.0)


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def true_range(df: pd.DataFrame) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_pc = (df["high"] - df["close"].shift()).abs()
    low_pc = (df["low"] - df["close"].shift()).abs()
    return pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def adx(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    """Average Directional Index. Returns DataFrame with adx, +di, -di."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    tr = true_range(df)
    atr_w = tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()

    plus_di = (
        100.0
        * plus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
        / atr_w.replace(0, np.nan)
    )
    minus_di = (
        100.0
        * minus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
        / atr_w.replace(0, np.nan)
    )
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()

    return pd.DataFrame({"adx": adx_val, "+di": plus_di, "-di": minus_di})


def bollinger(series: pd.Series, length: int = 20, mult: float = 2.0) -> pd.DataFrame:
    mid = sma(series, length)
    std = series.rolling(window=length, min_periods=length).std(ddof=0)
    upper = mid + mult * std
    lower = mid - mult * std
    width = (upper - lower) / mid.replace(0, np.nan)
    return pd.DataFrame({
        "bb_mid": mid,
        "bb_upper": upper,
        "bb_lower": lower,
        "bb_width": width,
    })


__all__ = ["ema", "sma", "rsi", "macd", "true_range", "atr", "adx", "bollinger"]
