"""APScheduler entry-points for the agentic layer.

Four jobs are registered from `core.scheduler`:

    1. agentic-deep-cycle    — every AGENTIC_DEEP_CYCLE_MIN min, Mon-Fri 09-15
                               IST. Runs deterministic workers and persists a
                               briefing before optional AI work is queued.
    2. agentic-fast-monitor  — every minute Mon-Fri 09-15 IST. Deterministic
                               60-sec body that wakes the deep cycle on
                               material change (invalidation breach, new
                               top mover, deep-cycle overdue).
    3. agentic-weekly-retrain — Sunday 22:00 IST. Re-fits Random Forest
                                so the user never needs to click Train.
    4. agentic-ai-tasks       — every minute, including after market hours.
                                Processes one pending Ollama task when ready.

Each job is exception-safe — failures log but never crash the scheduler.
A `_deep_lock` prevents two worker cycles running concurrently.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from ..analysis import ml_rf
from ..config import get_settings
from ..db import session_scope
from ..live_analysis import service as live_service
from ..models.agent_orm import PendingAgentTask
from . import ai_tasks
from . import monitoring_agent as monitor_mod
from . import orchestrator

log = logging.getLogger(__name__)

_deep_lock = threading.Lock()
def _trigger_deep_cycle_now() -> None:
    """Schedule deterministic workers after a material monitor change."""
    from ..core import scheduler as core_scheduler

    sched = core_scheduler._scheduler
    if sched is not None and not is_deep_cycle_running():
        sched.add_job(run_deep_cycle_job, kwargs={"force": True},
                      id="agentic-triggered-worker-cycle", replace_existing=True,
                      coalesce=True, max_instances=1)


def pending_task(db) -> Optional[PendingAgentTask]:
    return db.get(PendingAgentTask, 1)


def handle_fast_result(result: monitor_mod.FastTickResult) -> None:
    if result.triggered_deep_cycle:
        log.info("agentic: monitor requested worker cycle: %s", result.note)


def run_deep_cycle_job(*, force: bool = False, use_llm: bool = True, triggered_by: str | None = None) -> None:
    """Scheduler entrypoint for the 15-min deep cycle.

    Short-circuits when:
        - market is closed AND `force` is False AND there is no pending request
        - another deep cycle is already running
    """
    if not force and not live_service.is_market_open():
        return
    if not _deep_lock.acquire(blocking=False):
        log.info("agentic: deep cycle already running; skipping this tick")
        return

    try:
        result = orchestrator.run_deep_cycle(
            triggered_by=triggered_by or ("monitor" if force else "scheduler"),
            use_llm=use_llm,
        )
        with session_scope() as db:
            legacy = pending_task(db)
            if legacy is not None:
                db.delete(legacy)
        log.info(
            "agentic-deep-cycle: status=%s duration=%.1fs picks=%d",
            result.status, result.duration_s, len(result.top_picks),
        )
    except Exception:  # noqa: BLE001
        log.exception("agentic-deep-cycle: unhandled error")
    finally:
        _deep_lock.release()


def run_fast_monitor_job() -> None:
    """Scheduler entrypoint for the 60-sec fast monitor. Deterministic body
    that only wakes the deep cycle on triggers."""
    try:
        if live_service.is_market_open():
            result = monitor_mod.run_fast_tick(trigger_deep_cycle_callback=_trigger_deep_cycle_now)
            handle_fast_result(result)
            log.info("agentic-fast-monitor: movers=%d note=%s", result.movers_count, result.note)
    except Exception:  # noqa: BLE001
        log.exception("agentic-fast-monitor: unhandled error")


def run_weekly_retrain_job() -> None:
    """Scheduler entrypoint for Sunday 22:00 IST retrain. Re-fits Random Forest so the user never needs to manually click Train."""
    log.info("agentic-weekly-retrain: starting Random Forest refit")
    settings = get_settings()
    if not settings.AGENTIC_ENABLED:
        log.info("agentic-weekly-retrain: AGENTIC_ENABLED=false, skipping")
        return
    for name, train_fn in (
        ("rf", ml_rf.train),
    ):
        try:
            train_fn()
            log.info("agentic-weekly-retrain: %s OK", name)
        except Exception:  # noqa: BLE001
            log.exception("agentic-weekly-retrain: %s failed", name)


def run_boot_cycle_job() -> None:
    """Fired once from `main.lifespan` so the dashboard never shows stale
    data on app startup. Runs even outside market hours so a fresh boot
    after-hours still produces a briefing."""
    if not _deep_lock.acquire(blocking=False):
        log.info("agentic-boot: deep cycle already running; skipping boot tick")
        return
    try:
        log.info("agentic-boot-cycle: running on-startup deep cycle")
        result = orchestrator.run_boot_cycle()
        with session_scope() as db:
            legacy = pending_task(db)
            if legacy is not None:
                db.delete(legacy)
        log.info(
            "agentic-boot-cycle: status=%s duration=%.1fs picks=%d",
            result.status, result.duration_s, len(result.top_picks),
        )
    except Exception:  # noqa: BLE001
        log.exception("agentic-boot-cycle: unhandled error")
    finally:
        _deep_lock.release()


def is_deep_cycle_running() -> bool:
    """Diagnostic for the API / dashboard."""
    locked = _deep_lock.acquire(blocking=False)
    if locked:
        _deep_lock.release()
        return False
    return True


def has_pending_deep_request() -> bool:
    return False


def run_ai_task_job() -> None:
    try:
        ai_tasks.process_one()
    except Exception:  # noqa: BLE001
        log.exception("ai-task-processor: unhandled error")


__all__ = [
    "run_deep_cycle_job",
    "run_fast_monitor_job",
    "run_weekly_retrain_job",
    "run_boot_cycle_job",
    "is_deep_cycle_running",
    "has_pending_deep_request",
    "run_ai_task_job",
]
