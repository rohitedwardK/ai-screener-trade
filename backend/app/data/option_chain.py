"""Index option-chain fetcher with NSE primary + yfinance fallback.

NSE's `option-chain-indices` endpoint is unofficial and bot-detected; we use
a `requests.Session()` that warms cookies on the NSE landing page first, sets
realistic browser headers, and caches every response for `_CACHE_TTL` seconds
to avoid hammering the upstream.

If NSE returns a non-200 / empty payload (rate-limited, blocked, network
issue), we fall back to `yfinance.Ticker(symbol).option_chain(expiry)` which
has spotty Indian-index coverage but is at least available offline-friendly.

Returned shape is normalised to a single dict regardless of source so
analysis code can stay agnostic.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import yfinance as yf

log = logging.getLogger(__name__)


# Cache window for raw upstream payloads (seconds). Option chain refreshes
# every minute on NSE so 60s is generous.
_CACHE_TTL = 60.0
_cache_lock = threading.Lock()
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


_NSE_BASE = "https://www.nseindia.com"
_NSE_OPTION_CHAIN_URL = f"{_NSE_BASE}/api/option-chain-indices?symbol={{}}"
_NSE_HOMEPAGE = f"{_NSE_BASE}/option-chain"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/option-chain",
    "Connection": "keep-alive",
}


# Thread-local NSE session reused across calls (cookie persistence).
_session_lock = threading.Lock()
_session: Optional[requests.Session] = None
_session_warmed_at: float = 0.0
_SESSION_TTL = 600.0  # re-warm cookies every 10 minutes


def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_BROWSER_HEADERS)
    return s


def _ensure_session() -> requests.Session:
    """Create a session (lazily), refresh cookies if stale."""
    global _session, _session_warmed_at
    with _session_lock:
        now = time.monotonic()
        if _session is None or (now - _session_warmed_at) > _SESSION_TTL:
            sess = _build_session()
            try:
                # Two warm-up hops: home page sets cookies, then the
                # option-chain page sets the per-page bot-detection cookies.
                sess.get(_NSE_BASE, timeout=10)
                sess.get(_NSE_HOMEPAGE, timeout=10)
                _session = sess
                _session_warmed_at = now
            except Exception:  # noqa: BLE001
                log.warning("NSE session warm-up failed", exc_info=True)
                _session = sess  # use anyway; downstream will surface failure
                _session_warmed_at = now
        return _session


# ---------- Normalisation ----------

@dataclass
class OptionRow:
    strike: float
    ce_oi: Optional[float] = None
    ce_change_oi: Optional[float] = None
    ce_volume: Optional[float] = None
    ce_iv: Optional[float] = None
    ce_ltp: Optional[float] = None
    ce_bid: Optional[float] = None
    ce_ask: Optional[float] = None
    pe_oi: Optional[float] = None
    pe_change_oi: Optional[float] = None
    pe_volume: Optional[float] = None
    pe_iv: Optional[float] = None
    pe_ltp: Optional[float] = None
    pe_bid: Optional[float] = None
    pe_ask: Optional[float] = None


@dataclass
class OptionChainPayload:
    code: str                              # NIFTY / BANKNIFTY / SENSEX
    spot: Optional[float]
    expiry: date
    expiries: List[date]
    fetched_at: datetime
    source: str                            # nse | yfinance
    rows: List[OptionRow]


def _parse_expiry(s: str) -> Optional[date]:
    """NSE returns expiry as 'DD-Mon-YYYY' (e.g. '02-May-2026')."""
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _normalise_nse(raw: Dict[str, Any], expiry: date) -> OptionChainPayload:
    records = (raw.get("records") or {})
    spot = records.get("underlyingValue")
    expiries: List[date] = []
    for s in (records.get("expiryDates") or []):
        d = _parse_expiry(s)
        if d is not None:
            expiries.append(d)

    rows: List[OptionRow] = []
    for entry in (records.get("data") or []):
        e_exp = _parse_expiry(entry.get("expiryDate") or "")
        if e_exp != expiry:
            continue
        strike = entry.get("strikePrice")
        if strike is None:
            continue
        ce = entry.get("CE") or {}
        pe = entry.get("PE") or {}
        rows.append(OptionRow(
            strike=float(strike),
            ce_oi=_f(ce.get("openInterest")),
            ce_change_oi=_f(ce.get("changeinOpenInterest")),
            ce_volume=_f(ce.get("totalTradedVolume")),
            ce_iv=_f(ce.get("impliedVolatility")),
            ce_ltp=_f(ce.get("lastPrice")),
            ce_bid=_f(ce.get("bidprice")),
            ce_ask=_f(ce.get("askPrice")),
            pe_oi=_f(pe.get("openInterest")),
            pe_change_oi=_f(pe.get("changeinOpenInterest")),
            pe_volume=_f(pe.get("totalTradedVolume")),
            pe_iv=_f(pe.get("impliedVolatility")),
            pe_ltp=_f(pe.get("lastPrice")),
            pe_bid=_f(pe.get("bidprice")),
            pe_ask=_f(pe.get("askPrice")),
        ))
    rows.sort(key=lambda r: r.strike)
    return OptionChainPayload(
        code=raw.get("filtered", {}).get("CE", [{}])[0].get("underlying", "NIFTY") if rows else "NIFTY",
        spot=_f(spot),
        expiry=expiry,
        expiries=expiries,
        fetched_at=datetime.utcnow(),
        source="nse",
        rows=rows,
    )


def _f(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ---------- NSE fetch ----------

def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        ts, payload = hit
        if (time.monotonic() - ts) > _CACHE_TTL:
            return None
        return payload


def _cache_put(key: str, payload: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), payload)


def fetch_nse_option_chain(code: str) -> Optional[Dict[str, Any]]:
    """Raw JSON from NSE for one underlying (NIFTY / BANKNIFTY / FINNIFTY).

    Returns None on any failure so the caller can fall back."""
    code = code.upper()
    cached = _cache_get(f"nse:{code}")
    if cached is not None:
        return cached

    sess = _ensure_session()
    url = _NSE_OPTION_CHAIN_URL.format(code)
    try:
        r = sess.get(url, timeout=15)
        if r.status_code != 200:
            log.info("NSE option-chain non-200 for %s: %s", code, r.status_code)
            return None
        payload = r.json()
        if not payload or "records" not in payload:
            return None
        _cache_put(f"nse:{code}", payload)
        return payload
    except Exception:  # noqa: BLE001
        log.warning("NSE option-chain fetch failed for %s", code, exc_info=True)
        return None


# ---------- yfinance fallback ----------

def _yf_chain(symbol: str) -> Optional[OptionChainPayload]:
    """Best-effort yfinance fallback. Indian index option chain coverage is partial."""
    try:
        t = yf.Ticker(symbol)
        expiries_raw = list(t.options or [])
        if not expiries_raw:
            return None
        expiries = [_parse_expiry(e) for e in expiries_raw]
        expiries = [e for e in expiries if e is not None]
        if not expiries:
            return None
        nearest = min(expiries)
        chain = t.option_chain(nearest.isoformat())
        calls = chain.calls if chain is not None else pd.DataFrame()
        puts = chain.puts if chain is not None else pd.DataFrame()
        if (calls is None or calls.empty) and (puts is None or puts.empty):
            return None
        spot: Optional[float] = None
        try:
            info = t.fast_info if hasattr(t, "fast_info") else {}
            spot = float(getattr(info, "last_price", None) or info.get("lastPrice", None) or 0.0) or None
        except Exception:  # noqa: BLE001
            spot = None

        strikes = sorted({float(s) for s in (list(calls["strike"]) + list(puts["strike"]))})
        rows: List[OptionRow] = []
        ce_idx = calls.set_index("strike") if not calls.empty else pd.DataFrame()
        pe_idx = puts.set_index("strike") if not puts.empty else pd.DataFrame()

        for strike in strikes:
            ce = ce_idx.loc[strike] if (not ce_idx.empty and strike in ce_idx.index) else None
            pe = pe_idx.loc[strike] if (not pe_idx.empty and strike in pe_idx.index) else None
            rows.append(OptionRow(
                strike=float(strike),
                ce_oi=_f(getattr(ce, "openInterest", None)) if ce is not None else None,
                ce_volume=_f(getattr(ce, "volume", None)) if ce is not None else None,
                ce_iv=_f(getattr(ce, "impliedVolatility", None)) if ce is not None else None,
                ce_ltp=_f(getattr(ce, "lastPrice", None)) if ce is not None else None,
                pe_oi=_f(getattr(pe, "openInterest", None)) if pe is not None else None,
                pe_volume=_f(getattr(pe, "volume", None)) if pe is not None else None,
                pe_iv=_f(getattr(pe, "impliedVolatility", None)) if pe is not None else None,
                pe_ltp=_f(getattr(pe, "lastPrice", None)) if pe is not None else None,
            ))
        return OptionChainPayload(
            code=symbol,
            spot=spot,
            expiry=nearest,
            expiries=expiries,
            fetched_at=datetime.utcnow(),
            source="yfinance",
            rows=rows,
        )
    except Exception:  # noqa: BLE001
        log.warning("yfinance option-chain fallback failed for %s", symbol, exc_info=True)
        return None


# ---------- Public API ----------

def fetch_option_chain(
    code: str,
    underlying_yf_symbol: str,
    *,
    expiry: Optional[date] = None,
) -> Optional[OptionChainPayload]:
    """Return a normalised option-chain payload or None on hard failure.

    Source order (each falls through on `None`):
      1. Upstox v2 — best quality (bid/ask, IV via Greeks, per-leg
         instrument_keys reusable by the live verifier). Requires an active
         `UPSTOX_ACCESS_TOKEN`.
      2. NSE public endpoint — covers NIFTY / BANKNIFTY / FINNIFTY.
      3. yfinance — partial coverage for Indian indices but always reachable.

    The caller must handle `None` (signal generation still works without
    a chain — it just won't be biased by put/call OI).
    """
    code = code.upper()

    # Lazy import to avoid a hard dependency cycle when Upstox is disabled
    # (upstox_options imports from this module to share OptionRow / _f).
    try:
        from . import upstox_options as upstox_oc  # noqa: WPS433 - intentional local import
    except ImportError:
        upstox_oc = None

    if upstox_oc is not None and code in {"NIFTY", "BANKNIFTY", "SENSEX"}:
        target = expiry
        if target is None:
            # Fallback: ask Upstox for the contract list. Empty => let the
            # NSE/yfinance branches below derive an expiry from their own
            # payload.
            ups_expiries = upstox_oc.list_upstox_expiries(code)
            target = min(ups_expiries) if ups_expiries else None
        if target is not None:
            ups_result = upstox_oc.fetch_upstox_option_chain(code, target)
            if ups_result is not None:
                payload, _keys = ups_result
                return payload

    if code in {"NIFTY", "BANKNIFTY", "FINNIFTY"}:
        raw = fetch_nse_option_chain(code)
        if raw is not None:
            records = raw.get("records") or {}
            expiries = [_parse_expiry(e) for e in (records.get("expiryDates") or [])]
            expiries = [e for e in expiries if e is not None]
            if not expiries:
                return None
            target = expiry or min(expiries)
            return _normalise_nse(raw, target)

    return _yf_chain(underlying_yf_symbol)


def list_expiries(code: str, underlying_yf_symbol: str) -> List[date]:
    p = fetch_option_chain(code, underlying_yf_symbol)
    if p is None:
        return []
    return list(p.expiries)
