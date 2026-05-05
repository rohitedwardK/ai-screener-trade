"""FastAPI entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    admin,
    explain,
    indices,
    live_analysis,
    paper_index_trading,
    paper_trading,
    screener,
    stocks,
)
from .config import get_settings
from .core.scheduler import start_scheduler, stop_scheduler
from .data import index_repository as idx_repo, repository as repo
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
        repo.upsert_stocks(db, stock_meta())
        idx_repo.upsert_indices(db, index_meta())
    log.info("Starting scheduler...")
    start_scheduler()
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
    app.include_router(explain.router)
    app.include_router(admin.router)
    app.include_router(paper_trading.router)
    app.include_router(indices.router)
    app.include_router(paper_index_trading.router)
    app.include_router(live_analysis.router)

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
