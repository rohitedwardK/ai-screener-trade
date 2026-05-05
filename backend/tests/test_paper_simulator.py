"""PaperOrderSimulator tests with deterministic synthetic candles."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.paper.simulator import (
    EV_ENTRY_EXPIRED,
    EV_ENTRY_FILL,
    EV_STOP_LOSS,
    EV_TARGET_1,
    EV_TARGET_2,
    EV_TIME_EXIT,
    EV_TRAIL,
    SimPosition,
    simulate_entry,
    simulate_position,
)


def _candles(rows: list[tuple[float, float, float, float]], start: date | None = None) -> pd.DataFrame:
    """Build a DataFrame of (open, high, low, close) tuples with daily index."""
    start = start or date(2026, 5, 6)
    idx = pd.date_range(start=pd.Timestamp(start), periods=len(rows), freq="B")
    return pd.DataFrame(
        rows, columns=["open", "high", "low", "close"], index=idx,
    ).assign(volume=1_000_000.0)


def _pos(**overrides) -> SimPosition:
    base = dict(
        symbol="TEST.NS",
        entry_price=100.0,
        quantity=10,
        stop_loss=95.0,
        target_1=110.0,
        target_2=120.0,
    )
    base.update(overrides)
    return SimPosition(**base)


# --- Entry simulation ---

def test_entry_fills_when_in_range():
    pos = _pos()
    candles = _candles([(99.0, 102.0, 98.0, 101.0)])
    ev, idx = simulate_entry(pos, candles)
    assert ev is not None
    assert ev.event_type == EV_ENTRY_FILL
    assert ev.price == 100.0
    assert ev.quantity == 10
    assert idx == 0


def test_entry_does_not_fill_when_above_high():
    pos = _pos(entry_price=105.0)
    candles = _candles([(99.0, 102.0, 98.0, 101.0)])
    ev, _ = simulate_entry(pos, candles)
    assert ev is None  # still pending


def test_entry_expires_after_n_candles():
    pos = _pos(entry_price=120.0)  # never reachable
    candles = _candles([(99.0, 100.0, 98.0, 99.0)] * 8)
    ev, _ = simulate_entry(pos, candles, expiry_days=5)
    assert ev is not None
    assert ev.event_type == EV_ENTRY_EXPIRED


# --- Post-entry: stop / target / partial / breakeven trail ---

def test_stop_loss_hit_full_exit():
    pos = _pos()
    candles = _candles([(100.0, 102.0, 94.0, 96.0)])  # breaches stop 95
    events = simulate_position(pos, candles, policy="conservative")
    assert len(events) == 1
    assert events[0].event_type == EV_STOP_LOSS
    assert events[0].quantity == 10
    assert events[0].pnl == (95.0 - 100.0) * 10  # -50


def test_target_1_partial_then_target_2():
    pos = _pos()
    # Day 1: hits T1 only (high=112). Day 2: hits T2 (high=121).
    candles = _candles([
        (100.0, 112.0, 99.0, 109.0),
        (109.0, 121.0, 108.0, 119.0),
    ])
    events = simulate_position(pos, candles, partial_exit_pct=50.0)
    types = [e.event_type for e in events]
    assert types == [EV_TARGET_1, EV_TARGET_2]
    assert events[0].quantity == 5  # 50% of 10
    assert events[0].pnl == (110.0 - 100.0) * 5
    assert events[1].quantity == 5
    assert events[1].pnl == (120.0 - 100.0) * 5


def test_breakeven_trail_after_t1():
    """After T1 hit, stop should move to entry; subsequent stop hit closes at entry."""
    pos = _pos()
    # Day 1: hit T1 (partial).  Day 2: dump to break entry (low 95) but trailing stop is now at 100 entry.
    candles = _candles([
        (100.0, 112.0, 99.0, 109.0),
        (108.0, 109.0, 95.0, 96.0),
    ])
    events = simulate_position(pos, candles, partial_exit_pct=50.0, trailing_stop_enabled=True)
    types = [e.event_type for e in events]
    assert types[0] == EV_TARGET_1
    assert types[1] == EV_TRAIL
    # Trailing stop = entry 100 -> pnl on remaining 5 = 0
    assert events[1].price == 100.0
    assert events[1].pnl == 0.0


def test_target_1_only_when_no_target_2():
    pos = _pos(target_2=None)
    candles = _candles([(100.0, 115.0, 99.0, 113.0)])
    events = simulate_position(pos, candles, partial_exit_pct=50.0)
    # T1 hits, but with no T2 we still partial. The remaining 5 stays open.
    assert events[0].event_type == EV_TARGET_1
    assert events[0].quantity == 5


# --- Same-candle conflict policies ---

def _conflict_candle() -> pd.DataFrame:
    """One candle that touches both target_1 (110) and stop_loss (95)."""
    return _candles([(100.0, 112.0, 90.0, 96.0)])  # close < open -> bearish if ohlc_approx


def test_same_candle_conservative_picks_stop():
    events = simulate_position(_pos(), _conflict_candle(), policy="conservative")
    assert events[0].event_type == EV_STOP_LOSS
    assert events[0].pnl == (95.0 - 100.0) * 10


def test_same_candle_optimistic_picks_target():
    events = simulate_position(_pos(), _conflict_candle(), policy="optimistic")
    # Should produce T1 partial (and potentially T2 if also reached). T2 is 120, here 112 < 120, so just T1.
    assert events[0].event_type == EV_TARGET_1


def test_same_candle_ohlc_approx_picks_stop_when_bearish():
    # close < open -> bearish -> stop wins
    events = simulate_position(_pos(), _conflict_candle(), policy="ohlc_approx")
    assert events[0].event_type == EV_STOP_LOSS


def test_same_candle_ohlc_approx_picks_target_when_bullish():
    # close > open -> bullish -> target wins
    bullish = _candles([(96.0, 112.0, 90.0, 111.0)])
    events = simulate_position(_pos(), bullish, policy="ohlc_approx")
    assert events[0].event_type == EV_TARGET_1


# --- Time exit (intraday) ---

def test_time_exit_for_intraday_when_neither_hit():
    pos = _pos(is_intraday=True)
    # candle stays inside [stop, target] range
    candles = _candles([(100.0, 105.0, 98.0, 103.0)])
    events = simulate_position(pos, candles, intraday_horizon_days=1)
    assert events[0].event_type == EV_TIME_EXIT
    assert events[0].pnl == (103.0 - 100.0) * 10


def test_no_exit_until_signal():
    pos = _pos()
    candles = _candles([(100.0, 105.0, 99.0, 102.0)] * 3)
    events = simulate_position(pos, candles)
    assert events == []  # still open
