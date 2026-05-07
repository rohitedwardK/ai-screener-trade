"""Pure decision logic for the live strike-recommendation verifier.

The companion orchestrator in `core/live_strike_verification.py` loads
ACTIVE recommendations, fetches their current premium from Upstox (with
yfinance/NSE fallback), and the parent signal's stop-loss from the spot
quote. This module then decides the new status for each row.

Status precedence (highest first):
  EXPIRED      - today >= expiry; chain is cash-settled, no further moves.
  INVALIDATED  - parent spot signal's SL has been breached; the strike
                 thesis no longer holds even if the option still has time.
  T2_HIT       - current premium >= t2_premium.
  T1_HIT       - current premium >= t1_premium.
  STOP_HIT     - current premium <= sl_premium.
  ACTIVE       - none of the above.

Pure: no DB, no network. Returns a frozen dataclass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


# ----- Status constants -----
STATUS_ACTIVE = "ACTIVE"
STATUS_T1_HIT = "T1_HIT"
STATUS_T2_HIT = "T2_HIT"
STATUS_STOP_HIT = "STOP_HIT"
STATUS_EXPIRED = "EXPIRED"
STATUS_INVALIDATED = "INVALIDATED"
STATUS_REJECTED = "REJECTED"

ALL_STATUSES = (
    STATUS_ACTIVE,
    STATUS_T1_HIT,
    STATUS_T2_HIT,
    STATUS_STOP_HIT,
    STATUS_EXPIRED,
    STATUS_INVALIDATED,
    STATUS_REJECTED,
)

# Statuses that won't transition further — used by the orchestrator to skip.
TERMINAL_STATUSES = frozenset({
    STATUS_T2_HIT,
    STATUS_STOP_HIT,
    STATUS_EXPIRED,
    STATUS_INVALIDATED,
    STATUS_REJECTED,
})


@dataclass(frozen=True)
class PersistedRecommendation:
    """DTO mirror of `IndexStrikeRecommendation` columns used by the verifier.

    Accepting a DTO instead of the ORM object keeps this module pure and
    independently unit-testable.
    """
    id: int
    expiry: date
    entry_premium: float
    sl_premium: float
    t1_premium: float
    t2_premium: float
    current_status: str = STATUS_ACTIVE


@dataclass(frozen=True)
class StrikeVerification:
    recommendation_id: int
    status: str
    last_premium: Optional[float]
    pnl_pct: Optional[float]
    notes: List[str] = field(default_factory=list)


def _pnl_pct(entry: float, current: Optional[float]) -> Optional[float]:
    if current is None or entry <= 0:
        return None
    return round((current - entry) / entry * 100.0, 2)


def evaluate(
    rec: PersistedRecommendation,
    *,
    current_premium: Optional[float],
    today: date,
    spot_sl_violated: bool,
) -> StrikeVerification:
    """Return the new verification record for one recommendation.

    Args:
        current_premium    : Latest option-leg premium (mid bid/ask preferred).
                             None when the price source is unavailable —
                             status stays at the current value, only the
                             `last_premium` column gets cleared.
        today              : Reference date for expiry comparison.
        spot_sl_violated   : True when the parent spot signal's stop has
                             been breached on the underlying live LTP.
    """
    notes: List[str] = []
    pnl = _pnl_pct(rec.entry_premium, current_premium)

    # Expiry beats everything — the contract is settled.
    if today >= rec.expiry:
        notes.append(f"Reached expiry {rec.expiry.isoformat()}")
        return StrikeVerification(
            recommendation_id=rec.id, status=STATUS_EXPIRED,
            last_premium=current_premium, pnl_pct=pnl, notes=notes,
        )

    # Spot SL invalidation runs before profit/loss gates so a recommendation
    # whose underlying thesis broke is flagged even when the option premium
    # hasn't yet caught up.
    if spot_sl_violated:
        notes.append("Underlying spot SL breached — thesis invalidated")
        return StrikeVerification(
            recommendation_id=rec.id, status=STATUS_INVALIDATED,
            last_premium=current_premium, pnl_pct=pnl, notes=notes,
        )

    # No live premium ⇒ keep the existing status, just record nothing fresh.
    if current_premium is None:
        notes.append("Premium price unavailable from live feed")
        return StrikeVerification(
            recommendation_id=rec.id, status=rec.current_status,
            last_premium=None, pnl_pct=None, notes=notes,
        )

    if current_premium >= rec.t2_premium and rec.t2_premium > 0:
        notes.append(
            f"Premium {current_premium:.2f} >= T2 {rec.t2_premium:.2f}"
        )
        return StrikeVerification(
            recommendation_id=rec.id, status=STATUS_T2_HIT,
            last_premium=current_premium, pnl_pct=pnl, notes=notes,
        )
    if current_premium >= rec.t1_premium and rec.t1_premium > 0:
        notes.append(
            f"Premium {current_premium:.2f} >= T1 {rec.t1_premium:.2f}"
        )
        return StrikeVerification(
            recommendation_id=rec.id, status=STATUS_T1_HIT,
            last_premium=current_premium, pnl_pct=pnl, notes=notes,
        )
    if current_premium <= rec.sl_premium:
        notes.append(
            f"Premium {current_premium:.2f} <= SL {rec.sl_premium:.2f}"
        )
        return StrikeVerification(
            recommendation_id=rec.id, status=STATUS_STOP_HIT,
            last_premium=current_premium, pnl_pct=pnl, notes=notes,
        )

    notes.append(f"Premium {current_premium:.2f} inside trade window")
    return StrikeVerification(
        recommendation_id=rec.id, status=STATUS_ACTIVE,
        last_premium=current_premium, pnl_pct=pnl, notes=notes,
    )


__all__ = [
    "ALL_STATUSES",
    "PersistedRecommendation",
    "STATUS_ACTIVE",
    "STATUS_EXPIRED",
    "STATUS_INVALIDATED",
    "STATUS_REJECTED",
    "STATUS_STOP_HIT",
    "STATUS_T1_HIT",
    "STATUS_T2_HIT",
    "StrikeVerification",
    "TERMINAL_STATUSES",
    "evaluate",
]
