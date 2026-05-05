"""SQLAlchemy ORM models for the paper-INDEX-trading layer.

Six tables, parallel to the stock paper bot but with option-specific fields
(underlying / option_type / strike / expiry / lot_size / lots). All share the
same declarative `Base` so `init_db()` picks them up automatically.

  - paper_index_bot_config        : single-row config (max trades, capital, ...)
  - paper_index_trade_signals     : selected AND skipped index signals (audit log)
  - paper_index_orders            : simulated order book entries
  - paper_index_positions         : open / closed simulated option positions
  - paper_index_ledger            : immutable event stream
  - paper_index_daily_performance : per-day equity / P&L / metrics
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


class PaperIndexBotConfig(Base):
    __tablename__ = "paper_index_bot_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    virtual_capital = Column(Float, nullable=False, default=100_000.0)
    max_trades_per_day = Column(Integer, nullable=False, default=5)
    max_open_positions = Column(Integer, nullable=False, default=3)
    max_risk_per_trade_percent = Column(Float, nullable=False, default=1.0)
    max_daily_loss_percent = Column(Float, nullable=False, default=3.0)
    min_score = Column(Float, nullable=False, default=70.0)
    min_risk_reward = Column(Float, nullable=False, default=1.5)
    partial_exit_percent = Column(Float, nullable=False, default=50.0)
    trailing_stop_enabled = Column(Boolean, nullable=False, default=True)
    same_candle_policy = Column(String, nullable=False, default="conservative")
    # Option-specific knobs ---------------------------------------------
    option_moneyness = Column(String, nullable=False, default="ATM")     # ATM | ITM1 | OTM1
    option_delta_estimate = Column(Float, nullable=False, default=0.5)   # used by simulator premium model
    use_option_chain_bias = Column(Boolean, nullable=False, default=True)
    intraday_poll_seconds = Column(Integer, nullable=False, default=60)  # 60s frontend polling cadence
    intraday_signal_minutes = Column(Integer, nullable=False, default=5)
    # Index-options weekly lifecycle is ~5 trading days (Tue/Wed/Thu expiries),
    # so the bot intentionally trades on a tighter horizon than the stock layer.
    entry_order_expiry_days = Column(Integer, nullable=False, default=1)   # pending entry expires next candle
    max_holding_days = Column(Integer, nullable=False, default=3)          # exit before theta crush near expiry
    intraday_horizon_days = Column(Integer, nullable=False, default=1)     # is_intraday=True positions
    # Live trade-management agent: when ON, the scheduler polls live spot
    # prices every minute during NSE hours and walks OPEN positions through
    # the live_engine for premium-level SL/T1/T2/trail. Simulation only -
    # never opens new positions intraday (PENDING entries still fill via
    # the daily simulate_day pass).
    live_trading_enabled = Column(Boolean, nullable=False, default=False)
    live_poll_interval_seconds = Column(Integer, nullable=False, default=60)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaperIndexTradeSignal(Base):
    """Selected AND skipped index-bot decisions for full auditability."""
    __tablename__ = "paper_index_trade_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_date = Column(Date, nullable=False)
    symbol = Column(String, nullable=False)               # ^NSEI / ^BSESN / ^NSEBANK
    code = Column(String, nullable=False)                 # NIFTY / SENSEX / BANKNIFTY
    setup_type = Column(String, nullable=False)           # Trend Continuation, Breakout, Pullback, OptionChainBias, ...
    direction = Column(String, nullable=False, default="LONG")  # LONG | SHORT
    option_type = Column(String, nullable=False, default="CE")  # CE | PE
    trend = Column(String, nullable=True)
    market_regime = Column(String, nullable=True)
    option_chain_bias = Column(String, nullable=True)
    screener_score = Column(Float, nullable=False)
    automation_score = Column(Float, nullable=False)
    confidence = Column(String, nullable=True)
    risk_level = Column(String, nullable=True)
    risk_reward = Column(Float, nullable=True)

    # Spot / underlying reference levels
    spot = Column(Float, nullable=True)
    spot_stop_loss = Column(Float, nullable=True)
    spot_target_1 = Column(Float, nullable=True)
    spot_target_2 = Column(Float, nullable=True)
    spot_invalidation = Column(Float, nullable=True)

    # Option contract specifics
    strike = Column(Float, nullable=True)
    expiry = Column(Date, nullable=True)
    lot_size = Column(Integer, nullable=True)
    lots = Column(Integer, nullable=True)
    entry_premium = Column(Float, nullable=True)
    stop_loss_premium = Column(Float, nullable=True)
    target_1_premium = Column(Float, nullable=True)
    target_2_premium = Column(Float, nullable=True)
    delta_estimate = Column(Float, nullable=True)

    rsi = Column(Float, nullable=True)
    atr_percent = Column(Float, nullable=True)
    pcr = Column(Float, nullable=True)
    max_pain = Column(Float, nullable=True)

    decision = Column(String, nullable=False)              # selected | skipped
    skip_reason = Column(String, nullable=True)
    ai_reason = Column(String, nullable=True)
    extras_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    orders = relationship("PaperIndexOrder", back_populates="signal", cascade="all, delete-orphan")
    positions = relationship("PaperIndexPosition", back_populates="signal", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_paper_idx_signals_date_decision", "signal_date", "decision"),
        Index("ix_paper_idx_signals_symbol", "symbol"),
    )


class PaperIndexOrder(Base):
    __tablename__ = "paper_index_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("paper_index_trade_signals.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    code = Column(String, nullable=False)
    option_type = Column(String, nullable=False)
    strike = Column(Float, nullable=False)
    expiry = Column(Date, nullable=False)
    lot_size = Column(Integer, nullable=False)
    lots = Column(Integer, nullable=False)
    paper_order_type = Column(String, nullable=False)
    side = Column(String, nullable=False, default="BUY")
    planned_premium = Column(Float, nullable=False)
    filled_premium = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="PENDING")
    note = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)

    signal = relationship("PaperIndexTradeSignal", back_populates="orders")

    __table_args__ = (
        Index("ix_paper_idx_orders_status", "status"),
        Index("ix_paper_idx_orders_symbol_status", "symbol", "status"),
    )


class PaperIndexPosition(Base):
    __tablename__ = "paper_index_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("paper_index_trade_signals.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    code = Column(String, nullable=False)
    setup_type = Column(String, nullable=False)
    direction = Column(String, nullable=False, default="LONG")
    option_type = Column(String, nullable=False)
    strike = Column(Float, nullable=False)
    expiry = Column(Date, nullable=False)
    lot_size = Column(Integer, nullable=False)
    lots = Column(Integer, nullable=False)

    # Underlying spot levels at entry/exit (recorded for analysis)
    entry_spot = Column(Float, nullable=True)
    exit_spot = Column(Float, nullable=True)
    spot_stop_loss = Column(Float, nullable=True)
    spot_target_1 = Column(Float, nullable=True)
    spot_target_2 = Column(Float, nullable=True)

    # Option premium levels (canonical for P&L)
    entry_date = Column(Date, nullable=True)
    entry_premium = Column(Float, nullable=True)
    quantity = Column(Integer, nullable=False, default=0)        # lots * lot_size, used by sim P&L math
    remaining_quantity = Column(Integer, nullable=False, default=0)
    stop_loss = Column(Float, nullable=False)                    # premium-level stop
    target_1 = Column(Float, nullable=True)
    target_2 = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)                 # latest mark premium

    delta_estimate = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="PENDING_ENTRY")
    realized_pnl = Column(Float, nullable=False, default=0.0)
    unrealized_pnl = Column(Float, nullable=False, default=0.0)
    exit_date = Column(Date, nullable=True)
    exit_price = Column(Float, nullable=True)
    exit_reason = Column(String, nullable=True)
    holding_days = Column(Integer, nullable=True)
    is_intraday = Column(Boolean, nullable=False, default=True)  # index options are weekly/intraday by default
    breakeven_moved = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    signal = relationship("PaperIndexTradeSignal", back_populates="positions")
    ledger_events = relationship("PaperIndexLedger", back_populates="position", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_paper_idx_positions_status_symbol", "status", "symbol"),
        Index("ix_paper_idx_positions_symbol", "symbol"),
    )


class PaperIndexLedger(Base):
    __tablename__ = "paper_index_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("paper_index_positions.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    event_type = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    code = Column(String, nullable=False)
    option_type = Column(String, nullable=False)
    strike = Column(Float, nullable=False)
    expiry = Column(Date, nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=False, default=0.0)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    position = relationship("PaperIndexPosition", back_populates="ledger_events")

    __table_args__ = (
        Index("ix_paper_idx_ledger_date_symbol", "date", "symbol"),
        Index("ix_paper_idx_ledger_position", "position_id"),
    )


class PaperIndexDailyPerformance(Base):
    __tablename__ = "paper_index_daily_performance"

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
        UniqueConstraint("date", name="uq_paper_idx_daily_performance_date"),
    )
