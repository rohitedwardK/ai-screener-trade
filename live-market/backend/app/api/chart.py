"""Per-index chart + detail endpoint."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..core import intraday_store
from ..core.universe import get_meta
from ..db import get_db
from ..models.orm import IntradayBar, RegimeSnapshot, ScalpSetup, SwingSetup
from ..models.schemas import (
    IndexDetailDTO,
    IntradayBarDTO,
    RegimeSnapshotDTO,
    ScalpSetupDTO,
    SwingSetupDTO,
)
from .market import _build_index_card

router = APIRouter(prefix="/v1/chart", tags=["chart"])


@router.get("/{symbol:path}", response_model=IndexDetailDTO)
def index_detail(
    symbol: str,
    lookback: int = Query(180, ge=10, le=1000),
    history_limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> IndexDetailDTO:
    meta = get_meta(symbol)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"unknown index: {symbol}")

    bars = list(db.scalars(
        select(IntradayBar)
        .where(IntradayBar.symbol == meta.symbol)
        .order_by(desc(IntradayBar.ts))
        .limit(lookback)
    ))
    bars.reverse()

    active_scalps = list(db.scalars(
        select(ScalpSetup).where(
            ScalpSetup.symbol == meta.symbol,
            ScalpSetup.status == "ACTIVE",
        ).order_by(desc(ScalpSetup.created_at))
    ))
    active_swings = list(db.scalars(
        select(SwingSetup).where(
            SwingSetup.symbol == meta.symbol,
            SwingSetup.status == "ACTIVE",
        ).order_by(desc(SwingSetup.created_at))
    ))
    history_scalps = list(db.scalars(
        select(ScalpSetup).where(
            ScalpSetup.symbol == meta.symbol,
            ScalpSetup.status != "ACTIVE",
        ).order_by(desc(ScalpSetup.resolved_at), desc(ScalpSetup.created_at)).limit(history_limit)
    ))
    history_swings = list(db.scalars(
        select(SwingSetup).where(
            SwingSetup.symbol == meta.symbol,
            SwingSetup.status != "ACTIVE",
        ).order_by(desc(SwingSetup.resolved_at), desc(SwingSetup.created_at)).limit(history_limit)
    ))
    regimes = list(db.scalars(
        select(RegimeSnapshot)
        .where(RegimeSnapshot.symbol == meta.symbol)
        .order_by(desc(RegimeSnapshot.ts))
        .limit(60)
    ))

    return IndexDetailDTO(
        card=_build_index_card(db, meta),
        bars=[IntradayBarDTO.model_validate(b) for b in bars],
        active_scalps=[ScalpSetupDTO.model_validate(r) for r in active_scalps],
        active_swings=[SwingSetupDTO.model_validate(r) for r in active_swings],
        recent_history_scalps=[ScalpSetupDTO.model_validate(r) for r in history_scalps],
        recent_history_swings=[SwingSetupDTO.model_validate(r) for r in history_swings],
        recent_regimes=[RegimeSnapshotDTO.model_validate(r) for r in regimes],
    )
