"""MonitoringAgent — deterministic 60-sec loop body.

By design this is NOT an LLM agent — running an LLM every 60s on a 3B
local model would saturate Ollama within a minute. Instead we keep the
fast loop fully deterministic and only WAKE the deep cycle when something
material has changed:

    - a tracked top-pick has crossed its invalidation level
    - a new symbol has entered the top-mover ladder
    - the previous deep cycle is older than `AGENTIC_DEEP_CYCLE_MIN` minutes
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select

from ..config import get_settings
from ..db import session_scope
from ..models.agent_orm import DailyBriefing
from ..models.notification_orm import Notification
from .tools import (
    check_invalidations_impl,
    live_movers_impl,
    refresh_verification_impl,
)

log = logging.getLogger(__name__)


@dataclass
class FastTickResult:
    ran_at: str
    movers_count: int
    invalidations: List[Dict[str, Any]] = field(default_factory=list)
    new_movers: List[str] = field(default_factory=list)
    triggered_deep_cycle: bool = False
    note: str = ""


_lock = threading.Lock()
_last_movers: List[str] = []
_last_deep_cycle_at: Optional[float] = None


def mark_deep_cycle_complete() -> None:
    """Called by the orchestrator after a successful deep cycle so the fast
    monitor stops requesting one for the next AGENTIC_DEEP_CYCLE_MIN."""
    global _last_deep_cycle_at
    with _lock:
        _last_deep_cycle_at = time.monotonic()


def _deep_cycle_overdue() -> bool:
    settings = get_settings()
    with _lock:
        last = _last_deep_cycle_at
    if last is None:
        return True
    return (time.monotonic() - last) >= (settings.AGENTIC_DEEP_CYCLE_MIN * 60.0)


def _latest_briefing_top_picks() -> List[Dict[str, Any]]:
    """Pull the top picks from the most recent persisted briefing."""
    try:
        with session_scope() as db:
            row = db.scalar(
                select(DailyBriefing).order_by(desc(DailyBriefing.run_at)).limit(1)
            )
            if row is None:
                return []
            return list(row.top_picks_json or [])
    except Exception:  # noqa: BLE001
        log.exception("monitoring_agent: failed to read latest briefing")
        return []


def _notify(event_type: str, symbol: str, title: str, message: str, severity: str = "INFO") -> None:
    """Persist a deduplicated operator alert; never affects signal evaluation."""
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=15)
        with session_scope() as db:
            exists = db.scalar(select(Notification).where(
                Notification.event_type == event_type,
                Notification.symbol == symbol,
                Notification.created_at >= cutoff,
            ).limit(1))
            if exists is None:
                db.add(Notification(symbol=symbol, title=title, message=message,
                                    event_type=event_type, severity=severity,
                                    route=f"/indices/{symbol}"))
    except Exception:  # noqa: BLE001
        log.exception("monitoring_agent: notification persistence failed")


def _scan_index_opportunities() -> None:
    from ..analysis.index_forecast import evaluate
    from ..core.index_universe import all_index_symbols
    from ..data import index_csv_store

    for symbol in all_index_symbols():
        forecast = evaluate(index_csv_store.load(symbol), index_csv_store.load(symbol, intraday=True))
        if forecast.setup == "NO_TRADE" or forecast.confidence < 70:
            continue
        level = forecast.breakout_level if forecast.next_5m_bias == "UP" else forecast.breakdown_level
        _notify(
            "SCALP_OPPORTUNITY", symbol,
            f"{symbol} {forecast.setup.replace('_', ' ').title()}",
            f"{forecast.hourly_bias} hourly structure; 15-minute momentum is {forecast.fifteen_minute_bias.lower()}. Trigger {level:.2f}, invalidation {forecast.invalidation:.2f}.",
            "WARNING",
        )


def run_fast_tick(*, trigger_deep_cycle_callback=None) -> FastTickResult:
    """Execute one 60-sec tick. Idempotent and exception-safe.

    Args:
        trigger_deep_cycle_callback : optional zero-arg function called when
            we decide a deep cycle is needed. The orchestrator hands us a
            function that schedules a one-shot via APScheduler.
    """
    global _last_movers
    ran_at = datetime.now(timezone.utc).isoformat()

    movers_payload = live_movers_impl(k=15)
    if "error" in movers_payload:
        return FastTickResult(
            ran_at=ran_at, movers_count=0,
            note=f"movers error: {movers_payload['error']}",
        )

    movers = movers_payload.get("movers") or []
    current_symbols = [m["symbol"] for m in movers]

    with _lock:
        prev = list(_last_movers)
        _last_movers = current_symbols

    new_movers = [s for s in current_symbols if s not in prev]
    top_picks = _latest_briefing_top_picks()
    invalidations = check_invalidations_impl(top_picks)
    for breach in invalidations:
        symbol = str(breach.get("symbol") or "Market")
        _notify("SETUP_INVALIDATED", symbol, f"{symbol} setup closed by invalidation",
                str(breach.get("reason") or "Price crossed the published invalidation level."), "CRITICAL")
    _scan_index_opportunities()

    # Refresh the live verifier opportunistically — it short-circuits outside
    # market hours and is bounded to ~1s when nothing has changed.
    try:
        refresh_verification_impl()
    except Exception:  # noqa: BLE001
        log.exception("monitoring_agent: live verifier refresh failed (non-fatal)")

    overdue = _deep_cycle_overdue()
    should_trigger = bool(invalidations) or bool(new_movers) or overdue

    triggered = False
    if should_trigger and trigger_deep_cycle_callback is not None:
        try:
            trigger_deep_cycle_callback()
            triggered = True
        except Exception:  # noqa: BLE001
            log.exception("monitoring_agent: trigger_deep_cycle_callback failed")

    note_parts = []
    if invalidations:
        note_parts.append(f"{len(invalidations)} invalidation(s)")
    if new_movers:
        note_parts.append(f"{len(new_movers)} new mover(s)")
    if overdue:
        note_parts.append("deep-cycle overdue")
    note = "; ".join(note_parts) if note_parts else "no triggers"

    return FastTickResult(
        ran_at=ran_at,
        movers_count=len(current_symbols),
        invalidations=invalidations,
        new_movers=new_movers,
        triggered_deep_cycle=triggered,
        note=note,
    )


__all__ = ["FastTickResult", "run_fast_tick", "mark_deep_cycle_complete"]
