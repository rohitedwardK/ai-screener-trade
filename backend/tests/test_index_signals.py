"""Tests for the index signal generator."""
from __future__ import annotations

import pandas as pd

from app.analysis.index_signals import evaluate_index, signal_to_dict


def test_uptrend_yields_long_signals(uptrend_df):
    out = evaluate_index("^NSEI", "NIFTY", uptrend_df)
    assert out
    assert any(rec.direction == "LONG" for rec in out)
    # No SHORT signals from a clean uptrend.
    assert not any(rec.direction == "SHORT" for rec in out)
    for rec in out:
        assert rec.plan is not None
        assert rec.plan.entry > rec.plan.stop_loss
        assert rec.plan.target_1 > rec.plan.entry
        assert rec.plan.invalidation == rec.plan.stop_loss


def test_downtrend_yields_short_signals(downtrend_df):
    out = evaluate_index("^NSEI", "NIFTY", downtrend_df)
    assert any(rec.direction == "SHORT" for rec in out)
    for rec in out:
        if rec.direction == "SHORT":
            assert rec.plan is not None
            assert rec.plan.entry < rec.plan.stop_loss
            assert rec.plan.target_1 < rec.plan.entry


def test_range_market_produces_no_breakout_signals(range_df):
    out = evaluate_index("^NSEI", "NIFTY", range_df)
    # A sideways-only fixture should not trip the breakout-retest rule.
    assert not any(r.category == "BREAKOUT_RETEST" for r in out)


def test_chain_bias_boosts_long_score(uptrend_df):
    no_bias = evaluate_index("^NSEI", "NIFTY", uptrend_df)
    with_bull = evaluate_index(
        "^NSEI", "NIFTY", uptrend_df,
        chain_bias="Bullish", chain_strength=0.6, chain_notes=["PCR 1.4 (high)"],
    )
    if not no_bias or not with_bull:
        return
    base_score = max(r.score for r in no_bias if r.direction == "LONG")
    boosted_score = max(r.score for r in with_bull if r.direction == "LONG")
    assert boosted_score >= base_score


def test_chain_bias_penalises_long_when_bearish(uptrend_df):
    no_bias = evaluate_index("^NSEI", "NIFTY", uptrend_df)
    with_bear = evaluate_index(
        "^NSEI", "NIFTY", uptrend_df,
        chain_bias="Bearish", chain_strength=0.7,
    )
    if not no_bias or not with_bear:
        return
    base_score = max(r.score for r in no_bias if r.direction == "LONG")
    penalised = max(r.score for r in with_bear if r.direction == "LONG")
    assert penalised <= base_score


def test_short_history_returns_empty():
    df = pd.DataFrame({
        "open": [100, 101], "high": [102, 102], "low": [99, 100],
        "close": [101, 101], "volume": [1000, 1000],
    }, index=pd.date_range("2026-04-01", periods=2, freq="B"))
    assert evaluate_index("^NSEI", "NIFTY", df) == []


def test_signal_to_dict_round_trip(uptrend_df):
    out = evaluate_index("^NSEI", "NIFTY", uptrend_df)
    if not out:
        return
    d = signal_to_dict(out[0])
    for k in ("symbol", "as_of_date", "category", "direction", "score", "spot", "entry"):
        assert k in d
    assert d["symbol"] == "^NSEI"
    assert d["direction"] in {"LONG", "SHORT"}
