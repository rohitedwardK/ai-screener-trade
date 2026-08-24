"""Unit tests for scalp_signals."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from app.analysis.range_detector import RangeLevels
from app.analysis.scalp_signals import evaluate


def _frame(closes, *, opens=None, highs=None, lows=None, volumes=None) -> pd.DataFrame:
    n = len(closes)
    if opens is None:
        opens = [c for c in closes]
    if highs is None:
        highs = [max(o, c) + 0.05 for o, c in zip(opens, closes)]
    if lows is None:
        lows = [min(o, c) - 0.05 for o, c in zip(opens, closes)]
    if volumes is None:
        volumes = [1000] * n
    base = datetime(2026, 1, 6, 9, 15)
    idx = [base + timedelta(minutes=i) for i in range(n)]
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=idx)


def test_no_setups_when_levels_none():
    df = _frame([100.0, 100.1])
    out = evaluate("^NSEI", df, levels=None)  # type: ignore[arg-type]
    assert out == []


def test_range_bounce_long_fires_at_support():
    levels = RangeLevels(
        support=99.5, resistance=100.5, mid=100.0,
        width_pct=0.01, samples_used=5,
    )
    # Engineer a bar series where:
    #   - last close is very near 99.5 (within 0.15% of support)
    #   - last 3 bars hold above 99.5
    #   - RSI ends below 50 (downward momentum into support)
    closes = [100.4, 100.2, 100.0, 99.8, 99.62, 99.55, 99.55, 99.55]
    # Build enough bars for RSI(14)
    closes = [100.5] * 10 + closes
    df = _frame(closes)
    out = evaluate("^NSEI", df, levels=levels)
    assert any(r.category == "RANGE_BOUNCE_LONG" and r.direction == "LONG" for r in out)
    rec = next(r for r in out if r.category == "RANGE_BOUNCE_LONG")
    assert rec.spot_invalidation == rec.spot_stop
    assert rec.spot_stop < rec.spot_entry < rec.spot_t1 <= rec.spot_t2


def test_range_bounce_short_fires_at_resistance():
    levels = RangeLevels(
        support=99.5, resistance=100.5, mid=100.0,
        width_pct=0.01, samples_used=5,
    )
    closes = [99.5] * 10 + [99.6, 99.8, 100.0, 100.2, 100.38, 100.45, 100.45, 100.45]
    df = _frame(closes)
    out = evaluate("^NSEI", df, levels=levels)
    assert any(r.category == "RANGE_BOUNCE_SHORT" for r in out)
    rec = next(r for r in out if r.category == "RANGE_BOUNCE_SHORT")
    assert rec.spot_stop > rec.spot_entry > rec.spot_t1 >= rec.spot_t2


def test_false_breakout_long_after_whipsaw():
    levels = RangeLevels(
        support=99.5, resistance=100.5, mid=100.0,
        width_pct=0.01, samples_used=5,
    )
    # Prev bar: low pierces 99.5; current bar: bullish body closing above 99.5.
    n_pad = 10
    closes = [100.0] * n_pad + [100.0]  # padding
    opens = list(closes)
    highs = [c + 0.05 for c in closes]
    lows = [c - 0.05 for c in closes]
    # Append the whipsaw bars:
    closes += [99.4]            # prev close (sub-support)
    opens += [99.8]
    highs += [99.85]
    lows += [99.30]             # prev low broke support
    closes += [99.95]           # current bullish reclaim
    opens += [99.5]
    highs += [100.0]
    lows += [99.45]
    df = _frame(closes, opens=opens, highs=highs, lows=lows)
    out = evaluate("^NSEI", df, levels=levels)
    assert any(r.category == "FALSE_BREAKOUT_LONG" for r in out)


def test_vwap_reclaim_long():
    levels = RangeLevels(
        support=99.0, resistance=101.0, mid=100.0,
        width_pct=0.02, samples_used=5,
    )
    # Two-bar reclaim: prev close < vwap, current close > vwap with bullish body.
    closes = [100.0] * 12
    opens = list(closes)
    highs = [c + 0.05 for c in closes]
    lows = [c - 0.05 for c in closes]
    closes += [99.8]           # prev close < vwap (100.0)
    opens += [100.1]
    highs += [100.1]
    lows += [99.7]
    closes += [100.3]          # current reclaim
    opens += [99.9]
    highs += [100.4]
    lows += [99.85]
    df = _frame(closes, opens=opens, highs=highs, lows=lows)
    out = evaluate("^NSEI", df, levels=levels, vwap_value=100.0)
    assert any(r.category == "VWAP_RECLAIM_LONG" for r in out)


def test_every_setup_carries_invalidation():
    """Hard rule: no plan returned without an invalidation level."""
    levels = RangeLevels(
        support=99.5, resistance=100.5, mid=100.0,
        width_pct=0.01, samples_used=5,
    )
    n_pad = 10
    closes = [100.0] * n_pad + [99.6, 99.8, 100.0, 100.2, 100.38, 100.45, 100.45, 100.45]
    df = _frame(closes)
    out = evaluate("^NSEI", df, levels=levels, vwap_value=100.0)
    for r in out:
        assert r.spot_invalidation is not None
        assert r.spot_invalidation == r.spot_stop
