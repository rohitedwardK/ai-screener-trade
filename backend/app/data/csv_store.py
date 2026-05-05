"""Per-symbol CSV cache for OHLCV data.

CSVs are the canonical OHLCV store; SQLite is kept as a fast indexed mirror.
On first run we fetch 5y in small batches and persist to disk. On subsequent
runs we read the CSV, fetch only days after the latest stored date (with a
small overlap to catch dividend / split adjustments), and merge.

CSV layout (one file per symbol, e.g. data/ohlcv/RELIANCE.NS.csv):

    date,open,high,low,close,volume
    2021-05-05,1990.10,2010.50,1985.00,2005.30,10234567
    ...
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

# data/ohlcv lives next to the working directory of the backend (where uvicorn runs).
CSV_DIR = Path("data") / "ohlcv"
CSV_DIR.mkdir(parents=True, exist_ok=True)


def csv_path(symbol: str) -> Path:
    return CSV_DIR / f"{symbol}.csv"


def load(symbol: str) -> pd.DataFrame:
    """Return the cached frame (empty DataFrame if no file exists)."""
    p = csv_path(symbol)
    if not p.exists():
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    try:
        df = pd.read_csv(p, parse_dates=["date"])
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed reading %s: %s. Treating as empty.", p, exc)
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = df.set_index("date")
    df.index = pd.to_datetime(df.index).normalize()
    return df.sort_index()


def last_date(symbol: str) -> Optional[date]:
    df = load(symbol)
    if df.empty:
        return None
    return df.index[-1].date()


def save(symbol: str, df: pd.DataFrame) -> None:
    """Atomically write the (full) frame to CSV."""
    if df is None or df.empty:
        return
    p = csv_path(symbol)
    tmp = p.with_suffix(".csv.tmp")
    out = df.copy()
    out.index = pd.to_datetime(out.index).normalize()
    out.index.name = "date"
    out = out[["open", "high", "low", "close", "volume"]].sort_index()
    out.to_csv(tmp)
    tmp.replace(p)


def merge_save(symbol: str, new_df: pd.DataFrame) -> int:
    """Merge `new_df` into the cached CSV (new rows replace overlapping ones).
    Returns the number of net new rows added.
    """
    if new_df is None or new_df.empty:
        return 0

    existing = load(symbol)
    before = len(existing)

    new_df = new_df.copy()
    new_df.index = pd.to_datetime(new_df.index).normalize()

    if existing.empty:
        merged = new_df
    else:
        # Newer rows win on duplicates -> keep="last"
        merged = pd.concat([existing, new_df])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()

    save(symbol, merged)
    added = len(merged) - before
    log.debug("%s: merged %d rows into CSV (now %d)", symbol, len(new_df), len(merged))
    return added


def needs_full_refresh(symbol: str, max_age_days: int = 7) -> bool:
    """True if the cache is missing or its last date is older than `max_age_days`.

    Yahoo retroactively adjusts close prices on splits/dividends; if our cache
    has been stale for too long the older adjusted values may have drifted, so
    a full re-fetch is safer than incremental.
    """
    last = last_date(symbol)
    if last is None:
        return True
    return (date.today() - last) > timedelta(days=max_age_days)


def incremental_start(symbol: str, overlap_days: int = 5) -> Optional[date]:
    """Returns the start date for an incremental fetch, or None if full refresh needed."""
    last = last_date(symbol)
    if last is None:
        return None
    # overlap a few days so corporate-action adjustments propagate.
    return last - timedelta(days=overlap_days)


def list_cached_symbols() -> list[str]:
    return sorted(p.stem for p in CSV_DIR.glob("*.csv"))
