"""DAO for index_* tables. Mirrors `data/repository.py` for the new ORM."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models.index_orm import (
    IndexCandle,
    IndexInstrument,
    IndexOptionSnapshot,
    IndexSignal,
    IndexSnapshot,
)

log = logging.getLogger(__name__)


# ---------- Instruments ----------

def upsert_indices(db: Session, rows: Iterable[dict]) -> None:
    # Filter to ORM columns only — index_meta() also carries human-readable
    # fields like weekly_expiry_day that the simulator reads from the in-memory
    # IndexMeta dataclass and we deliberately do not persist.
    cols = {c.name for c in IndexInstrument.__table__.columns}
    rows_list = [{k: v for k, v in r.items() if k in cols} for r in rows]
    rows_list = [r for r in rows_list if r]
    if not rows_list:
        return
    stmt = sqlite_insert(IndexInstrument).values(rows_list)
    stmt = stmt.on_conflict_do_update(
        index_elements=[IndexInstrument.symbol],
        set_={
            "code": stmt.excluded.code,
            "name": stmt.excluded.name,
            "exchange": stmt.excluded.exchange,
            "lot_size": stmt.excluded.lot_size,
            "strike_step": stmt.excluded.strike_step,
            "has_options": stmt.excluded.has_options,
            "has_nse_option_chain": stmt.excluded.has_nse_option_chain,
        },
    )
    db.execute(stmt)
    db.commit()


def list_indices(db: Session) -> List[IndexInstrument]:
    return list(db.scalars(select(IndexInstrument).order_by(IndexInstrument.symbol)))


def get_index(db: Session, symbol: str) -> Optional[IndexInstrument]:
    return db.get(IndexInstrument, symbol)


# ---------- Candles ----------

def latest_candle_date(db: Session, symbol: str) -> Optional[date]:
    return db.scalar(select(func.max(IndexCandle.date)).where(IndexCandle.symbol == symbol))


def upsert_candles(db: Session, symbol: str, df: pd.DataFrame) -> int:
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
    stmt = sqlite_insert(IndexCandle).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[IndexCandle.symbol, IndexCandle.date],
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
        select(IndexCandle.date, IndexCandle.open, IndexCandle.high, IndexCandle.low, IndexCandle.close, IndexCandle.volume)
        .where(IndexCandle.symbol == symbol)
        .order_by(IndexCandle.date.asc())
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
    option_chain_summary: Optional[Dict] = None,
) -> IndexSnapshot:
    existing = db.scalar(
        select(IndexSnapshot).where(IndexSnapshot.symbol == symbol, IndexSnapshot.as_of_date == as_of)
    )
    if existing:
        existing.close = close
        existing.indicators_json = indicators
        existing.regime = regime
        existing.atr = atr
        existing.atr_pct = atr_pct
        existing.run_at = datetime.utcnow()
        if option_chain_summary is not None:
            existing.option_chain_summary_json = option_chain_summary
        db.commit()
        db.refresh(existing)
        return existing
    snap = IndexSnapshot(
        symbol=symbol,
        as_of_date=as_of,
        close=close,
        indicators_json=indicators,
        regime=regime,
        atr=atr,
        atr_pct=atr_pct,
        option_chain_summary_json=option_chain_summary,
        run_at=datetime.utcnow(),
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def latest_snapshot(db: Session, symbol: str) -> Optional[IndexSnapshot]:
    return db.scalar(
        select(IndexSnapshot)
        .where(IndexSnapshot.symbol == symbol)
        .order_by(IndexSnapshot.as_of_date.desc())
    )


# ---------- Signals ----------

def save_signals(db: Session, signals: List[dict]) -> int:
    if not signals:
        return 0
    objs = [IndexSignal(**s) for s in signals]
    db.add_all(objs)
    db.commit()
    return len(objs)


def latest_signals(
    db: Session,
    symbol: Optional[str] = None,
    category: Optional[str] = None,
    min_score: float = 0.0,
) -> List[IndexSignal]:
    latest_run = db.scalar(select(func.max(IndexSignal.run_at)))
    if latest_run is None:
        return []
    stmt = (
        select(IndexSignal)
        .where(IndexSignal.run_at == latest_run, IndexSignal.score >= min_score)
        .order_by(IndexSignal.score.desc())
    )
    if symbol:
        stmt = stmt.where(IndexSignal.symbol == symbol)
    if category:
        stmt = stmt.where(IndexSignal.category == category)
    return list(db.scalars(stmt))


def signals_for_symbol(db: Session, symbol: str, limit: int = 10) -> List[IndexSignal]:
    stmt = (
        select(IndexSignal)
        .where(IndexSignal.symbol == symbol)
        .order_by(IndexSignal.run_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def purge_old_signals(db: Session, keep_runs: int = 10) -> int:
    runs = db.execute(
        select(IndexSignal.run_at).distinct().order_by(IndexSignal.run_at.desc()).limit(keep_runs)
    ).scalars().all()
    if not runs:
        return 0
    cutoff = runs[-1]
    result = db.execute(delete(IndexSignal).where(IndexSignal.run_at < cutoff))
    db.commit()
    return result.rowcount or 0


# ---------- Option snapshots ----------

def insert_option_snapshots(db: Session, rows: List[dict]) -> int:
    """Append-only inserts. Use `purge_old_option_snapshots` to age the table."""
    if not rows:
        return 0
    objs = [IndexOptionSnapshot(**r) for r in rows]
    db.add_all(objs)
    db.commit()
    return len(objs)


def latest_option_snapshots(
    db: Session,
    symbol: str,
    expiry: Optional[date] = None,
    limit: int = 200,
) -> List[IndexOptionSnapshot]:
    last_at = db.scalar(
        select(func.max(IndexOptionSnapshot.snapshot_at))
        .where(IndexOptionSnapshot.symbol == symbol)
    )
    if last_at is None:
        return []
    stmt = (
        select(IndexOptionSnapshot)
        .where(IndexOptionSnapshot.symbol == symbol, IndexOptionSnapshot.snapshot_at == last_at)
        .order_by(IndexOptionSnapshot.strike.asc())
    )
    if expiry is not None:
        stmt = stmt.where(IndexOptionSnapshot.expiry == expiry)
    return list(db.scalars(stmt.limit(limit)))


def purge_old_option_snapshots(db: Session, keep_days: int = 7) -> int:
    """Trim the option snapshots table; we keep `keep_days` worth of history."""
    cutoff = datetime.utcnow().date()
    from datetime import timedelta as _td
    cutoff_dt = datetime.combine(cutoff - _td(days=keep_days), datetime.min.time())
    result = db.execute(
        delete(IndexOptionSnapshot).where(IndexOptionSnapshot.snapshot_at < cutoff_dt)
    )
    db.commit()
    return result.rowcount or 0
