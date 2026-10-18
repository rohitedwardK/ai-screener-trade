"""MCX Gold / Silver — monthly mini futures via Upstox, Yahoo COMEX proxy fallback.

Yahoo Finance has no MCX GOLD / SILVER contracts (GOLD.MCX 404s). The
dashboard symbols `GOLD.MCX` and `SILVER.MCX` therefore:

  1. Resolve the nearest monthly GOLDM / SILVERM FUT on the public Upstox
     MCX instrument master and pull LTP + daily candles through the
     existing read-only Upstox client.
  2. If Upstox is unconfigured and there is no MCX cache yet, synthesise an
     INR print from COMEX `GC=F` / `SI=F` × `INR=X`. Never merge that proxy
     into an existing MCX series — the level diverges enough to fake crashes.
"""
from __future__ import annotations

import gzip
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import httpx
import pandas as pd

from ..core.commodity_universe import COMMODITY_BY_SYMBOL
from . import csv_store, yf_client

log = logging.getLogger(__name__)

MCX_INSTRUMENTS_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/MCX.json.gz"
)
_INSTRUMENT_TTL_S = 6 * 3600.0

# 1 troy ounce in grams. MCX gold is INR per 10 g; silver is INR per kg.
TROY_OZ_GRAMS = 31.1034768

_MCX_OPEN_HHMM = (9, 0)
_MCX_CLOSE_HHMM = (23, 30)
_IST_OFFSET_MINUTES = 5 * 60 + 30

_DAY_MS = 86_400_000

_lock = threading.Lock()
_instruments: Optional[List[dict]] = None
_instruments_at: float = 0.0
_front_month: Dict[str, dict] = {}
# In-progress session quote, shared by the detail chart and the scorer.
_session_quote: Dict[str, Tuple[float, object]] = {}
_SESSION_QUOTE_TTL_S = 30.0


def reset_cache() -> None:
    """Test hook."""
    global _instruments, _instruments_at, _front_month, _session_quote
    with _lock:
        _instruments = None
        _instruments_at = 0.0
        _front_month = {}
        _session_quote = {}


def _now_ist() -> datetime:
    utc_now = datetime.now(timezone.utc)
    ist = utc_now.astimezone(timezone(timedelta(minutes=_IST_OFFSET_MINUTES)))
    return ist.replace(tzinfo=None)


def is_mcx_session_open(at: Optional[datetime] = None) -> bool:
    """True Mon-Fri 09:00-23:30 IST (regular MCX bullion session)."""
    now = at or _now_ist()
    if now.weekday() >= 5:
        return False
    open_t = now.replace(
        hour=_MCX_OPEN_HHMM[0], minute=_MCX_OPEN_HHMM[1],
        second=0, microsecond=0,
    )
    close_t = now.replace(
        hour=_MCX_CLOSE_HHMM[0], minute=_MCX_CLOSE_HHMM[1],
        second=0, microsecond=0,
    )
    return open_t <= now <= close_t


def gold_inr_per_10g(comex_usd_oz: float, usd_inr: float) -> float:
    return comex_usd_oz * usd_inr * 10.0 / TROY_OZ_GRAMS


def silver_inr_per_kg(comex_usd_oz: float, usd_inr: float) -> float:
    return comex_usd_oz * usd_inr * (1000.0 / TROY_OZ_GRAMS)


