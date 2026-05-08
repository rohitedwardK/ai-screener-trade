"""India VIX (^INDIAVIX) helper for the MarketContextAgent.

Returns the latest VIX print and a coarse band classification used by the
agent to decide how aggressively to surface signals. Bands are configured
via `INDIA_VIX_HIGH` / `INDIA_VIX_PANIC` in `app.config`.

Source priority mirrors `live_quotes`:
    1. Upstox (^INDIAVIX is mapped in `upstox_client.instrument_key_for`)
    2. yfinance fallback (15-min delayed but always available)

The result is memoised for 60 seconds in-process so a noisy fast-monitor
loop does not hammer the upstream feed.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from ..config import get_settings
from . import live_quotes

log = logging.getLogger(__name__)

VIX_SYMBOL = "^INDIAVIX"
_CACHE_TTL_SECONDS = 60.0

BAND_NORMAL = "NORMAL"
BAND_ELEVATED = "ELEVATED"
BAND_PANIC = "PANIC"
BAND_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class VixSnapshot:
    """Minimal VIX read used by the agent layer."""

    value: Optional[float]
    band: str
    source: str
    fetched_at: float

    def is_fresh(self, ttl: float = _CACHE_TTL_SECONDS) -> bool:
        return (time.monotonic() - self.fetched_at) < ttl


_lock = threading.Lock()
_cached: Optional[VixSnapshot] = None


def _classify(value: Optional[float]) -> str:
    if value is None or value <= 0:
        return BAND_UNKNOWN
    settings = get_settings()
    if value >= settings.INDIA_VIX_PANIC:
        return BAND_PANIC
    if value >= settings.INDIA_VIX_HIGH:
        return BAND_ELEVATED
    return BAND_NORMAL


def fetch_vix(*, force: bool = False) -> VixSnapshot:
    """Return the latest VIX snapshot, using the 60-second cache when possible.

    `force=True` bypasses the cache (used by the manual API trigger).
    """
    global _cached
    with _lock:
        if not force and _cached is not None and _cached.is_fresh():
            return _cached

    prices = live_quotes.fetch_live_prices([VIX_SYMBOL])
    raw = prices.get(VIX_SYMBOL)
    value = float(raw) if raw and raw > 0 else None
    snap = VixSnapshot(
        value=value,
        band=_classify(value),
        source=live_quotes.last_source(),
        fetched_at=time.monotonic(),
    )

    with _lock:
        _cached = snap
    return snap


def reset_cache() -> None:
    """Test hook so deterministic pytest fixtures can clear in-process state."""
    global _cached
    with _lock:
        _cached = None


__all__ = [
    "VIX_SYMBOL",
    "BAND_NORMAL",
    "BAND_ELEVATED",
    "BAND_PANIC",
    "BAND_UNKNOWN",
    "VixSnapshot",
    "fetch_vix",
    "reset_cache",
]
