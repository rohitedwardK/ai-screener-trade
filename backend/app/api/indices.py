"""Index analysis endpoints — list / detail / option-chain / live prices."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Dict, FrozenSet, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..analysis import option_chain_metrics as ocm
from ..core.index_universe import all_index_symbols, get_index, index_meta
from ..data import index_fetcher, index_repository as idx_repo, option_chain as oc_data
from ..db import get_db
from ..models.index_orm import IndexStrikeRecommendation
from ..models.index_schemas import (
    ContractRecommendationOut,
    IndexCandleOut,
    IndexDetailOut,
    IndexInstrumentOut,
    IndexRow,
    IndexSignalOut,
    IndexSnapshotOut,
    OptionChainOut,
    OptionChainRow,
    OptionChainSummary,
    StrikeLegOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/indices", tags=["indices"])


# Live-quote cache (TTL = 30s) — same pattern as the stocks endpoint.
_LIVE_TTL = 30.0
_lock = threading.Lock()
_cache: Dict[str, float] = {}
_cache_keys: FrozenSet[str] = frozenset()
_cache_at: float = 0.0


def _live_prices(symbols: List[str]) -> Dict[str, float]:
    global _cache, _cache_keys, _cache_at
    key = frozenset(symbols)
    now = time.monotonic()
    with _lock:
        if key == _cache_keys and (now - _cache_at) < _LIVE_TTL:
            return dict(_cache)
    result = index_fetcher.fetch_live_index_prices(symbols)
    if result:
        with _lock:
            _cache = dict(result)
            _cache_keys = key
            _cache_at = now
    return result


_RANGE_TO_BARS = {"1m": 22, "3m": 66, "6m": 132, "1y": 252, "2y": 504, "5y": 1260}


def _rec_to_schema(rec: IndexStrikeRecommendation) -> ContractRecommendationOut:
    """Map the ORM recommendation row to the API schema (legs are JSON, not ORM)."""
    legs = [StrikeLegOut.model_validate(l) for l in (rec.legs_json or [])]
    return ContractRecommendationOut(
        id=int(rec.id),
        signal_id=int(rec.signal_id),
        symbol=rec.symbol,
        code=rec.code,
        strategy=rec.strategy,
        direction=rec.direction,
        expiry=rec.expiry,
        legs=legs,
        net_debit=float(rec.net_debit),
        max_profit=float(rec.max_profit) if rec.max_profit is not None else None,
        max_loss=float(rec.max_loss),
        entry_premium=float(rec.entry_premium),
        sl_premium=float(rec.sl_premium),
        t1_premium=float(rec.t1_premium),
        t2_premium=float(rec.t2_premium),
        breakeven=float(rec.breakeven) if rec.breakeven is not None else None,
        notes=list(rec.notes_json or []),
        rejection_reason=rec.rejection_reason,
        status=rec.status,
        last_premium=float(rec.last_premium) if rec.last_premium is not None else None,
        last_checked_at=rec.last_checked_at,
        created_at=rec.created_at,
    )


@router.get("", response_model=List[IndexInstrumentOut])
def list_indices(db: Session = Depends(get_db)) -> List[IndexInstrumentOut]:
    rows = idx_repo.list_indices(db)
    if not rows:
        idx_repo.upsert_indices(db, index_meta())
        rows = idx_repo.list_indices(db)
    return [IndexInstrumentOut.model_validate(r) for r in rows]


@router.get("/dashboard", response_model=List[IndexRow])
def dashboard(db: Session = Depends(get_db)) -> List[IndexRow]:
    out: List[IndexRow] = []
    for sym in all_index_symbols():
        meta = get_index(sym)
        if meta is None:
            continue
        snap = idx_repo.latest_snapshot(db, sym)
        signals = idx_repo.signals_for_symbol(db, sym, limit=1)
        sig = signals[0] if signals else None
        ind = (snap.indicators_json if snap else {}) or {}
        chain = (snap.option_chain_summary_json if snap else None) or {}
        chain_dict = chain if isinstance(chain, dict) else {}
        out.append(IndexRow(
            symbol=sym,
            code=meta.code,
            name=meta.name,
            exchange=meta.exchange,
            close=float(snap.close) if snap else 0.0,
            regime=snap.regime if snap else "RANGE",
            score=float(sig.score) if sig else 0.0,
            confidence=float(sig.confidence) if sig else 0.0,
            direction=sig.direction if sig else None,
            rsi=ind.get("rsi14"),
            adx=ind.get("adx"),
            atr_pct=ind.get("atr_pct"),
            pivot_p=ind.get("pivot_p"),
            pivot_r1=ind.get("pivot_r1"),
            pivot_s1=ind.get("pivot_s1"),
            pcr=chain_dict.get("pcr"),
            pcr_volume=chain_dict.get("pcr_volume"),
            max_pain=chain_dict.get("max_pain"),
            max_pain_distance_pct=chain_dict.get("max_pain_distance_pct"),
            iv_skew=chain_dict.get("iv_skew"),
            option_chain_bias=chain_dict.get("bias"),
            entry=sig.entry if sig else None,
            stop_loss=sig.stop_loss if sig else None,
            target_1=sig.target_1 if sig else None,
            target_2=sig.target_2 if sig else None,
            invalidation=sig.invalidation if sig else None,
            category=sig.category if sig else None,
            reasons=(sig.reasons_json or []) if sig else [],
        ))
    return out


@router.get("/prices", response_model=Dict[str, float])
def prices(symbols: Optional[str] = Query(None)) -> Dict[str, float]:
    syms = (
        [s.strip() for s in symbols.split(",") if s.strip()]
        if symbols else all_index_symbols()
    )
    if not syms:
        return {}
    return _live_prices(syms)


@router.get("/strike-recommendations/active", response_model=List[ContractRecommendationOut])
def list_active_strike_recommendations(
    db: Session = Depends(get_db),
) -> List[ContractRecommendationOut]:
    """All currently-ACTIVE strike recommendations across every index.

    Powers the live "tracker" panel in the UI. Sorted newest first by
    `created_at` (already enforced in the repo helper)."""
    rows = idx_repo.active_recommendations(db)
    return [_rec_to_schema(r) for r in rows]


@router.get("/{symbol:path}", response_model=IndexDetailOut)
def get_index_detail(symbol: str, db: Session = Depends(get_db)) -> IndexDetailOut:
    instrument = idx_repo.get_index(db, symbol)
    if instrument is None:
        raise HTTPException(404, f"Index {symbol} not found")
    snap = idx_repo.latest_snapshot(db, symbol)
    sigs = idx_repo.signals_for_symbol(db, symbol, limit=10)
    # Bulk-attach recommendations for the listed signals so the UI can show
    # premium-level SL/T inline. One query, not N+1.
    recs_by_sig = idx_repo.recommendations_for_signals(db, [int(s.id) for s in sigs])

    signals_out: List[IndexSignalOut] = []
    for sig in sigs:
        out = IndexSignalOut.model_validate(sig)
        recs = recs_by_sig.get(int(sig.id), [])
        if recs:
            out = out.model_copy(update={
                "recommendations": [_rec_to_schema(r) for r in recs],
            })
        signals_out.append(out)

    snap_out: Optional[IndexSnapshotOut] = (
        IndexSnapshotOut.model_validate(snap) if snap is not None else None
    )
    return IndexDetailOut(
        instrument=IndexInstrumentOut.model_validate(instrument),
        snapshot=snap_out,
        signals=signals_out,
    )


@router.get("/{symbol:path}/history", response_model=List[IndexCandleOut])
def get_history(
    symbol: str,
    range: str = Query("1y", description="One of 1m/3m/6m/1y/2y/5y"),
    db: Session = Depends(get_db),
) -> List[IndexCandleOut]:
    bars = _RANGE_TO_BARS.get(range, 252)
    df = idx_repo.load_candles(db, symbol, limit=bars)
    if df.empty:
        return []
    out: List[IndexCandleOut] = []
    for ts, row in df.iterrows():
        out.append(IndexCandleOut(
            date=ts.date(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        ))
    return out


@router.get(
    "/{symbol:path}/strike-recommendations",
    response_model=List[ContractRecommendationOut],
)
def get_strike_recommendations(
    symbol: str,
    signal_id: Optional[int] = Query(
        None,
        description="Specific signal ID. When omitted returns the recs for the latest signal of this index.",
    ),
    db: Session = Depends(get_db),
) -> List[ContractRecommendationOut]:
    instrument = idx_repo.get_index(db, symbol)
    if instrument is None:
        raise HTTPException(404, f"Index {symbol} not found")
    if signal_id is None:
        latest = idx_repo.signals_for_symbol(db, symbol, limit=1)
        if not latest:
            return []
        signal_id = int(latest[0].id)
    rows = idx_repo.recommendations_for_signal(db, signal_id)
    return [_rec_to_schema(r) for r in rows]


@router.get("/{symbol:path}/option-chain", response_model=OptionChainOut)
def option_chain(symbol: str) -> OptionChainOut:
    meta = get_index(symbol)
    if meta is None:
        raise HTTPException(404, f"Index {symbol} not found")
    if not meta.has_options:
        raise HTTPException(400, f"{meta.code} does not have an option chain")
    payload = oc_data.fetch_option_chain(meta.code, meta.symbol)
    if payload is None:
        raise HTTPException(503, "Option chain temporarily unavailable")
    rows = [
        ocm.OCRow(
            strike=r.strike,
            ce_oi=r.ce_oi, ce_change_oi=r.ce_change_oi, ce_volume=r.ce_volume,
            ce_iv=r.ce_iv, ce_ltp=r.ce_ltp,
            pe_oi=r.pe_oi, pe_change_oi=r.pe_change_oi, pe_volume=r.pe_volume,
            pe_iv=r.pe_iv, pe_ltp=r.pe_ltp,
        ) for r in payload.rows
    ]
    summary = ocm.summarise(rows, spot=payload.spot)
    return OptionChainOut(
        symbol=meta.symbol,
        code=meta.code,
        spot=payload.spot,
        expiry=payload.expiry,
        expiries=payload.expiries,
        fetched_at=payload.fetched_at,
        source=payload.source,
        summary=OptionChainSummary(
            pcr=summary.pcr,
            pcr_volume=summary.pcr_volume,
            max_pain=summary.max_pain,
            max_pain_distance_pct=summary.max_pain_distance_pct,
            total_ce_oi=summary.total_ce_oi,
            total_pe_oi=summary.total_pe_oi,
            total_ce_change_oi=summary.total_ce_change_oi,
            total_pe_change_oi=summary.total_pe_change_oi,
            iv_skew=summary.iv_skew,
            bias=summary.bias,
            bias_strength=summary.bias_strength,
            notes=summary.notes,
        ),
        rows=[OptionChainRow(
            strike=r.strike,
            ce_oi=r.ce_oi, ce_change_oi=r.ce_change_oi, ce_volume=r.ce_volume,
            ce_iv=r.ce_iv, ce_ltp=r.ce_ltp,
            pe_oi=r.pe_oi, pe_change_oi=r.pe_change_oi, pe_volume=r.pe_volume,
            pe_iv=r.pe_iv, pe_ltp=r.pe_ltp,
        ) for r in payload.rows],
    )
