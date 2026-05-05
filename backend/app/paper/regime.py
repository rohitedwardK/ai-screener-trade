"""Aggregate the per-stock regime distribution into a market regime.

Spec:
    Bullish  if >= 60% of stocks are UPTREND or STRONG_UPTREND
    Bearish  if >= 60% of stocks are DOWNTREND or STRONG_DOWNTREND
    Sideways otherwise
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.orm import Snapshot

BULLISH_REGIMES = {"UPTREND", "STRONG_UPTREND"}
BEARISH_REGIMES = {"DOWNTREND", "STRONG_DOWNTREND"}

THRESHOLD = 0.60


def aggregate(regimes: Iterable[str]) -> str:
    """Pure function: collapse a list of regimes into Bullish/Bearish/Sideways."""
    items = list(regimes)
    if not items:
        return "Sideways"
    bull = sum(1 for r in items if r in BULLISH_REGIMES)
    bear = sum(1 for r in items if r in BEARISH_REGIMES)
    n = len(items)
    if bull / n >= THRESHOLD:
        return "Bullish"
    if bear / n >= THRESHOLD:
        return "Bearish"
    return "Sideways"


def market_regime(db: Session, as_of: Optional[date] = None) -> str:
    """Compute the current market regime from the latest snapshots.

    If `as_of` is given, only snapshots on/before that date are considered;
    we take the latest snapshot per symbol up to that date.
    """
    # Latest as_of_date per symbol (optionally bounded by `as_of`).
    base = select(Snapshot.symbol, func.max(Snapshot.as_of_date).label("max_date"))
    if as_of is not None:
        base = base.where(Snapshot.as_of_date <= as_of)
    base = base.group_by(Snapshot.symbol).subquery()

    stmt = (
        select(Snapshot.regime)
        .join(base, (Snapshot.symbol == base.c.symbol) & (Snapshot.as_of_date == base.c.max_date))
    )
    regimes = list(db.scalars(stmt))
    return aggregate(regimes)


def regime_breakdown(db: Session, as_of: Optional[date] = None) -> dict:
    """Optional helper for diagnostics / API responses."""
    base = select(Snapshot.symbol, func.max(Snapshot.as_of_date).label("max_date"))
    if as_of is not None:
        base = base.where(Snapshot.as_of_date <= as_of)
    base = base.group_by(Snapshot.symbol).subquery()
    stmt = (
        select(Snapshot.regime)
        .join(base, (Snapshot.symbol == base.c.symbol) & (Snapshot.as_of_date == base.c.max_date))
    )
    regimes = list(db.scalars(stmt))
    counts = Counter(regimes)
    n = len(regimes) or 1
    return {
        "n": len(regimes),
        "regime": aggregate(regimes),
        "counts": dict(counts),
        "bullish_pct": round(sum(counts[r] for r in BULLISH_REGIMES) / n * 100.0, 1),
        "bearish_pct": round(sum(counts[r] for r in BEARISH_REGIMES) / n * 100.0, 1),
    }
