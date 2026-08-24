"""FastAPI entry point for the Live Market service (port 8001)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, chart, market, setups
from .config import get_settings
from .core import intraday_store
from .core.scheduler import start_scheduler, stop_scheduler
from .core.universe import INDICES
from .db import init_db, session_scope

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("live-market: initialising database...")
    init_db()

    settings = get_settings()
    if settings.LIVE_MARKET_HYDRATE_ON_BOOT:
        # Best-effort: pull today's 1-min bars so the rolling buffer isn't
        # cold for the first ~20 ticks. Failures are non-fatal because the
        # per-tick path repopulates the buffer minute by minute regardless.
        try:
            with session_scope() as db:
                for meta in INDICES:
                    inserted = intraday_store.hydrate_from_upstox(db, meta.symbol)
                    if inserted:
                        log.info("hydrated %d bars for %s", inserted, meta.symbol)
        except Exception:  # noqa: BLE001
            log.exception("intraday hydrate on boot failed - continuing")

    log.info("live-market: starting scheduler...")
    start_scheduler()
    try:
        yield
    finally:
        log.info("live-market: stopping scheduler...")
        stop_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Live Market - Intraday Regime + Scalp/Swing Setups",
        version="1.0.0",
        description=(
            "Read-only intraday analysis for ^NSEI / ^NSEBANK / ^BSESN. "
            "Detects RANGE_BOUND vs TRENDING_UP/DOWN and emits scalp setups "
            "(5-15 min, range-bound only) or 2-3 day swing setups "
            "(trending only) with ATM CE/PE option plans where chains are "
            "available. Research and decision-support only. Not financial "
            "advice."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(market.router)
    app.include_router(setups.router)
    app.include_router(chart.router)
    app.include_router(admin.router)

    @app.get("/")
    def root() -> dict:
        return {
            "name": "Live Market",
            "version": "1.0.0",
            "disclaimer": "Research and decision-support only. Not financial advice.",
            "docs": "/docs",
        }

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
