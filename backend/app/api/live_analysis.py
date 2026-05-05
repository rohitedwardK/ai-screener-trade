"""FastAPI endpoints for the Live Analysis Mode."""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..live_analysis import service

router = APIRouter(prefix="/v1/live-analysis", tags=["live-analysis"])

DbSession = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class ModeOut(BaseModel):
    mode: str
    market_open: bool


class ModeIn(BaseModel):
    mode: str = Field(description="HISTORICAL | LIVE")


class WeightsIn(BaseModel):
    w1_z: Optional[float] = None
    w2_slope: Optional[float] = None
    w3_vwap: Optional[float] = None
    w4_ema20: Optional[float] = None
    w5_rvol: Optional[float] = None
    w6_body: Optional[float] = None
    w7_rsi_penalty: Optional[float] = None


class ConfigIn(BaseModel):
    mode: Optional[str] = None
    poll_interval_min: Optional[int] = Field(default=None, ge=1, le=60)
    observation_samples: Optional[int] = Field(default=None, ge=2, le=20)
    top_k_movers: Optional[int] = Field(default=None, ge=1, le=50)
    cooldown_min: Optional[int] = Field(default=None, ge=0, le=240)
    decision_threshold: Optional[float] = Field(default=None, ge=0.0, le=20.0)
    confidence_threshold: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    regime_risk_on_z: Optional[float] = Field(default=None, ge=-5.0, le=5.0)
    regime_risk_off_z: Optional[float] = Field(default=None, ge=-5.0, le=5.0)
    weights: Optional[WeightsIn] = None


class TickOut(BaseModel):
    processed_at: str
    mode: str
    market_open: bool
    regime: str
    symbols_priced: int
    top_movers_count: int
    observations_active: int
    observations_started: int
    decisions_emitted: int
    cooldowns_released: int
    note: str = ""


# Standard error contract for the 400 raised when an invalid mode/config
# value is submitted. Documented once and reused across endpoints below.
_BAD_REQUEST_RESPONSES = {
    400: {"description": "Invalid request body (e.g. unknown mode or out-of-range weight)"},
}


# ---------------------------------------------------------------------------
# Mode toggle
# ---------------------------------------------------------------------------
@router.get("/mode")
def get_mode(db: DbSession) -> ModeOut:
    return ModeOut(mode=service.get_mode(db), market_open=service.is_market_open())


@router.post("/mode", responses=_BAD_REQUEST_RESPONSES)
def set_mode(db: DbSession, payload: Annotated[ModeIn, Body()]) -> ModeOut:
    try:
        new_mode = service.set_mode(db, payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ModeOut(mode=new_mode, market_open=service.is_market_open())


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@router.get("/config")
def get_config(db: DbSession) -> Dict[str, Any]:
    return service.get_config_dict(db)


@router.post("/config", responses=_BAD_REQUEST_RESPONSES)
def update_config(
    db: DbSession,
    payload: Annotated[ConfigIn, Body()],
) -> Dict[str, Any]:
    fields = payload.model_dump(exclude_none=True)
    weights = fields.pop("weights", None)
    if weights:
        fields["weights"] = {k: v for k, v in weights.items() if v is not None}
    try:
        return service.update_config(db, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Dashboard / reads
# ---------------------------------------------------------------------------
@router.get("/dashboard")
def get_dashboard(db: DbSession) -> Dict[str, Any]:
    return service.get_dashboard(db)


@router.get("/decisions")
def get_decisions(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> List[Dict[str, Any]]:
    return service.get_decisions(db, limit=limit)


@router.get("/observations")
def get_observations(
    db: DbSession,
    only_active: Annotated[bool, Query()] = True,
) -> List[Dict[str, Any]]:
    return service.get_observations(db, only_active=only_active)


# ---------------------------------------------------------------------------
# Manual tick (debugging / forced refresh)
# ---------------------------------------------------------------------------
@router.post("/tick")
def trigger_tick(db: DbSession) -> TickOut:
    """Manually run one Live Analysis tick.

    Mirrors the paper-trading `/process-live-tick` endpoint - useful when
    debugging or when you want to force a refresh outside the cron schedule.
    Still gated on `mode == LIVE` inside the engine; if you call this with
    mode=HISTORICAL you'll get back a no-op summary.
    """
    summary = service.run_tick(db)
    return TickOut(**summary.__dict__)
