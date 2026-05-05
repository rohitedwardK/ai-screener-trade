"""Aggregate the per-index regime distribution into a market regime.

A simpler version of `app.paper.regime` because we only have 3 indices.
We treat the trio as the universe; the regime is set by the strongest
direction across all three (Nifty 50 / Bank Nifty / Sensex).
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.index_orm import IndexSnapshot

BULLISH_REGIMES = {"UPTREND", "STRONG_UPTREND"}
BEARISH_REGIMES = {"DOWNTREND", "STRONG_DOWNTREND"}


def aggregate(regimes: Iterable[str]) -> str:
    items = list(regimes)
    if not items:
        return "Sideways"
    bull = sum(1 for r in items if r in BULLISH_REGIMES)
    bear = sum(1 for r in items if r in BEARISH_REGIMES)
    n = len(items)
    if bull / n >= 0.5:
        return "Bullish"
    if bear / n >= 0.5:
        return "Bearish"
    return "Sideways"


def market_regime(db: Session, as_of: Optional[date] = None) -> str:
    base = select(IndexSnapshot.symbol, func.max(IndexSnapshot.as_of_date).label("max_date"))
    if as_of is not None:
        base = base.where(IndexSnapshot.as_of_date <= as_of)
    base = base.group_by(IndexSnapshot.symbol).subquery()
    stmt = (
        select(IndexSnapshot.regime)
        .join(base, (IndexSnapshot.symbol == base.c.symbol) & (IndexSnapshot.as_of_date == base.c.max_date))
    )
    return aggregate(list(db.scalars(stmt)))
