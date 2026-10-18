"""Serial dispatcher for optional local Ollama tasks."""
from __future__ import annotations

import logging
import threading

from sqlalchemy import select

from ..data import ai_task_repository as queue
from ..db import session_scope
from ..models.agent_orm import AgentRun, DailyBriefing, ResearchRun
from ..models.notification_orm import Notification
from . import context_agent, llm, research
from .orchestrator import (
    _HEAD_SYSTEM_PROMPT,
    _fallback_summary_md,
    _llm_prompt_for_payload,
    briefing_text_is_usable,
)
from .tools import DISCLAIMER

log = logging.getLogger(__name__)
_lock = threading.Lock()


def _notify_offline(count: int) -> None:
    with session_scope() as db:
        existing = db.scalar(select(Notification).where(
            Notification.event_type == "OLLAMA_NEEDED",
            Notification.status == "UNREAD",
        ).limit(1))
        message = f"{count} AI task(s) pending. Start Ollama to process them."
        if existing is None:
            db.add(Notification(title="AI analysis pending", message=message,
                                event_type="OLLAMA_NEEDED", severity="WARNING", route="/agents"))
        else:
            existing.message = message


def _clear_offline_notification() -> None:
    with session_scope() as db:
        for note in db.scalars(select(Notification).where(
            Notification.event_type == "OLLAMA_NEEDED",
            Notification.status == "UNREAD",
        )):
            note.status = "READ"


def _record_context_status(briefing_id: int | None, status: str) -> None:
    if briefing_id is None:
        return
    with session_scope() as db:
        briefing = db.get(DailyBriefing, briefing_id)
        run = db.get(AgentRun, briefing.agent_run_id) if briefing else None
        if run is not None:
            statuses = dict(run.json_statuses_json or {})
            statuses["context_agent"] = status
            run.json_statuses_json = statuses


def _execute(task: dict) -> dict:
    kind = task["task_type"]
    if kind == "MARKET_CONTEXT":
        result = context_agent.run_llm()
        _record_context_status(task["briefing_id"], "VALID")
        return {"context": result}
    if kind == "BRIEFING":
        summary = llm.chat(_llm_prompt_for_payload(task["payload"]), system=_HEAD_SYSTEM_PROMPT)
        if not briefing_text_is_usable(summary, task["payload"]):
            summary = _fallback_summary_md(task["payload"])
        elif not summary.rstrip().endswith(DISCLAIMER):
            summary = f"{summary.rstrip()}\n\n{DISCLAIMER}"
        with session_scope() as db:
            briefing = db.get(DailyBriefing, task["briefing_id"])
            if briefing is not None:
                briefing.market_summary_md = summary
                run = db.get(AgentRun, briefing.agent_run_id)
                if run is not None:
                    run.head_agent_status = "OK"
                    statuses = dict(run.worker_statuses_json or {})
                    statuses["head_agent"] = "OK"
                    run.worker_statuses_json = statuses
        return {"summary_md": summary}
    if kind == "RESEARCH":
        payload = task["payload"]
        request = research.ResearchRequest.model_validate(payload["request"])
        result = research.run_research(request, payload.get("context") or {})
        if result.mode != "agent":
            raise ValueError("Research agent did not complete tool selection")
        with session_scope() as db:
            row = db.get(ResearchRun, task["research_run_id"])
            if row is not None:
                row.result_json = result.model_dump(mode="json")
        return {"mode": result.mode, "ideas": len(result.ideas)}
    raise ValueError(f"Unknown AI task type: {kind}")


def process_one() -> None:
    """Process at most one task; offline leaves every task untouched."""
    if not _lock.acquire(blocking=False):
        return
    try:
        queue.expire_stale()
        pending, _ = queue.summary(limit=0)
        if pending == 0:
            _clear_offline_notification()
            return
        if not llm.is_available():
            _notify_offline(pending)
            return
        task = queue.claim_next()
        if task is None:
            return
        try:
            result = _execute(task)
        except llm.AgenticUnavailable:
            queue.defer_offline(task["id"])
            _notify_offline(pending)
        except Exception as exc:  # noqa: BLE001
            log.warning("AI task %s failed; queued for retry: %s", task["id"], exc)
            if task["task_type"] == "MARKET_CONTEXT" and isinstance(exc, (ValueError, TypeError)):
                _record_context_status(task["briefing_id"], "INVALID")
            queue.retry(task["id"], str(exc))
        else:
            queue.complete(task["id"], result)
        remaining, _ = queue.summary(limit=0)
        if remaining == 0:
            _clear_offline_notification()
    finally:
        _lock.release()


def is_running() -> bool:
    return _lock.locked()
