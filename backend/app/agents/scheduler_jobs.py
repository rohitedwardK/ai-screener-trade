"""APScheduler entry-points for the agentic layer.

Three jobs are registered from `core.scheduler`:

    1. agentic-deep-cycle    — every AGENTIC_DEEP_CYCLE_MIN min, Mon-Fri 09-15
                               IST. Runs the full crew (Data → Analysis →
                               Context → Head) and persists a briefing.
    2. agentic-fast-monitor  — every minute Mon-Fri 09-15 IST. Deterministic
                               60-sec body that wakes the deep cycle on
                               material change (invalidation breach, new
                               top mover, deep-cycle overdue).
    3. agentic-weekly-retrain — Sunday 22:00 IST. Re-fits RF + GBM + LSTM
                                so the user never needs to click Train.

Each job is exception-safe — failures log but never crash the scheduler.
A re-entrant `_deep_lock` prevents two deep cycles running concurrently
(LLM-on-CPU would otherwise queue indefinitely).
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from ..analysis import ml_gbm, ml_lstm, ml_rf
from ..config import get_settings
from ..live_analysis import service as live_service
from . import monitoring_agent as monitor_mod
from . import orchestrator

log = logging.getLogger(__name__)

_deep_lock = threading.Lock()
_pending_deep_request: bool = False
_pending_lock = threading.Lock()


def _trigger_deep_cycle_now() -> None:
    """Set a flag the next deep-cycle tick checks. Avoids running an LLM
    cycle from the 60-sec fast monitor thread (CPU contention)."""
    global _pending_deep_request
    with _pending_lock:
        _pending_deep_request = True
    log.info("agentic: fast monitor flagged deep-cycle as needed")


def _consume_deep_request() -> bool:
    global _pending_deep_request
    with _pending_lock:
        flag = _pending_deep_request
        _pending_deep_request = False
    return flag


def run_deep_cycle_job(*, force: bool = False) -> None:
    """Scheduler entrypoint for the 15-min deep cycle.

    Short-circuits when:
        - market is closed AND `force` is False AND there is no pending request
        - another deep cycle is already running
    """
    if not force and not _consume_deep_request() and not live_service.is_market_open():
        return

    if not _deep_lock.acquire(blocking=False):
        log.info("agentic: deep cycle already running; skipping this tick")
        return

    try:
        result = orchestrator.run_deep_cycle(triggered_by="scheduler")
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
    if not live_service.is_market_open():
        return
    try:
        result = monitor_mod.run_fast_tick(
            trigger_deep_cycle_callback=_trigger_deep_cycle_now,
        )
        log.info(
            "agentic-fast-monitor: movers=%d note=%s triggered_deep=%s",
            result.movers_count, result.note, result.triggered_deep_cycle,
        )
    except Exception:  # noqa: BLE001
        log.exception("agentic-fast-monitor: unhandled error")


def run_weekly_retrain_job() -> None:
    """Scheduler entrypoint for Sunday 22:00 IST retrain. Re-fits RF + GBM +
    LSTM so the user never needs to manually click Train."""
    log.info("agentic-weekly-retrain: starting RF + GBM + LSTM refit")
    settings = get_settings()
    if not settings.AGENTIC_ENABLED:
        log.info("agentic-weekly-retrain: AGENTIC_ENABLED=false, skipping")
        return
    for name, train_fn in (
        ("rf", ml_rf.train),
        ("gbm", ml_gbm.train),
        ("lstm", ml_lstm.train),
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
    with _pending_lock:
        return _pending_deep_request


__all__ = [
    "run_deep_cycle_job",
    "run_fast_monitor_job",
    "run_weekly_retrain_job",
    "run_boot_cycle_job",
    "is_deep_cycle_running",
    "has_pending_deep_request",
]
