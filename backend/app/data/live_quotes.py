"""Shared live-price helper.

Used by both the `/stocks/prices` HTTP endpoint and the paper-trading
intraday scheduler so they hit the same in-memory cache (TTL = 30 s) and
respect the same rate-limits.

Source priority:
    1. Upstox for every mapped stock, index, and MCX commodity, including
       after the exchange closes (when Upstox returns the last traded quote).
    2. yfinance only for unmapped instruments or quotes Upstox did not return.
    3. If Upstox misses a commodity, use the last whole-rupee MCX close from
       the CSV cache. COMEX × USDINR is used only on cold start.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, FrozenSet, List, Tuple

import yfinance as yf

from ..core.commodity_universe import is_commodity_symbol
from . import upstox_client, yf_client

log = logging.getLogger(__name__)

LIVE_CACHE_TTL_SECONDS = 30.0

# Source labels surfaced through `last_source()`. "mixed" means some
# symbols came from Upstox and some from yfinance in the same call.
SOURCE_NONE = "none"
SOURCE_UPSTOX = "upstox"
SOURCE_YFINANCE = "yfinance"
SOURCE_SNAPSHOT = "snapshot"
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


def _last_closes_from_yf_df(df: object, symbols: List[str]) -> Dict[str, float]:
    """Parse a yfinance download frame (single- or multi-ticker) into last closes."""
    result: Dict[str, float] = {}
    if df is None or getattr(df, "empty", True):
        return result
    for sym in symbols:
        try:
            last = df[sym]["Close"].dropna().iloc[-1]
            result[sym] = float(last)
        except (KeyError, IndexError, TypeError):
            try:
                # Single-symbol downloads return a flat DataFrame, not MultiIndex.
                last = df["Close"].dropna().iloc[-1]
                result[sym] = float(last)
            except (KeyError, IndexError, TypeError):
                pass
    return result


def _yf_download_closes(
    symbols: List[str], *, period: str, interval: str
) -> Dict[str, float]:
    if not symbols:
        return {}
    yf_client.pace()
    try:
        df = yf.download(
            " ".join(symbols),
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )
    except Exception:
        log.warning(
            "yfinance live price fetch failed (interval=%s)", interval, exc_info=True
        )
        return {}
    return _last_closes_from_yf_df(df, symbols)


def _fetch_mcx_fallback(symbols: List[str]) -> Dict[str, float]:
    """MCX symbols when Upstox is unavailable.

    Prefer the last real MCX close from CSV (Upstox-backed history). Only
    fall back to COMEX×INR when there is no cached MCX row yet.
    """
    if not symbols:
        return {}
    from . import mcx as mcx_data

    out = mcx_data.cached_close_ltp(symbols)
    missing = [s for s in symbols if s not in out]
    if missing:
        out.update(mcx_data.comex_proxy_ltp(missing))
    return out


def _fetch_from_yfinance(symbols: List[str]) -> Dict[str, float]:
    """Batched yfinance last-close. MCX app symbols have no Yahoo ticker;
    they use cached MCX closes or, on cold start, COMEX×INR proxy.
    """
    if not symbols:
        return {}
    direct = [s for s in symbols if not is_commodity_symbol(s)]
    mcx_syms = [s for s in symbols if is_commodity_symbol(s)]
    result: Dict[str, float] = {}
    if direct:
        result.update(_yf_download_closes(direct, period="1d", interval="1m"))
        missing = [s for s in direct if s not in result]
        if missing:
            result.update(_yf_download_closes(missing, period="5d", interval="1d"))
    if mcx_syms:
        result.update(_fetch_mcx_fallback(mcx_syms))
    return result


def _classify_source(
    *,
    upstox_prices: Dict[str, float],
    yf_prices: Dict[str, float],
    mcx_syms: List[str],
) -> str:
    """Map the merged fetch result to a UI-facing source label."""
    if not upstox_prices and not yf_prices:
        return SOURCE_NONE
    if upstox_prices and not yf_prices:
        return SOURCE_UPSTOX
    if yf_prices and not upstox_prices:
        if mcx_syms and all(s in yf_prices for s in mcx_syms):
            from . import mcx as mcx_data

            snap = mcx_data.cached_close_ltp(mcx_syms)
            if snap and all(s in snap for s in mcx_syms):
                return SOURCE_SNAPSHOT
            if snap and any(s in snap for s in mcx_syms):
                return SOURCE_MIXED
        return SOURCE_YFINANCE
    return SOURCE_MIXED


def fetch_live_prices(symbols: List[str]) -> Dict[str, float]:
    """Return the latest live price per symbol.

    Behaviour:
        - Returns the cached dict if `symbols` matches the previous call's
          set and fewer than 30 s have elapsed.
        - Tries Upstox first for every mapped stock, index, and commodity,
          regardless of session state.
        - Uses yfinance only for unmapped symbols or quotes Upstox did not
          return, so an expired token does not remove all price coverage.
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

    yf_prices = _fetch_from_yfinance(yf_targets) if yf_targets else {}
    mcx_syms = [s for s in symbols if is_commodity_symbol(s)]

    merged: Dict[str, float] = {}
    merged.update(upstox_prices)
    for s, p in yf_prices.items():
        merged.setdefault(s, p)

    source = _classify_source(
        upstox_prices=upstox_prices,
        yf_prices=yf_prices,
        mcx_syms=mcx_syms,
    )

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

    One of: "upstox" | "yfinance" | "snapshot" | "mixed" | "none".
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
