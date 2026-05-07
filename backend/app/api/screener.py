"""Screener endpoints."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis.signals import CATEGORIES
from ..data import repository as repo
from ..db import get_db
from ..models.orm import LiveSignalVerification
from ..models.schemas import CategoryCount, LiveVerificationView, ScreenerRow

router = APIRouter(prefix="/screener", tags=["screener"])


def _live_view_for(verification: Optional[LiveSignalVerification]) -> Optional[LiveVerificationView]:
    if verification is None:
        return None
    return LiveVerificationView(
        status=verification.status,
        live_close=float(verification.live_close),
        live_rsi=verification.live_rsi,
        live_adx=verification.live_adx,
        live_regime=verification.live_regime,
        score_delta=verification.score_delta,
        distance_to_stop_pct=verification.distance_to_stop_pct,
        distance_to_t1_pct=verification.distance_to_t1_pct,
        notes=list(verification.notes_json or []),
        source=verification.source,
        run_at=verification.run_at,
    )


def _row_from_signal(
    sig,
    snap,
    stock,
    verification: Optional[LiveSignalVerification] = None,
) -> ScreenerRow:
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
        live=_live_view_for(verification),
    )


def _verifications_for(
    db: Session,
    signal_ids: List[int],
) -> Dict[int, LiveSignalVerification]:
    """Fetch every verification row keyed by signal_id in one query."""
    if not signal_ids:
        return {}
    rows = db.scalars(
        select(LiveSignalVerification).where(
            LiveSignalVerification.signal_id.in_(signal_ids)
        )
    )
    return {row.signal_id: row for row in rows}


@router.get("", response_model=List[ScreenerRow])
def list_screener(
    category: Optional[str] = Query(None),
    min_score: float = Query(0.0, ge=0, le=100),
    sector: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[ScreenerRow]:
    sigs = repo.latest_signals(db, category=category, min_score=min_score)
    verifications = _verifications_for(db, [int(s.id) for s in sigs])
    rows: List[ScreenerRow] = []
    for s in sigs:
        snap = repo.latest_snapshot(db, s.symbol)
        stock = repo.get_stock(db, s.symbol)
        if sector and (stock is None or stock.sector != sector):
            continue
        rows.append(_row_from_signal(s, snap, stock, verifications.get(int(s.id))))
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

    verifications = _verifications_for(db, [int(s.id) for s in sigs])

    out: List[CategoryCount] = []
    for cat in CATEGORIES:
        items = by_cat.get(cat, [])
        items_sorted = sorted(items, key=lambda x: x.score, reverse=True)
        top_rows: List[ScreenerRow] = []
        for s in items_sorted[:top_n]:
            snap = repo.latest_snapshot(db, s.symbol)
            stock = repo.get_stock(db, s.symbol)
            top_rows.append(_row_from_signal(
                s, snap, stock, verifications.get(int(s.id)),
            ))
        out.append(CategoryCount(category=cat, count=len(items), top=top_rows))
    return out
