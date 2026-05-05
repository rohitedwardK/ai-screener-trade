"""Position manager: applies IndexSimEvent stream to ORM rows."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from ..models.paper_index_orm import (
    PaperIndexLedger,
    PaperIndexOrder,
    PaperIndexPosition,
    PaperIndexTradeSignal,
)
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
    IndexSimEvent,
)


def _holding_days(entry: Optional[date], exit_: Optional[date]) -> Optional[int]:
    if entry is None or exit_ is None:
        return None
    return max(0, (exit_ - entry).days)


def open_pending_position(
    db: Session,
    *,
    signal: PaperIndexTradeSignal,
    lots: int,
    quantity: int,
    entry_premium: float,
    stop_premium: float,
    target_1_premium: Optional[float],
    target_2_premium: Optional[float],
    delta_estimate: float,
    is_intraday: bool = True,
) -> PaperIndexPosition:
    pos = ledger.insert_position(
        db,
        signal_id=signal.id,
        symbol=signal.symbol,
        code=signal.code,
        setup_type=signal.setup_type,
        direction=signal.direction,
        option_type=signal.option_type,
        strike=signal.strike or 0.0,
        expiry=signal.expiry,
        lot_size=signal.lot_size or 1,
        lots=lots,
        quantity=quantity,
        remaining_quantity=quantity,
        stop_loss=stop_premium,
        target_1=target_1_premium,
        target_2=target_2_premium,
        spot_stop_loss=signal.spot_stop_loss,
        spot_target_1=signal.spot_target_1,
        spot_target_2=signal.spot_target_2,
        delta_estimate=delta_estimate,
        is_intraday=is_intraday,
        status="PENDING_ENTRY",
    )
    ledger.insert_order(
        db,
        signal_id=signal.id,
        symbol=signal.symbol,
        code=signal.code,
        option_type=signal.option_type,
        strike=signal.strike or 0.0,
        expiry=signal.expiry,
        lot_size=signal.lot_size or 1,
        lots=lots,
        paper_order_type="PAPER_LIMIT_ENTRY",
        side="BUY",
        planned_premium=entry_premium,
        status="PENDING",
    )
    return pos


def apply_entry_fill(
    db: Session, *, position: PaperIndexPosition, event: IndexSimEvent,
) -> PaperIndexLedger:
    position.entry_date = event.date
    position.entry_premium = event.price
    position.current_price = event.price
    position.entry_spot = event.spot
    position.status = "OPEN"
    for o in db.query(PaperIndexOrder).filter(
        PaperIndexOrder.signal_id == position.signal_id,
        PaperIndexOrder.paper_order_type == "PAPER_LIMIT_ENTRY",
        PaperIndexOrder.status == "PENDING",
    ).all():
        o.status = "FILLED"
        o.filled_premium = event.price
        o.filled_at = datetime.utcnow()
    return ledger.append_ledger(
        db,
        position_id=position.id,
        date=event.date,
        event_type=EV_ENTRY_FILL,
        symbol=position.symbol,
        code=position.code,
        option_type=position.option_type,
        strike=position.strike,
        expiry=position.expiry,
        quantity=event.quantity,
        price=event.price,
        pnl=0.0,
        note=event.note or "entry filled",
    )


def apply_entry_expired(
    db: Session, *, position: PaperIndexPosition, event: IndexSimEvent,
) -> PaperIndexLedger:
    position.status = "EXPIRED"
    position.exit_date = event.date
    position.exit_reason = "ENTRY_EXPIRED"
    for o in db.query(PaperIndexOrder).filter(
        PaperIndexOrder.signal_id == position.signal_id,
        PaperIndexOrder.status == "PENDING",
    ).all():
        o.status = "EXPIRED"
    return ledger.append_ledger(
        db,
        position_id=position.id,
        date=event.date,
        event_type=EV_ENTRY_EXPIRED,
        symbol=position.symbol,
        code=position.code,
        option_type=position.option_type,
        strike=position.strike,
        expiry=position.expiry,
        quantity=event.quantity,
        price=event.price,
        pnl=0.0,
        note=event.note,
    )


def apply_exit_event(
    db: Session, *, position: PaperIndexPosition, event: IndexSimEvent,
) -> PaperIndexLedger:
    position.realized_pnl = float(position.realized_pnl or 0.0) + float(event.pnl or 0.0)
    position.remaining_quantity = max(0, int(position.remaining_quantity) - int(event.quantity))
    position.current_price = event.price
    if event.spot is not None:
        position.exit_spot = event.spot

    if event.breakeven_after and position.entry_premium is not None:
        position.stop_loss = position.entry_premium
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
        code=position.code,
        option_type=position.option_type,
        strike=position.strike,
        expiry=position.expiry,
        quantity=event.quantity,
        price=event.price,
        pnl=event.pnl,
        note=event.note,
    )


def apply_event(
    db: Session, *, position: PaperIndexPosition, event: IndexSimEvent,
) -> PaperIndexLedger:
    if event.event_type == EV_ENTRY_FILL:
        return apply_entry_fill(db, position=position, event=event)
    if event.event_type == EV_ENTRY_EXPIRED:
        return apply_entry_expired(db, position=position, event=event)
    if event.event_type in EXIT_EVENTS:
        return apply_exit_event(db, position=position, event=event)
    raise ValueError(f"Unknown event type: {event.event_type}")


# --- mark-to-market ---

def mark_to_close(position: PaperIndexPosition, latest_premium: float) -> None:
    if position.entry_premium is None or position.remaining_quantity <= 0:
        position.unrealized_pnl = 0.0
        return
    position.current_price = float(latest_premium)
    position.unrealized_pnl = (
        (float(latest_premium) - float(position.entry_premium)) * float(position.remaining_quantity)
    )


def mark_open_positions(db: Session, premiums_by_id: Dict[int, float]) -> int:
    positions = ledger.open_positions(db)
    n = 0
    for p in positions:
        if p.status not in ("OPEN", "PARTIAL_EXIT"):
            continue
        prem = premiums_by_id.get(p.id)
        if prem is None:
            continue
        mark_to_close(p, prem)
        n += 1
    db.flush()
    return n
