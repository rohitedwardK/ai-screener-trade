"""SQLAlchemy ORM models for the Live Market service.

All tables share a single declarative `Base` so `init_db()` picks them
up via `Base.metadata.create_all`. SQLite-only; no Alembic. Schema
evolution is forward-only and additive (see `db._sync_sqlite_columns`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IntradayBar(Base):
    """Rolling 1-minute OHLCV per index. Composite PK (symbol, ts).

    The store keeps roughly `LIVE_MARKET_BAR_HISTORY` bars per symbol;
    older bars are pruned in `intraday_store.prune_old`.
    """
    __tablename__ = "intraday_bars"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RegimeSnapshot(Base):
    """Per-tick regime classification per index."""
    __tablename__ = "regime_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    regime: Mapped[str] = mapped_column(String(20), nullable=False)
    spot: Mapped[float] = mapped_column(Float, nullable=False)
    daily_adx: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_width_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ema_spread_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_range_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vwap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class ScalpSetup(Base):
    """5-15 min scalp setup emitted while regime is RANGE_BOUND."""
    __tablename__ = "scalp_setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)   # LONG | SHORT
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Spot plan (always populated)
    spot_entry: Mapped[float] = mapped_column(Float, nullable=False)
    spot_stop: Mapped[float] = mapped_column(Float, nullable=False)
    spot_t1: Mapped[float] = mapped_column(Float, nullable=False)
    spot_t2: Mapped[float] = mapped_column(Float, nullable=False)
    spot_invalidation: Mapped[float] = mapped_column(Float, nullable=False)

    # Option plan (None for Sensex - no option chain available)
    option_strike: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    option_type: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    option_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    option_instrument_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    option_premium_entry: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    option_premium_stop: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    option_premium_t1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    option_premium_t2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


class SwingSetup(Base):
    """2-3 day swing setup emitted while regime is TRENDING_UP / TRENDING_DOWN."""
    __tablename__ = "swing_setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    spot_entry: Mapped[float] = mapped_column(Float, nullable=False)
    spot_stop: Mapped[float] = mapped_column(Float, nullable=False)
    spot_t1: Mapped[float] = mapped_column(Float, nullable=False)
    spot_t2: Mapped[float] = mapped_column(Float, nullable=False)
    spot_invalidation: Mapped[float] = mapped_column(Float, nullable=False)

    option_strike: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    option_type: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    option_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    option_instrument_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    option_premium_entry: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    option_premium_stop: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    option_premium_t1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    option_premium_t2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    days_to_expiry: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


class OptionChainSnapshot(Base):
    """Per-tick option-chain analytics snapshot per index with a chain.

    We persist the derived analytics rather than the raw chain so the table
    stays small (one row per index per minute) and the dashboard query is
    cheap. The raw chain is always re-fetchable from Upstox via the
    `/option/chain` cache (60s TTL).
    """
    __tablename__ = "option_chain_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    expiry: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    spot: Mapped[float] = mapped_column(Float, nullable=False)

    pcr_oi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pcr_volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_ce_oi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_pe_oi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_pain: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    atm_iv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iv_skew: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    ce_oi_added: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pe_oi_added: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    flow_direction: Mapped[str] = mapped_column(String(16), nullable=False, default="NEUTRAL")

    bias_label: Mapped[str] = mapped_column(String(16), nullable=False, default="NEUTRAL")
    bias_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    bias_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Stored as JSON for fast UI consumption. Shape:
    # {"resistance": [{"strike": ..., "oi": ..., "side": "CE"}, ...],
    #  "support":    [{"strike": ..., "oi": ..., "side": "PE"}, ...]}
    oi_walls: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


# Indexes for the most common dashboard queries.
Index("ix_scalp_status_symbol", ScalpSetup.status, ScalpSetup.symbol)
Index("ix_swing_status_symbol", SwingSetup.status, SwingSetup.symbol)
Index("ix_optionchain_symbol_ts", OptionChainSnapshot.symbol, OptionChainSnapshot.ts.desc())


__all__ = [
    "Base", "IntradayBar", "RegimeSnapshot", "ScalpSetup", "SwingSetup",
    "OptionChainSnapshot",
]
