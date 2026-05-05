"""Seed script: run once after install to populate DB and generate first signals.

Usage:
    cd backend
    python -m app.seed
"""
from __future__ import annotations

import logging

from .core.pipeline import run_full_refresh
from .db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("seed")


def main() -> None:
    log.info("Initialising database...")
    init_db()
    log.info("Running full refresh (this may take 30-90s)...")
    result = run_full_refresh()
    log.info(
        "Done. fetched=%d signals=%d errors=%d",
        result.fetched_symbols, result.signals_generated, len(result.errors),
    )
    if result.errors:
        for e in result.errors[:10]:
            log.warning("err: %s", e)


if __name__ == "__main__":
    main()
