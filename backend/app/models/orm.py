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

    stock = relationship("Stock", back_populates="signals")

    __table_args__ = (
        Index("ix_signals_runat_category", "run_at", "category"),
        Index("ix_signals_symbol_runat", "symbol", "run_at"),
    )
