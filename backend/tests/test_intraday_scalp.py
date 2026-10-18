"""Unit tests for 15m intraday scalp analysis."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.intraday_scalp import evaluate_intraday


def _intraday_frame(n: int = 40, *, drift: float = 0.0, noise: float = 0.3) -> pd.DataFrame:
    idx = pd.date_range(end="2026-08-30 15:15", periods=n, freq="15min")
    rng = np.random.default_rng(7)
    base = 100.0
    closes = base + np.cumsum(rng.normal(drift, noise, n))
    spread = closes * 0.002
    return pd.DataFrame(
        {
            "open": np.r_[closes[0], closes[:-1]],
            "high": closes + spread,
            "low": closes - spread,
            "close": closes,
            "volume": rng.integers(5_000, 20_000, size=n).astype(float),
        },
        index=idx,
    )


def test_evaluate_returns_empty_on_short_frame():
    df = _intraday_frame(10)
    result = evaluate_intraday(df)
    assert result.scalps == []
    assert result.regime == "UNKNOWN"


def test_range_bounce_long_emits_with_flat_range():
    n = 45
    idx = pd.date_range(end="2026-08-30 15:15", periods=n, freq="15min")
    close = np.full(n, 500.0)
    close[-1] = 500.4
    close[-2] = 499.8
    df = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 10_000.0),
        },
        index=idx,
    )
    result = evaluate_intraday(df)
    assert result.scalps
    top = result.scalps[0]
    assert top.invalidation == top.stop_loss
    if top.direction == "LONG":
        assert top.target_1 > top.entry > top.stop_loss
    else:
        assert top.target_1 < top.entry < top.stop_loss


def test_trending_up_emits_momentum_or_pullback():
    df = _intraday_frame(50, drift=0.35, noise=0.05)
    result = evaluate_intraday(df, signal_direction="LONG")
    assert result.regime in ("TRENDING_UP", "RANGE_BOUND")
    if result.scalps:
        assert result.scalps[0].invalidation == result.scalps[0].stop_loss
        if result.aligned_with_signal is not None:
            assert isinstance(result.aligned_with_signal, bool)


def test_every_scalp_has_invalidation():
    df = _intraday_frame(55, drift=0.1, noise=0.2)
    result = evaluate_intraday(df)
    for scalp in result.scalps:
        assert scalp.invalidation == scalp.stop_loss
        assert scalp.stop_loss != scalp.entry
        assert scalp.hold_minutes >= 15
