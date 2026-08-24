"""Upstox v2 option-chain client for the Live Market service.

Adapted from the parent app's `backend/app/data/upstox_options.py`. Returns
an `OptionChainPayload` with the per-leg `instrument_key` map embedded so
the engine can fetch live CE/PE LTPs by key on every tick without re-hitting
the chain endpoint.

Hard rule: read-only. No order placement.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config import get_settings
from .option_types import OptionChainPayload, OptionRow
from .upstox_client import (
    INDEX_INSTRUMENT_KEYS,
    _f,
    _is_token_dead,
    _mark_token_dead,
    _request,
)

log = logging.getLogger(__name__)


# Per-(code, expiry) memo so two consecutive picker runs in the same minute
# don't hit Upstox twice.
_CACHE_TTL = 60.0
_cache_lock = threading.Lock()
_cache: Dict[Tuple[str, str], Tuple[float, OptionChainPayload]] = {}


def _underlying_key(code: str) -> Optional[str]:
    """Map our short code to the Upstox underlying instrument_key."""
    if code == "NIFTY":
        return INDEX_INSTRUMENT_KEYS.get("^NSEI")
    if code == "BANKNIFTY":
        return INDEX_INSTRUMENT_KEYS.get("^NSEBANK")
    if code == "SENSEX":
        return INDEX_INSTRUMENT_KEYS.get("^BSESN")
    return None


def _cache_get(code: str, expiry: date) -> Optional[OptionChainPayload]:
    key = (code, expiry.isoformat())
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        ts, payload = hit
        if (time.monotonic() - ts) > _CACHE_TTL:
            return None
        return payload


def _cache_put(code: str, expiry: date, payload: OptionChainPayload) -> None:
    key = (code, expiry.isoformat())
    with _cache_lock:
        _cache[key] = (time.monotonic(), payload)


def _instrument_keys_by_strike(raw: Dict[str, Any]) -> Dict[float, Dict[str, str]]:
    out: Dict[float, Dict[str, str]] = {}
    for entry in raw.get("data") or []:
        strike = entry.get("strike_price")
        if strike is None:
            continue
        ce = (entry.get("call_options") or {}).get("instrument_key")
        pe = (entry.get("put_options") or {}).get("instrument_key")
        leg: Dict[str, str] = {}
        if isinstance(ce, str) and ce:
            leg["CE"] = ce
        if isinstance(pe, str) and pe:
            leg["PE"] = pe
        if leg:
            out[float(strike)] = leg
    return out


def _normalise(raw: Dict[str, Any], *, code: str, expiry: date) -> Optional[OptionChainPayload]:
    data = raw.get("data") or []
    if not data:
        return None

    rows: List[OptionRow] = []
    spot: Optional[float] = None
    for entry in data:
        try:
            strike = entry.get("strike_price")
            if strike is None:
                continue
            if spot is None:
                spot = _f(entry.get("underlying_spot_price"))
            ce = entry.get("call_options") or {}
            pe = entry.get("put_options") or {}
            ce_md = ce.get("market_data") or {}
            pe_md = pe.get("market_data") or {}
            ce_g = ce.get("option_greeks") or {}
            pe_g = pe.get("option_greeks") or {}
            rows.append(OptionRow(
                strike=float(strike),
                ce_oi=_f(ce_md.get("oi")),
                ce_change_oi=_f(ce_md.get("oi_change")),
                ce_volume=_f(ce_md.get("volume")),
                ce_iv=_f(ce_g.get("iv")),
                ce_ltp=_f(ce_md.get("ltp")),
                ce_bid=_f(ce_md.get("bid_price")),
                ce_ask=_f(ce_md.get("ask_price")),
                pe_oi=_f(pe_md.get("oi")),
                pe_change_oi=_f(pe_md.get("oi_change")),
                pe_volume=_f(pe_md.get("volume")),
                pe_iv=_f(pe_g.get("iv")),
                pe_ltp=_f(pe_md.get("ltp")),
                pe_bid=_f(pe_md.get("bid_price")),
                pe_ask=_f(pe_md.get("ask_price")),
            ))
        except Exception:  # noqa: BLE001 - one bad entry must not drop the chain
            log.debug("upstox: skipped malformed strike row", exc_info=True)
            continue
    if not rows:
        return None
    rows.sort(key=lambda r: r.strike)
    keys_by_strike = _instrument_keys_by_strike(raw)
    return OptionChainPayload(
        code=code,
        spot=spot,
        expiry=expiry,
        expiries=[expiry],
        fetched_at=datetime.utcnow(),
        source="upstox",
        rows=rows,
        instrument_keys_by_strike=keys_by_strike,
    )


def fetch_option_chain(
    code: str, expiry: date, *, timeout_s: float = 8.0,
) -> Optional[OptionChainPayload]:
    """Fetch one expiry's option chain. None on token failure / network error."""
    code = code.upper()
    settings = get_settings()
    token = settings.UPSTOX_ACCESS_TOKEN.strip()
    if not token or _is_token_dead(token):
        return None
    underlying_key = _underlying_key(code)
    if underlying_key is None:
        return None

    cached = _cache_get(code, expiry)
    if cached is not None:
        return cached

    url = f"{settings.UPSTOX_BASE_URL.rstrip('/')}/option/chain"
    raw = _request(
        token, url,
        params={"instrument_key": underlying_key, "expiry_date": expiry.isoformat()},
        timeout_s=timeout_s,
    )
    if not raw:
        return None
    payload = _normalise(raw, code=code, expiry=expiry)
    if payload is None:
        return None
    _cache_put(code, expiry, payload)
    return payload


def list_expiries(code: str, *, timeout_s: float = 6.0) -> List[date]:
    """Fetch upcoming expiries via the contract endpoint."""
    settings = get_settings()
    token = settings.UPSTOX_ACCESS_TOKEN.strip()
    if not token or _is_token_dead(token):
        return []
    underlying_key = _underlying_key(code.upper())
    if underlying_key is None:
        return []

    url = f"{settings.UPSTOX_BASE_URL.rstrip('/')}/option/contract"
    raw = _request(
        token, url,
        params={"instrument_key": underlying_key},
        timeout_s=timeout_s,
    )
    if not raw:
        return []
    expiries: set[date] = set()
    for entry in raw.get("data") or []:
        exp = entry.get("expiry")
        if not isinstance(exp, str):
            continue
        try:
            expiries.add(datetime.strptime(exp, "%Y-%m-%d").date())
        except ValueError:
            continue
    return sorted(expiries)


__all__ = ["fetch_option_chain", "list_expiries"]
