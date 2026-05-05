"""SQLAlchemy ORM models for the paper-trading layer.

Six tables, all sharing the same declarative `Base` as the screener so
`init_db()` picks them up automatically:

  - paper_bot_config         : single-row config (max trades, capital, ...)
  - paper_trade_signals      : selected AND skipped signals (audit log)
  - paper_orders             : simulated order book entries
  - paper_positions          : open / closed simulated positions
  - paper_ledger             : immutable event stream
  - paper_daily_performance  : per-day equity / P&L / metrics
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


class PaperBotConfig(Base):
    __tablename__ = "paper_bot_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    virtual_capital = Column(Float, nullable=False, default=100_000.0)
    max_trades_per_day = Column(Integer, nullable=False, default=5)
    max_open_positions = Column(Integer, nullable=False, default=5)
    max_risk_per_trade_percent = Column(Float, nullable=False, default=0.5)
    max_daily_loss_percent = Column(Float, nullable=False, default=2.0)
    min_score = Column(Float, nullable=False, default=75.0)
    min_risk_reward = Column(Float, nullable=False, default=2.0)
    partial_exit_percent = Column(Float, nullable=False, default=50.0)
    trailing_stop_enabled = Column(Boolean, nullable=False, default=True)
    same_candle_policy = Column(String, nullable=False, default="conservative")
    # Live-tick mode: when enabled, the scheduler polls yfinance during NSE
    # market hours and fills/exits paper positions against live prices.
    live_trading_enabled = Column(Boolean, nullable=False, default=False)
    live_poll_interval_seconds = Column(Integer, nullable=False, default=60)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaperTradeSignal(Base):
    """Both selected AND skipped signals are stored here for full auditability."""
    __tablename__ = "paper_trade_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_date = Column(Date, nullable=False)
    symbol = Column(String, nullable=False)
    setup_type = Column(String, nullable=False)
    trend = Column(String, nullable=True)
    market_regime = Column(String, nullable=True)
    screener_score = Column(Float, nullable=False)
    automation_score = Column(Float, nullable=False)
    confidence = Column(String, nullable=True)             # Low | Medium | High
    risk_level = Column(String, nullable=True)             # Low | Medium | High
    risk_reward = Column(Float, nullable=True)
    entry = Column(Float, nullable=True)
    entry_zone_low = Column(Float, nullable=True)
    entry_zone_high = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    target_1 = Column(Float, nullable=True)
    target_2 = Column(Float, nullable=True)
    rsi = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    atr_percent = Column(Float, nullable=True)
    decision = Column(String, nullable=False)              # selected | skipped
    skip_reason = Column(String, nullable=True)
    ai_reason = Column(String, nullable=True)
    extras_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    orders = relationship("PaperOrder", back_populates="signal", cascade="all, delete-orphan")
    positions = relationship("PaperPosition", back_populates="signal", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_paper_signals_date_decision", "signal_date", "decision"),
        Index("ix_paper_signals_symbol", "symbol"),
    )


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("paper_trade_signals.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    paper_order_type = Column(String, nullable=False)
    side = Column(String, nullable=False, default="BUY")    # paper bot is long-only for now
    quantity = Column(Integer, nullable=False)
    planned_price = Column(Float, nullable=False)
    filled_price = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="PENDING")  # PENDING | FILLED | CANCELLED | EXPIRED
    note = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)

    signal = relationship("PaperTradeSignal", back_populates="orders")

    __table_args__ = (
        Index("ix_paper_orders_status", "status"),
        Index("ix_paper_orders_symbol_status", "symbol", "status"),
    )


class PaperPosition(Base):
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("paper_trade_signals.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    setup_type = Column(String, nullable=False)
    side = Column(String, nullable=False, default="LONG")
    entry_date = Column(Date, nullable=True)
    entry_price = Column(Float, nullable=True)
    quantity = Column(Integer, nullable=False, default=0)
    remaining_quantity = Column(Integer, nullable=False, default=0)
    stop_loss = Column(Float, nullable=False)
    target_1 = Column(Float, nullable=True)
    target_2 = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="PENDING_ENTRY")
    realized_pnl = Column(Float, nullable=False, default=0.0)
    unrealized_pnl = Column(Float, nullable=False, default=0.0)
    exit_date = Column(Date, nullable=True)
    exit_price = Column(Float, nullable=True)
    exit_reason = Column(String, nullable=True)
    holding_days = Column(Integer, nullable=True)
    is_intraday = Column(Boolean, nullable=False, default=False)
    breakeven_moved = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    signal = relationship("PaperTradeSignal", back_populates="positions")
    ledger_events = relationship("PaperLedger", back_populates="position", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_paper_positions_status_symbol", "status", "symbol"),
        Index("ix_paper_positions_symbol", "symbol"),
    )


class PaperLedger(Base):
    """Immutable event log of every state change."""
    __tablename__ = "paper_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("paper_positions.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    event_type = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=False, default=0.0)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    position = relationship("PaperPosition", back_populates="ledger_events")

    __table_args__ = (
        Index("ix_paper_ledger_date_symbol", "date", "symbol"),
        Index("ix_paper_ledger_position", "position_id"),
    )


class PaperDailyPerformance(Base):
    __tablename__ = "paper_daily_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    starting_capital = Column(Float, nullable=False, default=0.0)
    ending_capital = Column(Float, nullable=False, default=0.0)
    total_trades = Column(Integer, nullable=False, default=0)
    open_trades = Column(Integer, nullable=False, default=0)
    closed_trades = Column(Integer, nullable=False, default=0)
    winning_trades = Column(Integer, nullable=False, default=0)
    losing_trades = Column(Integer, nullable=False, default=0)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    unrealized_pnl = Column(Float, nullable=False, default=0.0)
    daily_return_percent = Column(Float, nullable=False, default=0.0)
    win_rate = Column(Float, nullable=False, default=0.0)
    average_win = Column(Float, nullable=False, default=0.0)
    average_loss = Column(Float, nullable=False, default=0.0)
    profit_factor = Column(Float, nullable=False, default=0.0)
    max_drawdown = Column(Float, nullable=False, default=0.0)
    bot_status = Column(String, nullable=False, default="ACTIVE")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", name="uq_paper_daily_performance_date"),
    )
