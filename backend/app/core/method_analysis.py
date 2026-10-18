"""Reusable services for method comparison and live-mover analysis.

FastAPI routes and agent capabilities both depend on this module so neither
layer needs to import private helpers from the other.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..analysis.indicators import compute_all
from ..analysis.signals import evaluate_symbol
from ..core.universe import all_symbols, stock_meta
from ..data import csv_store, live_quotes, upstox_client
from ..db import session_scope
from ..live_analysis.movers import MoverInput, rank_top_k
from ..models.orm import Candle

log = logging.getLogger(__name__)

AVG_VOLUME_WINDOW_DAYS = 20


def baseline_prev_close_avg_vol(
    db: Session,
    symbols: List[str],
) -> Dict[str, Tuple[float, int]]:
    """Map symbols to their prior close and trailing average daily volume."""
    out: Dict[str, Tuple[float, int]] = {}
    for symbol in symbols:
        rows = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == symbol)
                .order_by(desc(Candle.date))
                .limit(AVG_VOLUME_WINDOW_DAYS)
            )
        )
        if not rows:
            continue
        previous_close = float(rows[0].close)
        if len(rows) >= 2:
            average_volume = int(
                sum(float(row.volume) for row in rows[1:]) / max(len(rows) - 1, 1)
            )
        else:
            average_volume = int(rows[0].volume)
        out[symbol] = (previous_close, average_volume)
    return out


def fetch_quotes(
    symbols: List[str],
) -> Tuple[Dict[str, float], Dict[str, int], Dict[str, float], str]:
    """Fetch Upstox quotes first, falling back to yfinance prices."""
    if upstox_client.is_configured():
        quotes = upstox_client.fetch_quotes_batch(symbols)
        if quotes:
            return (
                {symbol: quote.last_price for symbol, quote in quotes.items()},
                {symbol: quote.volume for symbol, quote in quotes.items()},
                {
                    symbol: quote.close_prev
                    for symbol, quote in quotes.items()
                    if quote.close_prev > 0
                },
                "upstox",
            )
    return live_quotes.fetch_live_prices(symbols), {}, {}, "yfinance"


def get_live_movers(k: int = 15) -> Dict[str, object]:
    """Return ranked Nifty-50 movers with source and freshness metadata."""
    names = {item["symbol"]: item["name"] for item in stock_meta()}
    symbols = all_symbols()
    with session_scope() as db:
        baseline = baseline_prev_close_avg_vol(db, symbols)

    prices, volumes, feed_closes, source = fetch_quotes(symbols)
    inputs: List[MoverInput] = []
    for symbol in symbols:
        last = prices.get(symbol)
        if not last or last <= 0:
            continue
        previous_close, average_volume = baseline.get(symbol, (0.0, 0))
        previous_close = feed_closes.get(symbol, previous_close) or previous_close
        if previous_close <= 0:
            continue
        inputs.append(
            MoverInput(
                symbol=symbol,
                last_price=float(last),
                prev_close=float(previous_close),
                volume=int(volumes.get(symbol, 0)),
                avg_volume=max(average_volume, 1),
            )
        )

    ranked = rank_top_k(inputs, k=max(1, min(k, 50)))
    return {
        "movers": [
            {
                "rank": mover.rank,
                "symbol": mover.symbol,
                "name": names.get(mover.symbol),
                "last_price": mover.last_price,
                "pct_change": mover.pct_change,
                "rvol": mover.rvol,
                "score": mover.score,
            }
            for mover in ranked
        ],
        "source": source,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def run_rule_based(name_map: Dict[str, str], top_k: int = 15) -> List[dict]:
    """Convert each cached symbol's strongest rule-based signal to a card."""
    best_per_symbol: Dict[str, dict] = {}
    for symbol in csv_store.list_cached_symbols():
        raw = csv_store.load(symbol)
        if len(raw) < 60:
            continue
        try:
            enriched = compute_all(raw)
            records = evaluate_symbol(symbol, raw, df_enriched=enriched)
        except Exception:
            log.debug("Rule-based eval failed for %s", symbol, exc_info=True)
            continue

        for record in records:
            previous = best_per_symbol.get(symbol)
            if previous is None or record.confidence > previous["confidence"]:
                best_per_symbol[symbol] = {
                    "symbol": symbol,
                    "name": name_map.get(symbol),
                    "confidence": round(record.confidence, 3),
                    "direction": record.direction,
                    "category": record.category,
                    "regime": record.regime,
                    "close": float(raw.iloc[-1]["close"]) if not raw.empty else 0.0,
                    "top_factors": record.reasons[:5],
                }

    cards = sorted(best_per_symbol.values(), key=lambda card: -card["confidence"])
    return cards[: max(1, min(top_k, 50))]


__all__ = [
    "AVG_VOLUME_WINDOW_DAYS",
    "baseline_prev_close_avg_vol",
    "fetch_quotes",
    "get_live_movers",
    "run_rule_based",
]
