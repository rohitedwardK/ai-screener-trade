"""Index OHLCV + option-chain ORM (mirrors the stock screener tables).

Five tables, all sharing the same declarative `Base` so `init_db()` picks
them up automatically:

  - indices                  : index metadata (symbol, code, lot_size, ...)
  - index_candles            : daily OHLCV mirror of the per-index CSV cache
  - index_snapshots          : latest indicator/regime snapshot per index per run
  - index_signals            : derived per-index trade plan (entry/SL/T1/T2/category)
  - index_option_snapshots   : per-(index, expiry, strike, run_at) option-chain rows
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .orm import Base


class IndexInstrument(Base):
    """One row per tradable index symbol (e.g. ^NSEI, ^BSESN, ^NSEBANK)."""
    __tablename__ = "indices"

    symbol = Column(String, primary_key=True)         # ^NSEI / ^BSESN / ^NSEBANK
    code = Column(String, nullable=False)             # NIFTY / SENSEX / BANKNIFTY
    name = Column(String, nullable=False)
    exchange = Column(String, nullable=False)         # NSE | BSE
    lot_size = Column(Integer, nullable=False, default=1)
    strike_step = Column(Float, nullable=False, default=50.0)
    has_options = Column(Boolean, nullable=False, default=True)
    has_nse_option_chain = Column(Boolean, nullable=False, default=False)

    candles = relationship("IndexCandle", back_populates="instrument", cascade="all, delete-orphan")
    snapshots = relationship("IndexSnapshot", back_populates="instrument", cascade="all, delete-orphan")
    signals = relationship("IndexSignal", back_populates="instrument", cascade="all, delete-orphan")


class IndexCandle(Base):
    __tablename__ = "index_candles"

    symbol = Column(String, ForeignKey("indices.symbol", ondelete="CASCADE"), primary_key=True)
    date = Column(Date, primary_key=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False, default=0.0)

    instrument = relationship("IndexInstrument", back_populates="candles")

    __table_args__ = (
        Index("ix_index_candles_symbol_date", "symbol", "date"),
    )


class IndexSnapshot(Base):
    __tablename__ = "index_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, ForeignKey("indices.symbol", ondelete="CASCADE"), nullable=False)
    run_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    as_of_date = Column(Date, nullable=False)
    close = Column(Float, nullable=False)
    indicators_json = Column(JSON, nullable=False, default=dict)
    regime = Column(String, nullable=False)
    atr = Column(Float, nullable=True)
    atr_pct = Column(Float, nullable=True)

    # Option-chain summary captured alongside the daily snapshot (Nifty / BankNifty only).
    option_chain_summary_json = Column(JSON, nullable=True)

    instrument = relationship("IndexInstrument", back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("symbol", "as_of_date", name="uq_index_snapshot_symbol_date"),
        Index("ix_index_snapshots_symbol_runat", "symbol", "run_at"),
    )


class IndexSignal(Base):
    __tablename__ = "index_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, ForeignKey("indices.symbol", ondelete="CASCADE"), nullable=False)
    run_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    as_of_date = Column(Date, nullable=False)
    category = Column(String, nullable=False)
    direction = Column(String, nullable=False, default="LONG")  # LONG (buy CE) | SHORT (buy PE)
    score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    spot = Column(Float, nullable=False)
    entry = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    target_1 = Column(Float, nullable=True)
    target_2 = Column(Float, nullable=True)
    invalidation = Column(Float, nullable=True)
    reasons_json = Column(JSON, nullable=False, default=list)
    option_chain_bias = Column(String, nullable=True)  # Bullish | Bearish | Neutral

    instrument = relationship("IndexInstrument", back_populates="signals")

    __table_args__ = (
        Index("ix_index_signals_runat_category", "run_at", "category"),
        Index("ix_index_signals_symbol_runat", "symbol", "run_at"),
    )


class IndexOptionSnapshot(Base):
    """One row per (symbol, expiry, strike, snapshot_at). Used both for live UI
    rendering and for daily summary persistence (PCR, max-pain, OI shift)."""
    __tablename__ = "index_option_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)            # NIFTY / BANKNIFTY / SENSEX
    underlying_yf_symbol = Column(String, nullable=False)  # ^NSEI etc.
    snapshot_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expiry = Column(Date, nullable=False)
    strike = Column(Float, nullable=False)

    spot = Column(Float, nullable=True)

    ce_oi = Column(Float, nullable=True)
    ce_change_oi = Column(Float, nullable=True)
    ce_volume = Column(Float, nullable=True)
    ce_iv = Column(Float, nullable=True)
    ce_ltp = Column(Float, nullable=True)
    ce_bid = Column(Float, nullable=True)
    ce_ask = Column(Float, nullable=True)

    pe_oi = Column(Float, nullable=True)
    pe_change_oi = Column(Float, nullable=True)
    pe_volume = Column(Float, nullable=True)
    pe_iv = Column(Float, nullable=True)
    pe_ltp = Column(Float, nullable=True)
    pe_bid = Column(Float, nullable=True)
    pe_ask = Column(Float, nullable=True)

    source = Column(String, nullable=False, default="nse")  # nse | yfinance

    __table_args__ = (
        Index(
            "ix_index_options_symbol_expiry_strike_at",
            "symbol", "expiry", "strike", "snapshot_at",
        ),
    )
