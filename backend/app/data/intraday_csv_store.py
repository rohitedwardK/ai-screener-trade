"""Per-symbol intraday CSV cache for stock and commodity OHLCV bars."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import get_settings

_BAR_COLS = ["open", "high", "low", "close", "volume"]


def _dir() -> Path:
    path = Path(get_settings().STOCK_INTRADAY_DATA_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(symbol: str) -> str:
    return symbol.replace("/", "_").replace("^", "_")


def csv_path(symbol: str, *, interval: str = "15m") -> Path:
    return _dir() / f"{_safe_name(symbol)}-{interval}.csv"


def load(symbol: str, *, interval: str = "15m") -> pd.DataFrame:
    path = csv_path(symbol, interval=interval)
    if not path.exists():
        return pd.DataFrame(columns=_BAR_COLS)
    df = pd.read_csv(path)
    if "ts" not in df.columns and len(df.columns) > 0:
        first = str(df.columns[0])
        if first.lower() in {"date", "datetime", "index", "unnamed: 0"}:
            df = df.rename(columns={df.columns[0]: "ts"})
    if "ts" not in df.columns:
        return pd.DataFrame(columns=_BAR_COLS)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    df = df.dropna(subset=["ts"])
    df = df.set_index("ts").sort_index()
    return df[[c for c in _BAR_COLS if c in df.columns]].dropna(subset=["close"])


def merge_save(symbol: str, new_df: pd.DataFrame, *, interval: str = "15m", max_rows: int = 1500) -> int:
    if new_df is None or new_df.empty:
        return 0
    existing = load(symbol, interval=interval)
    frames = [df for df in (existing, new_df) if df is not None and not df.empty]
    if not frames:
        return 0
    merged = pd.concat(frames)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index().tail(max_rows)
    out = merged.reset_index()
    out.to_csv(csv_path(symbol, interval=interval), index=False)
    return len(new_df)
