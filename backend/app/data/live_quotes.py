"""Shared yfinance live-price helper.

Used by both the `/stocks/prices` HTTP endpoint and the paper-trading
intraday scheduler so they hit the same in-memory cache (TTL = 30 s) and
respect the same yfinance pacing.

NSE caveat: yfinance 1-minute bars are published with a roughly 15-minute
delay for Indian equities. That is acceptable for paper-trading simulation
but should never be presented as a real-time feed.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, FrozenSet, List

import yfinance as yf

from . import yf_client

log = logging.getLogger(__name__)

LIVE_CACHE_TTL_SECONDS = 30.0

_lock = threading.Lock()
_prices: Dict[str, float] = {}
_symbols: FrozenSet[str] = frozenset()
_fetched_at: float = 0.0


def fetch_live_prices(symbols: List[str]) -> Dict[str, float]:
    """Return the latest 1-minute close per symbol.

    Behaviour:
        - Returns the cached dict if `symbols` matches the previous call's
          set and fewer than 30 s have elapsed.
        - Otherwise issues a single `yf.download(... interval="1m")` for the
          whole batch and overwrites the cache.
        - On any error returns an empty dict; callers must fall back.
    """
    global _prices, _symbols, _fetched_at

    if not symbols:
        return {}

    sym_set = frozenset(symbols)
    now = time.monotonic()

    with _lock:
        if sym_set == _symbols and (now - _fetched_at) < LIVE_CACHE_TTL_SECONDS:
            return dict(_prices)

    yf_client.pace()

    result: Dict[str, float] = {}
    try:
        tickers_str = " ".join(symbols)
        df = yf.download(
            tickers_str,
            period="1d",
            interval="1m",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )
        if df is None or df.empty:
            return result

        for sym in symbols:
            try:
                last = df[sym]["Close"].dropna().iloc[-1]
                result[sym] = float(last)
            except (KeyError, IndexError):
                # Single-symbol downloads return a flat DataFrame, not MultiIndex.
                try:
                    last = df["Close"].dropna().iloc[-1]
                    result[sym] = float(last)
                except (KeyError, IndexError):
                    pass
    except Exception:
        log.warning("Live price fetch failed", exc_info=True)
        return result

    with _lock:
        _prices = result
        _symbols = sym_set
        _fetched_at = time.monotonic()

    return result


def cached_prices() -> Dict[str, float]:
    """Return whatever the cache currently holds (may be stale or empty)."""
    with _lock:
        return dict(_prices)


def reset_cache() -> None:
    """Test hook: drop the cache so the next call refetches."""
    global _prices, _symbols, _fetched_at
    with _lock:
        _prices = {}
        _symbols = frozenset()
        _fetched_at = 0.0
