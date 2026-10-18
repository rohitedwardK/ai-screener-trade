"""Upstox v2 REST client for the Live Analysis Mode.

Wraps Upstox v2 Market Quote endpoints behind a small typed surface. Pure HTTP
layer with no business logic. The Live Analysis engine consumes this client.

Authentication
--------------
Upstox issues an OAuth access token that expires daily around 03:30 IST. The
operator places the token in `UPSTOX_ACCESS_TOKEN`. When the token is missing
or expired (HTTP 401), `fetch_quotes_batch` returns an empty dict and the
caller falls back to yfinance (which is ~15 min delayed). The engine still
runs - it just degrades gracefully.

Symbol mapping
--------------
Upstox identifies instruments by an ISIN-based key like `NSE_EQ|INE002A01018`,
not by the yfinance `RELIANCE.NS` ticker. The Nifty 50 ISINs are stable so
they are hardcoded here. For symbols outside the Nifty 50 the caller should
provide its own mapping.

Hard rule: this client is read-only - no order placement, no broker side
effects. Live Analysis Mode is simulation/analysis only.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Symbol -> instrument_key mapping (Nifty 50, ISIN-based, NSE equity segment).
#
# These ISINs were pulled from the official NSE listing and Upstox instrument
# master. They change only when a constituent is replaced in the index, which
# happens semi-annually at most. Update alongside `core/universe.py`.
# ---------------------------------------------------------------------------
NIFTY50_INSTRUMENT_KEYS: Dict[str, str] = {
    "RELIANCE.NS":   "NSE_EQ|INE002A01018",
    "TCS.NS":        "NSE_EQ|INE467B01029",
    "HDFCBANK.NS":   "NSE_EQ|INE040A01034",
    "INFY.NS":       "NSE_EQ|INE009A01021",
    "ICICIBANK.NS":  "NSE_EQ|INE090A01021",
    "HINDUNILVR.NS": "NSE_EQ|INE030A01027",
    "ITC.NS":        "NSE_EQ|INE154A01025",
    "SBIN.NS":       "NSE_EQ|INE062A01020",
    "BHARTIARTL.NS": "NSE_EQ|INE397D01024",
    "LT.NS":         "NSE_EQ|INE018A01030",
    "KOTAKBANK.NS":  "NSE_EQ|INE237A01028",
    "AXISBANK.NS":   "NSE_EQ|INE238A01034",
    "MARUTI.NS":     "NSE_EQ|INE585B01010",
    "ASIANPAINT.NS": "NSE_EQ|INE021A01026",
    "HCLTECH.NS":    "NSE_EQ|INE860A01027",
    "BAJFINANCE.NS": "NSE_EQ|INE296A01024",
    "SUNPHARMA.NS":  "NSE_EQ|INE044A01036",
    "TITAN.NS":      "NSE_EQ|INE280A01028",
    "M&M.NS":        "NSE_EQ|INE101A01026",
    "ULTRACEMCO.NS": "NSE_EQ|INE481G01011",
    "NTPC.NS":       "NSE_EQ|INE733E01010",
    "NESTLEIND.NS":  "NSE_EQ|INE239A01024",
    "POWERGRID.NS":  "NSE_EQ|INE752E01010",
    "TMPV.NS":       "NSE_EQ|INE155A01022",
    "WIPRO.NS":      "NSE_EQ|INE075A01022",
    "BAJAJFINSV.NS": "NSE_EQ|INE918I01026",
    "ONGC.NS":       "NSE_EQ|INE213A01029",
    "ADANIENT.NS":   "NSE_EQ|INE423A01024",
    "JSWSTEEL.NS":   "NSE_EQ|INE019A01038",
    "COALINDIA.NS":  "NSE_EQ|INE522F01014",
    "TATASTEEL.NS":  "NSE_EQ|INE081A01020",
    "HINDALCO.NS":   "NSE_EQ|INE038A01020",
    "GRASIM.NS":     "NSE_EQ|INE047A01021",
    "ADANIPORTS.NS": "NSE_EQ|INE742F01042",
    "BAJAJ-AUTO.NS": "NSE_EQ|INE917I01010",
    "INDUSINDBK.NS": "NSE_EQ|INE095A01012",
    "DRREDDY.NS":    "NSE_EQ|INE089A01031",
    "EICHERMOT.NS":  "NSE_EQ|INE066A01021",
    "CIPLA.NS":      "NSE_EQ|INE059A01026",
    "BRITANNIA.NS":  "NSE_EQ|INE216A01030",
    "HEROMOTOCO.NS": "NSE_EQ|INE158A01026",
    "APOLLOHOSP.NS": "NSE_EQ|INE437A01024",
    "DIVISLAB.NS":   "NSE_EQ|INE361B01024",
    "TECHM.NS":      "NSE_EQ|INE669C01036",
    "TATACONSUM.NS": "NSE_EQ|INE192A01025",
    "SBILIFE.NS":    "NSE_EQ|INE123W01016",
    "HDFCLIFE.NS":   "NSE_EQ|INE795G01014",
    "BPCL.NS":       "NSE_EQ|INE029A01011",
    "LTM.NS":        "NSE_EQ|INE214T01019",
    "SHRIRAMFIN.NS": "NSE_EQ|INE721A01013",
    # Spot indices (regime classifier + paper-index bot underlying).
    "^NSEI":         "NSE_INDEX|Nifty 50",
    "^NSEBANK":      "NSE_INDEX|Nifty Bank",
    "^BSESN":        "BSE_INDEX|SENSEX",
}


@dataclass(frozen=True)
class UpstoxQuote:
    """One symbol's snapshot from Upstox `quotes` endpoint."""
    symbol: str
    last_price: float
    open: float
    high: float
    low: float
    close_prev: float          # previous day's close
    volume: int                # cumulative volume since session open
    timestamp_ms: int          # exchange timestamp in epoch ms


