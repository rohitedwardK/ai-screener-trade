"""Tests for the live-tick paper-trading engine.

The live engine must agree with the historical simulator on what counts as
an entry fill, stop-loss exit, target-1 partial, and target-2 final exit -
the only difference is that it consumes a single price tick instead of an
OHLC bar. These tests therefore mirror the corresponding shapes in
`test_paper_simulator.py` but pass live prices directly.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.paper.live_engine import (
    evaluate_open_position,
    evaluate_pending_entry,
)
from app.paper.simulator import (
    EV_ENTRY_FILL,
    EV_STOP_LOSS,
    EV_TARGET_1,
    EV_TARGET_2,
    EV_TRAIL,
    SimPosition,
)


_TODAY = date(2026, 5, 6)


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


# --- Pending entry ---

def test_entry_fills_when_tick_below_entry():
    pos = _pos()
    ev = evaluate_pending_entry(pos, last_price=99.5, at=_TODAY)
    assert ev is not None
    assert ev.event_type == EV_ENTRY_FILL
    assert ev.price == 100.0  # fill at the limit, not the favourable tick
    assert ev.quantity == 10
    assert ev.new_status == "OPEN"


def test_entry_fills_at_exact_limit():
    pos = _pos()
    ev = evaluate_pending_entry(pos, last_price=100.0, at=_TODAY)
    assert ev is not None
    assert ev.event_type == EV_ENTRY_FILL


def test_entry_does_not_fill_above_limit():
    pos = _pos()
    assert evaluate_pending_entry(pos, last_price=100.5, at=_TODAY) is None


def test_entry_skipped_when_no_entry_price():
    pos = _pos(entry_price=None)
    assert evaluate_pending_entry(pos, last_price=99.0, at=_TODAY) is None


# --- Stop-loss ---

def test_stop_loss_hit_emits_stop_event():
    pos = _pos(remaining_quantity=10, status="OPEN")
    events = evaluate_open_position(pos, last_price=94.0, at=_TODAY)
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == EV_STOP_LOSS
    assert ev.price == 95.0  # exits at the stop, not the gap-down tick
    assert ev.quantity == 10
    assert ev.pnl == pytest.approx((95.0 - 100.0) * 10)
    assert ev.new_status == "CLOSED_STOP_LOSS"


def test_breakeven_moved_position_emits_trailing_stop():
    pos = _pos(
        remaining_quantity=5,
        status="PARTIAL_EXIT",
        breakeven_moved=True,
        stop_loss=100.0,
    )
    events = evaluate_open_position(pos, last_price=99.0, at=_TODAY)
    assert len(events) == 1
    assert events[0].event_type == EV_TRAIL
    assert events[0].new_status == "CLOSED_TRAILING_STOP"
    assert events[0].pnl == pytest.approx(0.0)  # exited at breakeven


# --- Targets ---

def test_target_1_emits_partial_and_marks_breakeven():
    pos = _pos(remaining_quantity=10, status="OPEN")
    events = evaluate_open_position(
        pos, last_price=110.5, at=_TODAY,
        partial_exit_pct=50.0, trailing_stop_enabled=True,
    )
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == EV_TARGET_1
    assert ev.price == 110.0
    assert ev.quantity == 5
    assert ev.pnl == pytest.approx(50.0)
    assert ev.breakeven_after is True
    assert ev.new_status is None  # still has a remainder


def test_target_2_emits_t1_then_t2_when_remainder_full():
    pos = _pos(remaining_quantity=10, status="OPEN")
    events = evaluate_open_position(
        pos, last_price=121.0, at=_TODAY,
        partial_exit_pct=50.0, trailing_stop_enabled=True,
    )
    assert len(events) == 2
    assert events[0].event_type == EV_TARGET_1
    assert events[0].quantity == 5
    assert events[0].breakeven_after is True
    assert events[1].event_type == EV_TARGET_2
    assert events[1].quantity == 5
    assert events[1].new_status == "CLOSED_TARGET"
    assert events[1].pnl == pytest.approx(100.0)


def test_target_2_after_breakeven_skips_t1_step():
    pos = _pos(
        remaining_quantity=5,
        status="PARTIAL_EXIT",
        breakeven_moved=True,
        stop_loss=100.0,
    )
    events = evaluate_open_position(
        pos, last_price=121.0, at=_TODAY,
        partial_exit_pct=50.0, trailing_stop_enabled=True,
    )
    assert len(events) == 1
    assert events[0].event_type == EV_TARGET_2
    assert events[0].quantity == 5
    assert events[0].new_status == "CLOSED_TARGET"


def test_no_event_when_price_inside_band():
    pos = _pos(remaining_quantity=10, status="OPEN")
    events = evaluate_open_position(pos, last_price=105.0, at=_TODAY)
    assert events == []


# --- Priority order: stop wins over target on the same tick ---

def test_stop_wins_when_both_levels_breached():
    """A single tick can only equal one price; if the live feed prints below
    stop, we exit on the stop regardless of any prior target proximity."""
    pos = _pos(remaining_quantity=10, status="OPEN", stop_loss=95.0, target_1=96.0, target_2=97.0)
    events = evaluate_open_position(pos, last_price=94.5, at=_TODAY)
    assert len(events) == 1
    assert events[0].event_type == EV_STOP_LOSS


# --- Defensive / degenerate cases ---

def test_no_event_when_no_remaining_quantity():
    # SimPosition.__post_init__ resets remaining_quantity to quantity when 0,
    # so we have to drop both to actually construct a "nothing left" state.
    pos = _pos(quantity=0, remaining_quantity=0, status="CLOSED_TARGET")
    assert evaluate_open_position(pos, last_price=80.0, at=_TODAY) == []


def test_no_event_when_entry_price_missing():
    pos = _pos(entry_price=None, remaining_quantity=10, status="OPEN")
    assert evaluate_open_position(pos, last_price=80.0, at=_TODAY) == []


def test_target_1_full_exit_when_qty_does_not_split():
    pos = _pos(quantity=1, remaining_quantity=1, status="OPEN")
    events = evaluate_open_position(
        pos, last_price=111.0, at=_TODAY,
        partial_exit_pct=50.0, trailing_stop_enabled=True,
    )
    assert len(events) == 1
    assert events[0].event_type == EV_TARGET_1
    assert events[0].quantity == 1
    assert events[0].new_status == "CLOSED_TARGET"
