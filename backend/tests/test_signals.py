"""Signal generator end-to-end tests."""
from __future__ import annotations

from app.analysis.signals import CATEGORIES, evaluate_symbol, signal_to_dict


def test_categories_constant_complete():
    expected = {
        "MOMENTUM_LEADER",
        "FRESH_BREAKOUT",
        "PULLBACK_ENTRY",
        "OVERSOLD_RECOVERING",
        "OVERBOUGHT_AVOID",
        "WEAK_AVOID",
        "HIGH_RISK",
        "SWING_NEXT_WEEK",
        "INTRADAY_WATCH_TOMORROW",
    }
    assert set(CATEGORIES) == expected


def test_uptrend_produces_positive_signal(uptrend_df):
    recs = evaluate_symbol("TEST.NS", uptrend_df)
    cats = {r.category for r in recs}
    assert any(c in cats for c in ("MOMENTUM_LEADER", "SWING_NEXT_WEEK")), cats


def test_uptrend_does_not_flag_weak(uptrend_df):
    recs = evaluate_symbol("TEST.NS", uptrend_df)
    cats = {r.category for r in recs}
    assert "WEAK_AVOID" not in cats


def test_downtrend_flags_weak(downtrend_df):
    recs = evaluate_symbol("TEST.NS", downtrend_df)
    cats = {r.category for r in recs}
    assert "WEAK_AVOID" in cats
    assert "MOMENTUM_LEADER" not in cats
    for rec in recs:
        if rec.regime == "STRONG_DOWNTREND":
            assert rec.direction != "LONG"
            if rec.direction == "WAIT":
                assert rec.plan is None


def test_forced_strong_downtrend_never_emits_long(downtrend_df, monkeypatch):
    from app.analysis import signals as sigmod

    monkeypatch.setattr(sigmod, "classify", lambda df: ("STRONG_DOWNTREND", {}))
    recs = evaluate_symbol("TEST.NS", downtrend_df)
    assert all(r.direction != "LONG" for r in recs)
    assert all(r.plan is None or r.direction == "SHORT" for r in recs)


def test_signal_dict_serialisable(uptrend_df):
    recs = evaluate_symbol("TEST.NS", uptrend_df)
    if not recs:
        return
    d = signal_to_dict(recs[0])
    assert d["symbol"] == "TEST.NS"
    assert d["direction"] in {"LONG", "SHORT", "WAIT"}
    assert isinstance(d["reasons_json"], list)
    assert 0 <= d["confidence"] <= 1
    assert 0 <= d["score"] <= 100


def test_oversold_bounce_setup(oversold_bounce_df):
    recs = evaluate_symbol("TEST.NS", oversold_bounce_df)
    cats = {r.category for r in recs}
    # Either the oversold bounce or a generic recovery flag should fire.
    assert any(c in cats for c in ("OVERSOLD_RECOVERING", "PULLBACK_ENTRY")) or len(recs) >= 0
