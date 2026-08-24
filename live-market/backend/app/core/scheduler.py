"""APScheduler integration for the Live Market service.

Single job: `live_market_tick` runs every minute Mon-Fri inside NSE hours
(09:15-15:30 IST). The job is idempotent and the scheduler is configured
with `coalesce=True` so a missed-tick burst (e.g. process restart) doesn't
fire several copies in quick succession.

We deliberately do NOT register any "trade-management" / "auto-execution"
jobs - the parent app's hard rule against autonomous trading bots applies
here too.
"""
from __future__ import annotations

import logging
from datetime import time as dtime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import get_settings
from ..db import session_scope
from . import pipeline

log = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None
_NSE_OPEN = dtime(9, 15)
_NSE_CLOSE = dtime(15, 30)


def _is_nse_session_now() -> bool:
    """Return True between 09:15 and 15:30 IST on weekdays.

    APScheduler's CronTrigger already gates by weekday; this extra check
    in the job body keeps a manual `/v1/admin/tick` honest about whether
    the result will contain real intraday data or just a stale snapshot.
    """
    from .expiry import now_ist  # local import keeps test isolation simple
    now = now_ist()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return _NSE_OPEN <= t <= _NSE_CLOSE


def _tick_job() -> None:
    """Background job entry point. Wraps `pipeline.run_tick` with a session.

    Catches every exception so the scheduler keeps firing - intermittent
    Upstox failures are normal and we never want one bad tick to kill
    the whole loop.
    """
    if not _is_nse_session_now():
        return
    try:
        with session_scope() as db:
            result = pipeline.run_tick(db)
        log.info(
            "tick: priced=%d regimes=%s scalps+%d swings+%d resolved=%d %s",
            result.symbols_priced, result.regimes,
            result.scalps_emitted, result.swings_emitted,
            result.setups_resolved, result.note,
        )
    except Exception:  # noqa: BLE001
        log.exception("live_market_tick failed")


def start_scheduler() -> None:
    """Start the background scheduler. Idempotent."""
    global _scheduler
    settings = get_settings()
    if not settings.LIVE_MARKET_ENABLED:
        log.info("live-market scheduler disabled via LIVE_MARKET_ENABLED=false")
        return
    if _scheduler is not None and _scheduler.running:
        return

    sched = BackgroundScheduler(timezone="Asia/Kolkata")
    poll_min = max(int(settings.LIVE_MARKET_POLL_MIN), 1)
    sched.add_job(
        _tick_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute=f"*/{poll_min}",
            timezone="Asia/Kolkata",
        ),
        id="live_market_tick",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    sched.start()
    _scheduler = sched
    log.info("live-market scheduler started (every %d min, mon-fri, IST)", poll_min)


def stop_scheduler() -> None:
    """Stop the background scheduler. Idempotent."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None


__all__ = ["start_scheduler", "stop_scheduler"]
