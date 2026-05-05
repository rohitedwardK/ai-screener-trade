"""Lightweight pacing helper for yfinance.

yfinance >=1.3 uses its own internal `curl_cffi` session for browser
impersonation (required to bypass Yahoo's HTML consent pages) and rejects
external `requests-cache`/`requests` sessions. So we no longer pass a custom
session — we just pace our calls at the application layer.
"""
from __future__ import annotations

import threading
import time

# Minimum delay between successive yfinance calls (seconds).
# Yahoo will rate-limit aggressively above ~5 req/s; 0.30s = ~3 req/s is safe.
_MIN_INTERVAL_S = 0.30

_lock = threading.Lock()
_last_call_at: float = 0.0


def pace() -> None:
    """Block until at least `_MIN_INTERVAL_S` has elapsed since the previous call."""
    global _last_call_at
    with _lock:
        now = time.monotonic()
        wait = (_last_call_at + _MIN_INTERVAL_S) - now
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()
