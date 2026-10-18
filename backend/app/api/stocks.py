"""Stock detail and history endpoints."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..analysis.daily_forecast import evaluate_daily_forecast
from ..api.commodities import build_commodity_detail
from ..core.commodity_universe import is_commodity_symbol
from ..analysis.intraday_scalp import DISCLAIMER as INTRADAY_DISCLAIMER, evaluate_intraday
from ..data import csv_store
from ..data.intraday_fetcher import fetch_15m_bars, fetch_intraday_bars
from ..data import live_quotes, repository as repo
from ..db import get_db
from ..models.orm import Signal
from ..models.schemas import (
    CandleOut,
    DailyForecastOut,
    IntradayAnalysisOut,
    IntradayCandleOut,
    IntradayScalpOut,
    SignalOut,
    SnapshotOut,
    StockDetailOut,
    StockOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/stocks", tags=["stocks"])


# ---------------------------------------------------------------------------

_RANGE_TO_BARS = {
    "1m": 22,
    "3m": 66,
    "6m": 132,
    "1y": 252,
    "2y": 504,
    "5y": 1260,
}


@router.get("", response_model=List[StockOut])
def list_stocks(db: Session = Depends(get_db)) -> List[StockOut]:
    return [
        StockOut.model_validate(s)
        for s in repo.list_stocks(db)
        if not is_commodity_symbol(s.symbol)
    ]


@router.get("/prices", response_model=Dict[str, float])
def get_prices(
    symbols: str = Query(..., description="Comma-separated list of symbols"),
    db: Session = Depends(get_db),
) -> Dict[str, float]:
    """Return the latest live price for each requested symbol.

    Tries Yahoo Finance (1-min bars, cached 30 s) first; falls back to the
    most recent stored snapshot so the endpoint always returns something.
    """
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        return {}

    live = live_quotes.fetch_live_prices(sym_list)

    result: Dict[str, float] = {}
    for sym in sym_list:
        if sym in live:
            result[sym] = live[sym]
        else:
            # Fallback: last stored snapshot
            snap = repo.latest_snapshot(db, sym)
            if snap is not None:
                result[sym] = float(snap.close)

    return result


@router.get("/{symbol}", response_model=StockDetailOut)
def get_stock(symbol: str, db: Session = Depends(get_db)) -> StockDetailOut:
    stock = repo.get_stock(db, symbol)
    if stock is None:
        raise HTTPException(404, f"Symbol {symbol} not found")
    snap = repo.latest_snapshot(db, symbol)
    sigs = repo.signals_for_symbol(db, symbol, limit=10)

    snap_out: Optional[SnapshotOut] = (
        SnapshotOut.model_validate(snap) if snap is not None else None
    )
    sig_out = [SignalOut.model_validate(s) for s in sigs]
    live_price = None
    quote_source = None
    contract_label = None
    watch_notes: List[str] = []

    # Commodity cards recompute from the MCX cache and Upstox LTP. The stored
    # snapshot is only the last daily close, so the detail page must use the
    # same view or it shows a stale price and an older trade plan.
    if is_commodity_symbol(symbol):
        view = build_commodity_detail(symbol, snap, stock)
        if view.snapshot is not None:
            snap_out = view.snapshot
        if view.signals is not None:
            sig_out = view.signals
        live_price = view.live_price
        quote_source = view.quote_source
        contract_label = view.contract_label
        watch_notes = view.watch_notes

    return StockDetailOut(
        stock=StockOut.model_validate(stock),
        snapshot=snap_out,
        signals=sig_out,
        live_price=live_price,
        quote_source=quote_source,
        contract_label=contract_label,
        watch_notes=watch_notes,
    )


@router.get("/{symbol}/history", response_model=List[CandleOut])
def get_history(
    symbol: str,
    range: str = Query("1y", description="One of: 1m, 3m, 6m, 1y, 2y, 5y"),
    db: Session = Depends(get_db),
) -> List[CandleOut]:
    bars = _RANGE_TO_BARS.get(range, 252)
    if is_commodity_symbol(symbol):
        # CSV is the series the commodity card scores. SQLite can lag that file.
        from ..data.mcx import drop_synthetic_bars, overlay_live_session

        df = overlay_live_session(drop_synthetic_bars(csv_store.load(symbol)), symbol)
        if not df.empty:
            df = df.tail(bars)
        else:
            df = repo.load_candles(db, symbol, limit=bars)
    else:
        df = repo.load_candles(db, symbol, limit=bars)
    if df.empty:
        return []
    out: List[CandleOut] = []
    for ts, row in df.iterrows():
        out.append(CandleOut(
            date=ts.date(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        ))
    return out


@router.get("/{symbol}/daily-forecast", response_model=DailyForecastOut)
def daily_forecast(symbol: str, db: Session = Depends(get_db)) -> DailyForecastOut:
    stock = repo.get_stock(db, symbol)
    if stock is None:
        raise HTTPException(404, f"Symbol {symbol} not found")
    df = csv_store.load(symbol)
    if is_commodity_symbol(symbol):
        from ..data.mcx import drop_synthetic_bars, overlay_live_session

        df = overlay_live_session(drop_synthetic_bars(df), symbol)
    if df.empty:
        raise HTTPException(404, f"No cached daily history found for {symbol}")
    result = evaluate_daily_forecast(symbol, df)
    payload = result.__dict__.copy()
    # Empty dict is not a valid DailyForecastMetricsOut; treat as omitted.
    if not payload.get("metrics"):
        payload["metrics"] = None
    if is_commodity_symbol(symbol) and result.probability_up is None:
        notes = list(payload.get("notes") or [])
        notes.append(
            "MCX Gold/Silver daily history is the Upstox front-month cache, "
            "about one year. This symbol does not have enough of that cache yet."
        )
        payload["notes"] = notes
    return DailyForecastOut(**payload)


@router.get("/{symbol}/intraday-history", response_model=List[IntradayCandleOut])
def intraday_history(
    symbol: str,
    interval: str = Query("30m", description="One of: 15m, 30m, 60m"),
    db: Session = Depends(get_db),
) -> List[IntradayCandleOut]:
    stock = repo.get_stock(db, symbol)
    if stock is None:
        raise HTTPException(404, f"Symbol {symbol} not found")
    if interval not in {"15m", "30m", "60m"}:
        raise HTTPException(400, "interval must be one of: 15m, 30m, 60m")

    bars_df, _source = fetch_intraday_bars(symbol, interval=interval)  # type: ignore[arg-type]
    return [
        IntradayCandleOut(
            ts=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for ts, row in bars_df.iterrows()
    ]


@router.get("/{symbol}/intraday-analysis", response_model=IntradayAnalysisOut)
def intraday_analysis(
    symbol: str,
    signal_id: Optional[int] = Query(None, description="Optional persisted signal id for alignment"),
    db: Session = Depends(get_db),
) -> IntradayAnalysisOut:
    """15m candlestick + quick scalp suggestions for the detail page."""
    stock = repo.get_stock(db, symbol)
    if stock is None:
        raise HTTPException(404, f"Symbol {symbol} not found")

    sig_row: Optional[Signal] = None
    if signal_id is not None:
        sig_row = db.get(Signal, signal_id)
        if sig_row is None or sig_row.symbol != symbol:
            raise HTTPException(404, f"Signal {signal_id} not found for {symbol}")

    bars_df, source = fetch_15m_bars(symbol)
    if bars_df.empty:
        return IntradayAnalysisOut(
            symbol=symbol,
            source=source,
            regime="UNKNOWN",
            signal_id=signal_id,
            signal_category=sig_row.category if sig_row else None,
            signal_direction=sig_row.direction if sig_row else None,
            disclaimer=INTRADAY_DISCLAIMER,
        )

    analysis = evaluate_intraday(
        bars_df,
        signal_direction=sig_row.direction if sig_row else None,
    )

    candle_out = [
        IntradayCandleOut(
            ts=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for ts, row in bars_df.iterrows()
    ]

    scalp_out = [
        IntradayScalpOut(
            category=s.category,
            direction=s.direction,
            score=s.score,
            entry=s.entry,
            stop_loss=s.stop_loss,
            target_1=s.target_1,
            target_2=s.target_2,
            invalidation=s.invalidation,
            hold_minutes=s.hold_minutes,
            reasons=s.reasons,
        )
        for s in analysis.scalps
    ]

    return IntradayAnalysisOut(
        symbol=symbol,
        source=source,
        regime=analysis.regime,
        bars=candle_out,
        support=analysis.support,
        resistance=analysis.resistance,
        vwap=analysis.vwap,
        atr=analysis.atr,
        rsi=analysis.rsi,
        patterns=analysis.patterns,
        scalps=scalp_out,
        signal_id=signal_id,
        signal_category=sig_row.category if sig_row else None,
        signal_direction=sig_row.direction if sig_row else None,
        aligned_with_signal=analysis.aligned_with_signal,
        disclaimer=INTRADAY_DISCLAIMER,
    )
