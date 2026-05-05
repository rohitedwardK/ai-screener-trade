"""PaperOrderSimulator.

Pure-function order simulation against an OHLCV DataFrame slice. Produces a
deterministic stream of `SimEvent`s that the position manager / ledger can
persist. No I/O, no DB, no clock.

Supported event types:
    ENTRY_FILL, STOP_LOSS_HIT, TARGET_1_HIT, TARGET_2_HIT,
    TRAILING_STOP_HIT, TIME_EXIT, ENTRY_EXPIRED

Same-candle conflict policy:
    - "conservative" (default): stop wins if both stop and target trigger in
      the same candle.
    - "optimistic": target wins on conflict.
    - "ohlc_approx": infer order from open/close direction (close > open ->
      bullish, target first; else bearish, stop first). Falls back to
      conservative when the close == open.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from math import floor
from typing import List, Optional

import pandas as pd

# Public event-type constants ---------------------------------------------------
EV_ENTRY_FILL = "ENTRY_FILL"
EV_STOP_LOSS = "STOP_LOSS_HIT"
EV_TARGET_1 = "TARGET_1_HIT"
EV_TARGET_2 = "TARGET_2_HIT"
EV_TRAIL = "TRAILING_STOP_HIT"
EV_TIME_EXIT = "TIME_EXIT"
EV_ENTRY_EXPIRED = "ENTRY_EXPIRED"

EXIT_EVENTS = {EV_STOP_LOSS, EV_TARGET_1, EV_TARGET_2, EV_TRAIL, EV_TIME_EXIT}


@dataclass
class SimPosition:
    """In-memory position state used by the simulator (no DB binding)."""
    symbol: str
    entry_price: Optional[float]
    quantity: int
    stop_loss: float
    target_1: Optional[float]
    target_2: Optional[float]
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    entry_date: Optional[date] = None
    is_intraday: bool = False
    breakeven_moved: bool = False
    remaining_quantity: int = 0
    status: str = "PENDING_ENTRY"

    def __post_init__(self) -> None:
        if self.remaining_quantity == 0:
            self.remaining_quantity = self.quantity


@dataclass
class SimEvent:
    date: date
    event_type: str
    price: float
    quantity: int
    pnl: float = 0.0
    note: str = ""
    breakeven_after: bool = False
    new_status: Optional[str] = None
    realized_pnl_total: float = 0.0
    fields: dict = field(default_factory=dict)


# --- helpers ---

def _entry_in_range(low: Optional[float], high: Optional[float], target: float) -> bool:
    if low is None or high is None:
        return False
    return low <= target <= high


def _candle(row: pd.Series) -> tuple[float, float, float, float]:
    return float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])


def _resolve_same_candle(
    open_: float, close_: float, policy: str, sl_in: bool, tgt_in: bool,
) -> str:
    """Return 'stop' or 'target' or 'both' (split) or 'none'."""
    if not sl_in and not tgt_in:
        return "none"
    if sl_in and not tgt_in:
        return "stop"
    if tgt_in and not sl_in:
        return "target"
    # both are in range -> resolve via policy
    if policy == "optimistic":
        return "target"
    if policy == "ohlc_approx":
        if close_ > open_:
            return "target"
        if close_ < open_:
            return "stop"
        return "stop"
    return "stop"  # conservative default


# --- entry simulation ---

def simulate_entry(
    pos: SimPosition,
    candles: pd.DataFrame,
    *,
    expiry_days: int = 5,
) -> tuple[Optional[SimEvent], int]:
    """Walk forward from `candles[0]` until entry fills or the order expires.

    Returns (event_or_None, last_index_processed).
    The candle index *must* be strictly after the signal date (no look-ahead).
    """
    if candles is None or candles.empty or pos.quantity <= 0:
        return None, -1

    fill_target: Optional[float] = pos.entry_price
    if fill_target is None and pos.entry_zone_high is not None:
        fill_target = pos.entry_zone_high

    if fill_target is None:
        return None, -1

    consumed = 0
    for i, (ts, row) in enumerate(candles.iterrows()):
        consumed = i
        if i >= expiry_days:
            return SimEvent(
                date=pd.Timestamp(ts).date(),
                event_type=EV_ENTRY_EXPIRED,
                price=fill_target,
                quantity=pos.quantity,
                note=f"entry order expired after {expiry_days} candles",
                new_status="EXPIRED",
            ), i
        o, h, l, c = _candle(row)
        # Limit-style fill: any candle whose [low,high] contains the entry price.
        if l <= fill_target <= h:
            fill_price = fill_target
            return SimEvent(
                date=pd.Timestamp(ts).date(),
                event_type=EV_ENTRY_FILL,
                price=fill_price,
                quantity=pos.quantity,
                note="limit entry filled",
                new_status="OPEN",
                fields={"open": o, "high": h, "low": l, "close": c},
            ), i

    # ran out of data: keep order pending
    return None, consumed


# --- post-entry simulation ---

def simulate_position(
    pos: SimPosition,
    candles_after_entry: pd.DataFrame,
    *,
    policy: str = "conservative",
    partial_exit_pct: float = 50.0,
    trailing_stop_enabled: bool = True,
    intraday_horizon_days: int = 1,
    swing_horizon_days: int = 30,
) -> List[SimEvent]:
    """Walk through candles after entry, emitting exit events until closed.

    The position object is *not* mutated; the caller updates DB state from
    the returned events.
    """
    events: List[SimEvent] = []
    if candles_after_entry is None or candles_after_entry.empty:
        return events
    if pos.quantity <= 0 or pos.entry_price is None:
        return events

    remaining = pos.remaining_quantity or pos.quantity
    realized = 0.0
    stop = pos.stop_loss
    breakeven_moved = pos.breakeven_moved
    horizon = intraday_horizon_days if pos.is_intraday else swing_horizon_days

    qty_t1 = max(1, floor(pos.quantity * (partial_exit_pct / 100.0)))
    if qty_t1 >= pos.quantity:
        qty_t1 = max(1, pos.quantity - 1)  # always leave something for T2

    for i, (ts, row) in enumerate(candles_after_entry.iterrows()):
        d = pd.Timestamp(ts).date()
        o, h, l, c = _candle(row)

        sl_in = l <= stop <= h or l <= stop  # stop hit if low penetrates
        sl_in = l <= stop
        t1_in = pos.target_1 is not None and h >= pos.target_1 and remaining > 0
        t2_in = pos.target_2 is not None and h >= pos.target_2 and remaining > 0

        # Time exit (intraday): close at the last candle's close.
        if pos.is_intraday and i + 1 >= horizon:
            # If neither stop nor target hit inside this candle, close at close.
            decision = _resolve_same_candle(o, c, policy, sl_in, t1_in or t2_in)
            if decision == "stop":
                pnl = (stop - pos.entry_price) * remaining
                realized += pnl
                events.append(SimEvent(
                    date=d, event_type=EV_STOP_LOSS, price=stop,
                    quantity=remaining, pnl=pnl,
                    note="intraday: stop hit at end of horizon",
                    new_status="CLOSED_STOP_LOSS",
                    realized_pnl_total=realized,
                ))
                return events
            if decision == "target":
                # treat as T1 (then time-exit T2 if applicable below)
                if t2_in and pos.target_2 is not None:
                    pnl = (pos.target_2 - pos.entry_price) * remaining
                    realized += pnl
                    events.append(SimEvent(
                        date=d, event_type=EV_TARGET_2, price=pos.target_2,
                        quantity=remaining, pnl=pnl,
                        note="intraday: T2 hit at end of horizon",
                        new_status="CLOSED_TARGET",
                        realized_pnl_total=realized,
                    ))
                    return events
                if t1_in and pos.target_1 is not None and remaining > qty_t1:
                    pnl = (pos.target_1 - pos.entry_price) * qty_t1
                    realized += pnl
                    remaining -= qty_t1
                    events.append(SimEvent(
                        date=d, event_type=EV_TARGET_1, price=pos.target_1,
                        quantity=qty_t1, pnl=pnl,
                        note="intraday: T1 partial",
                        breakeven_after=trailing_stop_enabled,
                        realized_pnl_total=realized,
                    ))
                    if trailing_stop_enabled:
                        stop = pos.entry_price
                        breakeven_moved = True
                    # then time-exit the remainder at close
            # close remainder at close (time exit)
            pnl = (c - pos.entry_price) * remaining
            realized += pnl
            events.append(SimEvent(
                date=d, event_type=EV_TIME_EXIT, price=c,
                quantity=remaining, pnl=pnl,
                note="intraday time exit at close",
                new_status="CLOSED_TIME_EXIT",
                realized_pnl_total=realized,
            ))
            return events

        decision = _resolve_same_candle(o, c, policy, sl_in, t1_in or t2_in)

        if decision == "stop":
            pnl = (stop - pos.entry_price) * remaining
            realized += pnl
            events.append(SimEvent(
                date=d, event_type=EV_TRAIL if breakeven_moved else EV_STOP_LOSS,
                price=stop, quantity=remaining, pnl=pnl,
                note="trailing stop hit" if breakeven_moved else "stop loss hit",
                new_status="CLOSED_TRAILING_STOP" if breakeven_moved else "CLOSED_STOP_LOSS",
                realized_pnl_total=realized,
            ))
            return events

        if decision == "target":
            # First, T2 if available and clearly hit and remaining matches the full leg.
            if t2_in and pos.target_2 is not None:
                # If T1 not previously hit and remaining > qty_t1, take T1 first then T2.
                if not breakeven_moved and pos.target_1 is not None and remaining > qty_t1 and t1_in:
                    pnl1 = (pos.target_1 - pos.entry_price) * qty_t1
                    realized += pnl1
                    remaining -= qty_t1
                    events.append(SimEvent(
                        date=d, event_type=EV_TARGET_1, price=pos.target_1,
                        quantity=qty_t1, pnl=pnl1,
                        note="T1 partial exit",
                        breakeven_after=trailing_stop_enabled,
                        realized_pnl_total=realized,
                    ))
                    if trailing_stop_enabled:
                        stop = pos.entry_price
                        breakeven_moved = True
                # Then T2 closes remaining
                pnl2 = (pos.target_2 - pos.entry_price) * remaining
                realized += pnl2
                events.append(SimEvent(
                    date=d, event_type=EV_TARGET_2, price=pos.target_2,
                    quantity=remaining, pnl=pnl2,
                    note="T2 final exit",
                    new_status="CLOSED_TARGET",
                    realized_pnl_total=realized,
                ))
                return events

            # Otherwise just T1 partial (if eligible) or close on T1 alone.
            if t1_in and pos.target_1 is not None:
                if remaining > qty_t1:
                    pnl1 = (pos.target_1 - pos.entry_price) * qty_t1
                    realized += pnl1
                    remaining -= qty_t1
                    events.append(SimEvent(
                        date=d, event_type=EV_TARGET_1, price=pos.target_1,
                        quantity=qty_t1, pnl=pnl1,
                        note="T1 partial exit",
                        breakeven_after=trailing_stop_enabled,
                        realized_pnl_total=realized,
                    ))
                    if trailing_stop_enabled:
                        stop = pos.entry_price
                        breakeven_moved = True
                else:
                    pnl1 = (pos.target_1 - pos.entry_price) * remaining
                    realized += pnl1
                    events.append(SimEvent(
                        date=d, event_type=EV_TARGET_1, price=pos.target_1,
                        quantity=remaining, pnl=pnl1,
                        note="T1 final exit",
                        new_status="CLOSED_TARGET",
                        realized_pnl_total=realized,
                    ))
                    return events

        # No exit on this candle: nothing to emit; loop continues.

    # Ran out of candles before any exit triggered -> position remains open.
    return events
