"""Live-tick evaluator for the paper-INDEX bot.

Pure-function counterpart of [`backend/app/paper/live_engine.py`](../paper/live_engine.py)
that translates a single spot-price tick on the underlying index into option
premium moves via the existing delta approximation, then walks an open
position through the same SL / T1 / T2 / breakeven-trail priority order as
the historical [`simulator.simulate_position`](./simulator.py).

Trade-management agent contract (per design):
    - Manages OPEN / PARTIAL_EXIT positions only.
    - Does NOT open new positions or fill PENDING_ENTRY orders intraday.
      Pending entries continue to be filled by the daily simulate_day pass
      so we keep entry timing under one well-tested code path.
    - Returns a list of `IndexSimEvent`; never mutates the position object.
    - No DB, no clock, no I/O.
"""
from __future__ import annotations

from datetime import date as _date
from math import floor
from typing import List

from .simulator import (
    EV_STOP_LOSS,
    EV_TARGET_1,
    EV_TARGET_2,
    EV_TRAIL,
    IndexSimEvent,
    IndexSimPosition,
)


def spot_to_premium(
    *,
    spot: float,
    entry_spot: float,
    entry_premium: float,
    delta: float,
    direction: str,
) -> float:
    """Map an underlying spot to an estimated option premium.

    LONG/CE:   premium  = entry_premium + delta * (spot - entry_spot)
    SHORT/PE:  premium  = entry_premium + delta * (entry_spot - spot)

    Premium is clamped to >= 0 (option premium can't go negative).
    """
    if direction == "LONG":
        prem = float(entry_premium) + float(delta) * (float(spot) - float(entry_spot))
    else:
        prem = float(entry_premium) + float(delta) * (float(entry_spot) - float(spot))
    return max(0.0, prem)


def evaluate_open_position(
    pos: IndexSimPosition,
    spot_price: float,
    *,
    at: _date,
    partial_exit_pct: float = 50.0,
    trailing_stop_enabled: bool = True,
) -> List[IndexSimEvent]:
    """Walk a single live spot tick against an OPEN/PARTIAL_EXIT position.

    Priority order on a single price point (matches the historical simulator):
        1. Stop-loss / trailing stop (lowest tolerated risk wins on conflict).
        2. Target-2 (full exit, taking T1 first if not yet partialled).
        3. Target-1 (partial exit + optional breakeven move).

    The premium is mark-to-spot via `spot_to_premium`. We never re-evaluate
    pending entries here; PENDING_ENTRY positions are owned by the daily
    `simulator.simulate_entry` path so entry pricing stays deterministic.
    """
    events: List[IndexSimEvent] = []

    if pos.entry_premium is None or pos.entry_premium <= 0:
        return events
    if pos.quantity <= 0:
        return events
    # `__post_init__` guarantees remaining_quantity is populated, so trust it
    # directly here. Using `or` would mask a fully-exited position because 0
    # is falsy.
    remaining = int(pos.remaining_quantity)
    if remaining <= 0:
        return events

    prem = spot_to_premium(
        spot=spot_price,
        entry_spot=pos.entry_spot,
        entry_premium=pos.entry_premium,
        delta=pos.delta,
        direction=pos.direction,
    )

    # 1. Stop-loss / trailing stop.
    if prem <= pos.stop_loss:
        pnl = (pos.stop_loss - pos.entry_premium) * remaining
        is_trail = bool(pos.breakeven_moved)
        events.append(IndexSimEvent(
            date=at,
            event_type=EV_TRAIL if is_trail else EV_STOP_LOSS,
            price=pos.stop_loss,
            quantity=remaining,
            pnl=pnl,
            note="live tick: trailing stop hit" if is_trail else "live tick: premium stop hit",
            new_status="CLOSED_TRAILING_STOP" if is_trail else "CLOSED_STOP_LOSS",
            realized_pnl_total=pnl,
            spot=float(spot_price),
        ))
        return events

    qty_t1 = max(1, floor(int(pos.quantity) * (float(partial_exit_pct) / 100.0)))
    if qty_t1 >= int(pos.quantity):
        qty_t1 = max(1, int(pos.quantity) - 1)

    # 2. Target-2 takes the full remainder (taking T1 first if not yet hit).
    if pos.target_2 is not None and prem >= pos.target_2:
        realized = 0.0
        if (
            not pos.breakeven_moved
            and pos.target_1 is not None
            and remaining > qty_t1
        ):
            pnl1 = (pos.target_1 - pos.entry_premium) * qty_t1
            realized += pnl1
            events.append(IndexSimEvent(
                date=at,
                event_type=EV_TARGET_1,
                price=pos.target_1,
                quantity=qty_t1,
                pnl=pnl1,
                note="live tick: T1 partial exit",
                breakeven_after=trailing_stop_enabled,
                realized_pnl_total=realized,
                spot=float(spot_price),
            ))
            remaining -= qty_t1
        pnl2 = (pos.target_2 - pos.entry_premium) * remaining
        realized += pnl2
        events.append(IndexSimEvent(
            date=at,
            event_type=EV_TARGET_2,
            price=pos.target_2,
            quantity=remaining,
            pnl=pnl2,
            note="live tick: T2 final exit",
            new_status="CLOSED_TARGET",
            realized_pnl_total=realized,
            spot=float(spot_price),
        ))
        return events

    # 3. Target-1: partial when there's a remainder left, otherwise final close.
    if (
        pos.target_1 is not None
        and prem >= pos.target_1
        and not pos.breakeven_moved
    ):
        if remaining > qty_t1:
            pnl1 = (pos.target_1 - pos.entry_premium) * qty_t1
            events.append(IndexSimEvent(
                date=at,
                event_type=EV_TARGET_1,
                price=pos.target_1,
                quantity=qty_t1,
                pnl=pnl1,
                note="live tick: T1 partial exit",
                breakeven_after=trailing_stop_enabled,
                realized_pnl_total=pnl1,
                spot=float(spot_price),
            ))
        else:
            pnl1 = (pos.target_1 - pos.entry_premium) * remaining
            events.append(IndexSimEvent(
                date=at,
                event_type=EV_TARGET_1,
                price=pos.target_1,
                quantity=remaining,
                pnl=pnl1,
                note="live tick: T1 final exit",
                new_status="CLOSED_TARGET",
                realized_pnl_total=pnl1,
                spot=float(spot_price),
            ))
        return events

    return events


__all__ = ["spot_to_premium", "evaluate_open_position"]
