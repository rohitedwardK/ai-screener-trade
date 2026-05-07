"""Tests for the pure live-signal verifier.

Uses the deterministic synthetic OHLCV fixtures from `conftest.py`. No DB,
no network — every test calls `verify_signal` and `project_today_bar`
directly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.live_verifier import (
    ALL_STATUSES,
    PersistedSignal,
    STATUS_CONFIRMED,
    STATUS_INVALIDATED,
    STATUS_STRENGTHENED,
    STATUS_WEAKENING,
    project_today_bar,
    verify_signal,
)


# ---------------------------------------------------------------------------
# project_today_bar
# ---------------------------------------------------------------------------
def test_project_today_bar_appends_one_row(uptrend_df):
    today = pd.Timestamp("2026-05-04")
    out = project_today_bar(uptrend_df, ltp=200.0, today=today)
    assert len(out) == len(uptrend_df) + 1
    last = out.iloc[-1]
    assert pytest.approx(last["close"], abs=1e-9) == 200.0
    # high / low must contain close.
    assert last["high"] >= last["close"]
    assert last["low"] <= last["close"]
    # OHLC self-consistency.
    assert last["high"] >= last["open"]
    assert last["low"] <= last["open"]


def test_project_today_bar_replaces_existing_today_row(uptrend_df):
    """If today's date is already present (EOD ran early), it gets replaced."""
    today = pd.Timestamp("2026-05-04")
    # Spike the original frame to put 2026-05-04 in the index already.
    augmented = uptrend_df.copy()
    augmented.loc[today] = {
        "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
    }
    out = project_today_bar(augmented, ltp=300.0, today=today)
    assert (out.index == today).sum() == 1
    assert pytest.approx(out.iloc[-1]["close"]) == 300.0


def test_project_today_bar_uses_provided_session_open(uptrend_df):
    today = pd.Timestamp("2026-05-04")
    out = project_today_bar(
        uptrend_df, ltp=205.0,
        session_open=198.0, intraday_high=210.0, intraday_low=195.0,
        volume=1_500_000.0,
        today=today,
    )
    last = out.iloc[-1]
    assert last["open"] == pytest.approx(198.0)
    # high gets clamped up to max(open, ltp, intraday_high) — already 210.
    assert last["high"] == pytest.approx(210.0)
    assert last["low"] == pytest.approx(195.0)
    assert last["volume"] == pytest.approx(1_500_000.0)


def test_project_today_bar_rejects_invalid_inputs(uptrend_df):
    with pytest.raises(ValueError):
        project_today_bar(pd.DataFrame(), ltp=100.0)
    with pytest.raises(ValueError):
        project_today_bar(uptrend_df, ltp=0.0)
    with pytest.raises(ValueError):
        project_today_bar(uptrend_df, ltp=np.nan)


# ---------------------------------------------------------------------------
# verify_signal generic gates
# ---------------------------------------------------------------------------
def _long_signal(**overrides) -> PersistedSignal:
    """Helper: a stock momentum-leader long signal with sensible defaults."""
    base = {
        "id": 1, "symbol": "TEST.NS", "category": "MOMENTUM_LEADER",
        "score": 80.0, "entry": 100.0, "stop_loss": 95.0, "target_1": 110.0,
        "persisted_rsi": 60.0, "persisted_regime": "UPTREND",
    }
    base.update(overrides)
    return PersistedSignal(**base)


def _short_signal(**overrides) -> PersistedSignal:
    base = {
        "id": 2, "symbol": "WEAK.NS", "category": "WEAK_AVOID",
        "score": 70.0, "entry": 100.0, "stop_loss": 105.0, "target_1": 92.0,
        "persisted_rsi": 35.0, "persisted_regime": "DOWNTREND",
    }
    base.update(overrides)
    return PersistedSignal(**base)


def test_verify_returns_invalidated_when_long_breaks_stop():
    sig = _long_signal()
    rec = verify_signal(
        sig,
        live_price=94.0,  # below stop 95
        live_rsi=55.0,
        live_adx=22.0,
        live_regime="UPTREND",
        live_atr=2.0,
        live_categories=["MOMENTUM_LEADER"],
        live_score=80.0,
    )
    assert rec.status == STATUS_INVALIDATED
    assert rec.signal_id == sig.id
    assert any("stop" in n.lower() for n in rec.notes)
    assert rec.distance_to_stop_pct is not None
    # Distance to stop < 0 because live < stop level.
    assert rec.distance_to_stop_pct < 0


