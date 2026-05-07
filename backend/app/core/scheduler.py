"""APScheduler wiring.

Drives three recurring jobs during NSE hours (Mon-Fri 09-15 IST):

    1. Daily EOD refresh of stock + index OHLCV (single cron at the
       configured close-of-business hour).
    2. Intraday index refresh every 5 min — keeps the index dashboard
       and intraday signals fresh while the market is open.
    3. Live Analysis tick every `LIVE_ANALYSIS_POLL_MIN` (Upstox-backed,
       yfinance fallback). Short-circuits when mode != LIVE.
    4. Live screener verification every 15 min — cross-checks persisted
       EOD signals against current LTPs.

Paper-trading auto-bots have been removed from this app. Anything that
made autonomous order/sizing/exit decisions used to live here too; the
remaining jobs are read-only data refreshes + verification.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import get_settings
from ..db import SessionLocal
from ..live_analysis import config as live_cfg, service as live_service
from .index_pipeline import (
    refresh_intraday as run_index_intraday_refresh,
    run_full_refresh as run_index_full_refresh,
)
from .live_strike_verification import run_strike_verification
from .live_verification import run_live_verification
from .pipeline import run_full_refresh

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def run_live_analysis_tick() -> None:
    """Scheduler entrypoint: poll Upstox (or yfinance fallback) and advance
    Live Analysis observation windows.

    Idempotent and exception-safe. Short-circuits when:
        - we are outside the NSE regular session,
        - or Live Analysis Mode is OFF in `live_analysis_config.mode`.
    """
    if not live_service.is_market_open():
        return
    with SessionLocal() as db:
        try:
            mode = live_cfg.get_mode(db)
        except Exception:
            log.exception("live-analysis tick: failed to read mode; skipping")
            return
        if mode != live_cfg.MODE_LIVE:
            return
        try:
            result = live_service.run_tick(db)
        except Exception:
            log.exception("live-analysis tick: run_tick failed")
            return
    log.info(
        "live-analysis tick: regime=%s priced=%d active=%d started=%d "
        "decisions=%d cooldowns_released=%d",
        result.regime, result.symbols_priced, result.observations_active,
        result.observations_started, result.decisions_emitted,
        result.cooldowns_released,
    )


def run_live_screener_verification() -> None:
    """Scheduler entrypoint: cross-check persisted EOD signals against live LTPs.

    Mon-Fri */15min during NSE regular session. Idempotent and exception-
    safe. Short-circuits outside market hours so the cron wake-up at the
    minute boundary doesn't churn the DB on weekends or pre-open.
    """
    if not live_service.is_market_open():
        return
    try:
        result = run_live_verification()
    except Exception:
        log.exception("live-screener-verification: run failed")
        return
    log.info(
        "live-screener-verification: signals=%d upserted=%d source=%s "
        "confirmed=%d weakening=%d invalidated=%d strengthened=%d",
        result.signals_evaluated, result.rows_upserted, result.source,
        result.by_status.get("CONFIRMED", 0),
        result.by_status.get("WEAKENING", 0),
        result.by_status.get("INVALIDATED", 0),
        result.by_status.get("STRENGTHENED", 0),
    )


def run_live_strike_verification_job() -> None:
    """Scheduler entrypoint: project ACTIVE strike recommendations onto the
    live option premium and underlying spot, marking T1/T2/STOP/INVALIDATED.

    Mon-Fri every 5 min during NSE regular session. Short-circuits outside
    market hours."""
    if not live_service.is_market_open():
        return
    try:
        result = run_strike_verification()
    except Exception:
        log.exception("live-strike-verification: run failed")
        return
    log.info(
        "live-strike-verification: rows_updated=%d active=%d t1=%d t2=%d "
        "stop=%d invalidated=%d expired=%d",
        result.rows_updated,
        result.by_status.get("ACTIVE", 0),
        result.by_status.get("T1_HIT", 0),
        result.by_status.get("T2_HIT", 0),
        result.by_status.get("STOP_HIT", 0),
        result.by_status.get("INVALIDATED", 0),
        result.by_status.get("EXPIRED", 0),
    )


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    settings = get_settings()
    if not settings.ENABLE_SCHEDULER:
        log.info("Scheduler disabled by config.")
        return None
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(timezone="Asia/Kolkata")
    sched.add_job(
        run_full_refresh,
        trigger=CronTrigger(
            hour=settings.REFRESH_CRON_HOUR,
            minute=settings.REFRESH_CRON_MINUTE,
        ),
        id="daily-refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    # Daily index refresh: a few minutes after the stock refresh so option-chain
    # snapshots align with the close.
    sched.add_job(
        run_index_full_refresh,
        trigger=CronTrigger(
            hour=settings.REFRESH_CRON_HOUR,
            minute=(settings.REFRESH_CRON_MINUTE + 5) % 60,
        ),
        id="daily-index-refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    # Intraday index refresh: every 5 minutes Mon-Fri 09-15 IST. Index options
    # have a ~5-day lifecycle so we monitor price action significantly tighter
    # than the daily stock refresh.
    sched.add_job(
        run_index_intraday_refresh,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/5",
        ),
        id="intraday-index-refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    # Live Analysis tick: every poll_interval_min (default 3) Mon-Fri
    # 09-15 IST. The job short-circuits when mode != LIVE, so this cron
    # just guarantees the wake-up. Cadence is fixed at the cron level so
    # APScheduler can plan deterministically; in-DB `poll_interval_min`
    # additionally throttles per-sample appends inside the engine.
    sched.add_job(
        run_live_analysis_tick,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute=f"*/{max(int(settings.LIVE_ANALYSIS_POLL_MIN), 1)}",
        ),
        id="intraday-live-analysis-tick",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    # Live screener verification: every 15 min Mon-Fri 09-15 IST. Reads the
    # latest persisted signals, builds an intraday-projected today-bar from
    # live LTPs, and writes one verification row per signal so the dashboard
    # can show CONFIRMED / WEAKENING / INVALIDATED / STRENGTHENED status.
    # Idempotent; the body itself short-circuits outside 09:15-15:30 IST.
    sched.add_job(
        run_live_screener_verification,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/15",
        ),
        id="live-screener-verification",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    # Live strike-recommendation verification: every 5 min Mon-Fri 09-15 IST.
    # Refreshes premium LTPs from Upstox (chain fallback for missing keys),
    # marks T1/T2/STOP/INVALIDATED/EXPIRED so the UI can render live status
    # pills next to each persisted weekly recommendation.
    sched.add_job(
        run_live_strike_verification_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/5",
        ),
        id="live-strike-verification",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    sched.start()
    _scheduler = sched
    log.info(
        "Scheduler started: daily-refresh @ %02d:%02d IST + index intraday */5 "
        "+ live-analysis */%d + live-verification */15 + strike-verification */5 "
        "(Mon-Fri)",
        settings.REFRESH_CRON_HOUR, settings.REFRESH_CRON_MINUTE,
        max(int(settings.LIVE_ANALYSIS_POLL_MIN), 1),
    )
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