def _normalise_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = df.rename(columns=str.lower)
    cols = ["open", "high", "low", "close", "volume"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        return pd.DataFrame(columns=cols)
    out = df[cols].copy().dropna(how="all")
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    out.index = pd.to_datetime(out.index).normalize()
    out.index.name = "date"
    return out.sort_index()


def _is_gold_mcx_asset(asset_symbol: str) -> bool:
    return asset_symbol.upper().startswith("GOLD")


def pick_front_month(
    rows: List[dict],
    asset_symbol: str,
    *,
    now_ms: Optional[int] = None,
    max_hold_days: int = 30,
) -> Optional[dict]:
    """Nearest unexpired monthly MCX FUT (GOLDM / SILVERM).

    Prefers a lot that expires within `max_hold_days` so the dashboard can
    offer a next-monthly trade. Falls back to the nearest unexpired lot
    (quotes only — analysis then skips the monthly window).
    """
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    unexpired: List[dict] = []
    for row in rows:
        if row.get("asset_symbol") != asset_symbol:
            continue
        if row.get("instrument_type") != "FUT":
            continue
        expiry = int(row.get("expiry") or 0)
        if expiry < now_ms:
            continue
        unexpired.append(row)
    if not unexpired:
        return None
    unexpired.sort(key=lambda r: int(r.get("expiry") or 0))
    if max_hold_days is not None and max_hold_days >= 0:
        cap = now_ms + max_hold_days * _DAY_MS
        near = [r for r in unexpired if int(r.get("expiry") or 0) <= cap]
        if near:
            return near[0]
    return unexpired[0]


def _download_instruments() -> List[dict]:
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(
                MCX_INSTRUMENTS_URL,
                headers={"User-Agent": "ai-screener-trade/1.0"},
            )
        resp.raise_for_status()
        data = json.loads(gzip.decompress(resp.content))
    except Exception:
        log.warning("MCX instrument master download failed", exc_info=True)
        return []
    if not isinstance(data, list):
        return []
    return data


def load_instruments(*, force: bool = False) -> List[dict]:
    global _instruments, _instruments_at
    now = time.monotonic()
    with _lock:
        if (
            not force
            and _instruments is not None
            and (now - _instruments_at) < _INSTRUMENT_TTL_S
        ):
            return _instruments
    rows = _download_instruments()
    with _lock:
        if rows:
            _instruments = rows
            _instruments_at = time.monotonic()
            return _instruments
        return _instruments or []


def _contract_row(symbol: str) -> Optional[dict]:
    """Cached front-month (weekly-hold) instrument row for GOLD.MCX / SILVER.MCX."""
    meta = COMMODITY_BY_SYMBOL.get(symbol)
    if meta is None:
        return None
    now_ms = int(time.time() * 1000)
    with _lock:
        cached = _front_month.get(symbol)
    if cached and int(cached.get("expiry") or 0) >= now_ms:
        return cached
    rows = load_instruments()
    if not rows:
        return cached if cached else None
    row = pick_front_month(rows, meta.mcx_asset, now_ms=now_ms)
    if row is None:
        return None
    with _lock:
        _front_month[symbol] = row
    log.info(
        "MCX weekly-hold monthly %s -> %s (%s)",
        symbol, row.get("instrument_key"), row.get("trading_symbol"),
    )
    return row


def instrument_key_for(symbol: str) -> Optional[str]:
    """Upstox `MCX_FO|...` key for GOLD.MCX / SILVER.MCX, else None."""
    row = _contract_row(symbol)
    if row is None:
        return None
    key = str(row.get("instrument_key") or "")
    return key or None


def contract_expiry_date(symbol: str) -> Optional[date]:
    row = _contract_row(symbol)
    if row is None:
        return None
    ms = int(row.get("expiry") or 0)
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()


def contract_label(symbol: str) -> Optional[str]:
    row = _contract_row(symbol)
    if row is None:
        return None
    label = row.get("trading_symbol")
    return str(label) if label else None


def _yf_daily(symbol: str, start: date, end: date) -> pd.DataFrame:
    yf_client.pace()
    import yfinance as yf

    t = yf.Ticker(symbol)
    df = t.history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=True,
        actions=False,
        raise_errors=False,
    )
    return _normalise_ohlcv(df)


def synthetic_daily(symbol: str, start: date, end: date) -> pd.DataFrame:
    """COMEX × USDINR proxy series in MCX quote units."""
    meta = COMMODITY_BY_SYMBOL.get(symbol)
    if meta is None:
        return _normalise_ohlcv(pd.DataFrame())
    comex = _yf_daily(meta.comex_symbol, start, end)
    inr = _yf_daily("INR=X", start, end)
    if comex.empty or inr.empty:
        return _normalise_ohlcv(pd.DataFrame())
    joined = comex.join(inr[["close"]].rename(columns={"close": "usd_inr"}), how="inner")
    if joined.empty:
        return _normalise_ohlcv(pd.DataFrame())
    convert = gold_inr_per_10g if _is_gold_mcx_asset(meta.mcx_asset) else silver_inr_per_kg
    fx = joined["usd_inr"]
    out = pd.DataFrame({
        "open": [convert(float(o), float(f)) for o, f in zip(joined["open"], fx)],
        "high": [convert(float(h), float(f)) for h, f in zip(joined["high"], fx)],
        "low": [convert(float(lo), float(f)) for lo, f in zip(joined["low"], fx)],
        "close": [convert(float(c), float(f)) for c, f in zip(joined["close"], fx)],
        "volume": joined["volume"].to_numpy(),
    }, index=joined.index)
    return _normalise_ohlcv(out)


