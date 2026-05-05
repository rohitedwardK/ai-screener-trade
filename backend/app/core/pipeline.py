"""Refresh pipeline: fetch -> persist candles -> compute -> save snapshots/signals."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Tuple

from sqlalchemy.orm import Session

from ..analysis import indicators as ind_mod
from ..analysis.regime import classify
from ..analysis.signals import evaluate_symbol, signal_to_dict
from ..core.universe import all_symbols, stock_meta
from ..data import fetcher, repository as repo
from ..db import session_scope
from ..models.schemas import RefreshResult

log = logging.getLogger(__name__)


def _ensure_universe(db: Session) -> None:
    repo.upsert_stocks(db, stock_meta())


def run_full_refresh(
    period: str | None = None,
    interval: str | None = None,
    force_full: bool = False,
) -> RefreshResult:
    """Fetch all symbols (CSV-cached, incremental by default), compute indicators, persist signals.

    Args:
        period     : history period for first-time / forced full fetches (e.g. "5y").
        interval   : candle interval; "1d" is the only supported value for now.
        force_full : when True, ignore CSV cache and re-download full history for every symbol.
    """
    started = datetime.utcnow()
    errors: List[str] = []
    fetched = 0
    saved_signals = 0

    with session_scope() as db:
        _ensure_universe(db)

    symbols = all_symbols()
    log.info("Starting refresh for %d symbols (force_full=%s)", len(symbols), force_full)

    try:
        frames = fetcher.download_batch(
            symbols,
            period=period,
            interval=interval,
            force_full=force_full,
        )
    except Exception as exc:
        log.exception("Batch download failed")
        return RefreshResult(
            started_at=started,
            finished_at=datetime.utcnow(),
            fetched_symbols=0,
            signals_generated=0,
            errors=[f"download: {exc}"],
        )

    with session_scope() as db:
        signals_payload: List[dict] = []
        for symbol in symbols:
            df = frames.get(symbol)
            if df is None or df.empty:
                errors.append(f"{symbol}: no data")
                continue
            try:
                # On incremental runs only the most recent slice needs to be
                # upserted into SQLite; the older history is already there.
                # On the first run / forced full refresh we upsert everything.
                latest_known = repo.latest_candle_date(db, symbol)
                if latest_known is None or force_full:
                    repo.upsert_candles(db, symbol, df)
                else:
                    new_slice = df[df.index.date > latest_known]
                    if not new_slice.empty:
                        repo.upsert_candles(db, symbol, new_slice)
                fetched += 1

                # Compute indicators ONCE and reuse for both snapshot and signals.
                enriched = ind_mod.compute_all(df)
                regime, _ = classify(enriched)
                last_row = enriched.iloc[-1]
                ind_dict = ind_mod.latest_indicator_dict(enriched)
                repo.save_snapshot(
                    db,
                    symbol=symbol,
                    as_of=df.index[-1].date() if hasattr(df.index[-1], "date") else df.index[-1],
                    close=float(last_row["close"]),
                    indicators=ind_dict,
                    regime=regime,
                    atr=float(last_row.get("atr14")) if last_row.get("atr14") is not None else None,
                    atr_pct=float(last_row.get("atr_pct")) if last_row.get("atr_pct") is not None else None,
                )

                for rec in evaluate_symbol(symbol, df, df_enriched=enriched):
                    signals_payload.append(signal_to_dict(rec))
            except Exception as exc:
                log.exception("Pipeline failed for %s", symbol)
                errors.append(f"{symbol}: {exc}")

        # Stamp the entire run with one timestamp so "latest run" filter works.
        if signals_payload:
            run_at = datetime.utcnow()
            for s in signals_payload:
                s["run_at"] = run_at
            saved_signals = repo.save_signals(db, signals_payload)
            repo.purge_old_signals(db, keep_runs=10)

    finished = datetime.utcnow()
    log.info(
        "Refresh complete: fetched=%d signals=%d errors=%d duration=%.1fs",
        fetched, saved_signals, len(errors), (finished - started).total_seconds(),
    )

    return RefreshResult(
        started_at=started,
        finished_at=finished,
        fetched_symbols=fetched,
        signals_generated=saved_signals,
        errors=errors,
    )
