"""FastAPI entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import threading

from .agents import scheduler_jobs as agent_jobs
from .api import (
    admin,
    agents as agents_api,
    commodities,
    explain,
    indices,
    live_analysis,
    live_verification,
    method_analysis,
    notifications,
    screener,
    stocks,
)
from .config import get_settings
from .core.scheduler import start_scheduler, stop_scheduler
from .data import index_repository as idx_repo, repository as repo
from .core.commodity_universe import commodity_stock_meta
from .core.index_universe import index_meta
from .core.universe import stock_meta
from .db import init_db, session_scope


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Initialising database...")
    init_db()
    with session_scope() as db:
        repo.upsert_stocks(db, stock_meta() + commodity_stock_meta())
        idx_repo.upsert_indices(db, index_meta())
    log.info("Starting scheduler...")
    start_scheduler()
    settings = get_settings()
    if settings.AGENTIC_ENABLED and settings.AGENTIC_BOOT_CYCLE:
        # Fire the on-load deep cycle off-thread so /docs and /health stay
        # responsive while the crew runs (LLM path can take 60-180s on CPU).
        log.info("Scheduling on-load agentic boot cycle (background)")
        threading.Thread(
            target=agent_jobs.run_boot_cycle_job,
            daemon=True,
            name="agentic-boot-cycle",
        ).start()
    try:
        yield
    finally:
        log.info("Stopping scheduler...")
        stop_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Stock Screener",
        version="1.0.0",
        description="Rule-based + AI-explained Nifty 50 screener (research only).",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(screener.router)
    app.include_router(stocks.router)
    app.include_router(commodities.router)
    app.include_router(explain.router)
    app.include_router(admin.router)
    app.include_router(indices.router)
    app.include_router(live_analysis.router)
    app.include_router(live_verification.router)
    app.include_router(method_analysis.router)
    app.include_router(notifications.router)
    app.include_router(agents_api.router)

    @app.get("/")
    def root() -> dict:
        return {
            "name": "AI Stock Screener",
            "version": "1.0.0",
            "disclaimer": "Research and decision-support only. Not financial advice.",
            "docs": "/docs",
        }

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
