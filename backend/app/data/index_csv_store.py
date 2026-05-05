"""Per-index CSV cache for OHLCV data.

Mirrors `data/csv_store.py` but stores under `data/ohlcv-indices/` and
`data/ohlcv-indices-intraday/` to keep daily and intraday histories on
separate disks. Indices use Yahoo tickers like `^NSEI` which contain a
caret; we sanitise the filename component.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

DAILY_DIR = Path("data") / "ohlcv-indices"
INTRADAY_DIR = Path("data") / "ohlcv-indices-intraday"
DAILY_DIR.mkdir(parents=True, exist_ok=True)
INTRADAY_DIR.mkdir(parents=True, exist_ok=True)


def _safe_name(symbol: str) -> str:
    return symbol.replace("^", "_").replace("/", "_")


def _path(symbol: str, *, intraday: bool) -> Path:
    base = INTRADAY_DIR if intraday else DAILY_DIR
    return base / f"{_safe_name(symbol)}.csv"


def csv_path(symbol: str, *, intraday: bool = False) -> Path:
    return _path(symbol, intraday=intraday)


def load(symbol: str, *, intraday: bool = False) -> pd.DataFrame:
    p = _path(symbol, intraday=intraday)
    if not p.exists():
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    try:
        df = pd.read_csv(p, parse_dates=["date"])
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed reading %s: %s. Treating as empty.", p, exc)
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = df.set_index("date")
    df.index = pd.to_datetime(df.index)
    if not intraday:
        df.index = df.index.normalize()
    return df.sort_index()


def last_date(symbol: str, *, intraday: bool = False) -> Optional[date]:
    df = load(symbol, intraday=intraday)
    if df.empty:
        return None
    ts = df.index[-1]
    return ts.date() if hasattr(ts, "date") else ts


def save(symbol: str, df: pd.DataFrame, *, intraday: bool = False) -> None:
    if df is None or df.empty:
        return
    p = _path(symbol, intraday=intraday)
    tmp = p.with_suffix(".csv.tmp")
    out = df.copy()
    if intraday:
        out.index = pd.to_datetime(out.index)
    else:
        out.index = pd.to_datetime(out.index).normalize()
    out.index.name = "date"
    out = out[["open", "high", "low", "close", "volume"]].sort_index()
    out.to_csv(tmp)
    tmp.replace(p)


def merge_save(symbol: str, new_df: pd.DataFrame, *, intraday: bool = False) -> int:
    if new_df is None or new_df.empty:
        return 0
    existing = load(symbol, intraday=intraday)
    before = len(existing)

    new_df = new_df.copy()
    new_df.index = pd.to_datetime(new_df.index)
    if not intraday:
        new_df.index = new_df.index.normalize()

    if existing.empty:
        merged = new_df
    else:
        merged = pd.concat([existing, new_df])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()

    save(symbol, merged, intraday=intraday)
    return len(merged) - before


def needs_full_refresh(symbol: str, max_age_days: int = 7, *, intraday: bool = False) -> bool:
    last = last_date(symbol, intraday=intraday)
    if last is None:
        return True
    today = date.today()
    return (today - last) > timedelta(days=max_age_days)


def incremental_start(symbol: str, overlap_days: int = 5, *, intraday: bool = False) -> Optional[date]:
    last = last_date(symbol, intraday=intraday)
    if last is None:
        return None
    return last - timedelta(days=overlap_days)


def list_cached(*, intraday: bool = False) -> list[str]:
    base = INTRADAY_DIR if intraday else DAILY_DIR
    return sorted(p.stem.replace("_NSEI", "^NSEI").replace("_BSESN", "^BSESN").replace("_NSEBANK", "^NSEBANK")
                  for p in base.glob("*.csv"))
