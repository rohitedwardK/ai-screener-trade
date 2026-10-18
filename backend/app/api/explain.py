"""AI explanation endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..ai.prompts import DISCLAIMER, sections_to_text
from ..ai.provider import get_provider
from ..api.commodities import build_commodity_detail
from ..core.commodity_universe import is_commodity_symbol
from ..data import repository as repo
from ..db import get_db
from ..models.schemas import ExplainOut, ExplainSections

router = APIRouter(prefix="/explain", tags=["explain"])


@router.get("/{symbol}", response_model=ExplainOut)
def explain_stock(symbol: str, db: Session = Depends(get_db)) -> ExplainOut:
    snap = repo.latest_snapshot(db, symbol)
    sigs = repo.signals_for_symbol(db, symbol, limit=1)
    sig = sigs[0] if sigs else None

    if is_commodity_symbol(symbol):
        stock = repo.get_stock(db, symbol)
        view = build_commodity_detail(symbol, snap, stock)
        if view.snapshot is not None:
            snap = view.snapshot
        if view.signals is not None:
            sig = view.signals[0] if view.signals else None

    if snap is None:
        raise HTTPException(404, f"No snapshot for {symbol}. Run a refresh first.")

    payload = {
        "symbol": symbol,
        "category": sig.category if sig else "NO_SIGNAL",
        "regime": snap.regime,
        "score": float(sig.score) if sig else 0.0,
        "confidence": float(sig.confidence) if sig else 0.0,
        "direction": (sig.direction if sig and sig.direction else "WAIT"),
        "as_of_date": str(snap.as_of_date),
        "indicators": snap.indicators_json or {},
        "reasons": (sig.reasons_json or []) if sig else [],
        "plan": {
            "entry": sig.entry if sig else None,
            "stop_loss": sig.stop_loss if sig else None,
            "target_1": sig.target_1 if sig else None,
            "target_2": sig.target_2 if sig else None,
            "invalidation": sig.invalidation if sig else None,
        } if sig else {},
    }

    provider = get_provider()
    sections = provider.explain(payload)

    return ExplainOut(
        symbol=symbol,
        explanation=sections_to_text(sections),
        sections=ExplainSections.model_validate(sections),
        disclaimer=DISCLAIMER,
        invalidation_level=sig.invalidation if sig else None,
        confidence=float(sig.confidence) if sig else 0.0,
        provider=provider.name,
    )
