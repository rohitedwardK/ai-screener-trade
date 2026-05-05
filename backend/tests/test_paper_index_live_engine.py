"""Pure tests for the paper-INDEX live trade-management agent.

The live engine maps a single live spot tick to an option premium via the
existing delta approximation, then walks the position through the same
SL / T1 / T2 / breakeven-trail priority order as the historical simulator.
No DB, no clock, no I/O.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.paper_index.live_engine import evaluate_open_position, spot_to_premium
from app.paper_index.simulator import (
    EV_STOP_LOSS,
    EV_TARGET_1,
    EV_TARGET_2,
    EV_TRAIL,
    IndexSimPosition,
)


_TODAY = date(2026, 5, 5)


def _long_ce(**overrides) -> IndexSimPosition:
    """Standard NIFTY 25-lot CE position used as the baseline."""
    base = dict(
        symbol="^NSEI", code="NIFTY",
        direction="LONG", option_type="CE",
        strike=22500.0, expiry=date(2026, 5, 8),
        lot_size=25, lots=2,
        entry_spot=22500.0,
        entry_premium=100.0,
        quantity=50,
        stop_loss=80.0,
        target_1=120.0,
        target_2=150.0,
        delta=0.5,
        entry_date=_TODAY,
        is_intraday=True,
    )
    base.update(overrides)
    return IndexSimPosition(**base)


def _short_pe(**overrides) -> IndexSimPosition:
    """SHORT/PE bot picks a put when underlying expected to fall."""
    base = dict(
        symbol="^NSEBANK", code="BANKNIFTY",
        direction="SHORT", option_type="PE",
        strike=48000.0, expiry=date(2026, 5, 8),
        lot_size=15, lots=2,
        entry_spot=48000.0,
        entry_premium=120.0,
        quantity=30,
        stop_loss=100.0,
        target_1=144.0,
        target_2=180.0,
        delta=0.5,
        entry_date=_TODAY,
        is_intraday=True,
    )
    base.update(overrides)
    return IndexSimPosition(**base)


# ---- spot_to_premium math ----

def test_spot_to_premium_long_ce_increases_with_spot():
    p = spot_to_premium(spot=22600, entry_spot=22500, entry_premium=100, delta=0.5, direction="LONG")
    assert p == pytest.approx(150.0)


def test_spot_to_premium_short_pe_increases_when_spot_falls():
    # PE buy: position is SHORT in spot terms -> premium up when spot down.
    p = spot_to_premium(spot=47800, entry_spot=48000, entry_premium=120, delta=0.5, direction="SHORT")
    assert p == pytest.approx(220.0)


def test_spot_to_premium_clamped_to_zero():
    p = spot_to_premium(spot=20000, entry_spot=22500, entry_premium=100, delta=0.5, direction="LONG")
    assert p == 0.0


# ---- LONG / CE flow ----

def test_long_ce_no_action_when_within_band():
    pos = _long_ce()
    # Spot small move: premium ~110, between SL 80 and T1 120 => no events.
    events = evaluate_open_position(pos, spot_price=22520, at=_TODAY)
    assert events == []


def test_long_ce_stop_loss_emits_stop_event():
    pos = _long_ce()
    # Premium = 100 + 0.5 * (22460 - 22500) = 80 -> equal to stop.
    events = evaluate_open_position(pos, spot_price=22460, at=_TODAY)
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == EV_STOP_LOSS
    assert ev.price == pytest.approx(80.0)
    assert ev.quantity == 50
    assert ev.new_status == "CLOSED_STOP_LOSS"


def test_long_ce_trailing_stop_when_breakeven_already_moved():
    pos = _long_ce(breakeven_moved=True, stop_loss=100.0, remaining_quantity=25)
    # Premium drops to 100 -> trailing stop fires (BE-locked).
    events = evaluate_open_position(pos, spot_price=22500, at=_TODAY)
    assert len(events) == 1
    assert events[0].event_type == EV_TRAIL
    assert events[0].quantity == 25
    assert events[0].new_status == "CLOSED_TRAILING_STOP"


def test_long_ce_target_1_emits_partial_with_breakeven_after():
    pos = _long_ce()
    # Premium = 100 + 0.5*(22540-22500) = 120 -> hits T1 exactly.
    events = evaluate_open_position(
        pos, spot_price=22540, at=_TODAY,
        partial_exit_pct=50.0, trailing_stop_enabled=True,
    )
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == EV_TARGET_1
    assert ev.quantity == 25
    assert ev.breakeven_after is True
    assert ev.new_status is None  # still partially open


def test_long_ce_target_2_takes_t1_first_then_full_exit():
    pos = _long_ce()
    # Spot leaps past T2 in one tick (premium ~150).
    events = evaluate_open_position(pos, spot_price=22600, at=_TODAY)
    assert [e.event_type for e in events] == [EV_TARGET_1, EV_TARGET_2]
    t1, t2 = events
    assert t1.quantity == 25 and t2.quantity == 25
    assert t2.new_status == "CLOSED_TARGET"


def test_long_ce_target_2_after_breakeven_only_emits_t2():
    pos = _long_ce(breakeven_moved=True, remaining_quantity=25, stop_loss=100.0)
    events = evaluate_open_position(pos, spot_price=22600, at=_TODAY)
    assert [e.event_type for e in events] == [EV_TARGET_2]
    assert events[0].quantity == 25


# ---- SHORT / PE flow ----

def test_short_pe_target_1_when_spot_falls():
    pos = _short_pe()
    # Premium = 120 + 0.5*(48000 - 47952) = 144 -> hits T1.
    events = evaluate_open_position(pos, spot_price=47952, at=_TODAY)
    assert events and events[0].event_type == EV_TARGET_1
    assert events[0].breakeven_after is True


def test_short_pe_stop_loss_when_spot_rallies():
    pos = _short_pe()
    # Premium = 120 + 0.5*(48000 - 48040) = 100 -> stop hit.
    events = evaluate_open_position(pos, spot_price=48040, at=_TODAY)
    assert events and events[0].event_type == EV_STOP_LOSS


# ---- Edge cases ----

def test_no_events_when_position_already_fully_exited():
    # __post_init__ resets remaining_quantity=0 back to quantity, so emulate
    # the fully-exited state by mutating the dataclass after construction.
    pos = _long_ce()
    pos.remaining_quantity = 0
    events = evaluate_open_position(pos, spot_price=22600, at=_TODAY)
    assert events == []


def test_no_events_when_entry_premium_zero():
    pos = _long_ce(entry_premium=0.0)
    events = evaluate_open_position(pos, spot_price=22600, at=_TODAY)
    assert events == []


def test_stop_priority_over_target_when_both_reachable():
    # Engineered position where stop and target are *both* breached on the
    # tick price; SL must win on a single price point.
    pos = _long_ce(stop_loss=120.0, target_1=120.0, target_2=120.0)
    events = evaluate_open_position(pos, spot_price=22540, at=_TODAY)
    assert len(events) == 1
    assert events[0].event_type == EV_STOP_LOSS
