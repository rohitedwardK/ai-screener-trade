"""Data access layer: read/write OHLCV, snapshots, and signals.

Uses SQLAlchemy 2.x ORM, but exposes pure-Python interfaces so a future
swap to Postgres or Redis-backed cache is mechanical.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models.orm import Candle, Signal, Snapshot, Stock

log = logging.getLogger(__name__)


# ---------- Stocks ----------

def upsert_stocks(db: Session, rows: Iterable[dict]) -> None:
    stmt = sqlite_insert(Stock).values(list(rows))
    stmt = stmt.on_conflict_do_update(
        index_elements=[Stock.symbol],
        set_={"name": stmt.excluded.name, "sector": stmt.excluded.sector},
    )
    db.execute(stmt)
    db.commit()


def list_stocks(db: Session) -> List[Stock]:
    return list(db.scalars(select(Stock).order_by(Stock.symbol)))


def get_stock(db: Session, symbol: str) -> Optional[Stock]:
    return db.get(Stock, symbol)


# ---------- Candles ----------

def latest_candle_date(db: Session, symbol: str) -> Optional[date]:
    return db.scalar(select(func.max(Candle.date)).where(Candle.symbol == symbol))


def upsert_candles(db: Session, symbol: str, df: pd.DataFrame) -> int:
    """Insert / update OHLCV candles for a symbol. Returns rows affected."""
    if df is None or df.empty:
        return 0

    rows: List[dict] = []
    for ts, row in df.iterrows():
        if pd.isna(row.get("close")):
            continue
        rows.append({
            "symbol": symbol,
            "date": pd.Timestamp(ts).date(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0) or 0),
        })

    if not rows:
        return 0

    stmt = sqlite_insert(Candle).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Candle.symbol, Candle.date],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


def load_candles(db: Session, symbol: str, limit: Optional[int] = None) -> pd.DataFrame:
    stmt = (
        select(Candle.date, Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume)
        .where(Candle.symbol == symbol)
        .order_by(Candle.date.asc())
    )
    rows = db.execute(stmt).all()
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    if limit is not None:
        df = df.tail(limit)
    return df


# ---------- Snapshots ----------

def save_snapshot(
    db: Session,
    symbol: str,
    as_of: date,
    close: float,
    indicators: Dict,
    regime: str,
    atr: Optional[float],
    atr_pct: Optional[float],
) -> Snapshot:
    existing = db.scalar(
        select(Snapshot).where(Snapshot.symbol == symbol, Snapshot.as_of_date == as_of)
    )
    if existing:
        existing.close = close
        existing.indicators_json = indicators
        existing.regime = regime
        existing.atr = atr
        existing.atr_pct = atr_pct
        existing.run_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    snap = Snapshot(
        symbol=symbol,
        as_of_date=as_of,
        close=close,
        indicators_json=indicators,
        regime=regime,
        atr=atr,
        atr_pct=atr_pct,
        run_at=datetime.utcnow(),
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def latest_snapshot(db: Session, symbol: str) -> Optional[Snapshot]:
    return db.scalar(
        select(Snapshot).where(Snapshot.symbol == symbol).order_by(Snapshot.as_of_date.desc())
    )


# ---------- Signals ----------

def save_signals(db: Session, signals: List[dict]) -> int:
    if not signals:
        return 0
    objs = [Signal(**s) for s in signals]
    db.add_all(objs)
    db.commit()
    return len(objs)


def latest_signals(
    db: Session,
    category: Optional[str] = None,
    min_score: float = 0.0,
) -> List[Signal]:
    """Return the most recent signals (one per symbol) optionally filtered."""
    latest_run = db.scalar(select(func.max(Signal.run_at)))
    if latest_run is None:
        return []

    stmt = (
        select(Signal)
        .where(Signal.run_at == latest_run, Signal.score >= min_score)
        .order_by(Signal.score.desc())
    )
    if category:
        stmt = stmt.where(Signal.category == category)
    return list(db.scalars(stmt))


def signals_for_symbol(db: Session, symbol: str, limit: int = 5) -> List[Signal]:
    stmt = (
        select(Signal)
        .where(Signal.symbol == symbol)
        .order_by(Signal.run_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def purge_old_signals(db: Session, keep_runs: int = 5) -> int:
    """Keep only the N most recent run_at timestamps, delete older."""
    runs = db.execute(
        select(Signal.run_at).distinct().order_by(Signal.run_at.desc()).limit(keep_runs)
    ).scalars().all()
    if not runs:
        return 0
    cutoff = runs[-1]
    result = db.execute(delete(Signal).where(Signal.run_at < cutoff))
    db.commit()
    return result.rowcount or 0
