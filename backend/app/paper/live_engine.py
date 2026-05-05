"""Live-tick paper-trading engine.

Pure-function evaluator that maps a single live price tick (one number per
symbol) onto the same `SimEvent` stream that the historical `simulator.py`
emits. The orchestrator (`service.process_live_tick`) then persists those
events through the existing `positions.apply_event`, so the position state
machine, ledger, breakeven trailing, and daily-perf code paths are reused
without duplication.

Why a separate module from `simulator.py`?
    The historical simulator works on OHLC candles and has a same-candle
    conflict policy (stop vs. target inside one bar). A live tick is a
    single price point: there is no conflict to resolve, and the order of
    checks can be a strict priority list (stop -> T2 -> T1).

Strict invariants:
    - Long-only (matches the rest of the paper layer today).
    - Returns events; never mutates the position object.
    - No DB, no clock, no I/O.
"""
from __future__ import annotations

from datetime import date as _date
from math import floor
from typing import List, Optional

from .simulator import (
    EV_ENTRY_FILL,
    EV_STOP_LOSS,
    EV_TARGET_1,
    EV_TARGET_2,
    EV_TRAIL,
    SimEvent,
    SimPosition,
)


def evaluate_pending_entry(
    pos: SimPosition,
    last_price: float,
    *,
    at: _date,
) -> Optional[SimEvent]:
    """Limit-style fill: emit ENTRY_FILL when the live price has touched the
    planned entry from above. Returns None while the price stays above entry.

    The fill price is `pos.entry_price` (the limit), not `last_price`, so the
    paper bot doesn't get a free favourable slip when the tick happens to
    print well below entry. This matches `simulator.simulate_entry`.
    """
    if pos.quantity <= 0 or pos.entry_price is None:
        return None

    fill_target = pos.entry_price
    if last_price > fill_target:
        return None

    return SimEvent(
        date=at,
        event_type=EV_ENTRY_FILL,
        price=fill_target,
        quantity=pos.quantity,
        note="live tick: limit entry filled",
        new_status="OPEN",
    )


def evaluate_open_position(
    pos: SimPosition,
    last_price: float,
    *,
    at: _date,
    partial_exit_pct: float = 50.0,
    trailing_stop_enabled: bool = True,
) -> List[SimEvent]:
    """Walk a single live tick against an OPEN/PARTIAL_EXIT position.

    Priority order on a single price point:
        1. Stop-loss (lowest tolerated risk wins on conflict).
        2. Target-2 (full exit, taking T1 first if not yet partialled).
        3. Target-1 (partial exit + optional breakeven move).
    """
    events: List[SimEvent] = []

    if pos.entry_price is None:
        return events
    remaining = pos.remaining_quantity or pos.quantity
    if remaining <= 0:
        return events

    # 1. Stop-loss / trailing stop.
    if last_price <= pos.stop_loss:
        pnl = (pos.stop_loss - pos.entry_price) * remaining
        is_trail = bool(pos.breakeven_moved)
        events.append(SimEvent(
            date=at,
            event_type=EV_TRAIL if is_trail else EV_STOP_LOSS,
            price=pos.stop_loss,
            quantity=remaining,
            pnl=pnl,
            note="live tick: trailing stop hit" if is_trail else "live tick: stop loss hit",
            new_status="CLOSED_TRAILING_STOP" if is_trail else "CLOSED_STOP_LOSS",
            realized_pnl_total=pnl,
        ))
        return events

    qty_t1 = max(1, floor(pos.quantity * (partial_exit_pct / 100.0)))
    if qty_t1 >= pos.quantity:
        qty_t1 = max(1, pos.quantity - 1)

    # 2. Target-2 takes the full remainder (taking T1 first if not yet hit).
    if pos.target_2 is not None and last_price >= pos.target_2:
        realized = 0.0
        if (
            not pos.breakeven_moved
            and pos.target_1 is not None
            and remaining > qty_t1
        ):
            pnl1 = (pos.target_1 - pos.entry_price) * qty_t1
            realized += pnl1
            events.append(SimEvent(
                date=at,
                event_type=EV_TARGET_1,
                price=pos.target_1,
                quantity=qty_t1,
                pnl=pnl1,
                note="live tick: T1 partial exit",
                breakeven_after=trailing_stop_enabled,
                realized_pnl_total=realized,
            ))
            remaining -= qty_t1
        pnl2 = (pos.target_2 - pos.entry_price) * remaining
        realized += pnl2
        events.append(SimEvent(
            date=at,
            event_type=EV_TARGET_2,
            price=pos.target_2,
            quantity=remaining,
            pnl=pnl2,
            note="live tick: T2 final exit",
            new_status="CLOSED_TARGET",
            realized_pnl_total=realized,
        ))
        return events

    # 3. Target-1: partial if a remainder will be left, otherwise final close.
    if pos.target_1 is not None and last_price >= pos.target_1 and not pos.breakeven_moved:
        if remaining > qty_t1:
            pnl1 = (pos.target_1 - pos.entry_price) * qty_t1
            events.append(SimEvent(
                date=at,
                event_type=EV_TARGET_1,
                price=pos.target_1,
                quantity=qty_t1,
                pnl=pnl1,
                note="live tick: T1 partial exit",
                breakeven_after=trailing_stop_enabled,
                realized_pnl_total=pnl1,
            ))
        else:
            pnl1 = (pos.target_1 - pos.entry_price) * remaining
            events.append(SimEvent(
                date=at,
                event_type=EV_TARGET_1,
                price=pos.target_1,
                quantity=remaining,
                pnl=pnl1,
                note="live tick: T1 final exit",
                new_status="CLOSED_TARGET",
                realized_pnl_total=pnl1,
            ))
        return events

    return events
