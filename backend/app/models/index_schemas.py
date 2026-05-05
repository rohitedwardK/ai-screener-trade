"""Pydantic schemas for index analysis + paper-index-trading layers."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# Index analysis (read-only)
# ============================================================

class IndexInstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    code: str
    name: str
    exchange: str
    lot_size: int
    strike_step: float
    has_options: bool
    has_nse_option_chain: bool


class IndexCandleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndexSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    as_of_date: date
    close: float
    regime: str
    atr: Optional[float] = None
    atr_pct: Optional[float] = None
    indicators_json: Dict[str, Any] = Field(default_factory=dict)
    option_chain_summary_json: Optional[Dict[str, Any]] = None


class IndexSignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    run_at: datetime
    as_of_date: date
    category: str
    direction: str
    score: float
    confidence: float
    spot: float
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    invalidation: Optional[float] = None
    reasons_json: List[str] = Field(default_factory=list)
    option_chain_bias: Optional[str] = None


class IndexDetailOut(BaseModel):
    instrument: IndexInstrumentOut
    snapshot: Optional[IndexSnapshotOut] = None
    signals: List[IndexSignalOut] = Field(default_factory=list)


class IndexRow(BaseModel):
    """Compact row used by the dashboard list view."""
    symbol: str
    code: str
    name: str
    exchange: str
    close: float
    regime: str
    score: float
    confidence: float
    direction: Optional[str] = None
    rsi: Optional[float] = None
    adx: Optional[float] = None
    atr_pct: Optional[float] = None
    pivot_p: Optional[float] = None
    pivot_r1: Optional[float] = None
    pivot_s1: Optional[float] = None
    pcr: Optional[float] = None
    pcr_volume: Optional[float] = None
    max_pain: Optional[float] = None
    max_pain_distance_pct: Optional[float] = None
    iv_skew: Optional[float] = None
    option_chain_bias: Optional[str] = None
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    invalidation: Optional[float] = None
    category: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)


# ============================================================
# Option chain
# ============================================================

class OptionChainRow(BaseModel):
    strike: float
    ce_oi: Optional[float] = None
    ce_change_oi: Optional[float] = None
    ce_volume: Optional[float] = None
    ce_iv: Optional[float] = None
    ce_ltp: Optional[float] = None
    pe_oi: Optional[float] = None
    pe_change_oi: Optional[float] = None
    pe_volume: Optional[float] = None
    pe_iv: Optional[float] = None
    pe_ltp: Optional[float] = None


class OptionChainSummary(BaseModel):
    pcr: Optional[float] = None
    pcr_volume: Optional[float] = None
    max_pain: Optional[float] = None
    max_pain_distance_pct: Optional[float] = None
    total_ce_oi: float = 0.0
    total_pe_oi: float = 0.0
    total_ce_change_oi: float = 0.0
    total_pe_change_oi: float = 0.0
    iv_skew: Optional[float] = None
    bias: str = "Neutral"                 # Bullish | Bearish | Neutral
    bias_strength: float = 0.0            # 0..1
    notes: List[str] = Field(default_factory=list)


class OptionChainOut(BaseModel):
    symbol: str
    code: str
    spot: Optional[float] = None
    expiry: date
    expiries: List[date] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    summary: OptionChainSummary
    rows: List[OptionChainRow] = Field(default_factory=list)


# ============================================================
# Paper-index trading layer
# ============================================================

class PaperIndexBotConfigOut(BaseModel):
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
    option_moneyness: str
    option_delta_estimate: float
    use_option_chain_bias: bool
    intraday_poll_seconds: int
    intraday_signal_minutes: int
    entry_order_expiry_days: int
    max_holding_days: int
    intraday_horizon_days: int
    live_trading_enabled: bool
    live_poll_interval_seconds: int
    created_at: datetime
    updated_at: datetime


class PaperIndexBotConfigUpdate(BaseModel):
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
    option_moneyness: Optional[str] = None
    option_delta_estimate: Optional[float] = None
    use_option_chain_bias: Optional[bool] = None
    intraday_poll_seconds: Optional[int] = None
    intraday_signal_minutes: Optional[int] = None
    entry_order_expiry_days: Optional[int] = None
    max_holding_days: Optional[int] = None
    intraday_horizon_days: Optional[int] = None
    live_trading_enabled: Optional[bool] = None
    live_poll_interval_seconds: Optional[int] = None


class IndexScreenerSignal(BaseModel):
    """Canonical paper-index-bot input format (analogous to ScreenerSignal)."""
    symbol: str
    code: str
    date: date
    spot: float
    direction: str                                     # LONG | SHORT
    option_type: str                                   # CE | PE
    setup_type: str                                    # Trend Continuation, Breakout Retest, ...
    score: float
    confidence: str                                    # Low | Medium | High
    risk_level: str                                    # Low | Medium | High
    risk_reward: Optional[float] = None
    spot_entry: Optional[float] = None
    spot_stop_loss: Optional[float] = None
    spot_target_1: Optional[float] = None
    spot_target_2: Optional[float] = None
    spot_invalidation: Optional[float] = None
    rsi: Optional[float] = None
    atr_percent: Optional[float] = None
    market_regime: Optional[str] = None
    option_chain_bias: Optional[str] = None
    pcr: Optional[float] = None
    max_pain: Optional[float] = None
    ai_summary: Optional[str] = None


class PaperIndexTradeSignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_date: date
    symbol: str
    code: str
    setup_type: str
    direction: str
    option_type: str
    trend: Optional[str] = None
    market_regime: Optional[str] = None
    option_chain_bias: Optional[str] = None
    screener_score: float
    automation_score: float
    confidence: Optional[str] = None
    risk_level: Optional[str] = None
    risk_reward: Optional[float] = None
    spot: Optional[float] = None
    spot_stop_loss: Optional[float] = None
    spot_target_1: Optional[float] = None
    spot_target_2: Optional[float] = None
    spot_invalidation: Optional[float] = None
    strike: Optional[float] = None
    expiry: Optional[date] = None
    lot_size: Optional[int] = None
    lots: Optional[int] = None
    entry_premium: Optional[float] = None
    stop_loss_premium: Optional[float] = None
    target_1_premium: Optional[float] = None
    target_2_premium: Optional[float] = None
    delta_estimate: Optional[float] = None
    rsi: Optional[float] = None
    atr_percent: Optional[float] = None
    pcr: Optional[float] = None
    max_pain: Optional[float] = None
    decision: str
    skip_reason: Optional[str] = None
    ai_reason: Optional[str] = None
    created_at: datetime


class PaperIndexOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_id: int
    symbol: str
    code: str
    option_type: str
    strike: float
    expiry: date
    lot_size: int
    lots: int
    paper_order_type: str
    side: str
    planned_premium: float
    filled_premium: Optional[float] = None
    status: str
    note: Optional[str] = None
    created_at: datetime
    filled_at: Optional[datetime] = None


class PaperIndexPositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_id: int
    symbol: str
    code: str
    setup_type: str
    direction: str
    option_type: str
    strike: float
    expiry: date
    lot_size: int
    lots: int
    entry_spot: Optional[float] = None
    exit_spot: Optional[float] = None
    spot_stop_loss: Optional[float] = None
    spot_target_1: Optional[float] = None
    spot_target_2: Optional[float] = None
    entry_date: Optional[date] = None
    entry_premium: Optional[float] = None
    quantity: int
    remaining_quantity: int
    stop_loss: float
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    current_price: Optional[float] = None
    delta_estimate: Optional[float] = None
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


class PaperIndexLedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position_id: int
    date: date
    event_type: str
    symbol: str
    code: str
    option_type: str
    strike: float
    expiry: date
    quantity: int
    price: Optional[float] = None
    pnl: float
    note: Optional[str] = None
    created_at: datetime


class PaperIndexDailyPerformanceOut(BaseModel):
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


class PaperIndexStatusOut(BaseModel):
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
    market_regime: str
    reason: Optional[str] = None
    disclaimer: str = "Paper trading simulation only. Not financial advice."


class PaperIndexLiveTickOut(BaseModel):
    processed_at: datetime
    symbols_priced: int
    exits_triggered: int
    realized_pnl_today: float
    unrealized_pnl: float
    bot_status: str
    prices: Dict[str, float] = Field(default_factory=dict)
    disclaimer: str = "Paper trading simulation only. Not financial advice."


class PaperIndexSelectionOut(BaseModel):
    date: date
    market_regime: str
    candidates_evaluated: int
    selected: List[PaperIndexTradeSignalOut] = Field(default_factory=list)
    skipped: List[PaperIndexTradeSignalOut] = Field(default_factory=list)


class PaperIndexSimulateDayOut(BaseModel):
    date: date
    entries_filled: int
    exits_triggered: int
    realized_pnl: float
    unrealized_pnl: float
    bot_status: str
    events: List[PaperIndexLedgerOut] = Field(default_factory=list)


class PaperIndexReplaySummary(BaseModel):
    date: date
    bot_status: str
    selected: int
    skipped: int
    entries_filled: int
    exits_triggered: int
    realized_pnl: float
    ending_equity: float


class PaperIndexReplayOut(BaseModel):
    start: date
    end: date
    days_processed: int
    final_equity: float
    total_realized_pnl: float
    summary: List[PaperIndexReplaySummary] = Field(default_factory=list)


class PaperIndexPerformanceOut(BaseModel):
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
    daily: List[PaperIndexDailyPerformanceOut] = Field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list)


class PaperIndexJournalOut(BaseModel):
    date: date
    summary: str
    provider: str
    disclaimer: str = "Paper trading simulation only. Not financial advice."


class PaperIndexResetOut(BaseModel):
    deleted_signals: int
    deleted_orders: int
    deleted_positions: int
    deleted_ledger: int
    deleted_daily: int
    message: str = "Paper-index trading state has been reset."
