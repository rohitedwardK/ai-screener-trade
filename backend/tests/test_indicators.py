"""Indicator math sanity tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis import indicators as ind


def test_ema_matches_known_values():
    s = pd.Series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19], dtype=float)
    out = ind.ema(s, 3)
    assert pd.isna(out.iloc[0])
    last = out.iloc[-1]
    assert last > 14 and last < 19


def test_rsi_in_bounds(uptrend_df):
    r = ind.rsi(uptrend_df["close"], 14)
    valid = r.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_uptrend_reads_high(uptrend_df):
    r = ind.rsi(uptrend_df["close"], 14).iloc[-1]
    assert r > 55, f"Expected RSI > 55 in steady uptrend, got {r}"


def test_atr_positive(uptrend_df):
    a = ind.atr(uptrend_df, 14).dropna()
    assert (a > 0).all()


def test_compute_all_columns_present(uptrend_df):
    out = ind.compute_all(uptrend_df)
    expected = {
        "ema20", "ema50", "ema200", "rsi14",
        "macd", "macd_signal", "macd_hist",
        "adx", "+di", "-di",
        "atr14", "atr_pct",
        "bb_mid", "bb_upper", "bb_lower", "bb_width",
        "obv", "vol_avg20", "vol_ratio",
        "high_252", "low_252",
        "return_5d", "return_20d", "return_60d",
    }
    assert expected.issubset(set(out.columns))


def test_macd_signal_difference_equals_hist(uptrend_df):
    m = ind.macd(uptrend_df["close"])
    diff = (m["macd"] - m["signal"]).dropna()
    hist = m["hist"].dropna()
    aligned = diff.align(hist, join="inner")
    np.testing.assert_allclose(aligned[0].values, aligned[1].values, rtol=1e-9)
