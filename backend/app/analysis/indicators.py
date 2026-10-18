"""Technical indicator calculations.

We hand-roll the indicators with pandas/numpy (deterministic, no third-party
quirks) instead of depending on pandas-ta / pandas-ta-classic. This keeps unit
tests stable and avoids version drift in the active TA libraries.

All functions take a DataFrame with lowercase columns: open, high, low, close, volume.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from . import pivots as _pivots


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length, min_periods=length).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder's smoothing == EMA with alpha = 1/length
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # No losses at all -> RSI = 100; no gains at all -> RSI = 0; both zero -> 50.
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
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    return tr


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

    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean() / atr_w.replace(0, np.nan)
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean() / atr_w.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()

    return pd.DataFrame({
        "adx": adx_val,
        "+di": plus_di,
        "-di": minus_di,
    })


def bollinger(series: pd.Series, length: int = 20, mult: float = 2.0) -> pd.DataFrame:
    mid = sma(series, length)
    std = series.rolling(window=length, min_periods=length).std(ddof=0)
    upper = mid + mult * std
    lower = mid - mult * std
    width = (upper - lower) / mid.replace(0, np.nan)
    return pd.DataFrame({"bb_mid": mid, "bb_upper": upper, "bb_lower": lower, "bb_width": width})


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0.0))
    return (direction * df["volume"]).cumsum()


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df enriched with indicator columns."""
    out = df.copy()
    out["ema20"] = ema(df["close"], 20)
    out["ema50"] = ema(df["close"], 50)
    out["ema200"] = ema(df["close"], 200)
    out["rsi14"] = rsi(df["close"], 14)

    macd_df = macd(df["close"])
    out["macd"] = macd_df["macd"]
    out["macd_signal"] = macd_df["signal"]
    out["macd_hist"] = macd_df["hist"]

    adx_df = adx(df, 14)
    out["adx"] = adx_df["adx"]
    out["+di"] = adx_df["+di"]
    out["-di"] = adx_df["-di"]

    out["atr14"] = atr(df, 14)
    out["atr_pct"] = (out["atr14"] / df["close"]) * 100.0

    bb = bollinger(df["close"])
    out["bb_mid"] = bb["bb_mid"]
    out["bb_upper"] = bb["bb_upper"]
    out["bb_lower"] = bb["bb_lower"]
    out["bb_width"] = bb["bb_width"]

    out["obv"] = obv(df)

    out["vol_avg20"] = df["volume"].rolling(window=20, min_periods=10).mean()
    out["vol_avg50"] = df["volume"].rolling(window=50, min_periods=20).mean()
    out["vol_ratio"] = df["volume"] / out["vol_avg20"].replace(0, np.nan)

    out["high_252"] = df["high"].rolling(window=252, min_periods=50).max()
    out["low_252"] = df["low"].rolling(window=252, min_periods=50).min()
    out["pct_from_52w_high"] = (df["close"] / out["high_252"] - 1.0) * 100.0
    out["pct_from_52w_low"] = (df["close"] / out["low_252"] - 1.0) * 100.0

    out["return_5d"] = df["close"].pct_change(5, fill_method=None) * 100.0
    out["return_20d"] = df["close"].pct_change(20, fill_method=None) * 100.0
    out["return_60d"] = df["close"].pct_change(60, fill_method=None) * 100.0

    # Classical floor-trader pivots derived from the *previous* daily candle.
    # Vectorised so each row holds the levels valid for that trading day
    # without look-ahead (row N uses day N-1's H/L/C).
    pv = _pivots.compute_pivot_columns(df)
    for col in ("pivot_p", "pivot_r1", "pivot_r2", "pivot_r3",
                "pivot_s1", "pivot_s2", "pivot_s3"):
        out[col] = pv[col]
    out["pivot_distance_pct"] = (df["close"] / pv["pivot_p"].replace(0, np.nan) - 1.0) * 100.0

    return out


def latest_indicator_dict(df_with_indicators: pd.DataFrame) -> Dict[str, float]:
    """Return the latest row's indicator values as a JSON-serialisable dict."""
    if df_with_indicators.empty:
        return {}
    row = df_with_indicators.iloc[-1]
    keys = [
        "open", "high", "low", "close", "volume",
        "ema20", "ema50", "ema200",
        "rsi14",
        "macd", "macd_signal", "macd_hist",
        "adx", "+di", "-di",
        "atr14", "atr_pct",
        "bb_mid", "bb_upper", "bb_lower", "bb_width",
        "vol_avg20", "vol_avg50", "vol_ratio",
        "high_252", "low_252", "pct_from_52w_high", "pct_from_52w_low",
        "return_5d", "return_20d", "return_60d",
        "pivot_p", "pivot_r1", "pivot_r2", "pivot_r3",
        "pivot_s1", "pivot_s2", "pivot_s3", "pivot_distance_pct",
    ]
    out: Dict[str, float] = {}
    for k in keys:
        if k in row.index:
            v = row[k]
            if pd.isna(v):
                out[k] = None  # type: ignore[assignment]
            else:
                out[k] = float(v)
    return out
