"""ORM table for the cross-cutting EventEmitter.

A single append-only stream that any agent can publish to. Severity
classification (INFO / WARNING / CRITICAL / HALT) and consumer fan-out
land in PR3 (MonitoringAgent + SafetyAgent) — for now this is a passive
audit log so PR1 has somewhere to record FeatureStore hits, indicator
warnings, etc.

Schema choices:

* `payload_json` is the source of truth — most callers are emitting
  small dicts and we don't want to over-normalise.
* `severity` defaults to INFO and is constrained by convention rather
  than CHECK constraint (SQLite-friendly, future-friendly when PR3 adds
  more levels).
* Composite index on `(emitted_at, severity)` so the MonitoringAgent's
  "recent CRITICAL events" query is fast.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Index

from .orm import Base


# Severity vocabulary — kept minimal in PR1, MonitoringAgent will add
# semantic meaning in PR3 (suppress duplicate alerts, escalate to HALT
# above a threshold, etc.).
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HALT = "HALT"


class AgentEvent(Base):
    """One published event from any agent. Append-only, never updated."""

    __tablename__ = "agent_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    emitted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    source = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    severity = Column(String, nullable=False, default=SEVERITY_INFO)
    symbol = Column(String, nullable=True)
    message = Column(String, nullable=True)
    payload_json = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_agent_events_emitted", "emitted_at"),
        Index("ix_agent_events_severity_emitted", "severity", "emitted_at"),
        Index("ix_agent_events_source_type", "source", "event_type"),
    )


__all__ = [
    "AgentEvent",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "SEVERITY_CRITICAL",
    "SEVERITY_HALT",
]
