"""Singleton config for the Live Analysis Mode.

Mirrors the pattern in `paper/config.py`: a frozen snapshot dataclass that
the rest of the layer (`strategy`, `engine`, `service`) consumes immutably,
plus DB read/write helpers backed by the `live_analysis_config` table.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.live_analysis_orm import (
    DEFAULT_WEIGHTS,
    LiveAnalysisConfig as LiveAnalysisConfigORM,
)


# Allowed values for the `mode` field. Kept here (not in ORM) so pure
# downstream modules don't need to import SQLAlchemy.
MODE_HISTORICAL = "HISTORICAL"
MODE_LIVE = "LIVE"
ALLOWED_MODES = (MODE_HISTORICAL, MODE_LIVE)


@dataclass(frozen=True)
class LiveAnalysisConfigSnapshot:
    """Immutable view of the singleton config row.

    All Live Analysis pure functions take this snapshot as input - never the
    ORM object - so they remain easily testable and side-effect free.
    """
    mode: str = MODE_HISTORICAL
    poll_interval_min: int = 3
    observation_samples: int = 6
    top_k_movers: int = 8
    cooldown_min: int = 30
    decision_threshold: float = 1.5
    confidence_threshold: float = 65.0
    regime_risk_on_z: float = 0.5
    regime_risk_off_z: float = -0.5
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


def _get_or_create_row(db: Session) -> LiveAnalysisConfigORM:
    """Return the singleton row, creating it lazily on first access."""
    row = db.scalar(select(LiveAnalysisConfigORM).order_by(LiveAnalysisConfigORM.id).limit(1))
    if row is None:
        row = LiveAnalysisConfigORM()
        db.add(row)
        db.flush()
    return row


def snapshot(db: Session) -> LiveAnalysisConfigSnapshot:
    """Read the current config as an immutable snapshot."""
    row = _get_or_create_row(db)
    weights = dict(DEFAULT_WEIGHTS)
    if isinstance(row.weights, dict):
        weights.update(row.weights)
    return LiveAnalysisConfigSnapshot(
        mode=row.mode,
        poll_interval_min=int(row.poll_interval_min),
        observation_samples=int(row.observation_samples),
        top_k_movers=int(row.top_k_movers),
        cooldown_min=int(row.cooldown_min),
        decision_threshold=float(row.decision_threshold),
        confidence_threshold=float(row.confidence_threshold),
        regime_risk_on_z=float(row.regime_risk_on_z),
        regime_risk_off_z=float(row.regime_risk_off_z),
        weights=weights,
    )


def update(db: Session, **fields) -> LiveAnalysisConfigSnapshot:
    """Patch the singleton. Unknown fields are ignored.

    `mode` is validated against `ALLOWED_MODES` (raises `ValueError`).
    """
    row = _get_or_create_row(db)
    for k, v in fields.items():
        if v is None:
            continue
        if k == "mode":
            if v not in ALLOWED_MODES:
                raise ValueError(f"mode must be one of {ALLOWED_MODES}, got {v!r}")
            row.mode = v
        elif k == "weights":
            if not isinstance(v, dict):
                raise ValueError("weights must be a dict")
            merged = dict(DEFAULT_WEIGHTS)
            merged.update({wk: float(wv) for wk, wv in v.items() if wk in DEFAULT_WEIGHTS})
            row.weights = merged
        elif hasattr(row, k):
            setattr(row, k, v)
    db.flush()
    return snapshot(db)


def get_mode(db: Session) -> str:
    return _get_or_create_row(db).mode


def set_mode(db: Session, mode: str) -> str:
    if mode not in ALLOWED_MODES:
        raise ValueError(f"mode must be one of {ALLOWED_MODES}, got {mode!r}")
    row = _get_or_create_row(db)
    row.mode = mode
    db.flush()
    return row.mode
