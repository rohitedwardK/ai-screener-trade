"""Read-only SMA20 watchlist from completed daily caches."""
from __future__ import annotations

import pandas as pd

from ..analysis.ma_crossovers import recent_ma20_crossing
from ..data import csv_store
from .universe import stock_meta

DISCLAIMER = "Research and decision-support only. Not financial advice."


def scan_ma20_crossings(lookback: int = 3, now: pd.Timestamp | None = None) -> dict:
    now = pd.Timestamp.now(tz="Asia/Kolkata") if now is None else now
    if now.tzinfo is None:
        now = now.tz_localize("Asia/Kolkata")
    local = now.tz_convert("Asia/Kolkata").tz_localize(None)
    today = local.normalize()
    cutoff = today if local >= today + pd.Timedelta(hours=15, minutes=30) else today - pd.Timedelta(days=1)
    stocks = stock_meta()
    rows, skipped = [], []
    for stock in stocks:
        raw = csv_store.load(stock["symbol"])
        frame = raw.loc[raw.index <= cutoff] if len(raw) else raw
        if len(frame) < 20 + lookback:
            skipped.append({"symbol": stock["symbol"], "reason": "Insufficient completed daily bars"})
            continue
        recent = frame.tail(20 + lookback)
        if recent.index.has_duplicates or recent.isna().any().any():
            skipped.append({"symbol": stock["symbol"], "reason": "Incomplete or duplicate recent daily bars"})
            continue
        if (today - frame.index[-1]).days > 7:
            skipped.append({"symbol": stock["symbol"], "reason": "Daily cache older than seven days"})
            continue
        crossing = recent_ma20_crossing(frame, lookback)
        if crossing:
            rows.append({**stock, **crossing})
    rows.sort(key=lambda row: (row["status"] != "CONTINUING", -(row["relative_volume"] or 0),
                               row["sessions_since_cross"], row["symbol"]))
    return {"lookback": lookback, "scanned": len(stocks), "rows": rows, "skipped": skipped,
            "generated_at": now.isoformat(), "disclaimer": DISCLAIMER}
