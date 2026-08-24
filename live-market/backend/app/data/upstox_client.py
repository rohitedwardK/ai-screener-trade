"""Upstox v2 REST client (read-only) for the Live Market service.

Adapted from the parent app's `backend/app/data/upstox_client.py` so this
service has zero cross-imports. Same daily-token semantics: a 401 latches
the token as dead until the operator rotates `UPSTOX_ACCESS_TOKEN`.

Hard rule: this client is read-only. No order placement, no broker side
effects. Ever.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


# Spot-index instrument keys. Equities aren't used by the Live Market
# service (indices-only by design) so we keep this map deliberately tiny.
INDEX_INSTRUMENT_KEYS: Dict[str, str] = {
    "^NSEI":    "NSE_INDEX|Nifty 50",
    "^NSEBANK": "NSE_INDEX|Nifty Bank",
    "^BSESN":   "BSE_INDEX|SENSEX",
}


@dataclass(frozen=True)
class UpstoxQuote:
    """One symbol's snapshot from Upstox `quotes` endpoint."""
    symbol: str
    last_price: float
    open: float
    high: float
    low: float
    close_prev: float
    volume: int
    timestamp_ms: int


def instrument_key_for(symbol: str) -> Optional[str]:
    return INDEX_INSTRUMENT_KEYS.get(symbol)


def resolve_keys(symbols: Iterable[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for sym in symbols:
        k = instrument_key_for(sym)
        if k:
            out[sym] = k
    return out


# Pacing - Upstox free tier is ~25 req/s. A 100ms floor keeps us well clear.
_MIN_INTERVAL_S = 0.10
_pace_lock = threading.Lock()
_last_call_at: float = 0.0


def _pace() -> None:
    global _last_call_at
    with _pace_lock:
        now = time.monotonic()
        wait = (_last_call_at + _MIN_INTERVAL_S) - now
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


# Token-expiry latch: once we see a 401 we stop hammering the API until
# the operator rotates the env var.
_token_lock = threading.Lock()
_dead_token: str = ""


def _mark_token_dead(token: str) -> None:
    global _dead_token
    with _token_lock:
        _dead_token = token


def _is_token_dead(token: str) -> bool:
    with _token_lock:
        return bool(_dead_token) and _dead_token == token


def reset_token_state() -> None:
    """Test hook / operator helper: clear the dead-token latch."""
    global _dead_token
    with _token_lock:
        _dead_token = ""


def is_configured() -> bool:
    return bool(get_settings().UPSTOX_ACCESS_TOKEN.strip())


def _parse_timestamp_ms(raw_q: dict) -> int:
    raw_ltt = raw_q.get("last_trade_time")
    if isinstance(raw_ltt, (int, float)):
        return int(raw_ltt)
    if isinstance(raw_ltt, str) and raw_ltt.strip().isdigit():
        return int(raw_ltt.strip())
    raw_ts = raw_q.get("timestamp")
    if isinstance(raw_ts, str) and raw_ts.strip():
        try:
            return int(datetime.fromisoformat(raw_ts).timestamp() * 1000)
        except ValueError:
            pass
    return 0


def _f(v: object) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _i(v: object) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _parse_quote(sym: str, raw_q: dict) -> Optional[UpstoxQuote]:
    try:
        last_price = float(raw_q.get("last_price") or 0.0)
    except (TypeError, ValueError):
        return None
    if last_price <= 0:
        return None
    ohlc = raw_q.get("ohlc") or {}
    return UpstoxQuote(
        symbol=sym,
        last_price=last_price,
        open=_f(ohlc.get("open")),
        high=_f(ohlc.get("high")),
        low=_f(ohlc.get("low")),
        close_prev=_f(ohlc.get("close")),
        volume=_i(raw_q.get("volume")),
        timestamp_ms=_parse_timestamp_ms(raw_q),
    )


def _request(
    token: str,
    url: str,
    *,
    params: dict,
    timeout_s: float,
) -> Optional[dict]:
    """One HTTP GET. Centralised so all token-401 handling is in one place."""
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Api-Version": "2.0",
    }
    _pace()
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout_s)
    except httpx.HTTPError as e:
        log.warning("Upstox request failed (%s): %s", url, e)
        return None

    if resp.status_code == 401:
        log.warning(
            "Upstox 401 at %s - token expired/invalid. Rotate UPSTOX_ACCESS_TOKEN.",
            url,
        )
        _mark_token_dead(token)
        return None
    if resp.status_code != 200:
        log.warning("Upstox HTTP %d at %s: %s", resp.status_code, url, resp.text[:200])
        return None
    try:
        return resp.json()
    except ValueError:
        log.warning("Upstox non-JSON body from %s", url)
        return None


