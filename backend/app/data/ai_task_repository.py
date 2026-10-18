"""SQLite persistence for optional local AI work."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from ..db import session_scope
from ..models.agent_orm import AITask

ACTIVE = ("PENDING", "RETRY_WAIT", "RUNNING")


def enqueue(
    task_type: str,
    dedupe_key: str,
    payload: dict,
    *,
    expires_at: datetime | None = None,
    briefing_id: int | None = None,
    research_run_id: int | None = None,
) -> int:
    """Store one request per input snapshot; repeated triggers reuse it."""
    with session_scope() as db:
        if task_type in ("BRIEFING", "MARKET_CONTEXT"):
            for older in db.scalars(select(AITask).where(
                AITask.task_type == task_type,
                AITask.dedupe_key != dedupe_key,
                AITask.status.in_(("PENDING", "RETRY_WAIT")),
            )):
                older.status = "EXPIRED"
                older.error = "Superseded by newer market evidence"
                older.updated_at = datetime.utcnow()
        existing = db.scalar(select(AITask).where(AITask.dedupe_key == dedupe_key))
        if existing is not None:
            if existing.status in ("PENDING", "RETRY_WAIT"):
                existing.payload_json = payload
                existing.briefing_id = briefing_id or existing.briefing_id
                existing.research_run_id = research_run_id or existing.research_run_id
                existing.expires_at = expires_at
                existing.updated_at = datetime.utcnow()
            return int(existing.id)
        row = AITask(
            task_type=task_type, dedupe_key=dedupe_key, payload_json=payload,
            expires_at=expires_at, briefing_id=briefing_id,
            research_run_id=research_run_id,
        )
        db.add(row)
        db.flush()
        return int(row.id)


def claim_next() -> dict | None:
    """Claim one due task. The processor runs serially in this local app."""
    now = datetime.utcnow()
    with session_scope() as db:
        for row in db.scalars(select(AITask).where(
            AITask.status.in_((*ACTIVE,)),
        ).order_by(AITask.created_at, AITask.id)):
            if row.expires_at is not None and row.expires_at <= now:
                row.status = "EXPIRED"
                row.updated_at = now
                continue
            if row.status == "RUNNING":
                if row.lease_until is None or row.lease_until > now:
                    continue
            elif row.next_attempt_at is not None and row.next_attempt_at > now:
                continue
            row.status = "RUNNING"
            row.attempts = int(row.attempts or 0) + 1
            row.lease_until = now + timedelta(minutes=6)
            row.updated_at = now
            db.flush()
            return {
                "id": int(row.id), "task_type": row.task_type,
                "payload": dict(row.payload_json or {}),
                "briefing_id": row.briefing_id,
                "research_run_id": row.research_run_id,
                "attempts": row.attempts,
            }
    return None


def expire_stale() -> None:
    now = datetime.utcnow()
    with session_scope() as db:
        for row in db.scalars(select(AITask).where(AITask.status.in_(ACTIVE))):
            if row.expires_at is not None and row.expires_at <= now:
                row.status = "EXPIRED"
                row.lease_until = None
                row.updated_at = now


def complete(task_id: int, result: dict) -> None:
    with session_scope() as db:
        row = db.get(AITask, task_id)
        if row is None:
            return
        row.result_json = result
        row.status = "COMPLETED"
        row.error = None
        row.lease_until = None
        row.updated_at = datetime.utcnow()


def completed_result(task_id: int) -> dict | None:
    with session_scope() as db:
        row = db.get(AITask, task_id)
        return dict(row.result_json or {}) if row is not None and row.status == "COMPLETED" else None


def retry(task_id: int, error: str, *, max_attempts: int = 3) -> None:
    with session_scope() as db:
        row = db.get(AITask, task_id)
        if row is None:
            return
        now = datetime.utcnow()
        row.status = "FAILED" if row.attempts >= max_attempts else "RETRY_WAIT"
        row.error = error[:300]
        row.next_attempt_at = now + timedelta(minutes=min(2 * row.attempts, 15))
        row.lease_until = None
        row.updated_at = now


def defer_offline(task_id: int) -> None:
    """Transport outages never consume an AI task's attempt budget."""
    with session_scope() as db:
        row = db.get(AITask, task_id)
        if row is None:
            return
        row.status = "PENDING"
        row.attempts = max(int(row.attempts or 0) - 1, 0)
        row.next_attempt_at = datetime.utcnow() + timedelta(minutes=1)
        row.lease_until = None
        row.error = "Ollama unavailable; waiting to retry"
        row.updated_at = datetime.utcnow()


def summary(limit: int = 20) -> tuple[int, list[dict]]:
    with session_scope() as db:
        pending = list(db.scalars(select(AITask).where(AITask.status.in_(ACTIVE))))
        rows = list(db.scalars(select(AITask).order_by(AITask.id.desc()).limit(limit)))
        return len(pending), [{
            "id": int(row.id), "task_type": row.task_type, "status": row.status,
            "created_at": row.created_at, "updated_at": row.updated_at,
            "attempts": int(row.attempts or 0), "error": row.error,
            "result": dict(row.result_json or {}) if row.status == "COMPLETED" else None,
            "briefing_id": row.briefing_id, "research_run_id": row.research_run_id,
        } for row in rows]
