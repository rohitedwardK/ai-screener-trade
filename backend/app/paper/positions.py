"""PaperPositionManager.

Bridges the pure-function `simulator.SimEvent` stream to ORM updates:
- Creates positions when entry orders fill.
- Updates remaining_quantity, realized_pnl, status, exit metadata on exit events.
- Recomputes unrealized_pnl from a "current price" mark.
- Enforces no-duplicate-symbol guard.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from ..models.paper_orm import PaperLedger, PaperOrder, PaperPosition, PaperTradeSignal
from . import ledger
from .simulator import (
    EV_ENTRY_FILL,
    EV_ENTRY_EXPIRED,
    EV_STOP_LOSS,
    EV_TARGET_1,
    EV_TARGET_2,
    EV_TIME_EXIT,
    EV_TRAIL,
    EXIT_EVENTS,
    SimEvent,
)


def _holding_days(entry: Optional[date], exit_: Optional[date]) -> Optional[int]:
    if entry is None or exit_ is None:
        return None
    return max(0, (exit_ - entry).days)


def has_open_position(db: Session, symbol: str) -> bool:
    return symbol in ledger.open_symbols(db)


def open_pending_position(
    db: Session,
    *,
    signal: PaperTradeSignal,
    quantity: int,
    is_intraday: bool = False,
) -> PaperPosition:
    """Create a position in PENDING_ENTRY state and the matching PENDING entry order."""
    pos = ledger.insert_position(
        db,
        signal_id=signal.id,
        symbol=signal.symbol,
        setup_type=signal.setup_type,
        side="LONG",
        quantity=quantity,
        remaining_quantity=quantity,
        stop_loss=signal.stop_loss,
        target_1=signal.target_1,
        target_2=signal.target_2,
        is_intraday=is_intraday,
        status="PENDING_ENTRY",
    )
    ledger.insert_order(
        db,
        signal_id=signal.id,
        symbol=signal.symbol,
        paper_order_type="PAPER_LIMIT_ENTRY",
        side="BUY",
        quantity=quantity,
        planned_price=signal.entry,
        status="PENDING",
    )
    return pos


def apply_entry_fill(
    db: Session,
    *,
    position: PaperPosition,
    event: SimEvent,
) -> PaperLedger:
    position.entry_date = event.date
    position.entry_price = event.price
    position.current_price = event.price
    position.status = "OPEN"
    # mark order as filled
    for o in db.query(PaperOrder).filter(
        PaperOrder.signal_id == position.signal_id,
        PaperOrder.paper_order_type == "PAPER_LIMIT_ENTRY",
        PaperOrder.status == "PENDING",
    ).all():
        o.status = "FILLED"
        o.filled_price = event.price
        o.filled_at = datetime.utcnow()
    return ledger.append_ledger(
        db,
        position_id=position.id,
        date=event.date,
        event_type=EV_ENTRY_FILL,
        symbol=position.symbol,
        quantity=event.quantity,
        price=event.price,
        pnl=0.0,
        note=event.note or "entry filled",
    )


def apply_entry_expired(
    db: Session,
    *,
    position: PaperPosition,
    event: SimEvent,
) -> PaperLedger:
    position.status = "EXPIRED"
    position.exit_date = event.date
    position.exit_reason = "ENTRY_EXPIRED"
    for o in db.query(PaperOrder).filter(
        PaperOrder.signal_id == position.signal_id,
        PaperOrder.status == "PENDING",
    ).all():
        o.status = "EXPIRED"
    return ledger.append_ledger(
        db,
        position_id=position.id,
        date=event.date,
        event_type=EV_ENTRY_EXPIRED,
        symbol=position.symbol,
        quantity=event.quantity,
        price=event.price,
        pnl=0.0,
        note=event.note,
    )


def apply_exit_event(
    db: Session,
    *,
    position: PaperPosition,
    event: SimEvent,
) -> PaperLedger:
    """Apply a stop / target / trailing / time-exit event to the position."""
    position.realized_pnl = float(position.realized_pnl or 0.0) + float(event.pnl or 0.0)
    position.remaining_quantity = max(0, int(position.remaining_quantity) - int(event.quantity))
    position.current_price = event.price

    if event.breakeven_after and position.entry_price is not None:
        position.stop_loss = position.entry_price
        position.breakeven_moved = True

    if position.remaining_quantity == 0:
        if event.new_status:
            position.status = event.new_status
        else:
            mapping = {
                EV_STOP_LOSS: "CLOSED_STOP_LOSS",
                EV_TARGET_1: "CLOSED_TARGET",
                EV_TARGET_2: "CLOSED_TARGET",
                EV_TRAIL: "CLOSED_TRAILING_STOP",
                EV_TIME_EXIT: "CLOSED_TIME_EXIT",
            }
            position.status = mapping.get(event.event_type, "CLOSED_TARGET")
        position.exit_date = event.date
        position.exit_price = event.price
        position.exit_reason = event.event_type
        position.holding_days = _holding_days(position.entry_date, event.date)
        position.unrealized_pnl = 0.0
    else:
        position.status = "PARTIAL_EXIT"

    return ledger.append_ledger(
        db,
        position_id=position.id,
        date=event.date,
        event_type=event.event_type,
        symbol=position.symbol,
        quantity=event.quantity,
        price=event.price,
        pnl=event.pnl,
        note=event.note,
    )


def apply_event(
    db: Session,
    *,
    position: PaperPosition,
    event: SimEvent,
) -> PaperLedger:
    if event.event_type == EV_ENTRY_FILL:
        return apply_entry_fill(db, position=position, event=event)
    if event.event_type == EV_ENTRY_EXPIRED:
        return apply_entry_expired(db, position=position, event=event)
    if event.event_type in EXIT_EVENTS:
        return apply_exit_event(db, position=position, event=event)
    raise ValueError(f"Unknown event type: {event.event_type}")


# --- mark-to-market ---

def mark_position_to_close(position: PaperPosition, close_price: float) -> None:
    """Update unrealized_pnl + current_price for an open position from latest close."""
    if position.entry_price is None or position.remaining_quantity <= 0:
        position.unrealized_pnl = 0.0
        return
    position.current_price = float(close_price)
    position.unrealized_pnl = (
        (float(close_price) - float(position.entry_price)) * float(position.remaining_quantity)
    )


def mark_open_positions(
    db: Session, prices_by_symbol: Dict[str, float],
) -> int:
    """Mark every OPEN/PARTIAL_EXIT position to the supplied close prices."""
    positions = ledger.open_positions(db)
    n = 0
    for p in positions:
        if p.status not in ("OPEN", "PARTIAL_EXIT"):
            continue
        px = prices_by_symbol.get(p.symbol)
        if px is None:
            continue
        mark_position_to_close(p, px)
        n += 1
    db.flush()
    return n
