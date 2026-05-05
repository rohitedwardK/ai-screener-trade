"""Index refresh pipeline.

Mirrors `app.core.pipeline.run_full_refresh` but for the index universe:
fetch daily OHLCV → mirror to SQLite → compute indicators → fetch option
chain (Nifty / Bank Nifty only) → derive snapshot summary → run
`evaluate_index` → persist signals.

Intraday refresh is a separate, lighter loop that just refreshes intraday
CSVs and re-runs `evaluate_index` against a recent slice (kept in
`refresh_intraday`).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from ..analysis import index_signals as idx_signals
from ..analysis import option_chain_metrics as ocm
from ..analysis.indicators import compute_all, latest_indicator_dict
from ..analysis.regime import classify
from ..core.index_universe import INDICES, all_index_symbols, get_index, index_meta
from ..data import (
    index_csv_store,
    index_fetcher,
    index_repository as idx_repo,
    option_chain as oc_data,
)
from ..db import session_scope
from ..models.schemas import RefreshResult

log = logging.getLogger(__name__)


def _ensure_universe(db: Session) -> None:
    idx_repo.upsert_indices(db, index_meta())


def _fetch_chain_summary(
    code: str, underlying_yf_symbol: str, *, spot: float,
) -> Tuple[Optional[ocm.ChainSummary], List[ocm.OCRow], Optional[str], Optional[str]]:
    """Fetch + summarise option chain. Returns (summary, rows, source, expiry_iso)."""
    try:
        payload = oc_data.fetch_option_chain(code, underlying_yf_symbol)
    except Exception:  # noqa: BLE001
        log.exception("option chain fetch failed for %s", code)
        return None, [], None, None
    if payload is None:
        return None, [], None, None
    rows = [
        ocm.OCRow(
            strike=r.strike,
            ce_oi=r.ce_oi, ce_change_oi=r.ce_change_oi, ce_volume=r.ce_volume,
            ce_iv=r.ce_iv, ce_ltp=r.ce_ltp,
            pe_oi=r.pe_oi, pe_change_oi=r.pe_change_oi, pe_volume=r.pe_volume,
            pe_iv=r.pe_iv, pe_ltp=r.pe_ltp,
        )
        for r in payload.rows
    ]
    summary = ocm.summarise(rows, spot=payload.spot or spot)
    return summary, rows, payload.source, payload.expiry.isoformat()


def _summary_to_dict(s: ocm.ChainSummary, *, source: str, expiry: Optional[str]) -> Dict:
    return {
        "pcr": s.pcr,
        "pcr_volume": s.pcr_volume,
        "max_pain": s.max_pain,
        "max_pain_distance_pct": s.max_pain_distance_pct,
        "total_ce_oi": s.total_ce_oi,
        "total_pe_oi": s.total_pe_oi,
        "total_ce_change_oi": s.total_ce_change_oi,
        "total_pe_change_oi": s.total_pe_change_oi,
        "iv_skew": s.iv_skew,
        "bias": s.bias,
        "bias_strength": s.bias_strength,
        "notes": s.notes,
        "source": source,
        "expiry": expiry,
    }


def _persist_option_snapshots(
    db: Session, *, symbol: str, code: str, spot: Optional[float],
    expiry_iso: Optional[str], rows: List[ocm.OCRow], source: Optional[str],
) -> None:
    if not rows or expiry_iso is None or source is None:
        return
    from datetime import date as _date, datetime as _dt
    try:
        expiry = _dt.fromisoformat(expiry_iso).date()
    except ValueError:
        return
    snapshot_at = datetime.utcnow()
    payload = []
    for r in rows:
        payload.append({
            "symbol": code,
            "underlying_yf_symbol": symbol,
            "snapshot_at": snapshot_at,
            "expiry": expiry,
            "strike": r.strike,
            "spot": spot,
            "ce_oi": r.ce_oi, "ce_change_oi": r.ce_change_oi, "ce_volume": r.ce_volume,
            "ce_iv": r.ce_iv, "ce_ltp": r.ce_ltp,
            "pe_oi": r.pe_oi, "pe_change_oi": r.pe_change_oi, "pe_volume": r.pe_volume,
            "pe_iv": r.pe_iv, "pe_ltp": r.pe_ltp,
            "source": source,
        })
    idx_repo.insert_option_snapshots(db, payload)


def run_full_refresh(force_full: bool = False) -> RefreshResult:
    """Daily index refresh: OHLCV + indicators + option chain summary + signals."""
    started = datetime.utcnow()
    errors: List[str] = []
    fetched = 0
    saved_signals = 0

    with session_scope() as db:
        _ensure_universe(db)

    symbols = all_index_symbols()
    log.info("Starting index refresh for %d symbols (force_full=%s)", len(symbols), force_full)

    try:
        frames = index_fetcher.download_daily_batch(symbols, force_full=force_full)
    except Exception as exc:  # noqa: BLE001
        log.exception("Index batch download failed")
        return RefreshResult(
            started_at=started, finished_at=datetime.utcnow(),
            fetched_symbols=0, signals_generated=0,
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
                meta = get_index(symbol)
                if meta is None:
                    errors.append(f"{symbol}: missing meta")
                    continue
                code = meta.code

                latest_known = idx_repo.latest_candle_date(db, symbol)
                if latest_known is None or force_full:
                    idx_repo.upsert_candles(db, symbol, df)
                else:
                    new_slice = df[df.index.date > latest_known]
                    if not new_slice.empty:
                        idx_repo.upsert_candles(db, symbol, new_slice)
                fetched += 1

                enriched = compute_all(df)
                regime, _ = classify(enriched)
                last_row = enriched.iloc[-1]
                ind_dict = latest_indicator_dict(enriched)
                spot = float(last_row["close"])

                # Option chain summary (Nifty / BankNifty / FinNifty supported by NSE).
                chain_summary = None
                chain_rows: List[ocm.OCRow] = []
                chain_source = None
                chain_expiry = None
                if meta.has_options:
                    chain_summary, chain_rows, chain_source, chain_expiry = _fetch_chain_summary(
                        code, symbol, spot=spot,
                    )
                summary_dict = (
                    _summary_to_dict(chain_summary, source=chain_source or "n/a", expiry=chain_expiry)
                    if chain_summary is not None else None
                )

                idx_repo.save_snapshot(
                    db,
                    symbol=symbol,
                    as_of=df.index[-1].date() if hasattr(df.index[-1], "date") else df.index[-1],
                    close=spot,
                    indicators=ind_dict,
                    regime=regime,
                    atr=float(last_row.get("atr14")) if last_row.get("atr14") is not None else None,
                    atr_pct=float(last_row.get("atr_pct")) if last_row.get("atr_pct") is not None else None,
                    option_chain_summary=summary_dict,
                )

                if chain_summary is not None and chain_rows:
                    _persist_option_snapshots(
                        db, symbol=symbol, code=code, spot=spot,
                        expiry_iso=chain_expiry, rows=chain_rows, source=chain_source,
                    )

                bias = chain_summary.bias if chain_summary is not None else None
                strength = chain_summary.bias_strength if chain_summary is not None else 0.0
                notes = chain_summary.notes if chain_summary is not None else None

                for rec in idx_signals.evaluate_index(
                    symbol, code, df,
                    chain_bias=bias, chain_strength=strength, chain_notes=notes,
                ):
                    signals_payload.append(idx_signals.signal_to_dict(rec))
            except Exception as exc:  # noqa: BLE001
                log.exception("Index pipeline failed for %s", symbol)
                errors.append(f"{symbol}: {exc}")

        if signals_payload:
            run_at = datetime.utcnow()
            for s in signals_payload:
                s["run_at"] = run_at
            saved_signals = idx_repo.save_signals(db, signals_payload)
            idx_repo.purge_old_signals(db, keep_runs=10)

    finished = datetime.utcnow()
    log.info(
        "Index refresh complete: fetched=%d signals=%d errors=%d duration=%.1fs",
        fetched, saved_signals, len(errors), (finished - started).total_seconds(),
    )
    return RefreshResult(
        started_at=started,
        finished_at=finished,
        fetched_symbols=fetched,
        signals_generated=saved_signals,
        errors=errors,
    )


def refresh_intraday() -> Dict[str, int]:
    """Lightweight intraday refresh: pull recent intraday bars + re-run signals.

    This runs every `intraday_signal_minutes` during market hours via the
    scheduler. We *don't* re-fetch the option chain on every tick (NSE has
    rate limits and the daily snapshot already captured the bias); the
    intraday run reuses the latest persisted summary."""
    out = {"fetched": 0, "signals": 0, "errors": 0}
    symbols = all_index_symbols()
    try:
        frames = index_fetcher.download_intraday_batch(symbols)
    except Exception:  # noqa: BLE001
        log.exception("Intraday index batch fetch failed")
        out["errors"] = len(symbols)
        return out

    with session_scope() as db:
        signals_payload: List[dict] = []
        for symbol in symbols:
            df = frames.get(symbol)
            if df is None or df.empty:
                continue
            meta = get_index(symbol)
            if meta is None:
                continue
            try:
                # Use the daily candles for proper indicator history; intraday
                # only updates the most recent close. Combine: take daily
                # frame and append today's last intraday close as a synthetic
                # last candle. Keeps RSI/EMA stable.
                daily = idx_repo.load_candles(db, symbol)
                if daily.empty:
                    continue
                last_intraday = df.iloc[-1]
                synthesized = daily.copy()
                from datetime import datetime as _dt
                today_ts = pd.Timestamp(_dt.utcnow().date())
                synthesized.loc[today_ts] = {
                    "open": float(last_intraday["open"]),
                    "high": float(df["high"].max()),
                    "low": float(df["low"].min()),
                    "close": float(last_intraday["close"]),
                    "volume": float(df["volume"].sum() if "volume" in df.columns else 0.0),
                }
                synthesized = synthesized.sort_index()

                snap = idx_repo.latest_snapshot(db, symbol)
                summary = (snap.option_chain_summary_json or {}) if snap else {}
                bias = summary.get("bias")
                strength = float(summary.get("bias_strength") or 0.0)
                notes = summary.get("notes") or []

                for rec in idx_signals.evaluate_index(
                    symbol, meta.code, synthesized,
                    chain_bias=bias, chain_strength=strength, chain_notes=notes,
                ):
                    signals_payload.append(idx_signals.signal_to_dict(rec))
                out["fetched"] += 1
            except Exception:  # noqa: BLE001
                log.exception("Intraday refresh failed for %s", symbol)
                out["errors"] += 1

        if signals_payload:
            run_at = datetime.utcnow()
            for s in signals_payload:
                s["run_at"] = run_at
            out["signals"] = idx_repo.save_signals(db, signals_payload)

    return out
