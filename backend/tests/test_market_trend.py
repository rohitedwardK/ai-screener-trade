from __future__ import annotations

import pandas as pd


def _df(rows):
    return pd.DataFrame(
        rows,
        columns=["date", "open", "high", "low", "close", "volume"],
    ).assign(date=lambda d: pd.to_datetime(d["date"])).set_index("date")


def test_market_trend_uptrend_requires_daily_breakout_and_weekly_structure():
    from app.analysis.market_trend import classify_market_trend

    df = _df([
        ("2026-01-02", 100, 110, 95, 108, 1),
        ("2026-01-09", 108, 116, 100, 114, 1),
        ("2026-01-16", 114, 124, 108, 122, 1),
        ("2026-01-23", 122, 132, 116, 130, 1),
        ("2026-01-26", 130, 136, 126, 134, 1),
        ("2026-01-27", 134, 140, 132, 139, 1),
    ])

    result = classify_market_trend(df)

    assert result.trend == "UP"
    assert result.label == "Uptrend"
    assert result.daily_state == "UP_BREAKOUT"
    assert result.weekly_state == "UP"


def test_market_trend_downtrend_requires_daily_breakdown_and_weekly_structure():
    from app.analysis.market_trend import classify_market_trend

    df = _df([
        ("2026-01-02", 130, 136, 126, 128, 1),
        ("2026-01-09", 128, 132, 120, 122, 1),
        ("2026-01-16", 122, 126, 112, 114, 1),
        ("2026-01-23", 114, 118, 104, 106, 1),
        ("2026-01-26", 106, 110, 100, 102, 1),
        ("2026-01-27", 102, 108, 96, 98, 1),
    ])

    result = classify_market_trend(df)

    assert result.trend == "DOWN"
    assert result.label == "Downtrend"
    assert result.daily_state == "DOWN_BREAKDOWN"
    assert result.weekly_state == "DOWN"


def test_market_trend_inside_yesterday_range_is_mixed():
    from app.analysis.market_trend import classify_market_trend

    df = _df([
        ("2026-01-02", 100, 110, 95, 108, 1),
        ("2026-01-09", 108, 116, 100, 114, 1),
        ("2026-01-16", 114, 124, 108, 122, 1),
        ("2026-01-23", 122, 132, 116, 130, 1),
        ("2026-01-26", 130, 136, 126, 134, 1),
        ("2026-01-27", 134, 135, 127, 132, 1),
    ])

    result = classify_market_trend(df)

    assert result.trend == "MIXED"
    assert result.label == "Mixed"
    assert result.daily_state == "INSIDE_RANGE"


def test_market_trend_daily_breakdown_in_weekly_uptrend_is_mixed_pullback():
    from app.analysis.market_trend import classify_market_trend

    df = _df([
        ("2026-01-02", 100, 110, 95, 108, 1),
        ("2026-01-09", 108, 116, 100, 114, 1),
        ("2026-01-16", 114, 124, 108, 122, 1),
        ("2026-01-23", 122, 132, 116, 130, 1),
        ("2026-01-26", 130, 136, 126, 134, 1),
        ("2026-01-27", 134, 135, 124, 125, 1),
    ])

    result = classify_market_trend(df)

    assert result.trend == "MIXED"
    assert result.label == "Mixed pullback"
    assert result.daily_state == "DOWN_BREAKDOWN"
    assert result.weekly_state == "UP"
