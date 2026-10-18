"""SQLAlchemy ORM models."""
from __future__ import annotations

from datetime import datetime, date as date_type

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "stocks"

    symbol = Column(String, primary_key=True)
    name = Column(String, nullable=True)
    sector = Column(String, nullable=True)

    candles = relationship("Candle", back_populates="stock", cascade="all, delete-orphan")
    snapshots = relationship("Snapshot", back_populates="stock", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="stock", cascade="all, delete-orphan")


class Candle(Base):
    __tablename__ = "candles"

    symbol = Column(String, ForeignKey("stocks.symbol", ondelete="CASCADE"), primary_key=True)
    date = Column(Date, primary_key=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

    stock = relationship("Stock", back_populates="candles")

    __table_args__ = (
        Index("ix_candles_symbol_date", "symbol", "date"),
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False)
    run_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    as_of_date = Column(Date, nullable=False)
    close = Column(Float, nullable=False)
    indicators_json = Column(JSON, nullable=False, default=dict)
    regime = Column(String, nullable=False)
    atr = Column(Float, nullable=True)
    atr_pct = Column(Float, nullable=True)

    stock = relationship("Stock", back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("symbol", "as_of_date", name="uq_snapshot_symbol_date"),
        Index("ix_snapshots_symbol_runat", "symbol", "run_at"),
    )


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False)
    run_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    as_of_date = Column(Date, nullable=False)
    category = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    entry = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    target_1 = Column(Float, nullable=True)
    target_2 = Column(Float, nullable=True)
    invalidation = Column(Float, nullable=True)
    reasons_json = Column(JSON, nullable=False, default=list)
    # Commodity weekly-on-monthly plans; Nifty screener rows leave these null.
    direction = Column(String, nullable=True)
    expiry = Column(Date, nullable=True)
    days_to_expiry = Column(Integer, nullable=True)
    horizon = Column(String, nullable=True)

    stock = relationship("Stock", back_populates="signals")
    live_verification = relationship(
        "LiveSignalVerification",
        back_populates="signal",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_signals_runat_category", "run_at", "category"),
        Index("ix_signals_symbol_runat", "symbol", "run_at"),
    )


class QualityObservation(Base):
    """Immutable research samples, independent of disposable screener rows."""
    __tablename__ = "quality_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sample_key = Column(String, nullable=False, unique=True)
    symbol = Column(String, nullable=False, index=True)
    observed_at = Column(DateTime, nullable=False)
    payload = Column(JSON, nullable=False)


class LiveSignalVerification(Base):
    """Latest live cross-check for a persisted EOD screener signal.

    One row per `signals.id`: each verification run upserts the row so the
    UI can surface the most recent reconciliation without scanning history.
    Verification cadence: every 15 min during NSE hours (cron) plus on
    every manual Refresh click. Status is one of CONFIRMED / WEAKENING /
    INVALIDATED / STRENGTHENED (see `analysis.live_verifier`).
    """
    __tablename__ = "live_signal_verifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(
        Integer,
        ForeignKey("signals.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    symbol = Column(String, nullable=False, index=True)
    run_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String, nullable=False)
    live_close = Column(Float, nullable=False)
    live_rsi = Column(Float, nullable=True)
    live_adx = Column(Float, nullable=True)
    live_regime = Column(String, nullable=False)
    score_delta = Column(Float, nullable=True)
    distance_to_stop_pct = Column(Float, nullable=True)
    distance_to_t1_pct = Column(Float, nullable=True)
    notes_json = Column(JSON, nullable=False, default=list)
    source = Column(String, nullable=True)

    signal = relationship("Signal", back_populates="live_verification")

    __table_args__ = (
        Index("ix_live_verif_status", "status"),
        Index("ix_live_verif_runat", "run_at"),
    )
