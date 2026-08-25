"""Agents API router.

Endpoints:

    GET  /v1/agents/status         per-agent state + recent runs
    GET  /v1/agents/briefing/latest most recent persisted DailyBriefing
    POST /v1/agents/run-deep-cycle  manual trigger (BackgroundTasks)
    POST /v1/agents/run-fast-tick   manual trigger (sync — quick)

The router is intentionally thin: the orchestrator and scheduler_jobs
modules already do all the work, and this layer just exposes them and
serialises the persisted state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..agents import monitoring_agent as monitor_mod
from ..agents import scheduler_jobs as agent_jobs
from ..agents.orchestrator import run_deep_cycle
from ..db import get_db
from ..models.agent_orm import AgentRun, DailyBriefing

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/agents", tags=["agents"])


class AgentRunOut(BaseModel):
    id: int
    run_at: datetime
    cycle_type: str
    status: str
    head_agent_status: Optional[str] = None
    worker_statuses: Dict[str, str] = {}
    duration_s: Optional[float] = None
    triggered_by: Optional[str] = None
    error: Optional[str] = None


class AgentStatusOut(BaseModel):
    deep_cycle_running: bool
    deep_cycle_pending: bool
    last_runs: List[AgentRunOut] = []
    last_deep_cycle_at: Optional[datetime] = None


class BriefingOut(BaseModel):
    id: int
    run_at: datetime
    agent_run_id: Optional[int] = None
    regime: str
    market_trend: Optional[str] = None
    vix_value: Optional[float] = None
    vix_band: Optional[str] = None
    market_summary_md: Optional[str] = None
    top_picks: List[Dict[str, Any]] = []
    consensus_picks: List[Dict[str, Any]] = []
    sector_rotation: List[Dict[str, Any]] = []
    news_headlines: List[Dict[str, Any]] = []
    method_outputs: Dict[str, Any] = {}
    counters: Dict[str, Any] = {}
    upcoming_events: List[Dict[str, Any]] = []
    disclaimer: str


def _utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Tag a stored naive-UTC timestamp as UTC so it serialises with a `+00:00`
    offset. Without this the client parses the bare ISO string as *local* time
    and every displayed time / relative age is off by the local UTC offset."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _serialize_run(row: AgentRun) -> AgentRunOut:
    return AgentRunOut(
        id=int(row.id),
        run_at=_utc_aware(row.run_at),
        cycle_type=row.cycle_type,
        status=row.status,
        head_agent_status=row.head_agent_status,
        worker_statuses=dict(row.worker_statuses_json or {}),
        duration_s=row.duration_s,
        triggered_by=row.triggered_by,
        error=row.error,
    )


def _serialize_briefing(row: DailyBriefing) -> BriefingOut:
    return BriefingOut(
        id=int(row.id),
        run_at=_utc_aware(row.run_at),
        agent_run_id=row.agent_run_id,
        regime=row.regime,
        market_trend=row.market_trend,
        vix_value=row.vix_value,
        vix_band=row.vix_band,
        market_summary_md=row.market_summary_md,
        top_picks=list(row.top_picks_json or []),
        consensus_picks=list(row.consensus_picks_json or []),
        sector_rotation=list(row.sector_rotation_json or []),
        news_headlines=list(row.news_headlines_json or []),
        method_outputs=dict(row.method_outputs_json or {}),
        counters=dict(row.counters_json or {}),
        upcoming_events=list(row.upcoming_events_json or []),
        disclaimer=row.disclaimer,
    )


@router.get("/status", response_model=AgentStatusOut)
def get_agent_status(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> AgentStatusOut:
    """Per-agent status + recent runs. Polled every few seconds by the UI."""
    rows = list(db.scalars(
        select(AgentRun).order_by(desc(AgentRun.run_at)).limit(limit)
    ))
    last_deep = next(
        (r.run_at for r in rows if r.cycle_type in ("DEEP", "BOOT")),
        None,
    )
    return AgentStatusOut(
        deep_cycle_running=agent_jobs.is_deep_cycle_running(),
        deep_cycle_pending=agent_jobs.has_pending_deep_request(),
        last_runs=[_serialize_run(r) for r in rows],
        last_deep_cycle_at=_utc_aware(last_deep),
    )


@router.get("/briefing/latest", response_model=Optional[BriefingOut])
def get_latest_briefing(db: Session = Depends(get_db)) -> Optional[BriefingOut]:
    """Most recent persisted DailyBriefing (or null when none has run yet)."""
    row = db.scalar(
        select(DailyBriefing).order_by(desc(DailyBriefing.run_at)).limit(1)
    )
    return _serialize_briefing(row) if row else None


@router.get("/briefings", response_model=List[BriefingOut])
def list_briefings(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> List[BriefingOut]:
    """Recent briefings (history view)."""
    rows = list(db.scalars(
        select(DailyBriefing).order_by(desc(DailyBriefing.run_at)).limit(limit)
    ))
    return [_serialize_briefing(r) for r in rows]


@router.post("/run-deep-cycle")
def trigger_deep_cycle(
    bg: BackgroundTasks,
    use_llm: bool = Query(True, description="Toggle LLM markdown summary."),
) -> Dict[str, Any]:
    """Schedule a one-shot deep cycle in a background task and return immediately.

    Useful when the operator wants a fresh briefing right now without waiting
    for the next cron tick. The crew is exception-safe so this is fire-and-forget.
    """
    if agent_jobs.is_deep_cycle_running():
        return {"status": "already_running"}
    bg.add_task(run_deep_cycle, triggered_by="api_manual", use_llm=use_llm)
    return {"status": "scheduled", "triggered_by": "api_manual", "use_llm": use_llm}


@router.post("/run-fast-tick")
def trigger_fast_tick() -> Dict[str, Any]:
    """Run one fast-monitor tick synchronously (quick, deterministic)."""
    result = monitor_mod.run_fast_tick(
        trigger_deep_cycle_callback=agent_jobs._trigger_deep_cycle_now,
    )
    return {
        "ran_at": result.ran_at,
        "movers_count": result.movers_count,
        "invalidations": result.invalidations,
        "new_movers": result.new_movers,
        "triggered_deep_cycle": result.triggered_deep_cycle,
        "note": result.note,
    }
