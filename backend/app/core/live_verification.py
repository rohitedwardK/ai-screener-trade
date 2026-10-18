"""Live screener verification orchestrator.

Bridges the pure verifier module with the rest of the stack:

    repository / signals  ─┐
    csv_store              ├─►  live_verifier.project_today_bar
    live_quotes (LTP)      ┘                       │
                                                   ▼
                            indicators.compute_all + regime.classify
                            signals.evaluate_symbol  (live re-eval)
                                                   │
                                                   ▼
                                           live_verifier.verify_signal
                                                   │
                                                   ▼
                                  upsert into live_signal_verifications

This is a sibling to `core/pipeline.py`. The EOD pipeline persists
historical signals; this orchestrator persists their live cross-checks
without ever rewriting the original `signals` rows.

All side effects (DB writes, network fetches) live here; `analysis/live_verifier`
stays pure and deterministic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis import indicators as ind_mod
from ..analysis import live_verifier as lv
from ..analysis.regime import classify
from ..analysis.signals import evaluate_symbol
from ..data import csv_store, live_quotes, repository as repo
from ..db import session_scope
from ..models.orm import LiveSignalVerification, Signal

log = logging.getLogger(__name__)


@dataclass
class LiveVerificationResult:
    """Summary of one verification run, returned by the API and logged."""
    started_at: datetime
    finished_at: datetime
    signals_evaluated: int
    rows_upserted: int
    by_status: Dict[str, int] = field(default_factory=dict)
    source: str = "none"
    errors: List[str] = field(default_factory=list)


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    return f


def _persisted_dto_from_signal(sig: Signal) -> lv.PersistedSignal:
    """Adapt the ORM row into the verifier-friendly DTO.

    Reads the persisted indicator dict off the signal's most-recent snapshot
    (which is loaded by the caller and passed in). When the snapshot is
    missing — e.g. a fresh DB or a symbol whose snapshot was purged —
    we fall back to None and the verifier treats RSI/regime deltas as
    unknown rather than asserting.
    """
    return lv.PersistedSignal(
        id=int(sig.id),
        symbol=str(sig.symbol),
        category=str(sig.category),
        score=float(sig.score),
        entry=_safe_float(sig.entry),
        stop_loss=_safe_float(sig.stop_loss),
        target_1=_safe_float(sig.target_1),
        direction=str(sig.direction) if getattr(sig, "direction", None) else None,
    )


def _enrich_with_snapshot(
    persisted: lv.PersistedSignal,
    snapshot,
) -> lv.PersistedSignal:
    """Attach persisted RSI / regime read from the latest snapshot."""
    if snapshot is None:
        return persisted
    indicators = snapshot.indicators_json or {}
    rsi_val = _safe_float(indicators.get("rsi14"))
    regime = str(snapshot.regime) if snapshot.regime else None
    return lv.PersistedSignal(
        id=persisted.id,
        symbol=persisted.symbol,
        category=persisted.category,
        score=persisted.score,
        entry=persisted.entry,
        stop_loss=persisted.stop_loss,
        target_1=persisted.target_1,
        persisted_rsi=rsi_val,
        persisted_regime=regime,
        direction=persisted.direction,
    )


def _live_re_evaluate(
    symbol: str,
    daily_df: pd.DataFrame,
    ltp: float,
) -> Optional[Tuple[Dict[str, Optional[float]], str, List[str], Dict[str, float]]]:
    """Project a today-bar, recompute indicators, and run the rule engine.

    Returns (indicator_dict, regime, live_categories, scores_by_category)
    or None if the cached history is too short for a meaningful re-evaluation.
    """
    if daily_df is None or daily_df.empty or len(daily_df) < 60:
        return None

    try:
        projected = lv.project_today_bar(daily_df, ltp)
    except ValueError as exc:
        log.debug("project_today_bar failed for %s: %s", symbol, exc)
        return None

    enriched = ind_mod.compute_all(projected)
    regime, _detail = classify(enriched)
    live_indicators = ind_mod.latest_indicator_dict(enriched)

    live_recs = evaluate_symbol(symbol, projected, df_enriched=enriched)
    live_categories = [r.category for r in live_recs]
    scores_by_cat = {r.category: float(r.score) for r in live_recs}

    return live_indicators, regime, live_categories, scores_by_cat


def _upsert_verification(
    db: Session,
    record: lv.VerificationRecord,
    *,
    source: str,
    run_at: datetime,
) -> None:
    """Insert / update one row in `live_signal_verifications`.

    We keep one row per `signal_id` (latest wins). This avoids unbounded
    growth and matches the UI which only renders the most recent reconcil-
    iation. History is implicit in the `signals` run_at timestamp.
    """
    existing = db.scalar(
        select(LiveSignalVerification)
        .where(LiveSignalVerification.signal_id == record.signal_id)
    )
    payload = {
        "symbol": record.symbol,
        "run_at": run_at,
        "status": record.status,
        "live_close": record.live_close,
        "live_rsi": record.live_rsi,
        "live_adx": record.live_adx,
        "live_regime": record.live_regime,
        "score_delta": record.score_delta,
        "distance_to_stop_pct": record.distance_to_stop_pct,
        "distance_to_t1_pct": record.distance_to_t1_pct,
        "notes_json": list(record.notes),
        "source": source,
    }
    if existing is None:
        db.add(LiveSignalVerification(signal_id=record.signal_id, **payload))
    else:
        for k, v in payload.items():
            setattr(existing, k, v)
    signal = db.get(Signal, record.signal_id)
    if signal is not None:
        repo.archive_quality_observation(db, signal, {
            "run_at": run_at.isoformat(), "status": record.status,
            "live_close": record.live_close, "live_rsi": record.live_rsi,
            "live_adx": record.live_adx, "score_delta": record.score_delta,
        })


def _purge_stale_verifications(
    db: Session,
    keep_signal_ids: set[int],
) -> int:
    """Delete verification rows whose underlying signal is no longer current.

    The screener UI only displays the latest run's signals (see
    `repository.latest_signals`). Verification rows pointing at older runs
    serve no purpose and would confuse the dashboard counters; we drop them
    every run so the table stays in sync.
    """
    rows = list(db.scalars(select(LiveSignalVerification)))
    deleted = 0
    for row in rows:
        if row.signal_id not in keep_signal_ids:
            db.delete(row)
            deleted += 1
    return deleted


def run_live_verification(
    *,
    symbols: Optional[List[str]] = None,
    db: Optional[Session] = None,
) -> LiveVerificationResult:
    """Execute one verification pass over the latest persisted signals.

    Args:
        symbols : Optional whitelist of symbols to verify. None = all
                  symbols present in the latest signal run.
        db      : Optional pre-opened session. When None we open our own
                  inside `session_scope` so the function remains usable
                  from APScheduler jobs and ad-hoc CLIs.

    Idempotent. Safe to fire from cron, manual Refresh, and tests alike.
    """
    started = datetime.utcnow()
    errors: List[str] = []
    by_status: Dict[str, int] = {s: 0 for s in lv.ALL_STATUSES}
    rows_upserted = 0
    signals_evaluated = 0
    source_label = live_quotes.SOURCE_NONE

    own_session = db is None
    db_ctx = session_scope() if own_session else None
    try:
        if db_ctx is not None:
            db = db_ctx.__enter__()
        assert db is not None

        signals = repo.latest_signals(db)
        if not signals:
            return LiveVerificationResult(
                started_at=started,
                finished_at=datetime.utcnow(),
                signals_evaluated=0,
                rows_upserted=0,
                by_status=by_status,
                source=source_label,
                errors=["no signals to verify"],
            )

        if symbols:
            wanted = {s.upper() for s in symbols}
            signals = [s for s in signals if s.symbol.upper() in wanted]

        unique_symbols = sorted({s.symbol for s in signals})
        ltps = live_quotes.fetch_live_prices(unique_symbols) if unique_symbols else {}
        source_label = live_quotes.last_source()

        cached_dfs: Dict[str, pd.DataFrame] = {}
        live_evals: Dict[str, Optional[Tuple[Dict[str, Optional[float]], str, List[str], Dict[str, float]]]] = {}
        for sym in unique_symbols:
            ltp = ltps.get(sym)
            if ltp is None or not pd.notna(ltp) or ltp <= 0:
                continue
            df = cached_dfs.setdefault(sym, csv_store.load(sym))
            try:
                live_evals[sym] = _live_re_evaluate(sym, df, float(ltp))
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not block the run
                log.exception("live re-eval failed for %s", sym)
                errors.append(f"{sym}: {exc}")

        run_at = datetime.utcnow()
        kept_ids: set[int] = set()
        for sig in signals:
            ltp = ltps.get(sig.symbol)
            if ltp is None or not pd.notna(ltp) or ltp <= 0:
                continue
            live_eval = live_evals.get(sig.symbol)
            if live_eval is None:
                continue

            indicators, regime, categories, scores = live_eval
            persisted = _persisted_dto_from_signal(sig)
            persisted = _enrich_with_snapshot(
                persisted,
                repo.latest_snapshot(db, sig.symbol),
            )

            try:
                record = lv.verify_signal(
                    persisted,
                    live_price=float(ltp),
                    live_rsi=indicators.get("rsi14"),
                    live_adx=indicators.get("adx"),
                    live_regime=regime,
                    live_atr=indicators.get("atr14"),
                    live_categories=categories,
                    live_score=scores.get(persisted.category),
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("verify_signal failed for %s", sig.symbol)
                errors.append(f"{sig.symbol}#{sig.id}: {exc}")
                continue

            _upsert_verification(db, record, source=source_label, run_at=run_at)
            kept_ids.add(record.signal_id)
            by_status[record.status] = by_status.get(record.status, 0) + 1
            signals_evaluated += 1
            rows_upserted += 1

        _purge_stale_verifications(db, kept_ids)
        if own_session:
            db.commit()
    finally:
        if db_ctx is not None:
            db_ctx.__exit__(None, None, None)

    finished = datetime.utcnow()
    log.info(
        "live verification complete: signals=%d upserted=%d source=%s "
        "confirmed=%d weakening=%d invalidated=%d strengthened=%d errors=%d",
        signals_evaluated, rows_upserted, source_label,
        by_status.get(lv.STATUS_CONFIRMED, 0),
        by_status.get(lv.STATUS_WEAKENING, 0),
        by_status.get(lv.STATUS_INVALIDATED, 0),
        by_status.get(lv.STATUS_STRENGTHENED, 0),
        len(errors),
    )
    return LiveVerificationResult(
        started_at=started,
        finished_at=finished,
        signals_evaluated=signals_evaluated,
        rows_upserted=rows_upserted,
        by_status=by_status,
        source=source_label,
        errors=errors,
    )


def get_summary(db: Session) -> Dict[str, object]:
    """Counts by status for the dashboard banner. Runs in O(rows)."""
    rows = list(db.scalars(select(LiveSignalVerification)))
    counters = {s: 0 for s in lv.ALL_STATUSES}
    last_run_at: Optional[datetime] = None
    source: Optional[str] = None
    for row in rows:
        counters[row.status] = counters.get(row.status, 0) + 1
        if last_run_at is None or (row.run_at and row.run_at > last_run_at):
            last_run_at = row.run_at
            source = row.source
    return {
        "confirmed": counters.get(lv.STATUS_CONFIRMED, 0),
        "weakening": counters.get(lv.STATUS_WEAKENING, 0),
        "invalidated": counters.get(lv.STATUS_INVALIDATED, 0),
        "strengthened": counters.get(lv.STATUS_STRENGTHENED, 0),
        "total": len(rows),
        "last_run_at": last_run_at.isoformat() if last_run_at else None,
        "source": source,
    }


__all__ = [
    "LiveVerificationResult",
    "run_live_verification",
    "get_summary",
]
