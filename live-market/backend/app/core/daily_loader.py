"""Read the parent app's daily index OHLCV CSVs.

The parent screener already maintains daily candles for ^NSEI / ^NSEBANK
/ ^BSESN under `INDEX_DATA_DIR` (default `../../backend/data/ohlcv-indices`
relative to the live-market backend). We read those CSVs directly so this
service doesn't duplicate yfinance pacing/retry logic.

Cached in-memory per UTC day - daily candles only change at the parent's
EOD refresh job, so re-reading from disk on every tick would be wasteful.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import pandas as pd

from ..config import get_settings

log = logging.getLogger(__name__)


_cache_lock = threading.Lock()
_cache: Dict[str, pd.DataFrame] = {}
_cache_date: Optional[str] = None


def _csv_path_for(symbol: str) -> str:
    settings = get_settings()
    base = settings.INDEX_DATA_DIR
    if not os.path.isabs(base):
        # Resolve relative to the backend working directory.
        base = os.path.abspath(base)
    safe = symbol.replace("^", "_")
    return os.path.join(base, f"{safe}.csv")


def _today_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _refresh_if_new_day() -> None:
    global _cache_date
    today = _today_utc_str()
    if _cache_date != today:
        _cache.clear()
        _cache_date = today


def load_daily(symbol: str) -> Optional[pd.DataFrame]:
    """Return the daily OHLCV DataFrame for `symbol` or None when missing.

    Columns: open, high, low, close, volume. Index: pandas DatetimeIndex
    (ascending).
    """
    with _cache_lock:
        _refresh_if_new_day()
        cached = _cache.get(symbol)
        if cached is not None:
            return cached.copy()

        path = _csv_path_for(symbol)
        if not os.path.exists(path):
            log.warning("daily CSV not found: %s", path)
            return None
        try:
            df = pd.read_csv(path)
        except Exception as e:  # noqa: BLE001
            log.warning("failed to read %s: %s", path, e)
            return None

        if df.empty:
            return None
        # First column is the date; the parent app writes lowercase OHLCV
        # column names, but be defensive.
        df.columns = [str(c).lower() for c in df.columns]
        if "date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "date"})
        try:
            df["date"] = pd.to_datetime(df["date"])
        except Exception:  # noqa: BLE001
            log.warning("failed to parse date column in %s", path)
            return None
        df = df.set_index("date").sort_index()
        cols = ["open", "high", "low", "close", "volume"]
        missing = [c for c in cols if c not in df.columns]
        if missing:
            log.warning("daily CSV %s missing cols: %s", path, missing)
            return None
        df = df[cols].dropna(how="all")
        _cache[symbol] = df
        return df.copy()


def latest_daily_atr_adx(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    """Convenience: latest daily ATR(14) and ADX(14) for the regime gate."""
    df = load_daily(symbol)
    if df is None or len(df) < 30:
        return None, None
    # Lazy import to avoid a top-level dependency cycle.
    from ..analysis import indicators

    atr_s = indicators.atr(df, 14)
    adx_df = indicators.adx(df, 14)
    atr_v = float(atr_s.iloc[-1]) if not atr_s.empty and pd.notna(atr_s.iloc[-1]) else None
    adx_v = float(adx_df["adx"].iloc[-1]) if not adx_df["adx"].empty and pd.notna(adx_df["adx"].iloc[-1]) else None
    return atr_v, adx_v


def reset_cache() -> None:
    """Test hook: drop the in-memory cache."""
    global _cache_date
    with _cache_lock:
        _cache.clear()
        _cache_date = None


__all__ = ["load_daily", "latest_daily_atr_adx", "reset_cache"]
