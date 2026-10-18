"""Index OHLCV fetcher (daily + intraday).

Reuses the same yfinance pacing + retry pattern as `fetcher.py` but writes
into `data/ohlcv-indices/` (daily) or `data/ohlcv-indices-intraday/` (1m/5m).

Yahoo intraday limits:
  - 1m  : last 7  days (`period="7d"`, `interval="1m"`)
  - 5m  : last 60 days (`period="60d"`, `interval="5m"`)
  - 15m : last 60 days
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
from . import index_csv_store
from .yf_client import pace

log = logging.getLogger(__name__)

DEFAULT_INTRADAY_PERIOD = "7d"
DEFAULT_INTRADAY_INTERVAL = "5m"


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
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
    df.index = pd.to_datetime(df.index)
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
                return _normalise(df)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.debug("%s: error attempt %d: %s", symbol, attempt + 1, exc)
        time.sleep((2 ** attempt) + random.uniform(0, 0.5))
    if last_exc is not None:
        log.warning("%s: giving up after %d attempts: %s", symbol, max_retries, last_exc)
    return _normalise(pd.DataFrame())


def fetch_daily(
    symbol: str,
    *,
    period: str,
    force_full: bool = False,
) -> Tuple[pd.DataFrame, str]:
    """Fetch daily OHLCV for one index symbol; returns (df, mode)."""
    if force_full or index_csv_store.needs_full_refresh(symbol):
        new_df = _yf_history(symbol, period=period, interval="1d", max_retries=3)
        if new_df.empty:
            return index_csv_store.load(symbol), "empty"
        index_csv_store.save(symbol, new_df)
        return new_df, "full"

    start = index_csv_store.incremental_start(symbol)
    today = date.today()
    if start is not None and start >= today:
        return index_csv_store.load(symbol), "noop"

    new_df = _yf_history(
        symbol,
        start=start,
        end=today + timedelta(days=1),
        interval="1d",
        max_retries=1,
    )
    if new_df.empty:
        return index_csv_store.load(symbol), "empty"
    index_csv_store.merge_save(symbol, new_df)
    return index_csv_store.load(symbol), "incremental"


def fetch_intraday(
    symbol: str,
    *,
    period: str = DEFAULT_INTRADAY_PERIOD,
    interval: str = DEFAULT_INTRADAY_INTERVAL,
) -> Tuple[pd.DataFrame, str]:
    """Refresh the intraday cache for one index. Yahoo enforces tight history
    windows so we always pull the full window and merge."""
    new_df = _yf_history(symbol, period=period, interval=interval, max_retries=2)
    if new_df.empty:
        return index_csv_store.load(symbol, intraday=True), "empty"
    index_csv_store.merge_save(symbol, new_df, intraday=True)
    return index_csv_store.load(symbol, intraday=True), "ok"


def download_daily_batch(
    symbols: List[str],
    *,
    period: Optional[str] = None,
    force_full: bool = False,
) -> Dict[str, pd.DataFrame]:
    settings = get_settings()
    period = period or settings.HISTORY_PERIOD
    out: Dict[str, pd.DataFrame] = {}
    if not symbols:
        return out

    log.info(
        "Index fetch (daily): %d symbols (period=%s force_full=%s)",
        len(symbols), period, force_full,
    )
    for sym in symbols:
        try:
            df, mode = fetch_daily(sym, period=period, force_full=force_full)
        except Exception:  # noqa: BLE001
            log.exception("%s: index fetch failed", sym)
            df, mode = index_csv_store.load(sym), "empty"
        out[sym] = df
        log.info(
            "[index] %s mode=%s rows=%d (last=%s)",
            sym, mode, len(df),
            df.index[-1].date() if not df.empty else "—",
        )
    return out


def download_intraday_batch(
    symbols: List[str],
    *,
    period: str = DEFAULT_INTRADAY_PERIOD,
    interval: str = DEFAULT_INTRADAY_INTERVAL,
) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    if not symbols:
        return out
    log.info(
        "Index fetch (intraday): %d symbols (period=%s interval=%s)",
        len(symbols), period, interval,
    )
    for sym in symbols:
        try:
            df, mode = fetch_intraday(sym, period=period, interval=interval)
        except Exception:  # noqa: BLE001
            log.exception("%s: intraday fetch failed", sym)
            df, mode = index_csv_store.load(sym, intraday=True), "empty"
        out[sym] = df
        log.info(
            "[index/intraday] %s mode=%s rows=%d",
            sym, mode, len(df),
        )
    return out


