"""Shared test fixtures - deterministic synthetic OHLCV.

No network, no external dependencies. Mirrors the parent app's testing
philosophy: every fixture is reproducible from a seed so test failures
point at real regressions, not data drift.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

import numpy as np
import pandas as pd
import pytest


def _make_intraday(
    *,
    n: int = 60,
    start_price: float = 100.0,
    drift: float = 0.0,
    noise: float = 0.05,
    seed: int = 42,
    start_ts: datetime | None = None,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = [start_price]
    for _ in range(n - 1):
        closes.append(closes[-1] + drift + rng.normal(0, noise))
    closes_arr = np.array(closes)
    highs = closes_arr + np.abs(rng.normal(0, noise, n))
    lows = closes_arr - np.abs(rng.normal(0, noise, n))
    opens = np.concatenate(([closes_arr[0]], closes_arr[:-1]))
    volumes = rng.integers(1000, 10000, n)

    base = start_ts or datetime(2026, 1, 6, 9, 15)
    idx = [base + timedelta(minutes=i) for i in range(n)]
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes_arr, "volume": volumes,
    }, index=idx)


@pytest.fixture
def trending_up_bars() -> pd.DataFrame:
    """60 1-min bars with a clear positive drift."""
    return _make_intraday(n=60, drift=0.20, noise=0.10, seed=11)


@pytest.fixture
def trending_down_bars() -> pd.DataFrame:
    return _make_intraday(n=60, drift=-0.20, noise=0.10, seed=12)


@pytest.fixture
def range_bound_bars() -> pd.DataFrame:
    """60 1-min bars oscillating tightly around 100."""
    rng = np.random.default_rng(13)
    n = 60
    base = 100.0
    closes = base + 0.5 * np.sin(np.linspace(0, 6 * np.pi, n)) + rng.normal(0, 0.05, n)
    highs = closes + np.abs(rng.normal(0, 0.05, n))
    lows = closes - np.abs(rng.normal(0, 0.05, n))
    opens = np.concatenate(([closes[0]], closes[:-1]))
    volumes = rng.integers(1000, 10000, n)
    start = datetime(2026, 1, 6, 9, 15)
    idx = [start + timedelta(minutes=i) for i in range(n)]
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=idx)


def _trend_with_pullbacks(
    *,
    start: float,
    drift: float,
    noise: float,
    seed: int,
    phase_start: float,
    phase_end: float,
    n: int = 100,
) -> pd.DataFrame:
    """Build daily OHLCV with a linear trend + cyclical pullbacks.

    A pure linear trend drives MACD hist to ~0 and saturates RSI at the
    extremes. Layering pullbacks (amplitude > drift over a half-cycle)
    keeps MACD hist alternating around the trend and ADX comfortably
    above 22 - which is what real index moves look like and what our
    gates were tuned for. Seed-locked for deterministic test runs.

    Caller controls the phase so the LAST bar lands on the right side of
    the cycle for the gate it wants to test (e.g. uptrend fixture ends
    on an up-stroke -> BREAKOUT_PULLBACK; downtrend fixture ends on a
    down-stroke -> BREAKDOWN_PULLBACK).
    """
    rng = np.random.default_rng(seed)
    base_closes = start + drift * np.arange(n)
    pullback = 18.0 * np.sin(np.linspace(phase_start, phase_end, n))
    noise_arr = rng.normal(0, noise, n)
    closes = base_closes + pullback + noise_arr
    highs = closes + np.abs(rng.normal(3, 0.5, n))
    lows = closes - np.abs(rng.normal(3, 0.5, n))
    opens = np.concatenate(([closes[0]], closes[:-1]))
    volumes = rng.integers(100_000, 1_000_000, n)
    start_dt = datetime(2026, 1, 1)
    idx = [start_dt + timedelta(days=i) for i in range(n)]
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=idx)


@pytest.fixture
def daily_uptrend() -> pd.DataFrame:
    """Strong uptrend with healthy pullbacks - last bar in an up-stroke."""
    return _trend_with_pullbacks(
        start=1000.0, drift=1.5, noise=1.0, seed=21,
        phase_start=0.0, phase_end=6 * 3.141592653589793,
    )


@pytest.fixture
def daily_downtrend() -> pd.DataFrame:
    """Strong downtrend - last bar in a down-stroke (just past a relief peak)."""
    import math
    return _trend_with_pullbacks(
        start=1500.0, drift=-1.5, noise=1.0, seed=22,
        phase_start=math.pi, phase_end=7 * math.pi,
    )


__all__: List[str] = []
