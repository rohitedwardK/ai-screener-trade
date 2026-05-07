"""Live signal verification endpoints.

Exposes the orchestrator in `core/live_verification.py` over HTTP:
    POST /v1/live-verification/run      -> run one verification pass now
    GET  /v1/live-verification/summary  -> counts by status (dashboard banner)
    GET  /v1/live-verification/signals  -> list current verification rows
                                           joined with the persisted signal

The router is mounted from `main.create_app()` alongside the screener.
Heavy lifting lives in the orchestrator; this layer only marshals payloads.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import live_verification as service
from ..db import get_db
from ..models.orm import LiveSignalVerification, Signal


router = APIRouter(prefix="/v1/live-verification", tags=["live-verification"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class RunResult(BaseModel):
    started_at: datetime
    finished_at: datetime
    signals_evaluated: int
    rows_upserted: int
    by_status: Dict[str, int]
    source: str
    errors: List[str] = []
    disclaimer: str = "Research and decision-support only. Not financial advice."


class SummaryOut(BaseModel):
    confirmed: int
    weakening: int
    invalidated: int
    strengthened: int
    total: int
    last_run_at: Optional[str] = None
    source: Optional[str] = None
    disclaimer: str = "Research and decision-support only. Not financial advice."


class VerificationSignalRow(BaseModel):
    """One verification row joined with the persisted signal it cross-checked."""
    model_config = ConfigDict(from_attributes=True)

    signal_id: int
    symbol: str
    category: str
    score: float
    persisted_close: float
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    status: str
    live_close: float
    live_rsi: Optional[float] = None
    live_adx: Optional[float] = None
    live_regime: str
    score_delta: Optional[float] = None
    distance_to_stop_pct: Optional[float] = None
    distance_to_t1_pct: Optional[float] = None
    notes: List[str] = []
    source: Optional[str] = None
    run_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/run", response_model=RunResult)
def trigger_run(
    background: bool = Query(False, description="If true, schedule run in background and return immediately."),
    bg: BackgroundTasks = BackgroundTasks(),
) -> RunResult:
    """Run one verification pass and return a summary.

    Synchronous by default — Nifty 50 takes a few seconds because the
    indicator math runs entirely in pandas. Pass `?background=true` to
    fire-and-forget when invoking from the UI's auto-poller.
    """
    if background:
        bg.add_task(service.run_live_verification)
        empty: Dict[str, int] = {
            "CONFIRMED": 0, "WEAKENING": 0,
            "INVALIDATED": 0, "STRENGTHENED": 0,
        }
        now = datetime.utcnow()
        return RunResult(
            started_at=now,
            finished_at=now,
            signals_evaluated=0,
            rows_upserted=0,
            by_status=empty,
            source="scheduled",
            errors=[],
        )
    result = service.run_live_verification()
    return RunResult(
        started_at=result.started_at,
        finished_at=result.finished_at,
        signals_evaluated=result.signals_evaluated,
        rows_upserted=result.rows_upserted,
        by_status=result.by_status,
        source=result.source,
        errors=result.errors,
    )


@router.get("/summary", response_model=SummaryOut)
def get_summary(db: Session = Depends(get_db)) -> SummaryOut:
    payload: Dict[str, Any] = service.get_summary(db)
    return SummaryOut(**payload)


@router.get("/signals", response_model=List[VerificationSignalRow])
def list_signals(
    status: Optional[str] = Query(None, description="Filter to one status (CONFIRMED/WEAKENING/INVALIDATED/STRENGTHENED)."),
    symbol: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[VerificationSignalRow]:
    """List the latest verification rows joined with their persisted signals.

    The screener table can drive its `live` column from this, but the
    nested screener endpoint already inlines `live` for first-paint
    economy; this endpoint exists for diagnostics and the dashboard.
    """
    stmt = (
        select(LiveSignalVerification, Signal)
        .join(Signal, Signal.id == LiveSignalVerification.signal_id)
        .order_by(LiveSignalVerification.run_at.desc())
    )
    if status:
        stmt = stmt.where(LiveSignalVerification.status == status.upper())
    if symbol:
        stmt = stmt.where(LiveSignalVerification.symbol == symbol.upper())

    rows = db.execute(stmt).all()
    out: List[VerificationSignalRow] = []
    for verification, sig in rows[:limit]:
        out.append(VerificationSignalRow(
            signal_id=int(sig.id),
            symbol=sig.symbol,
            category=sig.category,
            score=float(sig.score),
            persisted_close=float(sig.entry) if sig.entry is not None else float(verification.live_close),
            entry=float(sig.entry) if sig.entry is not None else None,
            stop_loss=float(sig.stop_loss) if sig.stop_loss is not None else None,
            target_1=float(sig.target_1) if sig.target_1 is not None else None,
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
        ))
    return out
