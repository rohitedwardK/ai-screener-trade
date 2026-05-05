"""DAO for the six paper_index_* tables. Append-only ledger semantics."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from ..models.paper_index_orm import (
    PaperIndexBotConfig,
    PaperIndexDailyPerformance,
    PaperIndexLedger,
    PaperIndexOrder,
    PaperIndexPosition,
    PaperIndexTradeSignal,
)


# ---------- Signals ----------

def insert_signal(db: Session, **fields) -> PaperIndexTradeSignal:
    s = PaperIndexTradeSignal(**fields)
    db.add(s)
    db.flush()
    return s


def list_signals(
    db: Session,
    *,
    signal_date: Optional[date] = None,
    decision: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 500,
) -> List[PaperIndexTradeSignal]:
    stmt = select(PaperIndexTradeSignal).order_by(
        desc(PaperIndexTradeSignal.signal_date), desc(PaperIndexTradeSignal.id)
    )
    if signal_date is not None:
        stmt = stmt.where(PaperIndexTradeSignal.signal_date == signal_date)
    if decision is not None:
        stmt = stmt.where(PaperIndexTradeSignal.decision == decision)
    if symbol is not None:
        stmt = stmt.where(PaperIndexTradeSignal.symbol == symbol)
    return list(db.scalars(stmt.limit(limit)))


# ---------- Orders ----------

def insert_order(db: Session, **fields) -> PaperIndexOrder:
    o = PaperIndexOrder(**fields)
    db.add(o)
    db.flush()
    return o


def list_orders(
    db: Session,
    *,
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 500,
) -> List[PaperIndexOrder]:
    stmt = select(PaperIndexOrder).order_by(desc(PaperIndexOrder.id))
    if status:
        stmt = stmt.where(PaperIndexOrder.status == status)
    if symbol:
        stmt = stmt.where(PaperIndexOrder.symbol == symbol)
    return list(db.scalars(stmt.limit(limit)))


# ---------- Positions ----------

def insert_position(db: Session, **fields) -> PaperIndexPosition:
    p = PaperIndexPosition(**fields)
    db.add(p)
    db.flush()
    return p


def open_positions(db: Session) -> List[PaperIndexPosition]:
    stmt = (
        select(PaperIndexPosition)
        .where(PaperIndexPosition.status.in_(["OPEN", "PARTIAL_EXIT", "PENDING_ENTRY"]))
        .order_by(PaperIndexPosition.id.asc())
    )
    return list(db.scalars(stmt))


def closed_positions(db: Session, *, limit: int = 500) -> List[PaperIndexPosition]:
    stmt = (
        select(PaperIndexPosition)
        .where(PaperIndexPosition.status.like("CLOSED_%"))
        .order_by(desc(PaperIndexPosition.exit_date), desc(PaperIndexPosition.id))
        .limit(limit)
    )
    return list(db.scalars(stmt))


def list_positions(
    db: Session,
    *,
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 500,
) -> List[PaperIndexPosition]:
    stmt = select(PaperIndexPosition).order_by(desc(PaperIndexPosition.id))
    if status == "open":
        stmt = stmt.where(PaperIndexPosition.status.in_(["OPEN", "PARTIAL_EXIT", "PENDING_ENTRY"]))
    elif status == "closed":
        stmt = stmt.where(PaperIndexPosition.status.like("CLOSED_%"))
    elif status:
        stmt = stmt.where(PaperIndexPosition.status == status)
    if symbol:
        stmt = stmt.where(PaperIndexPosition.symbol == symbol)
    return list(db.scalars(stmt.limit(limit)))


def open_symbol_directions(db: Session) -> set[str]:
    """Returns "<symbol>:<direction>" keys for open positions; the decision
    engine uses this to prevent stacking duplicates in the same direction."""
    stmt = (
        select(PaperIndexPosition.symbol, PaperIndexPosition.direction)
        .where(PaperIndexPosition.status.in_(["OPEN", "PARTIAL_EXIT", "PENDING_ENTRY"]))
    )
    return {f"{sym}:{direction}" for sym, direction in db.execute(stmt).all()}


# ---------- Ledger ----------

def append_ledger(db: Session, **fields) -> PaperIndexLedger:
    e = PaperIndexLedger(**fields)
    db.add(e)
    db.flush()
    return e


def list_ledger(
    db: Session,
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    symbol: Optional[str] = None,
    position_id: Optional[int] = None,
    limit: int = 1000,
) -> List[PaperIndexLedger]:
    stmt = select(PaperIndexLedger).order_by(PaperIndexLedger.date.asc(), PaperIndexLedger.id.asc())
    if from_date:
        stmt = stmt.where(PaperIndexLedger.date >= from_date)
    if to_date:
        stmt = stmt.where(PaperIndexLedger.date <= to_date)
    if symbol:
        stmt = stmt.where(PaperIndexLedger.symbol == symbol)
    if position_id is not None:
        stmt = stmt.where(PaperIndexLedger.position_id == position_id)
    return list(db.scalars(stmt.limit(limit)))


def realized_pnl_between(
    db: Session, from_date: Optional[date] = None, to_date: Optional[date] = None,
) -> float:
    stmt = select(func.coalesce(func.sum(PaperIndexLedger.pnl), 0.0))
    if from_date:
        stmt = stmt.where(PaperIndexLedger.date >= from_date)
    if to_date:
        stmt = stmt.where(PaperIndexLedger.date <= to_date)
    return float(db.scalar(stmt) or 0.0)


def total_unrealized_pnl(db: Session) -> float:
    stmt = (
        select(func.coalesce(func.sum(PaperIndexPosition.unrealized_pnl), 0.0))
        .where(PaperIndexPosition.status.in_(["OPEN", "PARTIAL_EXIT"]))
    )
    return float(db.scalar(stmt) or 0.0)


def signals_taken_on(db: Session, on_date: date) -> int:
    stmt = (
        select(func.count(PaperIndexTradeSignal.id))
        .where(
            PaperIndexTradeSignal.signal_date == on_date,
            PaperIndexTradeSignal.decision == "selected",
        )
    )
    return int(db.scalar(stmt) or 0)


def consecutive_recent_losses(db: Session, on_date: date, limit: int = 10) -> int:
    stmt = (
        select(PaperIndexPosition.realized_pnl)
        .where(
            PaperIndexPosition.status.like("CLOSED_%"),
            PaperIndexPosition.exit_date <= on_date,
        )
        .order_by(desc(PaperIndexPosition.exit_date), desc(PaperIndexPosition.id))
        .limit(limit)
    )
    pnls = list(db.scalars(stmt))
    streak = 0
    for p in pnls:
        if p is None or p >= 0:
            break
        streak += 1
    return streak


# ---------- Daily performance ----------

def upsert_daily_performance(db: Session, on_date: date, **fields) -> PaperIndexDailyPerformance:
    row = db.scalar(
        select(PaperIndexDailyPerformance).where(PaperIndexDailyPerformance.date == on_date)
    )
    if row is None:
        row = PaperIndexDailyPerformance(date=on_date, **fields)
        db.add(row)
        db.flush()
        return row
    for k, v in fields.items():
        if v is not None and hasattr(row, k):
            setattr(row, k, v)
    db.flush()
    return row


def daily_performance_between(
    db: Session, from_date: date, to_date: date,
) -> List[PaperIndexDailyPerformance]:
    stmt = (
        select(PaperIndexDailyPerformance)
        .where(
            PaperIndexDailyPerformance.date >= from_date,
            PaperIndexDailyPerformance.date <= to_date,
        )
        .order_by(PaperIndexDailyPerformance.date.asc())
    )
    return list(db.scalars(stmt))


# ---------- Reset ----------

def reset_all(db: Session) -> Dict[str, int]:
    counts = {
        "deleted_ledger": 0,
        "deleted_positions": 0,
        "deleted_orders": 0,
        "deleted_signals": 0,
        "deleted_daily": 0,
    }
    for table, key in [
        (PaperIndexLedger, "deleted_ledger"),
        (PaperIndexPosition, "deleted_positions"),
        (PaperIndexOrder, "deleted_orders"),
        (PaperIndexTradeSignal, "deleted_signals"),
        (PaperIndexDailyPerformance, "deleted_daily"),
    ]:
        result = db.execute(delete(table))
        counts[key] = int(result.rowcount or 0)
    db.commit()
    return counts
