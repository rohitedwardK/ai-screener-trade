"""Smart OHLCV fetcher with CSV-cached incremental updates.

Strategy:
- First run for a symbol  : fetch full `period` (e.g. 5y) and persist as CSV.
- Subsequent runs         : fetch only days after the latest cached date,
                             with a small overlap so that corporate-action
                             adjustments (splits/dividends) propagate.
- Stale cache (> N days)  : trigger a full re-fetch (older adjusted prices
                             may have drifted).

Each symbol's CSV is saved IMMEDIATELY after a successful fetch, so a partial
network failure mid-batch never loses progress.

yfinance >=1.3 manages its own internal `curl_cffi` session for browser
impersonation. We pace at the application layer (~3 req/s) and run sequentially.
"""
from __future__ import annotations

import logging
import random
import time
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from ..config import get_settings
from ..core.commodity_universe import is_commodity_symbol
from . import csv_store
from .yf_client import pace

log = logging.getLogger(__name__)

# Process N symbols, then pause briefly. Smaller batches = better resilience.
DEFAULT_BATCH_SIZE = 10
INTER_BATCH_SLEEP_S = 0.5


def _normalise_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = df.rename(columns=str.lower)
    cols = ["open", "high", "low", "close", "volume"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        return pd.DataFrame(columns=cols)

    df = df[cols].copy().dropna(how="all")
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df.index = pd.to_datetime(df.index).normalize()
    df.index.name = "date"
    return df


def _yf_history(
    symbol: str,
    *,
    period: Optional[str] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    interval: str = "1d",
    max_retries: int = 3,
) -> pd.DataFrame:
    """One yfinance call with retry + exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            pace()
            t = yf.Ticker(symbol)
            kwargs: dict = {
                "interval": interval,
                "auto_adjust": True,
                "actions": False,
                "raise_errors": False,
            }
            if period is not None:
                kwargs["period"] = period
            if start is not None:
                kwargs["start"] = start.isoformat()
            if end is not None:
                kwargs["end"] = end.isoformat()
            df = t.history(**kwargs)
            if df is not None and not df.empty:
                return _normalise_frame(df)
            log.debug("%s: empty frame on attempt %d", symbol, attempt + 1)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.debug("%s: error on attempt %d: %s", symbol, attempt + 1, exc)
        time.sleep((2 ** attempt) + random.uniform(0, 0.5))

    if last_exc is not None:
        log.warning("%s: giving up after %d attempts: %s", symbol, max_retries, last_exc)
    return _normalise_frame(pd.DataFrame())


def fetch_or_update(
    symbol: str,
    *,
    period: str,
    interval: str,
    force_full: bool = False,
) -> Tuple[pd.DataFrame, str]:
    """Fetch the latest data for one symbol using the CSV cache.

    Returns (full_dataframe, mode) where mode is one of:
      - "full"        : full re-download (CSV missing or stale)
      - "incremental" : only fetched days after the cached last date
      - "noop"        : already up to date (today's data already cached)
      - "empty"       : remote returned no data; CSV unchanged
    """
    if is_commodity_symbol(symbol):
        from . import mcx as mcx_data

        return mcx_data.fetch_or_update(symbol, force_full=force_full)

    # Full / first-time fetch: retry up to 3 times because we have no fallback.
    if force_full or csv_store.needs_full_refresh(symbol):
        new_df = _yf_history(symbol, period=period, interval=interval, max_retries=3)
        if new_df.empty:
            existing = csv_store.load(symbol)
            return existing, "empty"
        csv_store.save(symbol, new_df)
        return new_df, "full"

    start = csv_store.incremental_start(symbol)
    today = date.today()
    if start is not None and start >= today:
        return csv_store.load(symbol), "noop"

    # Incremental fetch: if Yahoo returns empty we keep the existing CSV, so
    # there's no benefit in slow exponential retries. One attempt is enough.
    new_df = _yf_history(
        symbol,
        start=start,
        end=today + timedelta(days=1),
        interval=interval,
        max_retries=1,
    )
    if new_df.empty:
        return csv_store.load(symbol), "empty"

    csv_store.merge_save(symbol, new_df)
    return csv_store.load(symbol), "incremental"


def download_batch(
    symbols: List[str],
    period: Optional[str] = None,
    interval: Optional[str] = None,
    force_full: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Dict[str, pd.DataFrame]:
    """Smart batch fetcher: per-symbol CSV cache + incremental fetch.

    Args:
        symbols    : tickers like ["RELIANCE.NS", "TCS.NS", ...]
        period     : full-history period (e.g. "5y"); falls back to settings.
        interval   : "1d" by default.
        force_full : refetch full history for every symbol regardless of cache.
        batch_size : pause briefly every N symbols for resilience.
    """
    settings = get_settings()
    period = period or settings.HISTORY_PERIOD
    interval = interval or settings.INTERVAL

    if not symbols:
        return {}

    out: Dict[str, pd.DataFrame] = {}
    counts = {"full": 0, "incremental": 0, "noop": 0, "empty": 0}

    log.info(
        "Fetching %d symbols (period=%s interval=%s force_full=%s batch_size=%d)",
        len(symbols), period, interval, force_full, batch_size,
    )

    for idx, symbol in enumerate(symbols, start=1):
        try:
            df, mode = fetch_or_update(
                symbol,
                period=period,
                interval=interval,
                force_full=force_full,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("%s: fetch_or_update failed", symbol)
            df, mode = csv_store.load(symbol), "empty"

        out[symbol] = df
        counts[mode] += 1
        log.info(
            "[%d/%d] %s mode=%s rows=%d (last=%s)",
            idx, len(symbols), symbol, mode, len(df),
            df.index[-1].date() if not df.empty else "—",
        )

        if idx % batch_size == 0 and idx < len(symbols):
            time.sleep(INTER_BATCH_SLEEP_S)

    log.info(
        "Batch done: full=%d incremental=%d noop=%d empty=%d",
        counts["full"], counts["incremental"], counts["noop"], counts["empty"],
    )
    return out
