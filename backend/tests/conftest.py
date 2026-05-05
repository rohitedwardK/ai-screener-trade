"""Shared fixtures: deterministic synthetic OHLCV frames."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _frame(closes: np.ndarray, vol: np.ndarray | None = None) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range(end="2026-04-30", periods=n, freq="B")
    rng = np.random.default_rng(42)
    spread = closes * 0.01
    high = closes + spread + rng.normal(0, spread * 0.2, n).clip(0)
    low = closes - spread - rng.normal(0, spread * 0.2, n).clip(0)
    opens = np.r_[closes[0], closes[:-1]]
    if vol is None:
        vol = rng.integers(800_000, 1_500_000, size=n).astype(float)
    return pd.DataFrame(
        {
            "open": opens,
            "high": high,
            "low": low,
            "close": closes,
            "volume": vol,
        },
        index=idx,
    )


@pytest.fixture
def uptrend_df() -> pd.DataFrame:
    n = 300
    base = 100.0
    x = np.arange(n)
    closes = base + x * 0.3 + np.sin(x / 10) * 1.5
    vol = np.full(n, 1_000_000.0)
    vol[-3:] = 2_500_000.0
    return _frame(closes, vol)


@pytest.fixture
def downtrend_df() -> pd.DataFrame:
    n = 300
    base = 200.0
    x = np.arange(n)
    closes = base - x * 0.25 + np.sin(x / 10) * 1.0
    return _frame(closes)


@pytest.fixture
def range_df() -> pd.DataFrame:
    n = 300
    x = np.arange(n)
    closes = 150.0 + np.sin(x / 8) * 3.0
    return _frame(closes)


@pytest.fixture
def oversold_bounce_df() -> pd.DataFrame:
    n = 250
    closes = np.r_[
        np.linspace(180, 110, 200),
        np.linspace(110, 105, 10),
        np.linspace(105, 118, 40),
    ]
    return _frame(closes)
