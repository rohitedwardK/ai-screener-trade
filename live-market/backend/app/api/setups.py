"""Active and historical setup endpoints."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.orm import ScalpSetup, SwingSetup
from ..models.schemas import ScalpSetupDTO, SwingSetupDTO

router = APIRouter(prefix="/v1/setups", tags=["setups"])


@router.get("/scalps/active", response_model=List[ScalpSetupDTO])
def active_scalps(
    symbol: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[ScalpSetupDTO]:
    q = select(ScalpSetup).where(ScalpSetup.status == "ACTIVE")
    if symbol:
        q = q.where(ScalpSetup.symbol == symbol)
    q = q.order_by(desc(ScalpSetup.created_at))
    return [ScalpSetupDTO.model_validate(r) for r in db.scalars(q)]


@router.get("/swings/active", response_model=List[SwingSetupDTO])
def active_swings(
    symbol: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[SwingSetupDTO]:
    q = select(SwingSetup).where(SwingSetup.status == "ACTIVE")
    if symbol:
        q = q.where(SwingSetup.symbol == symbol)
    q = q.order_by(desc(SwingSetup.created_at))
    return [SwingSetupDTO.model_validate(r) for r in db.scalars(q)]


@router.get("/scalps/history", response_model=List[ScalpSetupDTO])
def history_scalps(
    symbol: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[ScalpSetupDTO]:
    q = select(ScalpSetup).where(ScalpSetup.status != "ACTIVE")
    if symbol:
        q = q.where(ScalpSetup.symbol == symbol)
    q = q.order_by(desc(ScalpSetup.resolved_at), desc(ScalpSetup.created_at)).limit(limit)
    return [ScalpSetupDTO.model_validate(r) for r in db.scalars(q)]


@router.get("/swings/history", response_model=List[SwingSetupDTO])
def history_swings(
    symbol: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[SwingSetupDTO]:
    q = select(SwingSetup).where(SwingSetup.status != "ACTIVE")
    if symbol:
        q = q.where(SwingSetup.symbol == symbol)
    q = q.order_by(desc(SwingSetup.resolved_at), desc(SwingSetup.created_at)).limit(limit)
    return [SwingSetupDTO.model_validate(r) for r in db.scalars(q)]
