"""InformantAgent — surfaces upcoming market-moving events.

Wraps `data.event_calendar.fetch_upcoming_events` over the Nifty 50
universe. The orchestrator's deep cycle includes the agent's output in
the daily briefing payload so the dashboard can highlight stocks expected
to react in the next few days (earnings, ex-dividend, RBI/Fed, F&O
expiry, monthly auto sales).

Defaults to a 5-day forward window per the user's brief; overridable via
`AGENTIC_INFORMANT_DAYS_AHEAD` in `.env`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..config import get_settings
from ..core.universe import all_symbols, stock_meta
from .tools import upcoming_events_impl

log = logging.getLogger(__name__)


def run(days_ahead: int | None = None) -> Dict[str, Any]:
    """Pull events for the next `days_ahead` days. Returns the same shape
    `upcoming_events_impl` returns so the orchestrator can stitch directly.
    """
    settings = get_settings()
    horizon = int(days_ahead if days_ahead is not None else settings.AGENTIC_INFORMANT_DAYS_AHEAD)
    log.info("InformantAgent: scanning next %d days", horizon)
    return upcoming_events_impl(days_ahead=horizon)


# Aliased so the orchestrator can call it the same way it calls the others.
run_deterministic = run


__all__ = ["run", "run_deterministic"]
