"""Live Analysis service facade.

Thin layer used by both the API router and the scheduler. Wraps engine /
config calls in a session and exposes dashboard / decisions / observations
read-only views.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models.live_analysis_orm import (
    LiveDecision,
    LiveMarketSnapshot,
    LiveObservation,
)
from . import config as live_config
from . import engine as live_engine
from .observer import STATE_COOLDOWN, STATE_OBSERVING

log = logging.getLogger(__name__)

_IST_OFFSET_MINUTES = 5 * 60 + 30
_MARKET_OPEN_HHMM = (9, 15)
_MARKET_CLOSE_HHMM = (15, 30)


def _now_ist() -> datetime:
    """Naive IST datetime, regardless of host TZ. Mirrors `paper.service`."""
    from datetime import timezone, timedelta as _td
    utc_now = datetime.now(timezone.utc)
    ist = utc_now.astimezone(timezone(_td(minutes=_IST_OFFSET_MINUTES)))
    return ist.replace(tzinfo=None)


def is_market_open(at: Optional[datetime] = None) -> bool:
    """True during NSE regular session (Mon-Fri 09:15-15:30 IST)."""
    now = at or _now_ist()
    if now.weekday() >= 5:
        return False
    open_t = now.replace(
        hour=_MARKET_OPEN_HHMM[0], minute=_MARKET_OPEN_HHMM[1],
        second=0, microsecond=0,
    )
    close_t = now.replace(
        hour=_MARKET_CLOSE_HHMM[0], minute=_MARKET_CLOSE_HHMM[1],
        second=0, microsecond=0,
    )
    return open_t <= now <= close_t


# ---------------------------------------------------------------------------
# Mode + config (delegate to live_analysis.config)
# ---------------------------------------------------------------------------
def get_mode(db: Session) -> str:
    return live_config.get_mode(db)


def set_mode(db: Session, mode: str) -> str:
    out = live_config.set_mode(db, mode)
    db.commit()
    return out


def get_config_dict(db: Session) -> Dict[str, Any]:
    snap = live_config.snapshot(db)
    return {
        "mode": snap.mode,
        "poll_interval_min": snap.poll_interval_min,
        "observation_samples": snap.observation_samples,
        "top_k_movers": snap.top_k_movers,
        "cooldown_min": snap.cooldown_min,
        "decision_threshold": snap.decision_threshold,
        "confidence_threshold": snap.confidence_threshold,
        "regime_risk_on_z": snap.regime_risk_on_z,
        "regime_risk_off_z": snap.regime_risk_off_z,
        "weights": dict(snap.weights),
    }


def update_config(db: Session, **fields) -> Dict[str, Any]:
    live_config.update(db, **fields)
    db.commit()
    return get_config_dict(db)


# ---------------------------------------------------------------------------
# Tick (used by both /v1/live-analysis/tick and the APScheduler job)
# ---------------------------------------------------------------------------
@dataclass
class TickSummary:
    """Serializable view of `engine.TickResult` for the API."""
    processed_at: str
    mode: str
    market_open: bool
    regime: str
    symbols_priced: int
    top_movers_count: int
    observations_active: int
    observations_started: int
    decisions_emitted: int
    cooldowns_released: int
    note: str = ""


def run_tick(db: Session) -> TickSummary:
    """Execute one tick and return a serializable summary."""
    result = live_engine.run_tick(db)
    return TickSummary(
        processed_at=result.processed_at.isoformat(),
        mode=result.mode,
        market_open=result.market_open,
        regime=result.regime,
        symbols_priced=result.symbols_priced,
        top_movers_count=result.top_movers_count,
        observations_active=result.observations_active,
        observations_started=result.observations_started,
        decisions_emitted=result.decisions_emitted,
        cooldowns_released=result.cooldowns_released,
        note=result.note,
    )


# ---------------------------------------------------------------------------
# Read-only views for the dashboard
# ---------------------------------------------------------------------------
def _serialize_observation(row: LiveObservation) -> Dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "sample_count": row.sample_count,
        "samples": row.samples or [],
        "vwap": row.vwap,
        "rvol": row.rvol,
        "atr_3m": row.atr_3m,
        "rsi_3m": row.rsi_3m,
        "ema20_3m": row.ema20_3m,
        "note": row.note,
    }


def _serialize_decision(row: LiveDecision) -> Dict[str, Any]:
    return {
        "id": row.id,
        "observation_id": row.observation_id,
        "symbol": row.symbol,
        "ts": row.ts.isoformat() if row.ts else None,
        "direction": row.direction,
        "confidence": row.confidence,
        "long_raw": row.long_raw,
        "short_raw": row.short_raw,
        "invalidation": row.invalidation,
        "regime": row.regime,
        "factors": row.factors or {},
    }


def _serialize_market_snapshot(row: LiveMarketSnapshot) -> Dict[str, Any]:
    return {
        "id": row.id,
        "ts": row.ts.isoformat() if row.ts else None,
        "regime": row.regime,
        "nifty_last": row.nifty_last,
        "nifty_z": row.nifty_z,
        "nifty_slope": row.nifty_slope,
        "nifty_vwap_dev": row.nifty_vwap_dev,
        "top_movers": row.top_movers or [],
        "counters": row.counters or {},
    }


def get_observations(db: Session, *, only_active: bool = True) -> List[Dict[str, Any]]:
    stmt = select(LiveObservation).order_by(desc(LiveObservation.started_at))
    if only_active:
        stmt = stmt.where(LiveObservation.status.in_([STATE_OBSERVING, STATE_COOLDOWN]))
    rows = list(db.scalars(stmt))
    return [_serialize_observation(r) for r in rows]


def get_decisions(db: Session, *, limit: int = 50) -> List[Dict[str, Any]]:
    rows = list(db.scalars(
        select(LiveDecision)
        .order_by(desc(LiveDecision.ts))
        .limit(max(1, min(limit, 500)))
    ))
    return [_serialize_decision(r) for r in rows]


def get_dashboard(db: Session) -> Dict[str, Any]:
    """Bundle everything the Live Analysis page needs in one shot.

    Mirrors how `paper_trading` exposes a single `/status` endpoint so the
    frontend can avoid waterfall queries on first paint.
    """
    cfg = get_config_dict(db)
    market_open = is_market_open()

    last_snap = db.scalar(
        select(LiveMarketSnapshot)
        .order_by(desc(LiveMarketSnapshot.ts))
        .limit(1)
    )
    snapshot_dict = _serialize_market_snapshot(last_snap) if last_snap else None
    observations = get_observations(db, only_active=True)
    decisions = get_decisions(db, limit=25)

    return {
        "mode": cfg["mode"],
        "market_open": market_open,
        "config": cfg,
        "market_snapshot": snapshot_dict,
        "active_observations": observations,
        "recent_decisions": decisions,
        "disclaimer": "Research and decision-support only. Not financial advice.",
    }


__all__ = [
    "is_market_open",
    "get_mode",
    "set_mode",
    "get_config_dict",
    "update_config",
    "run_tick",
    "TickSummary",
    "get_observations",
    "get_decisions",
    "get_dashboard",
]