def test_verify_returns_invalidated_when_short_breaks_stop():
    sig = _short_signal()
    rec = verify_signal(
        sig,
        live_price=106.0,  # above stop 105
        live_rsi=40.0,
        live_adx=20.0,
        live_regime="DOWNTREND",
        live_atr=2.0,
        live_categories=["WEAK_AVOID"],
        live_score=70.0,
    )
    assert rec.status == STATUS_INVALIDATED


def test_verify_invalidates_long_on_bearish_regime_flip():
    """A long thesis is INVALIDATED when live regime turns clearly bearish."""
    sig = _long_signal()
    rec = verify_signal(
        sig,
        live_price=99.0,  # stop intact
        live_rsi=50.0,
        live_adx=22.0,
        live_regime="STRONG_DOWNTREND",
        live_atr=2.0,
        live_categories=["MOMENTUM_LEADER"],
        live_score=80.0,
    )
    assert rec.status == STATUS_INVALIDATED
    assert any("regime" in n.lower() for n in rec.notes)


def test_verify_returns_strengthened_when_progress_and_rsi_align():
    """Long thesis: price advanced >=0.5*ATR AND RSI rose >=3 points."""
    sig = _long_signal(persisted_rsi=58.0)
    rec = verify_signal(
        sig,
        live_price=102.0,  # entry 100 + 2 = 1 ATR (atr=2) of progress
        live_rsi=64.0,     # delta = +6
        live_adx=28.0,
        live_regime="UPTREND",
        live_atr=2.0,
        live_categories=["MOMENTUM_LEADER"],  # same category still fires
        live_score=85.0,
    )
    assert rec.status == STATUS_STRENGTHENED
    assert rec.score_delta == pytest.approx(5.0)


def test_verify_returns_confirmed_in_steady_state():
    """Same category fires, no STRENGTHENED gate hit, stop intact."""
    sig = _long_signal()
    rec = verify_signal(
        sig,
        live_price=100.5,  # tiny advance, < 0.5 * ATR
        live_rsi=60.5,     # tiny RSI delta
        live_adx=22.0,
        live_regime="UPTREND",
        live_atr=2.0,
        live_categories=["MOMENTUM_LEADER", "SWING_NEXT_WEEK"],
        live_score=80.0,
    )
    assert rec.status == STATUS_CONFIRMED


def test_verify_returns_weakening_when_category_drops_off():
    """Same category no longer fires on live data, but stop is still intact."""
    sig = _long_signal()
    rec = verify_signal(
        sig,
        live_price=99.0,            # above stop
        live_rsi=50.0,
        live_adx=18.0,
        live_regime="UPTREND",      # not contradictory
        live_atr=2.0,
        live_categories=["SWING_NEXT_WEEK"],  # MOMENTUM_LEADER absent
        live_score=None,
    )
    assert rec.status == STATUS_WEAKENING


def test_verify_short_strengthens_on_breakdown():
    """Short thesis: price falls toward target AND RSI weakens."""
    sig = _short_signal(persisted_rsi=38.0)
    rec = verify_signal(
        sig,
        live_price=98.0,  # entry 100 - 2 = 1 ATR of progress (short direction)
        live_rsi=33.0,    # delta -5  (>=3 absolute, correct direction)
        live_adx=26.0,
        live_regime="STRONG_DOWNTREND",  # short signals: strong downtrend is *favourable*
        live_atr=2.0,
        live_categories=["WEAK_AVOID"],
        live_score=75.0,
    )
    assert rec.status == STATUS_STRENGTHENED


def test_verify_status_always_in_known_set():
    """Property check: every output status is one of the four known values."""
    sig = _long_signal()
    for live_price in (90.0, 95.0, 99.0, 100.5, 102.0, 110.0):
        rec = verify_signal(
            sig,
            live_price=live_price,
            live_rsi=60.0,
            live_adx=22.0,
            live_regime="UPTREND",
            live_atr=2.0,
            live_categories=["MOMENTUM_LEADER"],
            live_score=80.0,
        )
        assert rec.status in ALL_STATUSES


def test_distance_metrics_are_signed():
    sig = _long_signal()
    rec = verify_signal(
        sig,
        live_price=104.0,
        live_rsi=60.0,
        live_adx=22.0,
        live_regime="UPTREND",
        live_atr=2.0,
        live_categories=["MOMENTUM_LEADER"],
        live_score=80.0,
    )
    # 104 vs stop 95 -> ~+9.47%
    assert rec.distance_to_stop_pct is not None
    assert rec.distance_to_stop_pct > 0
    # 104 vs target 110 -> ~-5.45%
    assert rec.distance_to_t1_pct is not None
    assert rec.distance_to_t1_pct < 0