def _quotes_from_payload(
    payload: dict,
    sym_by_key: Dict[str, str],
) -> Dict[str, UpstoxQuote]:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return {}
    result: Dict[str, UpstoxQuote] = {}
    for raw_key, raw_q in data.items():
        if not isinstance(raw_q, dict):
            continue
        # Upstox sometimes echoes the key as `instrument_token` rather than
        # the original `NSE_EQ|...` we sent. Try both lookups.
        key = raw_q.get("instrument_token") or raw_key
        sym = sym_by_key.get(key) or sym_by_key.get(raw_key)
        if not sym:
            continue
        quote = _parse_quote(sym, raw_q)
        if quote is not None:
            result[sym] = quote
    return result


def fetch_quotes_batch(
    symbols: List[str],
    *,
    timeout_s: float = 8.0,
) -> Dict[str, UpstoxQuote]:
    """Fetch full OHLC + LTP + volume quotes for a list of symbols."""
    if not symbols:
        return {}
    settings = get_settings()
    token = settings.UPSTOX_ACCESS_TOKEN.strip()
    if not token or _is_token_dead(token):
        return {}

    keys_by_symbol = resolve_keys(symbols)
    if not keys_by_symbol:
        return {}

    url = f"{settings.UPSTOX_BASE_URL.rstrip('/')}/market-quote/quotes"
    payload = _request(
        token, url,
        params={"instrument_key": ",".join(keys_by_symbol.values())},
        timeout_s=timeout_s,
    )
    if not payload:
        return {}
    sym_by_key = {k: s for s, k in keys_by_symbol.items()}
    return _quotes_from_payload(payload, sym_by_key)


def fetch_ltp_batch(symbols: List[str], *, timeout_s: float = 6.0) -> Dict[str, float]:
    quotes = fetch_quotes_batch(symbols, timeout_s=timeout_s)
    return {s: q.last_price for s, q in quotes.items()}


def fetch_quotes_by_instrument_keys(
    instrument_keys: List[str],
    *,
    timeout_s: float = 8.0,
) -> Dict[str, float]:
    """LTP fetch keyed by raw Upstox instrument keys.

    Used for `NSE_FO|...` option keys that have no yfinance equivalent and
    therefore aren't in `INDEX_INSTRUMENT_KEYS`. Returns {instrument_key:
    last_price}.
    """
    if not instrument_keys:
        return {}
    settings = get_settings()
    token = settings.UPSTOX_ACCESS_TOKEN.strip()
    if not token or _is_token_dead(token):
        return {}

    url = f"{settings.UPSTOX_BASE_URL.rstrip('/')}/market-quote/quotes"
    payload = _request(
        token, url,
        params={"instrument_key": ",".join(instrument_keys)},
        timeout_s=timeout_s,
    )
    if not payload:
        return {}
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, float] = {}
    for raw_key, raw_q in data.items():
        if not isinstance(raw_q, dict):
            continue
        key = raw_q.get("instrument_token") or raw_key
        try:
            ltp = float(raw_q.get("last_price") or 0.0)
        except (TypeError, ValueError):
            continue
        if ltp > 0:
            out[str(key)] = ltp
    return out


__all__ = [
    "INDEX_INSTRUMENT_KEYS",
    "UpstoxQuote",
    "instrument_key_for",
    "resolve_keys",
    "is_configured",
    "fetch_quotes_batch",
    "fetch_ltp_batch",
    "fetch_quotes_by_instrument_keys",
    "reset_token_state",
    "_f",  # exported for upstox_options + intraday clients
    "_i",
    "_request",
    "_is_token_dead",
    "_mark_token_dead",
]
