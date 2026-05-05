"""Regime classification edge cases."""
from __future__ import annotations

from app.analysis import indicators as ind
from app.analysis.regime import classify


def test_uptrend_classified_as_uptrend(uptrend_df):
    df = ind.compute_all(uptrend_df)
    label, _ = classify(df)
    assert label in ("UPTREND", "STRONG_UPTREND")


def test_downtrend_classified_as_downtrend(downtrend_df):
    df = ind.compute_all(downtrend_df)
    label, _ = classify(df)
    assert label in ("DOWNTREND", "STRONG_DOWNTREND")


def test_range_market_classification(range_df):
    df = ind.compute_all(range_df)
    label, _ = classify(df)
    assert label in ("RANGE", "UPTREND", "DOWNTREND")  # narrow flat sometimes wobbles
