"""Unit tests for swing_signals."""
from __future__ import annotations

import pandas as pd

from app.analysis.market_regime import (
    REGIME_CHOPPY,
    REGIME_RANGE_BOUND,
    REGIME_TRENDING_DOWN,
    REGIME_TRENDING_UP,
)
from app.analysis.swing_signals import evaluate


def test_no_setups_when_intraday_choppy(daily_uptrend):
    out = evaluate("^NSEI", daily_uptrend, intraday_regime=REGIME_CHOPPY)
    assert out == []


def test_no_setups_when_intraday_range(daily_uptrend):
    out = evaluate("^NSEI", daily_uptrend, intraday_regime=REGIME_RANGE_BOUND)
    assert out == []


def test_no_setups_when_data_too_short():
    df = pd.DataFrame({
        "open": [100] * 10, "high": [101] * 10, "low": [99] * 10,
        "close": [100] * 10, "volume": [1000] * 10,
    })
    out = evaluate("^NSEI", df, intraday_regime=REGIME_TRENDING_UP)
    assert out == []


def test_long_setup_emitted_on_uptrend_alignment(daily_uptrend):
    out = evaluate(
        "^NSEI", daily_uptrend,
        intraday_regime=REGIME_TRENDING_UP,
        live_spot=float(daily_uptrend["close"].iloc[-1]),
    )
    assert out, "expected at least one LONG setup on a clear daily uptrend"
    for rec in out:
        assert rec.direction == "LONG"
        assert rec.spot_stop < rec.spot_entry < rec.spot_t1 <= rec.spot_t2
        assert rec.spot_invalidation == rec.spot_stop
        assert rec.days_to_expiry >= 1


def test_short_setup_emitted_on_downtrend_alignment(daily_downtrend):
    out = evaluate(
        "^NSEI", daily_downtrend,
        intraday_regime=REGIME_TRENDING_DOWN,
        live_spot=float(daily_downtrend["close"].iloc[-1]),
    )
    assert out, "expected at least one SHORT setup on a clear daily downtrend"
    for rec in out:
        assert rec.direction == "SHORT"
        assert rec.spot_stop > rec.spot_entry > rec.spot_t1 >= rec.spot_t2
        assert rec.spot_invalidation == rec.spot_stop


def test_direction_mismatch_returns_empty(daily_uptrend):
    """Daily uptrend + intraday TRENDING_DOWN -> never emit a SHORT (direction
    mismatch) and the LONG-side gates won't fire because intraday says down."""
    out = evaluate(
        "^NSEI", daily_uptrend,
        intraday_regime=REGIME_TRENDING_DOWN,
        live_spot=float(daily_uptrend["close"].iloc[-1]),
    )
    # The SHORT gates check daily indicators (EMA20 < EMA50 etc.) so on a
    # daily uptrend they should NOT fire even when intraday is down.
    assert all(r.direction != "LONG" for r in out)
    assert all(r.direction != "SHORT" for r in out)  # daily uptrend prevents shorts
