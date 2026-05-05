"""Paper-index option order simulator.

Walks an underlying-spot OHLC frame and converts spot moves into option
*premium* moves via a delta approximation:

    premium(t)  =  entry_premium  +  delta * (spot(t) - entry_spot)         (LONG / CE)
    premium(t)  =  entry_premium  +  delta * (entry_spot - spot(t))         (SHORT / PE)

Simulation works at the **premium level**: stops, targets, and breakeven
levels are premium prices computed during sizing. The simulator just maps
each candle's high/low into premium high/low using delta and triggers
events accordingly.

Pure: no DB, no I/O. Mirrors the event-stream interface of
`app.paper.simulator` so the position-manager glue can stay similar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import floor
from typing import List, Optional

import pandas as pd


EV_ENTRY_FILL = "ENTRY_FILL"
EV_STOP_LOSS = "STOP_LOSS_HIT"
EV_TARGET_1 = "TARGET_1_HIT"
EV_TARGET_2 = "TARGET_2_HIT"
EV_TRAIL = "TRAILING_STOP_HIT"
EV_TIME_EXIT = "TIME_EXIT"
EV_ENTRY_EXPIRED = "ENTRY_EXPIRED"

EXIT_EVENTS = {EV_STOP_LOSS, EV_TARGET_1, EV_TARGET_2, EV_TRAIL, EV_TIME_EXIT}


@dataclass
class IndexSimPosition:
    symbol: str
    code: str
    direction: str           # LONG | SHORT
    option_type: str         # CE | PE
    strike: float
    expiry: date
    lot_size: int
    lots: int
    entry_spot: float
    entry_premium: float
    quantity: int            # lots * lot_size, used for P&L math
    stop_loss: float         # premium
    target_1: Optional[float]
    target_2: Optional[float]
    delta: float
    entry_date: Optional[date] = None
    is_intraday: bool = True
    breakeven_moved: bool = False
    remaining_quantity: int = 0
    status: str = "OPEN"

    def __post_init__(self) -> None:
        if self.remaining_quantity == 0:
            self.remaining_quantity = self.quantity


@dataclass
class IndexSimEvent:
    date: date
    event_type: str
    price: float             # premium price
    quantity: int
    pnl: float = 0.0
    note: str = ""
    breakeven_after: bool = False
    new_status: Optional[str] = None
    realized_pnl_total: float = 0.0
    spot: Optional[float] = None
    fields: dict = field(default_factory=dict)


# --- Helpers ---

def _candle_premium_range(
    spot_low: float, spot_high: float, *,
    entry_spot: float, entry_premium: float, delta: float, direction: str,
) -> tuple[float, float]:
    """Map a candle's spot [low, high] into premium [low, high].

    For LONG/CE buy: premium high is at spot high, premium low at spot low.
    For SHORT/PE buy: premium high is at spot low, premium low at spot high.
    """
    if direction == "LONG":
        prem_low = entry_premium + delta * (spot_low - entry_spot)
        prem_high = entry_premium + delta * (spot_high - entry_spot)
    else:
        prem_low = entry_premium + delta * (entry_spot - spot_high)
        prem_high = entry_premium + delta * (entry_spot - spot_low)
    # Premium can't go negative.
    prem_low = max(0.0, prem_low)
    prem_high = max(prem_low, prem_high)
    return prem_low, prem_high


def _candle_premium_close(
    spot_close: float, *,
    entry_spot: float, entry_premium: float, delta: float, direction: str,
) -> float:
    if direction == "LONG":
        c = entry_premium + delta * (spot_close - entry_spot)
    else:
        c = entry_premium + delta * (entry_spot - spot_close)
    return max(0.0, c)


def _resolve_same_candle(
    spot_open: float, spot_close: float, policy: str, sl_in: bool, tgt_in: bool,
) -> str:
    if not sl_in and not tgt_in:
        return "none"
    if sl_in and not tgt_in:
        return "stop"
    if tgt_in and not sl_in:
        return "target"
    if policy == "optimistic":
        return "target"
    if policy == "ohlc_approx":
        if spot_close > spot_open:
            return "target"
        if spot_close < spot_open:
            return "stop"
        return "stop"
    return "stop"


def _direction_aligned_open_close(
    direction: str, spot_open: float, spot_close: float,
) -> tuple[float, float]:
    """For premium-based same-candle resolution we need open/close in
    direction-aligned space (rising premium = "favourable")."""
    if direction == "LONG":
        return spot_open, spot_close
    return -spot_open, -spot_close


# --- Entry simulation ---

def simulate_entry(
    pos: IndexSimPosition,
    candles: pd.DataFrame,
    *,
    entry_spot_target: float,
    entry_zone_band: float = 0.002,  # +/- 0.2% around entry_spot_target
    expiry_days: int = 3,
) -> tuple[Optional[IndexSimEvent], int]:
    """Simulate a limit-style entry: any candle whose [low, high] crosses
    `entry_spot_target` (within ±band) fills at that target."""
    if candles is None or candles.empty or pos.quantity <= 0:
        return None, -1
    band_low = entry_spot_target * (1.0 - entry_zone_band)
    band_high = entry_spot_target * (1.0 + entry_zone_band)
    consumed = 0
    for i, (ts, row) in enumerate(candles.iterrows()):
        consumed = i
        if i >= expiry_days:
            return IndexSimEvent(
                date=pd.Timestamp(ts).date(),
                event_type=EV_ENTRY_EXPIRED,
                price=pos.entry_premium,
                quantity=pos.quantity,
                note=f"entry order expired after {expiry_days} candles",
                new_status="EXPIRED",
                spot=entry_spot_target,
            ), i
        low = float(row["low"])
        high = float(row["high"])
        if (low <= band_high) and (high >= band_low):
            return IndexSimEvent(
                date=pd.Timestamp(ts).date(),
                event_type=EV_ENTRY_FILL,
                price=pos.entry_premium,
                quantity=pos.quantity,
                note="limit entry filled",
                new_status="OPEN",
                spot=entry_spot_target,
                fields={"spot_low": low, "spot_high": high, "spot_close": float(row["close"])},
            ), i
    return None, consumed


# --- Post-entry simulation ---

def simulate_position(
    pos: IndexSimPosition,
    candles_after_entry: pd.DataFrame,
    *,
    policy: str = "conservative",
    partial_exit_pct: float = 50.0,
    trailing_stop_enabled: bool = True,
    intraday_horizon_days: int = 1,
    swing_horizon_days: int = 5,
) -> List[IndexSimEvent]:
    events: List[IndexSimEvent] = []
    if candles_after_entry is None or candles_after_entry.empty:
        return events
    if pos.quantity <= 0 or pos.entry_premium is None:
        return events

    remaining = pos.remaining_quantity or pos.quantity
    realized = 0.0
    stop = pos.stop_loss
    breakeven_moved = pos.breakeven_moved
    horizon = intraday_horizon_days if pos.is_intraday else swing_horizon_days
    qty_t1 = max(1, floor(pos.quantity * (partial_exit_pct / 100.0)))
    if qty_t1 >= pos.quantity:
        qty_t1 = max(1, pos.quantity - 1)

    for i, (ts, row) in enumerate(candles_after_entry.iterrows()):
        d = pd.Timestamp(ts).date()
        spot_open = float(row["open"])
        spot_high = float(row["high"])
        spot_low = float(row["low"])
        spot_close = float(row["close"])

        prem_low, prem_high = _candle_premium_range(
            spot_low, spot_high,
            entry_spot=pos.entry_spot, entry_premium=pos.entry_premium,
            delta=pos.delta, direction=pos.direction,
        )

        sl_in = prem_low <= stop
        t1_in = pos.target_1 is not None and prem_high >= pos.target_1 and remaining > 0
        t2_in = pos.target_2 is not None and prem_high >= pos.target_2 and remaining > 0

        # For same-candle conflict resolution we treat directional spot move as
        # "favourable open/close" so the existing helper still works.
        ao, ac = _direction_aligned_open_close(pos.direction, spot_open, spot_close)

        # Time exit on horizon for intraday
        if pos.is_intraday and i + 1 >= horizon:
            decision = _resolve_same_candle(ao, ac, policy, sl_in, t1_in or t2_in)
            if decision == "stop":
                pnl = (stop - pos.entry_premium) * remaining
                realized += pnl
                events.append(IndexSimEvent(
                    date=d, event_type=EV_STOP_LOSS, price=stop,
                    quantity=remaining, pnl=pnl,
                    note="intraday: premium stop hit at end of horizon",
                    new_status="CLOSED_STOP_LOSS",
                    realized_pnl_total=realized, spot=spot_close,
                ))
                return events
            if decision == "target":
                if t2_in and pos.target_2 is not None:
                    pnl = (pos.target_2 - pos.entry_premium) * remaining
                    realized += pnl
                    events.append(IndexSimEvent(
                        date=d, event_type=EV_TARGET_2, price=pos.target_2,
                        quantity=remaining, pnl=pnl,
                        note="intraday: T2 hit at end of horizon",
                        new_status="CLOSED_TARGET",
                        realized_pnl_total=realized, spot=spot_close,
                    ))
                    return events
                if t1_in and pos.target_1 is not None and remaining > qty_t1:
                    pnl = (pos.target_1 - pos.entry_premium) * qty_t1
                    realized += pnl
                    remaining -= qty_t1
                    events.append(IndexSimEvent(
                        date=d, event_type=EV_TARGET_1, price=pos.target_1,
                        quantity=qty_t1, pnl=pnl,
                        note="intraday: T1 partial",
                        breakeven_after=trailing_stop_enabled,
                        realized_pnl_total=realized, spot=spot_close,
                    ))
                    if trailing_stop_enabled:
                        stop = pos.entry_premium
                        breakeven_moved = True
            # close remainder at premium derived from candle close
            close_prem = _candle_premium_close(
                spot_close, entry_spot=pos.entry_spot,
                entry_premium=pos.entry_premium, delta=pos.delta, direction=pos.direction,
            )
            pnl = (close_prem - pos.entry_premium) * remaining
            realized += pnl
            events.append(IndexSimEvent(
                date=d, event_type=EV_TIME_EXIT, price=close_prem,
                quantity=remaining, pnl=pnl,
                note="intraday time exit at close",
                new_status="CLOSED_TIME_EXIT",
                realized_pnl_total=realized, spot=spot_close,
            ))
            return events

        decision = _resolve_same_candle(ao, ac, policy, sl_in, t1_in or t2_in)

        if decision == "stop":
            pnl = (stop - pos.entry_premium) * remaining
            realized += pnl
            events.append(IndexSimEvent(
                date=d, event_type=EV_TRAIL if breakeven_moved else EV_STOP_LOSS,
                price=stop, quantity=remaining, pnl=pnl,
                note="trailing stop hit" if breakeven_moved else "premium stop hit",
                new_status="CLOSED_TRAILING_STOP" if breakeven_moved else "CLOSED_STOP_LOSS",
                realized_pnl_total=realized, spot=spot_close,
            ))
            return events

        if decision == "target":
            if t2_in and pos.target_2 is not None:
                if not breakeven_moved and pos.target_1 is not None and remaining > qty_t1 and t1_in:
                    pnl1 = (pos.target_1 - pos.entry_premium) * qty_t1
                    realized += pnl1
                    remaining -= qty_t1
                    events.append(IndexSimEvent(
                        date=d, event_type=EV_TARGET_1, price=pos.target_1,
                        quantity=qty_t1, pnl=pnl1,
                        note="T1 partial exit",
                        breakeven_after=trailing_stop_enabled,
                        realized_pnl_total=realized, spot=spot_close,
                    ))
                    if trailing_stop_enabled:
                        stop = pos.entry_premium
                        breakeven_moved = True
                pnl2 = (pos.target_2 - pos.entry_premium) * remaining
                realized += pnl2
                events.append(IndexSimEvent(
                    date=d, event_type=EV_TARGET_2, price=pos.target_2,
                    quantity=remaining, pnl=pnl2,
                    note="T2 final exit",
                    new_status="CLOSED_TARGET",
                    realized_pnl_total=realized, spot=spot_close,
                ))
                return events

            if t1_in and pos.target_1 is not None:
                if remaining > qty_t1:
                    pnl1 = (pos.target_1 - pos.entry_premium) * qty_t1
                    realized += pnl1
                    remaining -= qty_t1
                    events.append(IndexSimEvent(
                        date=d, event_type=EV_TARGET_1, price=pos.target_1,
                        quantity=qty_t1, pnl=pnl1,
                        note="T1 partial exit",
                        breakeven_after=trailing_stop_enabled,
                        realized_pnl_total=realized, spot=spot_close,
                    ))
                    if trailing_stop_enabled:
                        stop = pos.entry_premium
                        breakeven_moved = True
                else:
                    pnl1 = (pos.target_1 - pos.entry_premium) * remaining
                    realized += pnl1
                    events.append(IndexSimEvent(
                        date=d, event_type=EV_TARGET_1, price=pos.target_1,
                        quantity=remaining, pnl=pnl1,
                        note="T1 final exit",
                        new_status="CLOSED_TARGET",
                        realized_pnl_total=realized, spot=spot_close,
                    ))
                    return events

    return events
