"""Shared live-price helper.

Used by both the `/stocks/prices` HTTP endpoint and the paper-trading
intraday scheduler so they hit the same in-memory cache (TTL = 30 s) and
respect the same rate-limits.

Source priority:
    1. Upstox v2 `market-quote/quotes` for any symbol present in the
       hardcoded Nifty 50 + indices instrument-key map. This is a true
       real-time intraday feed.
    2. yfinance 1-minute bars for everything else (and as a global
       fallback if Upstox isn't configured or the request fails).
       NSE caveat: yfinance 1-minute bars are roughly 15 minutes
       delayed for Indian equities - acceptable for paper-trading
       simulation but should never be presented as a real-time feed.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, FrozenSet, List, Tuple

import yfinance as yf

from . import upstox_client, yf_client

log = logging.getLogger(__name__)

LIVE_CACHE_TTL_SECONDS = 30.0

# Source labels surfaced through `last_source()`. "mixed" means some
# symbols came from Upstox and some from yfinance in the same call.
SOURCE_NONE = "none"
SOURCE_UPSTOX = "upstox"
SOURCE_YFINANCE = "yfinance"
SOURCE_MIXED = "mixed"

_lock = threading.Lock()
_prices: Dict[str, float] = {}
_symbols: FrozenSet[str] = frozenset()
_fetched_at: float = 0.0
_last_source: str = SOURCE_NONE


def _split_by_upstox_coverage(symbols: List[str]) -> Tuple[List[str], List[str]]:
    """Partition `symbols` into (upstox-eligible, yfinance-only)."""
    upstox_syms: List[str] = []
    yf_syms: List[str] = []
    for sym in symbols:
        if upstox_client.instrument_key_for(sym) is not None:
            upstox_syms.append(sym)
        else:
            yf_syms.append(sym)
    return upstox_syms, yf_syms


def _fetch_from_upstox(symbols: List[str]) -> Dict[str, float]:
    """Best-effort Upstox LTP fetch. Empty on any failure - caller decides
    whether to degrade or fall back."""
    if not symbols or not upstox_client.is_configured():
        return {}
    try:
        return upstox_client.fetch_ltp_batch(symbols)
    except Exception:  # noqa: BLE001 - we never want a fetch error to bubble
        log.warning("Upstox LTP fetch failed; will fall back to yfinance", exc_info=True)
        return {}


def _fetch_from_yfinance(symbols: List[str]) -> Dict[str, float]:
    """One batched `yf.download(... interval='1m')` for the supplied symbols.
    Returns a partial dict on per-symbol parse failures, empty dict on any
    request-level error."""
    if not symbols:
        return {}
    yf_client.pace()
    result: Dict[str, float] = {}
    try:
        df = yf.download(
            " ".join(symbols),
            period="1d",
            interval="1m",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )
    except Exception:
        log.warning("yfinance live price fetch failed", exc_info=True)
        return result
    if df is None or df.empty:
        return result

    for sym in symbols:
        try:
            last = df[sym]["Close"].dropna().iloc[-1]
            result[sym] = float(last)
        except (KeyError, IndexError):
            try:
                # Single-symbol downloads return a flat DataFrame, not MultiIndex.
                last = df["Close"].dropna().iloc[-1]
                result[sym] = float(last)
            except (KeyError, IndexError):
                pass
    return result


def fetch_live_prices(symbols: List[str]) -> Dict[str, float]:
    """Return the latest live price per symbol.

    Behaviour:
        - Returns the cached dict if `symbols` matches the previous call's
          set and fewer than 30 s have elapsed.
        - Otherwise tries Upstox for symbols in its instrument-key map,
          then yfinance for everything Upstox didn't cover or return.
        - On total failure returns an empty dict; callers must fall back.
    """
    global _prices, _symbols, _fetched_at, _last_source

    if not symbols:
        return {}

    sym_set = frozenset(symbols)
    now = time.monotonic()

    with _lock:
        if sym_set == _symbols and (now - _fetched_at) < LIVE_CACHE_TTL_SECONDS:
            return dict(_prices)

    upstox_syms, yf_syms = _split_by_upstox_coverage(symbols)

    upstox_prices = _fetch_from_upstox(upstox_syms)
    # Anything Upstox didn't return (rate-limited, after-hours gap, etc.) gets
    # picked up by yfinance so we don't lose coverage.
    upstox_misses = [s for s in upstox_syms if s not in upstox_prices]
    yf_targets = yf_syms + upstox_misses

    yf_prices = _fetch_from_yfinance(yf_targets)

    merged: Dict[str, float] = {}
    merged.update(upstox_prices)
    for s, p in yf_prices.items():
        merged.setdefault(s, p)

    if not merged:
        source = SOURCE_NONE
    elif upstox_prices and yf_prices:
        source = SOURCE_MIXED
    elif upstox_prices:
        source = SOURCE_UPSTOX
    else:
        source = SOURCE_YFINANCE

    with _lock:
        _prices = merged
        _symbols = sym_set
        _fetched_at = time.monotonic()
        _last_source = source

    return merged


def cached_prices() -> Dict[str, float]:
    """Return whatever the cache currently holds (may be stale or empty)."""
    with _lock:
        return dict(_prices)


def last_source() -> str:
    """Source label for the most recent successful `fetch_live_prices` call.

    One of: "upstox" | "yfinance" | "mixed" | "none". Useful for surfacing
    the active data feed in diagnostic UIs without re-issuing a request.
    """
    with _lock:
        return _last_source


def reset_cache() -> None:
    """Test hook: drop the cache so the next call refetches."""
    global _prices, _symbols, _fetched_at, _last_source
    with _lock:
        _prices = {}
        _symbols = frozenset()
        _fetched_at = 0.0
        _last_source = SOURCE_NONE