def drop_synthetic_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Drop COMEX×INR proxy rows that were merged into an MCX series.

    MCX gold/silver futures print in whole rupees. The Yahoo conversion
    leaves long fractional tails (e.g. 142821.88 vs 161985), which must
    not stay in the same series as exchange candles.
    """
    if df is None or df.empty or "close" not in df.columns:
        return df if df is not None else _normalise_ohlcv(pd.DataFrame())
    close = pd.to_numeric(df["close"], errors="coerce")
    keep = (close - close.round()).abs() < 1e-4
    return df.loc[keep].copy()


def _quote_session_date(quote) -> date:
    """IST session date of an Upstox quote. Falls back to today when the stamp is missing."""
    ms = int(getattr(quote, "timestamp_ms", 0) or 0)
    if ms > 0:
        ist = timezone(timedelta(minutes=_IST_OFFSET_MINUTES))
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(ist).date()
    return _now_ist().date()


def _cached_session_quote(symbol: str):
    """Upstox OHLC for one MCX symbol, reused for 30s across chart and scoring."""
    from . import upstox_client

    if symbol not in COMMODITY_BY_SYMBOL or not upstox_client.is_configured():
        return None
    now = time.monotonic()
    with _lock:
        cached = _session_quote.get(symbol)
        if cached is not None and (now - cached[0]) < _SESSION_QUOTE_TTL_S:
            return cached[1]
    try:
        quotes = upstox_client.fetch_quotes_batch([symbol])
    except Exception:
        log.warning("MCX live session quote failed for %s", symbol, exc_info=True)
        return None
    quote = quotes.get(symbol)
    if quote is None or float(getattr(quote, "last_price", 0) or 0) <= 0:
        return None
    with _lock:
        _session_quote[symbol] = (time.monotonic(), quote)
    return quote


def overlay_live_session(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Score and chart off the current MCX session, not the previous daily close.

    The CSV is the last completed download, so during the session it still
    ends yesterday. Entry, stop, and targets are sized from the last close.
    This appends (or refreshes) today's bar from the Upstox quote in memory
    and does not write it back to the cache.
    """
    if df is None or df.empty or "close" not in df.columns:
        return df
    quote = _cached_session_quote(symbol)
    if quote is None:
        return df
    session = _quote_session_date(quote)
    last_day = pd.Timestamp(df.index[-1]).normalize()
    session_ts = pd.Timestamp(session)
    if session_ts < last_day:
        return df

    last_px = float(quote.last_price)
    open_px = float(quote.open) if quote.open and quote.open > 0 else last_px
    high_px = float(quote.high) if quote.high and quote.high > 0 else last_px
    low_px = float(quote.low) if quote.low and quote.low > 0 else last_px
    high_px = max(high_px, last_px, open_px)
    low_px = min(low_px, last_px, open_px)
    volume = float(quote.volume or 0)

    out = df.copy()
    if session_ts == last_day:
        prev = out.iloc[-1]
        if float(prev["open"]) > 0:
            open_px = float(prev["open"])
        high_px = max(high_px, float(prev["high"]))
        low_px = min(low_px, float(prev["low"]))
        idx = out.index[-1]
        out.loc[idx, "open"] = open_px
        out.loc[idx, "high"] = high_px
        out.loc[idx, "low"] = low_px
        out.loc[idx, "close"] = last_px
        if volume > 0 and "volume" in out.columns:
            out.loc[idx, "volume"] = volume
        return out

    row = {c: (volume if c == "volume" else last_px) for c in out.columns}
    row["open"] = open_px
    row["high"] = high_px
    row["low"] = low_px
    row["close"] = last_px
    extra = pd.DataFrame(
        [row],
        index=pd.DatetimeIndex([session_ts], name=out.index.name or "date"),
    )
    return pd.concat([out, extra])


def cached_exchange_closes(symbols: List[str]) -> Dict[str, float]:
    """Last whole-rupee MCX close from the CSV cache (proxy bars skipped)."""
    from . import csv_store

    out: Dict[str, float] = {}
    for sym in symbols:
        df = drop_synthetic_bars(csv_store.load(sym))
        if df.empty:
            continue
        out[sym] = float(df["close"].iloc[-1])
    return out


def _candles_to_frame(candles: List[list]) -> pd.DataFrame:
    if not candles:
        return _normalise_ohlcv(pd.DataFrame())
    ist = timezone(timedelta(minutes=_IST_OFFSET_MINUTES))
    rows = []
    idx = []
    for c in candles:
        if not isinstance(c, (list, tuple)) or len(c) < 6:
            continue
        ts = pd.to_datetime(c[0], utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        # Session date in IST, not UTC — a 00:00+05:30 stamp is that IST day.
        naive = ts.tz_convert(ist).tz_localize(None).normalize()
        idx.append(naive)
        rows.append({
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5] or 0.0),
        })
    if not rows:
        return _normalise_ohlcv(pd.DataFrame())
    return _normalise_ohlcv(pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="date")))


