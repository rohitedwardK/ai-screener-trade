"""Screener endpoints."""
from __future__ import annotations

from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..analysis.signals import CATEGORIES
from ..data import repository as repo
from ..db import get_db
from ..models.schemas import CategoryCount, ScreenerRow

router = APIRouter(prefix="/screener", tags=["screener"])


def _row_from_signal(sig, snap, stock) -> ScreenerRow:
    ind = (snap.indicators_json if snap else {}) or {}
    return ScreenerRow(
        symbol=sig.symbol,
        name=stock.name if stock else None,
        sector=stock.sector if stock else None,
        category=sig.category,
        regime=snap.regime if snap else "RANGE",
        score=sig.score,
        confidence=sig.confidence,
        close=float(snap.close) if snap else 0.0,
        rsi=ind.get("rsi14"),
        adx=ind.get("adx"),
        atr_pct=ind.get("atr_pct"),
        entry=sig.entry,
        stop_loss=sig.stop_loss,
        target_1=sig.target_1,
        target_2=sig.target_2,
        invalidation=sig.invalidation,
        reasons=sig.reasons_json or [],
    )


@router.get("", response_model=List[ScreenerRow])
def list_screener(
    category: Optional[str] = Query(None),
    min_score: float = Query(0.0, ge=0, le=100),
    sector: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[ScreenerRow]:
    sigs = repo.latest_signals(db, category=category, min_score=min_score)
    rows: List[ScreenerRow] = []
    for s in sigs:
        snap = repo.latest_snapshot(db, s.symbol)
        stock = repo.get_stock(db, s.symbol)
        if sector and (stock is None or stock.sector != sector):
            continue
        rows.append(_row_from_signal(s, snap, stock))
        if len(rows) >= limit:
            break
    return rows


@router.get("/categories", response_model=List[CategoryCount])
def screener_categories(
    top_n: int = Query(3, ge=1, le=20),
    db: Session = Depends(get_db),
) -> List[CategoryCount]:
    sigs = repo.latest_signals(db)
    by_cat: dict[str, list] = defaultdict(list)
    for s in sigs:
        by_cat[s.category].append(s)

    out: List[CategoryCount] = []
    for cat in CATEGORIES:
        items = by_cat.get(cat, [])
        items_sorted = sorted(items, key=lambda x: x.score, reverse=True)
        top_rows: List[ScreenerRow] = []
        for s in items_sorted[:top_n]:
            snap = repo.latest_snapshot(db, s.symbol)
            stock = repo.get_stock(db, s.symbol)
            top_rows.append(_row_from_signal(s, snap, stock))
        out.append(CategoryCount(category=cat, count=len(items), top=top_rows))
    return out
