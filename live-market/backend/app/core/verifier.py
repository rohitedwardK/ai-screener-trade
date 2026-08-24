"""Re-evaluate ACTIVE scalp / swing setups against the latest spot.

Every tick the pipeline calls `verify(db, spots_by_symbol, now)` which:

  1. Loads ACTIVE rows from `scalp_setups` and `swing_setups`.
  2. For each row, decides:
       LONG  -> price <= invalidation -> STOPPED
                price >= t2          -> TARGET_HIT
                otherwise active.
       SHORT -> mirror.
  3. EXPIRED if `now > expires_at` and no terminal hit yet.
  4. Persists `resolved_at` + `resolved_price` for terminal transitions.

This is read-only with respect to the API: setups are NOT positions.
The status field tells the operator how the original signal would have
played out, not whether they actually entered.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.orm import ScalpSetup, SwingSetup

log = logging.getLogger(__name__)

STATUS_ACTIVE = "ACTIVE"
STATUS_TARGET_HIT = "TARGET_HIT"
STATUS_STOPPED = "STOPPED"
STATUS_INVALIDATED = "INVALIDATED"
STATUS_EXPIRED = "EXPIRED"


def _resolve_long(spot: float, *, t2: float, invalidation: float) -> str | None:
    if spot >= t2:
        return STATUS_TARGET_HIT
    if spot <= invalidation:
        return STATUS_STOPPED
    return None


def _resolve_short(spot: float, *, t2: float, invalidation: float) -> str | None:
    if spot <= t2:
        return STATUS_TARGET_HIT
    if spot >= invalidation:
        return STATUS_STOPPED
    return None


def _resolve_row(row, spot: float, when: datetime) -> str | None:
    if row.direction == "LONG":
        terminal = _resolve_long(spot, t2=row.spot_t2, invalidation=row.spot_invalidation)
    elif row.direction == "SHORT":
        terminal = _resolve_short(spot, t2=row.spot_t2, invalidation=row.spot_invalidation)
    else:
        terminal = STATUS_INVALIDATED   # malformed row defensively closed
    if terminal is not None:
        return terminal
    if when > row.expires_at:
        return STATUS_EXPIRED
    return None


def _apply_resolution(row, status: str, *, spot: float, when: datetime) -> None:
    row.status = status
    row.resolved_at = when
    row.resolved_price = float(spot)


def verify(
    db: Session,
    spots_by_symbol: Dict[str, float],
    *,
    now: datetime,
) -> Tuple[int, int]:
    """Resolve any ACTIVE setups whose terminal condition has been met.

    Returns `(scalps_resolved, swings_resolved)` for diagnostics.
    """
    scalps_resolved = 0
    swings_resolved = 0

    scalp_rows = list(db.scalars(
        select(ScalpSetup).where(ScalpSetup.status == STATUS_ACTIVE)
    ))
    for row in scalp_rows:
        spot = spots_by_symbol.get(row.symbol)
        if spot is None or spot <= 0:
            # No fresh spot this tick; check expiry only.
            if now > row.expires_at:
                _apply_resolution(row, STATUS_EXPIRED, spot=row.spot_entry, when=now)
                scalps_resolved += 1
            continue
        new_status = _resolve_row(row, float(spot), now)
        if new_status:
            _apply_resolution(row, new_status, spot=float(spot), when=now)
            scalps_resolved += 1

    swing_rows = list(db.scalars(
        select(SwingSetup).where(SwingSetup.status == STATUS_ACTIVE)
    ))
    for row in swing_rows:
        spot = spots_by_symbol.get(row.symbol)
        if spot is None or spot <= 0:
            if now > row.expires_at:
                _apply_resolution(row, STATUS_EXPIRED, spot=row.spot_entry, when=now)
                swings_resolved += 1
            continue
        new_status = _resolve_row(row, float(spot), now)
        if new_status:
            _apply_resolution(row, new_status, spot=float(spot), when=now)
            swings_resolved += 1

    return scalps_resolved, swings_resolved


__all__ = [
    "STATUS_ACTIVE",
    "STATUS_TARGET_HIT",
    "STATUS_STOPPED",
    "STATUS_INVALIDATED",
    "STATUS_EXPIRED",
    "verify",
]
