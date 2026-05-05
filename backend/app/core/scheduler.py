"""APScheduler wiring for daily refresh."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import get_settings
from ..db import SessionLocal
from ..paper import config as paper_cfg, service as paper_service
from ..paper_index import (
    config as paper_index_cfg,
    service as paper_index_service,
)
from ..paper_index.index_pipeline import (
    refresh_intraday as run_index_intraday_refresh,
    run_full_refresh as run_index_full_refresh,
)
from .pipeline import run_full_refresh

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def run_paper_live_tick() -> None:
    """Scheduler entrypoint: poll yfinance and apply live-tick logic.

    Idempotent and exception-safe. Short-circuits when:
        - we are outside the NSE regular session (handles weekends and the
          09:00-09:14 / 15:31-15:59 edges that the cron trigger leaves in),
        - or the operator has not switched on live trading in the bot config.
    """
    if not paper_service.is_market_open():
        return
    with SessionLocal() as db:
        try:
            cfg = paper_cfg.snapshot(db)
        except Exception:
            log.exception("paper live-tick: failed to read config; skipping")
            return
        if not cfg.live_trading_enabled:
            return
        try:
            result = paper_service.process_live_tick(db)
        except Exception:
            log.exception("paper live-tick: process_live_tick failed")
            return
    log.info(
        "paper live-tick: priced=%d entries=%d exits=%d realized_today=%.2f status=%s",
        result.symbols_priced, result.entries_filled, result.exits_triggered,
        result.realized_pnl_today, result.bot_status,
    )


def run_paper_index_live_tick() -> None:
    """Trade-management agent for the paper-INDEX bot.

    Mirrors `run_paper_live_tick` but for index option positions. Walks
    only OPEN/PARTIAL_EXIT positions through `paper_index.live_engine`;
    never opens new entries intraday. Simulation only.
    """
    if not paper_index_service.is_market_open():
        return
    with SessionLocal() as db:
        try:
            cfg = paper_index_cfg.snapshot(db)
        except Exception:
            log.exception("paper-index live-tick: failed to read config; skipping")
            return
        if not cfg.live_trading_enabled:
            return
        try:
            result = paper_index_service.process_live_tick(db)
        except Exception:
            log.exception("paper-index live-tick: process_live_tick failed")
            return
    log.info(
        "paper-index live-tick: priced=%d exits=%d realized_today=%.2f status=%s",
        result.symbols_priced, result.exits_triggered,
        result.realized_pnl_today, result.bot_status,
    )


def run_paper_auto_selection() -> None:
    """Scheduler entrypoint: run the daily Run Selection automatically.

    Fires once per day shortly after market open. Idempotent: skips when
    selection has already produced rows for today's date so a manual press
    earlier in the morning isn't double-counted. Gated on the live-trading
    toggle so manual users keep their existing workflow unchanged.
    """
    from datetime import date as _date
    from sqlalchemy import select as _select, func as _func
    from ..models.paper_orm import PaperTradeSignal

    if not paper_service.is_market_open():
        return
    with SessionLocal() as db:
        try:
            cfg = paper_cfg.snapshot(db)
        except Exception:
            log.exception("paper auto-selection: failed to read config; skipping")
            return
        if not cfg.live_trading_enabled:
            return

        today = _date.today()
        already = int(db.scalar(
            _select(_func.count(PaperTradeSignal.id)).where(
                PaperTradeSignal.signal_date == today
            )
        ) or 0)
        if already > 0:
            log.info("paper auto-selection: already ran today (%d rows); skipping", already)
            return

        try:
            result = paper_service.run_selection(db)
        except Exception:
            log.exception("paper auto-selection: run_selection failed")
            return
    log.info(
        "paper auto-selection: regime=%s candidates=%d selected=%d skipped=%d",
        result.market_regime, result.candidates_evaluated,
        len(result.selected), len(result.skipped),
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
    # Paper-trading live tick: every minute Mon-Fri 09-15 IST. The job
    # itself short-circuits outside 09:15-15:30 and when live trading is
    # disabled, so this cron just guarantees the wake-up.
    sched.add_job(
        run_paper_live_tick,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*",
        ),
        id="intraday-paper-tick",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    # Paper-trading auto Run Selection: once per trading day at 09:16 IST,
    # one minute after market open, so PENDING positions exist before the
    # live-tick loop starts evaluating fills. Gated on live_trading_enabled
    # and idempotent (skips when today's signals already exist).
    sched.add_job(
        run_paper_auto_selection,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=16,
        ),
        id="auto-paper-selection",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    # Paper-INDEX trade-management agent: every minute Mon-Fri 09-15 IST.
    # Same short-circuit pattern as the stock live-tick job (market closed
    # or live_trading_enabled off skips the body). Manages OPEN positions
    # only - never opens new ones intraday.
    sched.add_job(
        run_paper_index_live_tick,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*",
        ),
        id="intraday-paper-index-tick",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    sched.start()
    _scheduler = sched
    log.info(
        "Scheduler started: daily-refresh @ %02d:%02d IST + index intraday */5 + paper live-tick */1 + paper-index live-tick */1 + paper auto-selection @ 09:16 IST (Mon-Fri)",
        settings.REFRESH_CRON_HOUR, settings.REFRESH_CRON_MINUTE,
    )
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
