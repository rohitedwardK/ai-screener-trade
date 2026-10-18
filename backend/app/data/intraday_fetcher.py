"""15-minute intraday OHLCV for stock / commodity detail analysis.

Upstox 1-minute history is resampled to 15m when a token is present.
Nifty 50 names fall back to Yahoo `interval=15m`. MCX symbols require Upstox.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Literal, Tuple

import pandas as pd

from ..core.commodity_universe import COMMODITY_BY_SYMBOL, is_commodity_symbol
from . import intraday_csv_store, upstox_client
from .yf_client import pace

log = logging.getLogger(__name__)

_BAR_COLS = ["open", "high", "low", "close", "volume"]


def _normalise_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=_BAR_COLS)
    df = df.rename(columns=str.lower)
    missing = [c for c in _BAR_COLS if c not in df.columns]
    if missing:
        return pd.DataFrame(columns=_BAR_COLS)
    out = df[_BAR_COLS].copy().dropna(subset=["close"])
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    out.index = pd.to_datetime(out.index)
    out.index.name = "ts"
    return out.sort_index()


def _candles_to_frame(candles: list) -> pd.DataFrame:
    rows = []
    for raw in candles:
        if not isinstance(raw, list) or len(raw) < 6:
            continue
        try:
            ts_raw = raw[0]
            if isinstance(ts_raw, str):
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts.tzinfo is not None:
                    ts = ts.astimezone(tz=None).replace(tzinfo=None)
            else:
                continue
            rows.append({
                "ts": ts,
                "open": float(raw[1]),
                "high": float(raw[2]),
                "low": float(raw[3]),
                "close": float(raw[4]),
                "volume": float(raw[5] or 0),
            })
        except (TypeError, ValueError):
            continue
    if not rows:
        return _normalise_frame(pd.DataFrame())
    df = pd.DataFrame(rows).set_index("ts")
    return _normalise_frame(df)


IntradayInterval = Literal["15m", "30m", "60m"]


def _resample_minutes(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if df.empty:
        return df
    agg = df.resample(f"{minutes}min", label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    return _normalise_frame(agg.dropna(subset=["close"]))


def _fetch_upstox_1m(symbol: str, *, days: int) -> pd.DataFrame:
    key = upstox_client.instrument_key_for(symbol)
    if not key:
        return _normalise_frame(pd.DataFrame())
    end = date.today()
    start = end - timedelta(days=days)
    candles = upstox_client.fetch_historical_candles(
        key, start=start, end=end, interval="1minute",
    )
    return _candles_to_frame(candles)


def _fetch_yfinance_intraday(symbol: str, *, interval: IntradayInterval) -> pd.DataFrame:
    pace()
    import yfinance as yf

    yf_symbol = symbol
    if is_commodity_symbol(symbol):
        meta = COMMODITY_BY_SYMBOL.get(symbol)
        if meta is None:
            return _normalise_frame(pd.DataFrame())
        yf_symbol = meta.comex_symbol

    t = yf.Ticker(yf_symbol)
    df = t.history(
        period="5d",
        interval=interval,
        auto_adjust=True,
        actions=False,
        raise_errors=False,
    )
    return _normalise_frame(df)


def fetch_intraday_bars(
    symbol: str,
    *,
    interval: IntradayInterval = "15m",
    days: int = 5,
) -> Tuple[pd.DataFrame, str]:
    """Return recent intraday bars, falling back to the last matching cache."""
    sym = symbol.strip()
    minutes = 60 if interval == "60m" else 30 if interval == "30m" else 15

    if upstox_client.is_configured():
        raw = _fetch_upstox_1m(sym, days=days)
        if not raw.empty:
            bars = _resample_minutes(raw, minutes)
            if len(bars) >= 2:
                intraday_csv_store.merge_save(sym, bars, interval=interval)
                return bars.tail(240), "upstox"

    yf_bars = _fetch_yfinance_intraday(sym, interval=interval)
    if len(yf_bars) >= 2:
        label = "yfinance-proxy" if is_commodity_symbol(sym) else "yfinance"
        intraday_csv_store.merge_save(sym, yf_bars, interval=interval)
        return yf_bars.tail(240), label

    cached = intraday_csv_store.load(sym, interval=interval)
    if len(cached) >= 2:
        return cached.tail(240), "cached-intraday"

    return _normalise_frame(pd.DataFrame()), "none"


def fetch_15m_bars(symbol: str, *, days: int = 5) -> Tuple[pd.DataFrame, str]:
    """Return (15m OHLCV frame, source label)."""
    return fetch_intraday_bars(symbol, interval="15m", days=days)


__all__ = ["fetch_15m_bars", "fetch_intraday_bars"]
