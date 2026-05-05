"""Stock detail and history endpoints."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..data import live_quotes, repository as repo
from ..db import get_db
from ..models.schemas import (
    CandleOut,
    SignalOut,
    SnapshotOut,
    StockDetailOut,
    StockOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/stocks", tags=["stocks"])


# ---------------------------------------------------------------------------

_RANGE_TO_BARS = {
    "1m": 22,
    "3m": 66,
    "6m": 132,
    "1y": 252,
    "2y": 504,
    "5y": 1260,
}


@router.get("", response_model=List[StockOut])
def list_stocks(db: Session = Depends(get_db)) -> List[StockOut]:
    return [StockOut.model_validate(s) for s in repo.list_stocks(db)]


@router.get("/prices", response_model=Dict[str, float])
def get_prices(
    symbols: str = Query(..., description="Comma-separated list of symbols"),
    db: Session = Depends(get_db),
) -> Dict[str, float]:
    """Return the latest live price for each requested symbol.

    Tries Yahoo Finance (1-min bars, cached 30 s) first; falls back to the
    most recent stored snapshot so the endpoint always returns something.
    """
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        return {}

    live = live_quotes.fetch_live_prices(sym_list)

    result: Dict[str, float] = {}
    for sym in sym_list:
        if sym in live:
            result[sym] = live[sym]
        else:
            # Fallback: last stored snapshot
            snap = repo.latest_snapshot(db, sym)
            if snap is not None:
                result[sym] = float(snap.close)

    return result


@router.get("/{symbol}", response_model=StockDetailOut)
def get_stock(symbol: str, db: Session = Depends(get_db)) -> StockDetailOut:
    stock = repo.get_stock(db, symbol)
    if stock is None:
        raise HTTPException(404, f"Symbol {symbol} not found")
    snap = repo.latest_snapshot(db, symbol)
    sigs = repo.signals_for_symbol(db, symbol, limit=10)

    snap_out: Optional[SnapshotOut] = (
        SnapshotOut.model_validate(snap) if snap is not None else None
    )

    return StockDetailOut(
        stock=StockOut.model_validate(stock),
        snapshot=snap_out,
        signals=[SignalOut.model_validate(s) for s in sigs],
    )


@router.get("/{symbol}/history", response_model=List[CandleOut])
def get_history(
    symbol: str,
    range: str = Query("1y", description="One of: 1m, 3m, 6m, 1y, 2y, 5y"),
    db: Session = Depends(get_db),
) -> List[CandleOut]:
    bars = _RANGE_TO_BARS.get(range, 252)
    df = repo.load_candles(db, symbol, limit=bars)
    if df.empty:
        return []
    out: List[CandleOut] = []
    for ts, row in df.iterrows():
        out.append(CandleOut(
            date=ts.date(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        ))
    return out
