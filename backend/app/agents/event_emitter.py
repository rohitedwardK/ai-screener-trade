"""EventEmitter — shared publication bus for the agentic layer.

PR1 scaffold: a thin write-through to the `agent_events` table plus an
in-process subscriber list. Severity-aware routing, alert deduplication,
HALT escalation, and frontend SSE fan-out land in PR3 (MonitoringAgent +
SafetyAgent). Keeping the interface stable now means PR3 can wire those
behaviours behind this same `emit()` call without churning every
publisher site.

Why a singleton + a class
-------------------------
* The class makes the contract testable in isolation (instantiate a
  fresh emitter with a fake subscriber and assert what was published).
* The module-level singleton (`get_emitter()`) is what app code calls
  in the common path so we have one event log per process.
* Subscribers (PR3) will register here once at boot — the singleton's
  list is the authoritative consumer set.

Failures publishing to the DB are logged and swallowed: the publisher
should never crash because logging/observability blew up. The in-process
subscriber loop runs synchronously so test assertions are deterministic.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ..db import session_scope
from ..models.event_orm import (
    AgentEvent,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_CRITICAL,
    SEVERITY_HALT,
)

log = logging.getLogger(__name__)

# Subscribers receive a small dict — same shape as what's persisted —
# so they can implement custom routing without coupling to the ORM.
SubscriberFn = Callable[[Dict[str, Any]], None]


class EventEmitter:
    """In-process pub/sub with durable persistence."""

    def __init__(self, *, persist: bool = True) -> None:
        self._subscribers: List[SubscriberFn] = []
        self._lock = threading.RLock()
        self._persist = persist
        # Counters useful for tests and the future HealthAgent dashboard.
        self.counts: Dict[str, int] = {
            "emitted": 0,
            "persisted": 0,
            "subscriber_errors": 0,
            "persist_errors": 0,
        }

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------
    def emit(
        self,
        *,
        source: str,
        event_type: str,
        message: Optional[str] = None,
        severity: str = SEVERITY_INFO,
        symbol: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Publish one event. Returns the dict that was published, with
        an `emitted_at` ISO timestamp filled in. Never raises."""
        record: Dict[str, Any] = {
            "source": source,
            "event_type": event_type,
            "severity": severity,
            "symbol": symbol,
            "message": message,
            "payload": dict(payload or {}),
            "emitted_at": datetime.now(timezone.utc).isoformat(),
        }
        self.counts["emitted"] += 1

        if self._persist:
            self._persist_event(record)

        # Fan out synchronously — PR3 will swap this for an async queue,
        # for now sync makes ordering deterministic in tests. The local
        # snapshot guards against subscribers mutating the list mid-iteration
        # (e.g. an unsubscribe inside a callback).
        snapshot = list(self._subscribers)  # noqa: SonarLint:python:S6709 — intentional snapshot
        for sub in snapshot:
            try:
                sub(record)
            except Exception:  # noqa: BLE001
                self.counts["subscriber_errors"] += 1
                log.exception(
                    "EventEmitter: subscriber failed for %s/%s",
                    source, event_type,
                )

        return record

    # Convenience helpers — small wrappers around emit() for the
    # common levels. Keeps publisher sites readable.
    def info(self, source: str, event_type: str, **kw) -> Dict[str, Any]:
        return self.emit(source=source, event_type=event_type, severity=SEVERITY_INFO, **kw)

    def warning(self, source: str, event_type: str, **kw) -> Dict[str, Any]:
        return self.emit(source=source, event_type=event_type, severity=SEVERITY_WARNING, **kw)

    def critical(self, source: str, event_type: str, **kw) -> Dict[str, Any]:
        return self.emit(source=source, event_type=event_type, severity=SEVERITY_CRITICAL, **kw)

    def halt(self, source: str, event_type: str, **kw) -> Dict[str, Any]:
        return self.emit(source=source, event_type=event_type, severity=SEVERITY_HALT, **kw)

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------
    def subscribe(self, fn: SubscriberFn) -> SubscriberFn:
        """Register a subscriber. Returns the same function so the call
        site can use it as a decorator."""
        with self._lock:
            if fn not in self._subscribers:
                self._subscribers.append(fn)
        return fn

    def unsubscribe(self, fn: SubscriberFn) -> bool:
        with self._lock:
            try:
                self._subscribers.remove(fn)
                return True
            except ValueError:
                return False

    def clear_subscribers(self) -> None:
        with self._lock:
            self._subscribers.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _persist_event(self, record: Dict[str, Any]) -> None:
        try:
            with session_scope() as db:
                db.add(AgentEvent(
                    source=record["source"],
                    event_type=record["event_type"],
                    severity=record["severity"],
                    symbol=record.get("symbol"),
                    message=record.get("message"),
                    payload_json=record.get("payload") or {},
                ))
            self.counts["persisted"] += 1
        except Exception:  # noqa: BLE001
            self.counts["persist_errors"] += 1
            log.exception(
                "EventEmitter: persist failed for %s/%s",
                record["source"], record["event_type"],
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_default: Optional[EventEmitter] = None
_default_lock = threading.Lock()


def get_emitter() -> EventEmitter:
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = EventEmitter()
    return _default


def reset_emitter() -> None:
    """Test helper. Don't call from app code."""
    global _default
    with _default_lock:
        _default = None


__all__ = [
    "EventEmitter",
    "get_emitter",
    "reset_emitter",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "SEVERITY_CRITICAL",
    "SEVERITY_HALT",
]
