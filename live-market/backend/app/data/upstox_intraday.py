"""Upstox v2 intraday historical-candle client.

Wraps `GET /v2/historical-candle/intraday/{instrument_key}/{interval}` so we
can hydrate the rolling 1-min OHLCV buffer on boot (or after a process
restart inside a session) without waiting one tick at a time to repopulate.

Returns a list of `IntradayBar` value objects in ascending time order.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from ..config import get_settings
from .upstox_client import (
    INDEX_INSTRUMENT_KEYS,
    _is_token_dead,
    _request,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntradayBar:
    ts: datetime          # bar open time, naive UTC
    open: float
    high: float
    low: float
    close: float
    volume: int


def _parse_bar(raw: list) -> Optional[IntradayBar]:
    """Upstox intraday rows arrive as `[timestamp, open, high, low, close, volume, oi]`.

    Timestamps are ISO-8601 with TZ. We strip the TZ and store as naive UTC
    to match the rest of the codebase's ORM defaults.
    """
    if not isinstance(raw, list) or len(raw) < 6:
        return None
    try:
        ts_raw = raw[0]
        if not isinstance(ts_raw, str):
            return None
        ts = datetime.fromisoformat(ts_raw)
        if ts.tzinfo is not None:
            ts = ts.astimezone(tz=None).replace(tzinfo=None)
        return IntradayBar(
            ts=ts,
            open=float(raw[1]),
            high=float(raw[2]),
            low=float(raw[3]),
            close=float(raw[4]),
            volume=int(raw[5] or 0),
        )
    except (ValueError, TypeError, IndexError):
        return None


def fetch_intraday_1min(
    symbol: str, *, timeout_s: float = 8.0,
) -> List[IntradayBar]:
    """Fetch today's 1-minute candles for a spot index symbol.

    Returns an empty list on token failure / network error / unknown symbol.
    Bars are returned in ASCENDING time order (oldest first) so the caller
    can append to a rolling buffer naturally.
    """
    settings = get_settings()
    token = settings.UPSTOX_ACCESS_TOKEN.strip()
    if not token or _is_token_dead(token):
        return []

    instrument_key = INDEX_INSTRUMENT_KEYS.get(symbol)
    if not instrument_key:
        return []

    url = (
        f"{settings.UPSTOX_BASE_URL.rstrip('/')}/historical-candle/intraday/"
        f"{instrument_key}/1minute"
    )
    payload = _request(token, url, params={}, timeout_s=timeout_s)
    if not payload:
        return []

    data = payload.get("data") or {}
    candles = data.get("candles") or []
    if not isinstance(candles, list):
        return []

    bars: List[IntradayBar] = []
    for raw in candles:
        bar = _parse_bar(raw)
        if bar is not None:
            bars.append(bar)
    # Upstox returns DESCENDING by default (newest first); flip for callers.
    bars.sort(key=lambda b: b.ts)
    return bars


__all__ = ["IntradayBar", "fetch_intraday_1min"]
