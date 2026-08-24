"""Rolling 1-minute OHLCV store per index.

Two ways bars enter the store:

1. **Hydrate** on boot (or after a process restart inside a session):
   `hydrate_from_upstox(db, symbol)` pulls today's 1-min candles via
   `data.upstox_intraday.fetch_intraday_1min` and bulk-inserts them.

2. **Append per tick**: `append_tick(db, quote)` floors the quote's
   timestamp to the minute and updates (or creates) the bar for that
   minute. The same minute can be touched many times within 60s as the
   poll cadence overlaps a fresh bar boundary - each call updates
   high/low and overwrites close/volume from the most recent quote.

We keep `LIVE_MARKET_BAR_HISTORY` bars per symbol (default 375 = one
NSE session) and prune older rows in `prune_old`.

Pure DB layer. No analysis. No API.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

import pandas as pd
from sqlalchemy import asc, delete, desc, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..data.upstox_client import UpstoxQuote
from ..data.upstox_intraday import IntradayBar as RawBar, fetch_intraday_1min
from ..models.orm import IntradayBar

log = logging.getLogger(__name__)


def _floor_to_minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def _ts_from_quote(q: UpstoxQuote, *, fallback: datetime) -> datetime:
    """Use the exchange timestamp when present, else the wall clock.

    We strip timezone to keep things naive-UTC, matching ORM defaults.
    """
    if q.timestamp_ms > 0:
        ts = datetime.utcfromtimestamp(q.timestamp_ms / 1000.0)
    else:
        ts = fallback
    return _floor_to_minute(ts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def append_tick(
    db: Session, quote: UpstoxQuote, *, now: Optional[datetime] = None,
) -> IntradayBar:
    """Update or insert the 1-min bar for the quote's minute.

    If a bar already exists for (symbol, minute), we extend high/low and
    overwrite close/volume with the latest values. This makes the function
    idempotent at minute granularity even if called multiple times within
    the same minute.
    """
    when = now or datetime.utcnow()
    bar_ts = _ts_from_quote(quote, fallback=when)

    existing = db.scalar(
        select(IntradayBar).where(
            IntradayBar.symbol == quote.symbol,
            IntradayBar.ts == bar_ts,
        )
    )
    if existing is None:
        # New bar: open == current LTP because we only have a snapshot,
        # not a true bar open. Subsequent ticks within the minute will
        # extend the high/low naturally.
        bar = IntradayBar(
            symbol=quote.symbol,
            ts=bar_ts,
            open=float(quote.last_price),
            high=float(quote.last_price),
            low=float(quote.last_price),
            close=float(quote.last_price),
            volume=int(quote.volume),
        )
        db.add(bar)
        # Flush so the next call inside the same session (e.g. another
        # tick within the same wall-clock minute) sees this bar via the
        # query path instead of inserting a duplicate row.
        db.flush()
        return bar

    existing.high = max(existing.high, float(quote.last_price))
    existing.low = min(existing.low, float(quote.last_price))
    existing.close = float(quote.last_price)
    # Upstox volume is cumulative session volume, so the latest reading is
    # always the most accurate snapshot for the bar.
    existing.volume = int(quote.volume)
    return existing


def hydrate_from_upstox(db: Session, symbol: str) -> int:
    """Bulk-insert today's 1-min candles via Upstox historical-candle.

    Returns the count of NEW bars inserted (existing bars are left
    untouched). Empty list on token failure / network error - the caller
    should not treat that as fatal because the per-tick append path will
    rebuild the buffer minute by minute regardless.
    """
    bars = fetch_intraday_1min(symbol)
    if not bars:
        return 0

    existing_ts = {
        row[0]
        for row in db.execute(
            select(IntradayBar.ts).where(IntradayBar.symbol == symbol)
        )
    }
    inserted = 0
    for raw in bars:
        ts = _floor_to_minute(raw.ts)
        if ts in existing_ts:
            continue
        db.add(IntradayBar(
            symbol=symbol, ts=ts,
            open=raw.open, high=raw.high, low=raw.low, close=raw.close,
            volume=raw.volume,
        ))
        inserted += 1
    if inserted:
        log.info("intraday hydrate %s: +%d bars", symbol, inserted)
    return inserted


def prune_old(db: Session, symbol: str, *, keep: Optional[int] = None) -> int:
    """Drop bars beyond the rolling window cap. Returns rows deleted."""
    cap = keep if keep is not None else get_settings().LIVE_MARKET_BAR_HISTORY
    if cap <= 0:
        return 0
    # SQLite's window-function support is recent; do this with a 2-step
    # query instead so we work on the lowest common denominator.
    cutoff = db.scalar(
        select(IntradayBar.ts)
        .where(IntradayBar.symbol == symbol)
        .order_by(desc(IntradayBar.ts))
        .offset(cap)
        .limit(1)
    )
    if cutoff is None:
        return 0
    result = db.execute(
        delete(IntradayBar).where(
            IntradayBar.symbol == symbol,
            IntradayBar.ts < cutoff,
        )
    )
    return int(result.rowcount or 0)


def recent_bars(
    db: Session, symbol: str, *, lookback: Optional[int] = None,
) -> List[IntradayBar]:
    """Most recent N bars in ASCENDING time order (oldest first)."""
    n = lookback if lookback is not None else get_settings().LIVE_MARKET_BAR_HISTORY
    rows = list(db.scalars(
        select(IntradayBar)
        .where(IntradayBar.symbol == symbol)
        .order_by(desc(IntradayBar.ts))
        .limit(n)
    ))
    rows.reverse()
    return rows


def to_dataframe(bars: Iterable[IntradayBar]) -> pd.DataFrame:
    """Convert ORM bars to a tidy `[open, high, low, close, volume]` DataFrame."""
    rows = list(bars)
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame([
        {
            "ts": b.ts,
            "open": float(b.open), "high": float(b.high),
            "low": float(b.low), "close": float(b.close),
            "volume": int(b.volume),
        }
        for b in rows
    ])
    df = df.sort_values("ts").set_index("ts")
    df.index = pd.to_datetime(df.index)
    return df


def session_window(bars: Iterable[IntradayBar], *, session_minutes: int = 375) -> List[IntradayBar]:
    """Slice to today's NSE session bars (last `session_minutes` available).

    Convenience for VWAP / range detection that should reset at the
    session open instead of leaking yesterday's close into today's
    average.
    """
    rows = list(bars)
    if not rows:
        return rows
    return rows[-session_minutes:]


def latest_bar_age_seconds(db: Session, symbol: str, *, now: Optional[datetime] = None) -> Optional[float]:
    """Seconds since the most recent stored bar. None if there are no bars."""
    last_ts = db.scalar(
        select(IntradayBar.ts)
        .where(IntradayBar.symbol == symbol)
        .order_by(desc(IntradayBar.ts))
        .limit(1)
    )
    if last_ts is None:
        return None
    when = now or datetime.utcnow()
    return max((when - last_ts).total_seconds(), 0.0)


__all__ = [
    "append_tick",
    "hydrate_from_upstox",
    "prune_old",
    "recent_bars",
    "to_dataframe",
    "session_window",
    "latest_bar_age_seconds",
]
