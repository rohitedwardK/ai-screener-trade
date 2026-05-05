"""Tests for the paper-INDEX simulator (premium-level events)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.paper_index.simulator import (
    EV_ENTRY_FILL,
    EV_ENTRY_EXPIRED,
    EV_STOP_LOSS,
    EV_TARGET_1,
    EV_TARGET_2,
    EV_TIME_EXIT,
    IndexSimPosition,
    simulate_entry,
    simulate_position,
)


def _candles(rows):
    """rows = [(date, open, high, low, close), ...]"""
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [1.0] * len(rows),
        },
        index=idx,
    )


def _long_pos(**overrides) -> IndexSimPosition:
    base = dict(
        symbol="^NSEI", code="NIFTY",
        direction="LONG", option_type="CE",
        strike=20000.0, expiry=date(2026, 5, 8),
        lot_size=75, lots=2,
        entry_spot=20000.0, entry_premium=120.0,
        quantity=150,
        stop_loss=60.0,
        target_1=180.0,
        target_2=240.0,
        delta=0.5,
        is_intraday=True,
    )
    base.update(overrides)
    return IndexSimPosition(**base)


def _short_pos(**overrides) -> IndexSimPosition:
    base = dict(
        symbol="^NSEI", code="NIFTY",
        direction="SHORT", option_type="PE",
        strike=20000.0, expiry=date(2026, 5, 8),
        lot_size=75, lots=2,
        entry_spot=20000.0, entry_premium=120.0,
        quantity=150,
        stop_loss=60.0,
        target_1=180.0,
        target_2=240.0,
        delta=0.5,
        is_intraday=True,
    )
    base.update(overrides)
    return IndexSimPosition(**base)


# ---------- Entry simulation ----------

def test_entry_fills_when_candle_crosses_target():
    pos = _long_pos()
    candles = _candles([
        ("2026-05-05", 19950.0, 20030.0, 19940.0, 20015.0),
    ])
    ev, idx = simulate_entry(pos, candles, entry_spot_target=20000.0, entry_zone_band=0.002)
    assert ev is not None
    assert ev.event_type == EV_ENTRY_FILL
    assert idx == 0


def test_entry_expires_after_horizon():
    pos = _long_pos()
    candles = _candles([
        ("2026-05-05", 19500.0, 19550.0, 19480.0, 19510.0),
        ("2026-05-06", 19500.0, 19550.0, 19480.0, 19510.0),
        ("2026-05-07", 19500.0, 19550.0, 19480.0, 19510.0),
        ("2026-05-08", 19500.0, 19550.0, 19480.0, 19510.0),
    ])
    ev, _ = simulate_entry(pos, candles, entry_spot_target=20000.0, expiry_days=3)
    assert ev is not None
    assert ev.event_type == EV_ENTRY_EXPIRED


# ---------- Long premium stop ----------

def test_long_stop_hits_when_spot_drops():
    """spot dropping by 120 with delta 0.5 => premium drops by 60 to floor (60).
    Stop is at 60 => stop hits."""
    pos = _long_pos(is_intraday=False)
    candles = _candles([
        ("2026-05-06", 19960.0, 19970.0, 19850.0, 19880.0),
    ])
    events = simulate_position(pos, candles, policy="conservative")
    assert events
    last = events[-1]
    assert last.event_type == EV_STOP_LOSS
    assert last.pnl < 0


def test_long_target_1_partial_then_target_2():
    """spot move +400 => premium +200 => target 2 hit (240); intermediate target 1 (180) hit too."""
    pos = _long_pos(is_intraday=False)
    candles = _candles([
        ("2026-05-06", 20020.0, 20420.0, 19980.0, 20410.0),
    ])
    events = simulate_position(pos, candles, policy="conservative", partial_exit_pct=50.0)
    types = [e.event_type for e in events]
    assert EV_TARGET_1 in types
    assert EV_TARGET_2 in types
    total_pnl = sum(e.pnl for e in events)
    assert total_pnl > 0


def test_long_target_1_only_with_breakeven_trail():
    """spot move +120 (delta 0.5 => +60 premium = T1=180); afterwards spot drifts back
    to entry_spot, premium hits trailing stop at 120 (entry premium)."""
    pos = _long_pos(is_intraday=False, target_2=300.0)
    candles = _candles([
        ("2026-05-06", 20020.0, 20120.0, 19990.0, 20100.0),
        ("2026-05-07", 20100.0, 20105.0, 19995.0, 19995.0),
    ])
    events = simulate_position(
        pos, candles, policy="conservative",
        partial_exit_pct=50.0, trailing_stop_enabled=True,
    )
    types = [e.event_type for e in events]
    assert EV_TARGET_1 in types
    # Subsequent candles should kick in trailing stop at the entry premium.
    from app.paper_index.simulator import EV_TRAIL
    assert EV_TRAIL in types


# ---------- Short premium stop / target ----------

def test_short_target_when_spot_drops():
    """For SHORT/PE: premium rises when spot falls. spot -400 => premium +200 => T2 hit."""
    pos = _short_pos(is_intraday=False)
    candles = _candles([
        ("2026-05-06", 19980.0, 20020.0, 19580.0, 19590.0),
    ])
    events = simulate_position(pos, candles, policy="conservative")
    types = [e.event_type for e in events]
    assert EV_TARGET_2 in types or EV_TARGET_1 in types


def test_short_stop_when_spot_rallies():
    """Spot rallies => PE premium falls => stop hit at 60."""
    pos = _short_pos(is_intraday=False)
    candles = _candles([
        ("2026-05-06", 20020.0, 20150.0, 20010.0, 20140.0),
    ])
    events = simulate_position(pos, candles, policy="conservative")
    assert events
    assert events[-1].event_type == EV_STOP_LOSS
    assert events[-1].pnl < 0


# ---------- Intraday horizon time exit ----------

def test_intraday_time_exit_at_horizon():
    """is_intraday=True with horizon=1: even if no SL/TP triggered, position exits
    at end of first candle close."""
    pos = _long_pos(is_intraday=True)
    candles = _candles([
        ("2026-05-06", 19990.0, 20020.0, 19960.0, 19995.0),
    ])
    events = simulate_position(pos, candles, intraday_horizon_days=1)
    assert events
    last = events[-1]
    assert last.event_type in (EV_TIME_EXIT, EV_STOP_LOSS, EV_TARGET_1, EV_TARGET_2)


# ---------- Same-candle policies ----------

def test_same_candle_conservative_picks_stop():
    """A candle that hits both stop and target within the day => stop wins."""
    pos = _long_pos(is_intraday=False)
    candles = _candles([
        ("2026-05-06", 20000.0, 20420.0, 19850.0, 20300.0),
    ])
    events = simulate_position(pos, candles, policy="conservative")
    types = [e.event_type for e in events]
    # Conservative => stop on a both-hit candle.
    assert types[-1] == EV_STOP_LOSS


def test_same_candle_optimistic_picks_target():
    pos = _long_pos(is_intraday=False)
    candles = _candles([
        ("2026-05-06", 20000.0, 20420.0, 19850.0, 20300.0),
    ])
    events = simulate_position(pos, candles, policy="optimistic")
    types = [e.event_type for e in events]
    assert any(t in (EV_TARGET_1, EV_TARGET_2) for t in types)