# ---------------------------------------------------------------------------
# Instrument-key resolution
# ---------------------------------------------------------------------------
def instrument_key_for(symbol: str) -> Optional[str]:
    """Return the Upstox instrument key for a yfinance-style symbol.

    Returns None when the symbol is not in our hardcoded map and is not a
    resolvable MCX gold/silver front-month. Callers should treat None as
    "no Upstox data for this symbol" and fall back to yfinance.
    """
    key = NIFTY50_INSTRUMENT_KEYS.get(symbol)
    if key:
        return key
    from . import mcx as mcx_data

    return mcx_data.instrument_key_for(symbol)


def resolve_keys(symbols: Iterable[str]) -> Dict[str, str]:
    """Build a {symbol: instrument_key} dict, dropping unmapped symbols."""
    out: Dict[str, str] = {}
    for sym in symbols:
        k = instrument_key_for(sym)
        if k:
            out[sym] = k
    return out


# ---------------------------------------------------------------------------
# Pacing (mirrors yf_client.pace; Upstox limits at ~25 req/s on free tier).
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Token-expiry latch: once we see a 401, mark token dead until the operator
# rotates the env var. Avoids hammering Upstox with bad-auth calls every tick.
# ---------------------------------------------------------------------------
_token_lock = threading.Lock()
_dead_token: str = ""    # the token value we last saw rejected; "" means none


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def is_configured() -> bool:
    """True when an Upstox access token is present in settings."""
    settings = get_settings()
    return bool(settings.UPSTOX_ACCESS_TOKEN.strip())


def _parse_timestamp_ms(raw_q: dict) -> int:
    """Best-effort epoch-ms extractor.

    Upstox returns `last_trade_time` as an epoch-ms numeric string and
    `timestamp` as an ISO-8601 string with TZ. Either may be missing for
    indices or after-hours rows; we never want a malformed timestamp to
    drop the whole quote, so we degrade to 0.
    """
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


def _parse_quote(sym: str, raw_q: dict) -> Optional[UpstoxQuote]:
    """Build an `UpstoxQuote` from one row of the Upstox `data` payload.

    Returns None when the row has no usable LTP. Other fields degrade to 0
    individually so a single missing OHLC field never silently drops the row.
    """
    try:
        last_price = float(raw_q.get("last_price") or 0.0)
    except (TypeError, ValueError):
        return None
    if last_price <= 0:
        return None

    ohlc = raw_q.get("ohlc") or {}

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


def _request_quotes(
    token: str,
    instrument_keys: List[str],
    *,
    timeout_s: float,
) -> Optional[dict]:
    """One HTTP call to Upstox `quotes`. Returns parsed JSON or None on any error.

    Side-effect: marks `token` dead on a 401 so later ticks short-circuit
    until the env var is rotated.
    """
    settings = get_settings()
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Api-Version": "2.0",
    }
    params = {"instrument_key": ",".join(instrument_keys)}
    url = f"{settings.UPSTOX_BASE_URL.rstrip('/')}/market-quote/quotes"

    _pace()
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout_s)
    except httpx.HTTPError as e:
        log.warning("Upstox quotes request failed: %s", e)
        return None

    if resp.status_code == 401:
        log.warning(
            "Upstox returned 401 - access token expired or invalid. "
            "Refresh UPSTOX_ACCESS_TOKEN. Falling back to yfinance."
        )
        _mark_token_dead(token)
        return None
    if resp.status_code != 200:
        log.warning(
            "Upstox quotes returned HTTP %d: %s",
            resp.status_code, resp.text[:200],
        )
        return None

    try:
        return resp.json()
    except ValueError:
        log.warning("Upstox quotes returned non-JSON body")
        return None


def _normalise_instrument_key(key: object) -> str:
    return str(key or "").replace(":", "|").strip()


def _symbol_for_quote(
    raw_key: object,
    raw_q: dict,
    sym_by_key: Dict[str, str],
) -> Optional[str]:
    """Match an Upstox quote row back to our requested symbol.

    MCX payloads often echo `MCX_FO:563946`, a bare token, or
    `instrument_key` instead of the `MCX_FO|563946` we sent.
    """
    candidates = [
        raw_q.get("instrument_key"),
        raw_q.get("instrument_token"),
        raw_key,
    ]
    tails = {
        _normalise_instrument_key(k).rsplit("|", 1)[-1]: s
        for k, s in sym_by_key.items()
    }
    for c in candidates:
        if not c:
            continue
        s = str(c)
        if s in sym_by_key:
            return sym_by_key[s]
        n = _normalise_instrument_key(s)
        if n in sym_by_key:
            return sym_by_key[n]
        tail = n.rsplit("|", 1)[-1]
        if tail in tails:
            return tails[tail]
    return None


