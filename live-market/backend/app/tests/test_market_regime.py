"""Unit tests for the intraday regime classifier."""
from __future__ import annotations

import pandas as pd

from app.analysis import market_regime as regime_mod
from app.analysis.vwap import latest_vwap


def test_trending_up_classified_when_strong_drift_and_high_adx(trending_up_bars):
    df = trending_up_bars
    result = regime_mod.classify(
        df, daily_atr=2.0, daily_adx=30.0, vwap=latest_vwap(df),
    )
    # Trending up requires: ADX>=22, EMA9>EMA21, ema spread > 0.10%, range > 0.5x atr%.
    # The synthetic frame with drift=0.20 over 60 bars hits all of these.
    assert result.regime == regime_mod.REGIME_TRENDING_UP
    assert result.spot > 0
    assert any("ADX" in r for r in result.reasons)


def test_trending_down_classified(trending_down_bars):
    df = trending_down_bars
    result = regime_mod.classify(
        df, daily_atr=2.0, daily_adx=30.0, vwap=latest_vwap(df),
    )
    assert result.regime == regime_mod.REGIME_TRENDING_DOWN


def test_choppy_when_daily_adx_missing(trending_up_bars):
    result = regime_mod.classify(
        trending_up_bars, daily_atr=None, daily_adx=None, vwap=None,
    )
    assert result.regime == regime_mod.REGIME_CHOPPY


def test_choppy_when_too_few_bars():
    df = pd.DataFrame({
        "open": [100, 101], "high": [101, 102],
        "low": [99, 100], "close": [101, 102], "volume": [100, 100],
    })
    result = regime_mod.classify(df, daily_atr=2.0, daily_adx=25.0, vwap=None)
    assert result.regime == regime_mod.REGIME_CHOPPY


def test_choppy_when_empty_df():
    result = regime_mod.classify(
        pd.DataFrame(columns=["open", "high", "low", "close", "volume"]),
        daily_atr=None, daily_adx=None, vwap=None,
    )
    assert result.regime == regime_mod.REGIME_CHOPPY