def _fetch_upstox_daily(instrument_key: str, start: date, end: date) -> pd.DataFrame:
    from . import upstox_client

    candles = upstox_client.fetch_historical_candles(
        instrument_key, start=start, end=end, interval="day",
    )
    return _candles_to_frame(candles)


def fetch_or_update(symbol: str, *, force_full: bool = False) -> Tuple[pd.DataFrame, str]:
    """CSV-cached daily OHLCV for one MCX symbol. Same modes as stock fetcher."""
    today = date.today()
    start_full = today - timedelta(days=400)  # Upstox day candles ~1y
    existing_raw = csv_store.load(symbol)
    existing = drop_synthetic_bars(existing_raw)
    if len(existing) != len(existing_raw):
        csv_store.save(symbol, existing)
        log.warning("%s: stripped COMEX-proxy bars from MCX cache", symbol)

    if force_full or csv_store.needs_full_refresh(symbol):
        df = _load_remote(symbol, start_full, today)
        if df.empty:
            return existing, "empty"
        return _persist_mcx_frame(symbol, df, existing), "full"

    start = csv_store.incremental_start(symbol)
    if start is not None and start >= today:
        return csv_store.load(symbol), "noop"

    fetch_start = start or start_full
    new_df = _load_remote(symbol, fetch_start, today)
    if new_df.empty:
        return csv_store.load(symbol), "empty"
    return _persist_mcx_frame(symbol, new_df, existing), "incremental"


def _persist_mcx_frame(
    symbol: str,
    new_df: pd.DataFrame,
    existing: pd.DataFrame,
) -> pd.DataFrame:
    """Merge new Upstox bars into cache. Never replace a long series with a
    short front-month window (a new GOLDM listing is only a few sessions)."""
    incoming = drop_synthetic_bars(new_df)
    if incoming.empty:
        return existing
    if existing is None or existing.empty:
        csv_store.save(symbol, incoming)
        return incoming
    csv_store.merge_save(symbol, incoming)
    return drop_synthetic_bars(csv_store.load(symbol))


def _load_remote(symbol: str, start: date, end: date) -> pd.DataFrame:
    key = instrument_key_for(symbol)
    if key:
        df = _fetch_upstox_daily(key, start, end)
        if not df.empty:
            return df
        # Never blend COMEX proxy into an existing MCX series — the units
        # track but the level diverges enough to corrupt signals.
        if not csv_store.load(symbol).empty:
            log.info("%s: Upstox daily empty; keeping cached MCX history", symbol)
            return _normalise_ohlcv(pd.DataFrame())
        log.info("%s: cold start with COMEX×INR proxy (not MCX print)", symbol)
    elif not csv_store.load(symbol).empty:
        return _normalise_ohlcv(pd.DataFrame())
    return synthetic_daily(symbol, start, end)


def cached_close_ltp(symbols: List[str]) -> Dict[str, float]:
    """Last stored MCX daily close from the CSV cache (proxy bars skipped)."""
    wanted = [s for s in symbols if s in COMMODITY_BY_SYMBOL]
    return cached_exchange_closes(wanted)


def comex_proxy_ltp(symbols: List[str]) -> Dict[str, float]:
    """Last COMEX×INR print for the requested MCX app symbols."""
    wanted = [s for s in symbols if s in COMMODITY_BY_SYMBOL]
    if not wanted:
        return {}
    yf_client.pace()
    import yfinance as yf

    tickers = sorted({COMMODITY_BY_SYMBOL[s].comex_symbol for s in wanted} | {"INR=X"})
    try:
        df = yf.download(
            " ".join(tickers),
            period="5d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )
    except Exception:
        log.warning("COMEX×INR proxy LTP download failed", exc_info=True)
        return {}
    if df is None or getattr(df, "empty", True):
        return {}

    def _last(sym: str) -> Optional[float]:
        try:
            return float(df[sym]["Close"].dropna().iloc[-1])
        except (KeyError, IndexError, TypeError):
            try:
                return float(df["Close"].dropna().iloc[-1])
            except (KeyError, IndexError, TypeError):
                return None

    usd_inr = _last("INR=X")
    if usd_inr is None or usd_inr <= 0:
        return {}
    out: Dict[str, float] = {}
    for app_sym in wanted:
        meta = COMMODITY_BY_SYMBOL[app_sym]
        px = _last(meta.comex_symbol)
        if px is None:
            continue
        if _is_gold_mcx_asset(meta.mcx_asset):
            out[app_sym] = gold_inr_per_10g(px, usd_inr)
        else:
            out[app_sym] = silver_inr_per_kg(px, usd_inr)
    return out
