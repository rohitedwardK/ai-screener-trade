"""Pydantic schemas for the paper-trading layer."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Config ---

class PaperBotConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    virtual_capital: float
    max_trades_per_day: int
    max_open_positions: int
    max_risk_per_trade_percent: float
    max_daily_loss_percent: float
    min_score: float
    min_risk_reward: float
    partial_exit_percent: float
    trailing_stop_enabled: bool
    same_candle_policy: str
    live_trading_enabled: bool = False
    live_poll_interval_seconds: int = 60
    created_at: datetime
    updated_at: datetime


class PaperBotConfigUpdate(BaseModel):
    virtual_capital: Optional[float] = None
    max_trades_per_day: Optional[int] = None
    max_open_positions: Optional[int] = None
    max_risk_per_trade_percent: Optional[float] = None
    max_daily_loss_percent: Optional[float] = None
    min_score: Optional[float] = None
    min_risk_reward: Optional[float] = None
    partial_exit_percent: Optional[float] = None
    trailing_stop_enabled: Optional[bool] = None
    same_candle_policy: Optional[str] = None
    live_trading_enabled: Optional[bool] = None
    live_poll_interval_seconds: Optional[int] = None


# --- Screener-derived input (the "spec input") ---

class ScreenerSignal(BaseModel):
    """The canonical paper-bot input format."""
    symbol: str
    date: date
    close: float
    trend: str
    setup_type: str
    score: float
    confidence: str
    risk_level: str
    risk_reward: Optional[float] = None
    entry: Optional[float] = None
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    rsi: Optional[float] = None
    volume_ratio: Optional[float] = None
    atr_percent: Optional[float] = None
    market_regime: Optional[str] = None
    ai_summary: Optional[str] = None


# --- Output rows ---

class PaperTradeSignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_date: date
    symbol: str
    setup_type: str
    trend: Optional[str] = None
    market_regime: Optional[str] = None
    screener_score: float
    automation_score: float
    confidence: Optional[str] = None
    risk_level: Optional[str] = None
    risk_reward: Optional[float] = None
    entry: Optional[float] = None
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    rsi: Optional[float] = None
    volume_ratio: Optional[float] = None
    atr_percent: Optional[float] = None
    decision: str
    skip_reason: Optional[str] = None
    ai_reason: Optional[str] = None
    created_at: datetime


class PaperOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_id: int
    symbol: str
    paper_order_type: str
    side: str
    quantity: int
    planned_price: float
    filled_price: Optional[float] = None
    status: str
    note: Optional[str] = None
    created_at: datetime
    filled_at: Optional[datetime] = None


class PaperPositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_id: int
    symbol: str
    setup_type: str
    side: str
    entry_date: Optional[date] = None
    entry_price: Optional[float] = None
    quantity: int
    remaining_quantity: int
    stop_loss: float
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    current_price: Optional[float] = None
    status: str
    realized_pnl: float
    unrealized_pnl: float
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    holding_days: Optional[int] = None
    is_intraday: bool
    breakeven_moved: bool
    created_at: datetime
    updated_at: datetime


class PaperLedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position_id: int
    date: date
    event_type: str
    symbol: str
    quantity: int
    price: Optional[float] = None
    pnl: float
    note: Optional[str] = None
    created_at: datetime


class PaperDailyPerformanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    starting_capital: float
    ending_capital: float
    total_trades: int
    open_trades: int
    closed_trades: int
    winning_trades: int
    losing_trades: int
    realized_pnl: float
    unrealized_pnl: float
    daily_return_percent: float
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float
    max_drawdown: float
    bot_status: str
    created_at: datetime


# --- Aggregate / status responses ---

class PaperStatusOut(BaseModel):
    bot_status: str
    virtual_capital: float
    current_equity: float
    realized_pnl_today: float
    unrealized_pnl_today: float
    realized_pnl_total: float
    unrealized_pnl_total: float
    trades_taken_today: int
    remaining_trades_today: int
    open_positions: int
    daily_loss_limit_percent: float
    live_trading_enabled: bool = False
    is_market_open: bool = False
    last_live_tick_at: Optional[datetime] = None
    disclaimer: str = "Paper trading simulation only. Not financial advice."


class PaperLiveDebugOut(BaseModel):
    """Loose schema - the diagnostic returns a dict so we can evolve fields
    without churning the FastAPI contract for each new gate."""
    now_ist: str
    today: str
    blockers: List[str] = Field(default_factory=list)
    summary: str
    gates: Dict[str, Any] = Field(default_factory=dict)
    last_live_tick_at: Optional[str] = None
    last_run_selection: Dict[str, Any] = Field(default_factory=dict)
    prices_fetched: int = 0
    price_fetch_error: Optional[str] = None
    pending_positions: List[Dict[str, Any]] = Field(default_factory=list)
    open_positions: List[Dict[str, Any]] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = "Paper trading simulation only. Not financial advice."


class PaperLiveTickOut(BaseModel):
    processed_at: datetime
    symbols_priced: int
    entries_filled: int
    exits_triggered: int
    realized_pnl_today: float
    unrealized_pnl: float
    bot_status: str
    prices: Dict[str, float] = Field(default_factory=dict)
    events: List[PaperLedgerOut] = Field(default_factory=list)
    disclaimer: str = "Paper trading simulation only. Not financial advice."


class PaperSelectionOut(BaseModel):
    date: date
    market_regime: str
    candidates_evaluated: int
    selected: List[PaperTradeSignalOut] = Field(default_factory=list)
    skipped: List[PaperTradeSignalOut] = Field(default_factory=list)


class PaperSimulateDayOut(BaseModel):
    date: date
    entries_filled: int
    exits_triggered: int
    realized_pnl: float
    unrealized_pnl: float
    bot_status: str
    events: List[PaperLedgerOut] = Field(default_factory=list)


class PaperReplaySummary(BaseModel):
    date: date
    bot_status: str
    selected: int
    skipped: int
    entries_filled: int
    exits_triggered: int
    realized_pnl: float
    ending_equity: float


class PaperReplayOut(BaseModel):
    start: date
    end: date
    days_processed: int
    final_equity: float
    total_realized_pnl: float
    summary: List[PaperReplaySummary] = Field(default_factory=list)


class PaperPerformanceOut(BaseModel):
    from_date: date
    to_date: date
    total_trades: int
    closed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float
    expectancy: float
    max_drawdown_percent: float
    average_holding_days: float
    best_setup: Optional[str] = None
    worst_setup: Optional[str] = None
    by_setup: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    daily: List[PaperDailyPerformanceOut] = Field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list)


class PaperJournalOut(BaseModel):
    date: date
    summary: str
    provider: str
    disclaimer: str = "Paper trading simulation only. Not financial advice."


class PaperResetOut(BaseModel):
    deleted_signals: int
    deleted_orders: int
    deleted_positions: int
    deleted_ledger: int
    deleted_daily: int
    message: str = "Paper trading state has been reset."
