"""ORM tables backing the agentic layer (head + worker agents).

Two narrow tables, both sharing the project's single `Base` so `init_db()`
picks them up automatically:

    `agent_runs`         one row per deep-cycle / fast-monitor invocation
                         capturing per-worker status + duration. Used by the
                         /v1/agents/status endpoint and the Agents page.

    `daily_briefings`    one row per successful deep cycle holding the
                         orchestrator's final synthesis (regime, VIX band,
                         consensus picks, sector rotation, news headlines,
                         the human-readable markdown summary). Latest row
                         is rendered on the Dashboard.

History is intentionally bounded by `purge_old_runs` / `purge_old_briefings`
helpers in `data.repository_agents` (added in a follow-up todo if needed)
— for now we simply keep them lean and let SQLite vacuum handle space.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, Text, Index

from .orm import Base


CYCLE_DEEP = "DEEP"
CYCLE_FAST = "FAST"
CYCLE_BOOT = "BOOT"
CYCLE_RETRAIN = "RETRAIN"

RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_OK = "OK"
RUN_STATUS_PARTIAL = "PARTIAL"
RUN_STATUS_ERROR = "ERROR"
RUN_STATUS_SKIPPED = "SKIPPED"


class AgentRun(Base):
    """One invocation of either the deep-cycle Crew or the fast monitor.

    `worker_statuses_json` is a small dict like
        {"data_agent": "OK", "analysis_agent": "OK",
         "context_agent": "PARTIAL", "head_agent": "OK"}
    so the frontend can render four green/amber/red dots without needing
    a join. Schema is deliberately denormalised — the agent layer is
    additive observability, not a system of record.
    """

    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    cycle_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default=RUN_STATUS_RUNNING)
    head_agent_status = Column(String, nullable=True)
    worker_statuses_json = Column(JSON, nullable=False, default=dict)
    json_statuses_json = Column(JSON, nullable=True, default=dict)
    duration_s = Column(Float, nullable=True)
    triggered_by = Column(String, nullable=True)
    error = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_agent_runs_runat", "run_at"),
        Index("ix_agent_runs_cycle", "cycle_type", "run_at"),
    )


class ResearchRun(Base):
    """Immutable research evidence and selections; no position state."""

    __tablename__ = "research_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    asset_class = Column(String, nullable=False)
    horizon = Column(String, nullable=False)
    result_json = Column(JSON, nullable=False)


class PendingAgentTask(Base):
    """One coalesced monitor request awaiting a successful AI briefing."""

    __tablename__ = "pending_agent_tasks"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    symbols_json = Column(JSON, nullable=False, default=list)
    reason = Column(String, nullable=False, default="monitor")


class AITask(Base):
    """Durable request for optional local Ollama analysis."""

    __tablename__ = "ai_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_type = Column(String, nullable=False)
    dedupe_key = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default="PENDING")
    payload_json = Column(JSON, nullable=False, default=dict)
    result_json = Column(JSON, nullable=True)
    briefing_id = Column(Integer, nullable=True)
    research_run_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    next_attempt_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    lease_until = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    error = Column(String, nullable=True)

    __table_args__ = (Index("ix_ai_tasks_due", "status", "next_attempt_at"),)


class DailyBriefing(Base):
    """Synthesised output of one successful deep cycle.

    All large blobs live in JSON columns so the frontend can render the
    payload without any per-field DB roundtrips. The markdown summary
    (`market_summary_md`) is the orchestrator's natural-language output;
    the structured columns (top_picks, sector_rotation, headlines) back
    the dashboard widgets directly.
    """

    __tablename__ = "daily_briefings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    agent_run_id = Column(Integer, nullable=True, index=True)

    regime = Column(String, nullable=False, default="UNKNOWN")
    market_trend = Column(String, nullable=True)
    vix_value = Column(Float, nullable=True)
    vix_band = Column(String, nullable=True)

    market_summary_md = Column(Text, nullable=True)
    top_picks_json = Column(JSON, nullable=False, default=list)
    consensus_picks_json = Column(JSON, nullable=False, default=list)
    sector_rotation_json = Column(JSON, nullable=False, default=list)
    news_headlines_json = Column(JSON, nullable=False, default=list)
    method_outputs_json = Column(JSON, nullable=False, default=dict)
    counters_json = Column(JSON, nullable=False, default=dict)
    # Added in the InformantAgent rollout. `init_db` ALTERs SQLite to add
    # this column on existing DBs (additive only — no manual migration).
    # Nullable so the SQLite ALTER works on a populated table; the Python
    # default still produces `[]` on every fresh row.
    upcoming_events_json = Column(JSON, nullable=True, default=list)

    disclaimer = Column(
        String,
        nullable=False,
        default="Research and decision-support only. Not financial advice.",
    )

    __table_args__ = (
        Index("ix_briefings_runat", "run_at"),
    )


__all__ = [
    "AgentRun",
    "DailyBriefing",
    "PendingAgentTask",
    "AITask",
    "CYCLE_DEEP",
    "CYCLE_FAST",
    "CYCLE_BOOT",
    "CYCLE_RETRAIN",
    "RUN_STATUS_RUNNING",
    "RUN_STATUS_OK",
    "RUN_STATUS_PARTIAL",
    "RUN_STATUS_ERROR",
    "RUN_STATUS_SKIPPED",
]
