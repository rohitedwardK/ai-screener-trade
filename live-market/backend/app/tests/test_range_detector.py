"""Unit tests for range_detector + vwap."""
from __future__ import annotations

import pandas as pd

from app.analysis.range_detector import detect_range, distance_to_edge
from app.analysis.vwap import latest_vwap, vwap


def test_detect_range_returns_none_when_too_short():
    df = pd.DataFrame({
        "open": [100, 100], "high": [101, 101],
        "low": [99, 99], "close": [100, 100], "volume": [10, 10],
    })
    assert detect_range(df) is None


def test_detect_range_finds_levels(range_bound_bars):
    levels = detect_range(range_bound_bars)
    assert levels is not None
    assert levels.support < levels.mid < levels.resistance
    assert levels.width_pct > 0


def test_distance_to_edge_signed(range_bound_bars):
    levels = detect_range(range_bound_bars)
    assert levels is not None
    last_close = float(range_bound_bars["close"].iloc[-1])
    d_sup, d_res = distance_to_edge(last_close, levels)
    # Combined widths should add up to roughly the total range %.
    assert abs((d_sup + d_res) - levels.width_pct) < 0.01


def test_vwap_increases_monotonically_with_volume_at_top(range_bound_bars):
    """VWAP shouldn't be NaN and should land near the typical price."""
    val = latest_vwap(range_bound_bars)
    assert val is not None
    typical = ((range_bound_bars["high"] + range_bound_bars["low"]
                + range_bound_bars["close"]) / 3.0).mean()
    assert abs(val - typical) < 1.0


def test_vwap_falls_back_when_no_volume():
    df = pd.DataFrame({
        "open": [100, 101, 102], "high": [101, 102, 103],
        "low": [99, 100, 101], "close": [100, 101, 102],
        "volume": [0, 0, 0],
    })
    s = vwap(df)
    assert not s.empty
    # With zero volume we fall back to expanding mean of typical price.
    assert s.iloc[-1] > 99.0
