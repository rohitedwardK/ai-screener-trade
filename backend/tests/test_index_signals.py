"""Tests for the index signal generator."""
from __future__ import annotations

from datetime import date, time

import pandas as pd

from app.analysis.index_signals import (
    _horizon_distances,
    _trading_days_between,
    evaluate_index,
    next_weekly_expiry,
    signal_to_dict,
)


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
    # Plan now carries weekly-expiry metadata.
    assert d["expiry"] is not None
    assert d["days_to_expiry"] is not None and d["days_to_expiry"] >= 1
    assert d["horizon"] == "WEEKLY"


# ----- Weekly expiry helpers -------------------------------------------------

def test_next_weekly_expiry_rolls_forward_when_today_is_expiry_eod():
    # Tuesday 2026-05-05 is Nifty's weekly expiry. EOD (no time supplied)
    # must roll to the following Tuesday so we never recommend a strike on
    # the already-expired contract.
    expiry = next_weekly_expiry("Tuesday", date(2026, 5, 5))
    assert expiry == date(2026, 5, 12)


def test_next_weekly_expiry_keeps_today_when_before_cutoff():
    # On expiry day before 14:30 IST the contract still has hours of life.
    expiry = next_weekly_expiry("Tuesday", date(2026, 5, 5), now_time=time(10, 0))
    assert expiry == date(2026, 5, 5)


def test_next_weekly_expiry_picks_following_weekday():
    # Monday 2026-05-04 → Tuesday 2026-05-05 for Nifty.
    assert next_weekly_expiry("Tuesday", date(2026, 5, 4)) == date(2026, 5, 5)
    # Monday 2026-05-04 → Wednesday 2026-05-06 for BankNifty.
    assert next_weekly_expiry("Wednesday", date(2026, 5, 4)) == date(2026, 5, 6)


def test_trading_days_between_skips_weekends():
    # Friday → following Tuesday: only Mon + Tue = 2 trading days.
    assert _trading_days_between(date(2026, 5, 1), date(2026, 5, 5)) == 2


def test_horizon_distances_shrink_as_expiry_approaches():
    atr = 100.0
    long_dte_stop, _, long_dte_t2 = _horizon_distances(atr, days_to_expiry=5)
    short_dte_stop, _, short_dte_t2 = _horizon_distances(atr, days_to_expiry=1)
    # Stop is symmetric (1.0 × ATR) regardless of horizon.
    assert long_dte_stop == short_dte_stop
    # T2 must shrink with shorter horizon.
    assert short_dte_t2 < long_dte_t2


def test_evaluate_index_carries_expiry_into_plan(uptrend_df):
    # Pin "today" to a Monday so we know the next Tuesday expiry is 1 day away.
    out = evaluate_index(
        "^NSEI", "NIFTY", uptrend_df,
        weekly_expiry_day="Tuesday", today=date(2026, 5, 4),
    )
    assert out
    long_recs = [r for r in out if r.direction == "LONG"]
    assert long_recs
    plan = long_recs[0].plan
    assert plan is not None
    assert plan.expiry == date(2026, 5, 5)
    assert plan.days_to_expiry == 1
    assert plan.horizon == "WEEKLY"
    # Horizon note appears in the reasons.
    assert any("expiry" in r.lower() for r in long_recs[0].reasons)