def _quotes_from_payload(
    payload: dict,
    sym_by_key: Dict[str, str],
) -> Dict[str, UpstoxQuote]:
    """Project the raw `data` map onto our `UpstoxQuote` dataclasses."""
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return {}
    result: Dict[str, UpstoxQuote] = {}
    for raw_key, raw_q in data.items():
        if not isinstance(raw_q, dict):
            continue
        sym = _symbol_for_quote(raw_key, raw_q, sym_by_key)
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
    """Fetch full quotes for a batch of symbols.

    Returns a dict keyed by yfinance symbol. Symbols missing from the
    instrument-key map, or that Upstox didn't return, are silently omitted -
    callers should treat absence as "no data, fall back".

    On 401 (token expired/invalid) returns {} and latches the token as dead so
    later ticks short-circuit until the env var is rotated.
    """
    if not symbols:
        return {}
    token = get_settings().UPSTOX_ACCESS_TOKEN.strip()
    if not token or _is_token_dead(token):
        return {}

    keys_by_symbol = resolve_keys(symbols)
    if not keys_by_symbol:
        return {}

    payload = _request_quotes(token, list(keys_by_symbol.values()), timeout_s=timeout_s)
    if not payload:
        return {}
    sym_by_key = {k: s for s, k in keys_by_symbol.items()}
    return _quotes_from_payload(payload, sym_by_key)


def fetch_ltp_batch(symbols: List[str], *, timeout_s: float = 6.0) -> Dict[str, float]:
    """Lighter-weight LTP-only fetch. Useful for the regime tick.

    Returns {symbol: last_price}. Empty dict on auth failure / network error.
    """
    quotes = fetch_quotes_batch(symbols, timeout_s=timeout_s)
    return {s: q.last_price for s, q in quotes.items()}


def fetch_quotes_by_instrument_keys(
    instrument_keys: List[str],
    *,
    timeout_s: float = 8.0,
) -> Dict[str, float]:
    """LTP fetch keyed by raw Upstox instrument keys.

    Used by the live strike verifier for `NSE_FO|...` option keys that have no
    yfinance equivalent and therefore aren't in `NIFTY50_INSTRUMENT_KEYS`.
    Returns {instrument_key: last_price}.
    """
    if not instrument_keys:
        return {}
    token = get_settings().UPSTOX_ACCESS_TOKEN.strip()
    if not token or _is_token_dead(token):
        return {}
    payload = _request_quotes(token, instrument_keys, timeout_s=timeout_s)
    if not payload:
        return {}
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, float] = {}
    for raw_key, raw_q in data.items():
        if not isinstance(raw_q, dict):
            continue
        # Upstox echoes either the original key or an `instrument_token` form.
        # We don't try to remap; just emit whatever key the caller can match.
        key = raw_q.get("instrument_token") or raw_key
        try:
            ltp = float(raw_q.get("last_price") or 0.0)
        except (TypeError, ValueError):
            continue
        if ltp > 0:
            out[str(key)] = ltp
    return out


def fetch_historical_candles(
    instrument_key: str,
    *,
    start: datetime | date,
    end: datetime | date,
    interval: str = "day",
    timeout_s: float = 20.0,
) -> List[list]:
    """OHLC candles from Upstox History API. Empty list on any failure.

    Day bars are capped by Upstox at about one year. Read-only.
    """
    token = get_settings().UPSTOX_ACCESS_TOKEN.strip()
    if not token or _is_token_dead(token):
        return []

    def _ymd(d: datetime | date) -> str:
        if isinstance(d, datetime):
            return d.date().isoformat()
        return d.isoformat()

    from urllib.parse import quote

    settings = get_settings()
    key_enc = quote(instrument_key, safe="")
    url = (
        f"{settings.UPSTOX_BASE_URL.rstrip('/')}/historical-candle/"
        f"{key_enc}/{interval}/{_ymd(end)}/{_ymd(start)}"
    )
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Api-Version": "2.0",
    }
    _pace()
    try:
        resp = httpx.get(url, headers=headers, timeout=timeout_s)
    except httpx.HTTPError as e:
        log.warning("Upstox historical candles failed: %s", e)
        return []
    if resp.status_code == 401:
        log.warning("Upstox historical candles 401 — token expired.")
        _mark_token_dead(token)
        return []
    if resp.status_code != 200:
        log.warning(
            "Upstox historical candles HTTP %d: %s",
            resp.status_code, resp.text[:200],
        )
        return []
    try:
        payload = resp.json()
    except ValueError:
        return []
    candles = (payload.get("data") or {}).get("candles") or []
    return candles if isinstance(candles, list) else []
