"""MarketContextAgent — VIX, regime, sector rotation, news headlines.

Provides the macro context the head agent uses to filter consensus picks.
A high VIX (PANIC band) triggers a more defensive briefing; an UNKNOWN
regime triggers a "wait for confirmation" tone."""
from __future__ import annotations

import logging
from typing import Any, Dict

from .tools import (
    market_regime_impl,
    news_headlines_impl,
    sector_rotation_impl,
    vix_level_impl,
)

log = logging.getLogger(__name__)


def run(news_limit: int = 8) -> Dict[str, Any]:
    log.info("ContextAgent: regime + VIX + sectors + news")
    return {
        "vix": vix_level_impl(),
        "regime": market_regime_impl(),
        "sectors": sector_rotation_impl(),
        "headlines": news_headlines_impl(limit=news_limit),
    }


run_deterministic = run


__all__ = ["run", "run_deterministic"]
