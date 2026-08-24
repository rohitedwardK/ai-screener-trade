"""Operator endpoints: manual tick + health snapshot + intraday hydration."""
from __future__ import annotations

from datetime import datetime
from typing import Dict

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..core import intraday_store, pipeline
from ..core.universe import INDICES
from ..data import upstox_client
from ..db import get_db
from ..models.orm import IntradayBar, RegimeSnapshot
from ..models.schemas import HealthDTO, TickResultDTO

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.post("/tick", response_model=TickResultDTO)
def manual_tick(db: Session = Depends(get_db)) -> TickResultDTO:
    """Run one tick out of band. Useful in dev / for integration tests."""
    result = pipeline.run_tick(db)
    return TickResultDTO(
        processed_at=result.processed_at,
        symbols_priced=result.symbols_priced,
        regimes=result.regimes,
        scalps_emitted=result.scalps_emitted,
        swings_emitted=result.swings_emitted,
        setups_resolved=result.setups_resolved,
        note=result.note,
    )


@router.post("/hydrate", response_model=Dict[str, int])
def hydrate(db: Session = Depends(get_db)) -> Dict[str, int]:
    """Backfill today's 1-minute bars from Upstox historical-candle.

    Returns `{symbol: bars_inserted}`. Safe to call repeatedly - existing
    bars are left untouched.
    """
    out: Dict[str, int] = {}
    for meta in INDICES:
        out[meta.symbol] = intraday_store.hydrate_from_upstox(db, meta.symbol)
    db.commit()
    return out


@router.get("/health", response_model=HealthDTO)
def health(db: Session = Depends(get_db)) -> HealthDTO:
    last_tick_ts = db.scalar(
        select(RegimeSnapshot.ts).order_by(desc(RegimeSnapshot.ts)).limit(1)
    )
    bar_counts: Dict[str, int] = {}
    for meta in INDICES:
        cnt = db.scalar(
            select(func.count(IntradayBar.symbol)).where(IntradayBar.symbol == meta.symbol)
        ) or 0
        bar_counts[meta.symbol] = int(cnt)

    token = upstox_client.get_settings().UPSTOX_ACCESS_TOKEN.strip()
    token_dead = bool(token) and upstox_client._is_token_dead(token)
    return HealthDTO(
        status="ok",
        upstox_configured=bool(token),
        upstox_token_dead=token_dead,
        last_tick_ts=last_tick_ts,
        bar_counts=bar_counts,
    )
