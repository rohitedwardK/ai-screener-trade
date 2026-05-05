"""Ledger repository: CRUD for the six paper_* tables.

Strict invariants:
  - paper_ledger is **append-only** (no updates / deletes outside reset()).
  - `paper_orders` and `paper_positions` are mutated to reflect lifecycle changes.
  - Every state change in a position should produce at least one ledger row.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import and_, delete, desc, func, select
from sqlalchemy.orm import Session

from ..models.paper_orm import (
    PaperBotConfig,
    PaperDailyPerformance,
    PaperLedger,
    PaperOrder,
    PaperPosition,
    PaperTradeSignal,
)


# ---------- Signals ----------

def insert_signal(db: Session, **fields) -> PaperTradeSignal:
    sig = PaperTradeSignal(**fields)
    db.add(sig)
    db.flush()
    return sig


def list_signals(
    db: Session,
    *,
    signal_date: Optional[date] = None,
    decision: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 500,
) -> List[PaperTradeSignal]:
    stmt = select(PaperTradeSignal).order_by(desc(PaperTradeSignal.signal_date), desc(PaperTradeSignal.id))
    if signal_date is not None:
        stmt = stmt.where(PaperTradeSignal.signal_date == signal_date)
    if decision is not None:
        stmt = stmt.where(PaperTradeSignal.decision == decision)
    if symbol is not None:
        stmt = stmt.where(PaperTradeSignal.symbol == symbol)
    return list(db.scalars(stmt.limit(limit)))


# ---------- Orders ----------

def insert_order(db: Session, **fields) -> PaperOrder:
    o = PaperOrder(**fields)
    db.add(o)
    db.flush()
    return o


def list_orders(
    db: Session,
    *,
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 500,
) -> List[PaperOrder]:
    stmt = select(PaperOrder).order_by(desc(PaperOrder.id))
    if status:
        stmt = stmt.where(PaperOrder.status == status)
    if symbol:
        stmt = stmt.where(PaperOrder.symbol == symbol)
    return list(db.scalars(stmt.limit(limit)))


def pending_orders(db: Session) -> List[PaperOrder]:
    return list(db.scalars(
        select(PaperOrder).where(PaperOrder.status == "PENDING").order_by(PaperOrder.id.asc())
    ))


# ---------- Positions ----------

def insert_position(db: Session, **fields) -> PaperPosition:
    p = PaperPosition(**fields)
    db.add(p)
    db.flush()
    return p


def open_positions(db: Session) -> List[PaperPosition]:
    stmt = (
        select(PaperPosition)
        .where(PaperPosition.status.in_(["OPEN", "PARTIAL_EXIT", "PENDING_ENTRY"]))
        .order_by(PaperPosition.id.asc())
    )
    return list(db.scalars(stmt))


def closed_positions(db: Session, *, limit: int = 500) -> List[PaperPosition]:
    stmt = (
        select(PaperPosition)
        .where(PaperPosition.status.like("CLOSED_%"))
        .order_by(desc(PaperPosition.exit_date), desc(PaperPosition.id))
        .limit(limit)
    )
    return list(db.scalars(stmt))


def list_positions(
    db: Session,
    *,
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 500,
) -> List[PaperPosition]:
    stmt = select(PaperPosition).order_by(desc(PaperPosition.id))
    if status == "open":
        stmt = stmt.where(PaperPosition.status.in_(["OPEN", "PARTIAL_EXIT", "PENDING_ENTRY"]))
    elif status == "closed":
        stmt = stmt.where(PaperPosition.status.like("CLOSED_%"))
    elif status:
        stmt = stmt.where(PaperPosition.status == status)
    if symbol:
        stmt = stmt.where(PaperPosition.symbol == symbol)
    return list(db.scalars(stmt.limit(limit)))


def open_symbols(db: Session) -> set[str]:
    stmt = (
        select(PaperPosition.symbol)
        .where(PaperPosition.status.in_(["OPEN", "PARTIAL_EXIT", "PENDING_ENTRY"]))
    )
    return set(db.scalars(stmt))


# ---------- Ledger ----------

def append_ledger(db: Session, **fields) -> PaperLedger:
    e = PaperLedger(**fields)
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
) -> List[PaperLedger]:
    stmt = select(PaperLedger).order_by(PaperLedger.date.asc(), PaperLedger.id.asc())
    if from_date:
        stmt = stmt.where(PaperLedger.date >= from_date)
    if to_date:
        stmt = stmt.where(PaperLedger.date <= to_date)
    if symbol:
        stmt = stmt.where(PaperLedger.symbol == symbol)
    if position_id is not None:
        stmt = stmt.where(PaperLedger.position_id == position_id)
    return list(db.scalars(stmt.limit(limit)))


def realized_pnl_between(
    db: Session, from_date: Optional[date] = None, to_date: Optional[date] = None,
) -> float:
    stmt = select(func.coalesce(func.sum(PaperLedger.pnl), 0.0))
    if from_date:
        stmt = stmt.where(PaperLedger.date >= from_date)
    if to_date:
        stmt = stmt.where(PaperLedger.date <= to_date)
    return float(db.scalar(stmt) or 0.0)


def total_unrealized_pnl(db: Session) -> float:
    stmt = (
        select(func.coalesce(func.sum(PaperPosition.unrealized_pnl), 0.0))
        .where(PaperPosition.status.in_(["OPEN", "PARTIAL_EXIT"]))
    )
    return float(db.scalar(stmt) or 0.0)


def signals_taken_on(db: Session, on_date: date) -> int:
    stmt = (
        select(func.count(PaperTradeSignal.id))
        .where(PaperTradeSignal.signal_date == on_date, PaperTradeSignal.decision == "selected")
    )
    return int(db.scalar(stmt) or 0)


def positions_opened_on(db: Session, on_date: date) -> int:
    stmt = select(func.count(PaperPosition.id)).where(PaperPosition.entry_date == on_date)
    return int(db.scalar(stmt) or 0)


def consecutive_recent_losses(db: Session, on_date: date, limit: int = 10) -> int:
    """Count tail-run of CLOSED_* positions with realized_pnl < 0 ending on `on_date`.

    Used by the kill switch to halt trading after N consecutive losses.
    """
    stmt = (
        select(PaperPosition.realized_pnl)
        .where(
            PaperPosition.status.like("CLOSED_%"),
            PaperPosition.exit_date <= on_date,
        )
        .order_by(desc(PaperPosition.exit_date), desc(PaperPosition.id))
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

def upsert_daily_performance(db: Session, on_date: date, **fields) -> PaperDailyPerformance:
    row = db.scalar(select(PaperDailyPerformance).where(PaperDailyPerformance.date == on_date))
    if row is None:
        row = PaperDailyPerformance(date=on_date, **fields)
        db.add(row)
        db.flush()
        return row
    for k, v in fields.items():
        if v is not None and hasattr(row, k):
            setattr(row, k, v)
    db.flush()
    return row


def latest_daily_performance(db: Session) -> Optional[PaperDailyPerformance]:
    return db.scalar(
        select(PaperDailyPerformance).order_by(desc(PaperDailyPerformance.date)).limit(1)
    )


def daily_performance_between(
    db: Session, from_date: date, to_date: date,
) -> List[PaperDailyPerformance]:
    stmt = (
        select(PaperDailyPerformance)
        .where(PaperDailyPerformance.date >= from_date, PaperDailyPerformance.date <= to_date)
        .order_by(PaperDailyPerformance.date.asc())
    )
    return list(db.scalars(stmt))


# ---------- Reset ----------

def reset_all(db: Session) -> Dict[str, int]:
    """Wipe every paper_* table EXCEPT paper_bot_config."""
    counts = {
        "deleted_ledger": 0,
        "deleted_positions": 0,
        "deleted_orders": 0,
        "deleted_signals": 0,
        "deleted_daily": 0,
    }
    for table, key in [
        (PaperLedger, "deleted_ledger"),
        (PaperPosition, "deleted_positions"),
        (PaperOrder, "deleted_orders"),
        (PaperTradeSignal, "deleted_signals"),
        (PaperDailyPerformance, "deleted_daily"),
    ]:
        result = db.execute(delete(table))
        counts[key] = int(result.rowcount or 0)
    db.commit()
    return counts
