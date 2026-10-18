"""INTRADAY_WATCH_TOMORROW uses signed evidence, not category-default LONG."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.analysis.indicators import compute_all
from app.analysis.signals import evaluate_symbol
from app.data import csv_store


def _watch(recs):
    return [r for r in recs if r.category == "INTRADAY_WATCH_TOMORROW"]


def test_bearish_pattern_in_strong_downtrend_is_short_not_long():
    """Synthetic bar: bearish engulfing + STRONG_DOWNTREND + ATR% gate — must not LONG."""
    from app.analysis import signals as sigmod

    n = 260
    idx = pd.date_range(end="2026-09-18", periods=n, freq="B")
    close = 262.3
    df = pd.DataFrame(
        {
            "open": [266.6] * n,
            "high": [266.6] * n,
            "low": [262.3] * n,
            "close": [close] * n,
            "volume": [14_000_000.0] * n,
        },
        index=idx,
    )
    df.iloc[-2, df.columns.get_loc("open")] = 265.0
    df.iloc[-2, df.columns.get_loc("close")] = 265.5
    df.iloc[-1, df.columns.get_loc("open")] = 266.6
    df.iloc[-1, df.columns.get_loc("close")] = close

    enriched = compute_all(df)
    original = sigmod.classify

    def _strong_down(_df):
        return "STRONG_DOWNTREND", {}

    sigmod.classify = _strong_down
    try:
        recs = evaluate_symbol("SYN.NS", df, df_enriched=enriched)
    finally:
        sigmod.classify = original

    watches = _watch(recs)
    assert watches, "expected intraday watch when ATR + bearish pattern"
    w = watches[0]
    assert w.direction == "SHORT"
    assert w.plan is not None
    assert w.plan.stop_loss > w.plan.entry
    assert w.confidence == 1.0
    assert w.direction != "LONG"


def test_conflicting_bullish_pattern_and_bearish_regime_is_wait():
    from app.analysis import signals as sigmod

    n = 260
    idx = pd.date_range(end="2026-09-18", periods=n, freq="B")
    df = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [2_000_000.0] * n,
        },
        index=idx,
    )
    enriched = compute_all(df)
    original = sigmod.classify

    def _strong_down(_df):
        return "STRONG_DOWNTREND", {}

    sigmod.classify = _strong_down
    try:
        recs = evaluate_symbol("SYN.NS", df, df_enriched=enriched)
    finally:
        sigmod.classify = original

    for w in _watch(recs):
        if "Conflicting" in " ".join(w.reasons):
            assert w.direction == "WAIT"
            assert w.plan is None
            assert w.confidence == 0.0


def test_atr_and_regime_without_pattern_does_not_emit_watch():
    from app.analysis import signals as sigmod

    n = 260
    idx = pd.date_range(end="2026-09-17", periods=n, freq="B")
    closes = [266.2 - i * 0.01 for i in range(n)]
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1_500_000.0] * n,
        },
        index=idx,
    )
    enriched = compute_all(df)
    recs = evaluate_symbol("SYN.NS", df, df_enriched=enriched)
    assert _watch(recs) == []


@pytest.mark.skipif(
    not Path(csv_store.csv_path("ITC.NS")).exists(),
    reason="ITC CSV cache not present",
)
def test_itc_cached_bar_never_long_on_intraday_watch():
    raw = csv_store.load("ITC.NS")
    cut = raw.loc[: "2026-09-18"]
    enriched = compute_all(cut)
    recs = evaluate_symbol("ITC.NS", cut, df_enriched=enriched)
    for w in _watch(recs):
        assert w.direction != "LONG"
        if w.direction == "SHORT" and w.plan is not None:
            assert w.plan.stop_loss > w.plan.entry
