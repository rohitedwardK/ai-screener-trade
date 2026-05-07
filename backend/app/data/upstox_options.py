"""Upstox v2 option-chain client.

Mirrors the surface of `data/option_chain.py` so the call site is a one-line
swap. Endpoint:

    GET /v2/option/chain
        ?instrument_key=NSE_INDEX|Nifty 50
        &expiry_date=YYYY-MM-DD

Returns per-strike CE/PE OI, IV, LTP, bid, ask, plus the per-leg
`instrument_key` we need later to fetch live LTPs cheaply.

Hard rule: this client is read-only — no order placement, no broker side
effects. We share the dead-token latch and pacing knobs from
`data/upstox_client.py` so a 401 here also stops the equity quotes loop
from hammering Upstox.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import get_settings
from .option_chain import OptionChainPayload, OptionRow, _f
from .upstox_client import (
    NIFTY50_INSTRUMENT_KEYS,
    _is_token_dead,
    _mark_token_dead,
    _pace,
)

log = logging.getLogger(__name__)


# Per-(code, expiry) cache so two consecutive picker runs in the same minute
# don't hit Upstox twice. NSE/yfinance already cache; we keep this layer
# independent so cache invalidation is per-source.
_CACHE_TTL = 60.0
_cache_lock = threading.Lock()
_cache: Dict[Tuple[str, str], Tuple[float, OptionChainPayload]] = {}


def _underlying_key(code: str) -> Optional[str]:
    """Map our short code to the Upstox underlying instrument_key.

    We reuse the index entries already present in `NIFTY50_INSTRUMENT_KEYS`
    so there is exactly one symbol map for the whole project.
    """
    if code == "NIFTY":
        return NIFTY50_INSTRUMENT_KEYS.get("^NSEI")
    if code == "BANKNIFTY":
        return NIFTY50_INSTRUMENT_KEYS.get("^NSEBANK")
    if code == "SENSEX":
        return NIFTY50_INSTRUMENT_KEYS.get("^BSESN")
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


def _normalise_upstox(
    raw: Dict[str, Any], *, code: str, expiry: date,
) -> Optional[OptionChainPayload]:
    """Turn Upstox's `data` array into our canonical OptionChainPayload.

    Upstox shape (v2 option/chain):
        {
          "status": "success",
          "data": [
            { "strike_price": 22500, "underlying_spot_price": 22510.3,
              "expiry": "2026-05-12", "pcr": 0.91,
              "call_options": { "instrument_key": "NSE_FO|...",
                                "market_data": { "ltp": ..., "bid_price": ...,
                                                 "ask_price": ..., "oi": ...,
                                                 "volume": ... },
                                "option_greeks": { "iv": ..., "delta": ... } },
              "put_options":  { ... same shape ... }
            },
            ...
          ]
        }
    """
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
    return OptionChainPayload(
        code=code,
        spot=spot,
        expiry=expiry,
        expiries=[expiry],          # Upstox call is per-expiry; caller can extend
        fetched_at=datetime.utcnow(),
        source="upstox",
        rows=rows,
    )


def _instrument_keys_by_strike(raw: Dict[str, Any]) -> Dict[float, Dict[str, str]]:
    """Map strike → {"CE": instrument_key, "PE": instrument_key}.

    Returned alongside the OptionChainPayload so the live verifier can fetch
    premium LTPs by instrument_key without re-resolving them on every tick.
    """
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


def fetch_upstox_option_chain(
    code: str, expiry: date, *, timeout_s: float = 8.0,
) -> Optional[Tuple[OptionChainPayload, Dict[float, Dict[str, str]]]]:
    """Return (payload, instrument_keys_by_strike) or None on hard failure.

    Returning a tuple is a tiny break from the parent `OptionChainPayload`
    contract — the caller (`option_chain.fetch_option_chain`) discards the
    instrument-key map for now, and the live verifier (added separately)
    looks them up via a dedicated wrapper. This keeps the canonical payload
    shape source-agnostic.
    """
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
        return cached, {}      # we don't cache the instrument-key map

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Api-Version": "2.0",
    }
    params = {
        "instrument_key": underlying_key,
        "expiry_date": expiry.isoformat(),
    }
    url = f"{settings.UPSTOX_BASE_URL.rstrip('/')}/option/chain"

    _pace()
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout_s)
    except httpx.HTTPError as e:
        log.warning("Upstox option-chain request failed: %s", e)
        return None

    if resp.status_code == 401:
        log.warning("Upstox option-chain 401 — marking token dead")
        _mark_token_dead(token)
        return None
    if resp.status_code != 200:
        log.warning(
            "Upstox option-chain returned HTTP %d: %s",
            resp.status_code, resp.text[:200],
        )
        return None
    try:
        raw = resp.json()
    except ValueError:
        log.warning("Upstox option-chain returned non-JSON body")
        return None

    payload = _normalise_upstox(raw, code=code, expiry=expiry)
    if payload is None:
        return None
    keys_by_strike = _instrument_keys_by_strike(raw)
    _cache_put(code, expiry, payload)
    return payload, keys_by_strike


def list_upstox_expiries(code: str, *, timeout_s: float = 6.0) -> List[date]:
    """Fetch upcoming expiries via the contract endpoint.

    Falls back to an empty list when Upstox is unavailable; callers should
    then derive expiries from the canonical `next_weekly_expiry` helper.
    """
    settings = get_settings()
    token = settings.UPSTOX_ACCESS_TOKEN.strip()
    if not token or _is_token_dead(token):
        return []
    underlying_key = _underlying_key(code.upper())
    if underlying_key is None:
        return []
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Api-Version": "2.0",
    }
    params = {"instrument_key": underlying_key}
    url = f"{settings.UPSTOX_BASE_URL.rstrip('/')}/option/contract"
    _pace()
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout_s)
    except httpx.HTTPError:
        return []
    if resp.status_code == 401:
        _mark_token_dead(token)
        return []
    if resp.status_code != 200:
        return []
    try:
        raw = resp.json()
    except ValueError:
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


__all__ = [
    "fetch_upstox_option_chain",
    "list_upstox_expiries",
]
