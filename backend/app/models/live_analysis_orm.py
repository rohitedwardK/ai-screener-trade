"""SQLAlchemy ORM models for the Live Analysis Mode.

Four tables, all sharing the same declarative `Base` as the screener so
`init_db()` picks them up automatically:

  - live_analysis_config    : single-row config (mode, weights, thresholds)
  - live_market_snapshots   : per-tick regime + top-movers snapshot
  - live_observations       : per-symbol 6-sample window state
  - live_decisions          : emitted LONG/SHORT/HOLD calls with factor breakdown

All Live Analysis state is intentionally kept separate from the historical
screener and paper-trading tables so the two modes never cross-contaminate.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
)
from sqlalchemy.orm import relationship

from .orm import Base


# Default MFCS weights. Mirrored in `live_analysis/strategy.py`; the config
# row's `weights` JSON column overrides these per-deployment.
DEFAULT_WEIGHTS = {
    "w1_z": 2.0,
    "w2_slope": 2.0,
    "w3_vwap": 1.5,
    "w4_ema20": 1.5,
    "w5_rvol": 1.0,
    "w6_body": 1.0,
    "w7_rsi_penalty": 2.0,
}


class LiveAnalysisConfig(Base):
    """Singleton row controlling Live Analysis Mode.

    The `mode` column is the master switch consumed by both the scheduler
    tick (which short-circuits when mode != LIVE) and the frontend (which
    flips theme/nav when mode flips).
    """
    __tablename__ = "live_analysis_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mode = Column(String, nullable=False, default="HISTORICAL")  # HISTORICAL | LIVE
    poll_interval_min = Column(Integer, nullable=False, default=3)
    observation_samples = Column(Integer, nullable=False, default=6)
    top_k_movers = Column(Integer, nullable=False, default=8)
    cooldown_min = Column(Integer, nullable=False, default=30)
    # Score thresholds applied AFTER weights produce LONG_raw / SHORT_raw.
    decision_threshold = Column(Float, nullable=False, default=1.5)
    confidence_threshold = Column(Float, nullable=False, default=65.0)
    # Regime cutoffs on Nifty 50 z-score (computed on 3-min spot bars).
    regime_risk_on_z = Column(Float, nullable=False, default=0.5)
    regime_risk_off_z = Column(Float, nullable=False, default=-0.5)
    weights = Column(JSON, nullable=False, default=lambda: dict(DEFAULT_WEIGHTS))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class LiveMarketSnapshot(Base):
    """Per-tick market-wide snapshot. One row per scheduler tick in LIVE mode."""
    __tablename__ = "live_market_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, nullable=False, default=datetime.utcnow)
    regime = Column(String, nullable=False)            # RISK_ON | NEUTRAL | RISK_OFF
    nifty_last = Column(Float, nullable=True)
    nifty_z = Column(Float, nullable=True)
    nifty_slope = Column(Float, nullable=True)
    nifty_vwap_dev = Column(Float, nullable=True)
    # Top movers ranked at this tick: list of {symbol, last, pct_change, rvol, rank}.
    top_movers = Column(JSON, nullable=True)
    # Free-form diagnostic counters: {priced, observations_active, decisions_emitted}.
    counters = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_live_market_snapshots_ts", "ts"),
    )


class LiveObservation(Base):
    """A 6-sample / 15-min observation window for one symbol.

    Lifecycle: OBSERVING -> COMPLETED (decision emitted) | CANCELLED
    (e.g. data went stale). Re-observation is gated by `live_decisions.ts +
    cooldown_min`.
    """
    __tablename__ = "live_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="OBSERVING")  # OBSERVING | COMPLETED | CANCELLED
    sample_count = Column(Integer, nullable=False, default=0)
    samples = Column(JSON, nullable=False, default=list)
    # Aggregates computed on the closed window (filled on completion).
    vwap = Column(Float, nullable=True)
    rvol = Column(Float, nullable=True)
    atr_3m = Column(Float, nullable=True)
    rsi_3m = Column(Float, nullable=True)
    ema20_3m = Column(Float, nullable=True)
    note = Column(String, nullable=True)

    decisions = relationship(
        "LiveDecision",
        back_populates="observation",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_live_observations_symbol_status", "symbol", "status"),
        Index("ix_live_observations_started", "started_at"),
    )


class LiveDecision(Base):
    """Emitted LONG/SHORT/HOLD call from a completed observation window.

    Per project hard rule, every directional decision carries an
    `invalidation` level - the price at which the 15-min thesis is broken.
    """
    __tablename__ = "live_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    observation_id = Column(
        Integer, ForeignKey("live_observations.id", ondelete="CASCADE"), nullable=False,
    )
    symbol = Column(String, nullable=False)
    ts = Column(DateTime, nullable=False, default=datetime.utcnow)
    direction = Column(String, nullable=False)        # LONG | SHORT | HOLD
    confidence = Column(Float, nullable=False, default=0.0)
    long_raw = Column(Float, nullable=False, default=0.0)
    short_raw = Column(Float, nullable=False, default=0.0)
    invalidation = Column(Float, nullable=True)
    regime = Column(String, nullable=True)
    # Per-factor breakdown: {z, slope, vwap_dev, ema_dev, rvol, body, rsi_penalty, regime_mult}
    factors = Column(JSON, nullable=True)

    observation = relationship("LiveObservation", back_populates="decisions")

    __table_args__ = (
        Index("ix_live_decisions_ts", "ts"),
        Index("ix_live_decisions_symbol_ts", "symbol", "ts"),
    )
