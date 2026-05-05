export interface Stock {
  symbol: string;
  name: string | null;
  sector: string | null;
}

export interface ScreenerRow {
  symbol: string;
  name: string | null;
  sector: string | null;
  category: string;
  regime: string;
  score: number;
  confidence: number;
  close: number;
  rsi: number | null;
  adx: number | null;
  atr_pct: number | null;
  entry: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  invalidation: number | null;
  reasons: string[];
}

export interface CategoryCount {
  category: string;
  count: number;
  top: ScreenerRow[];
}

export interface Candle {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Snapshot {
  symbol: string;
  as_of_date: string;
  close: number;
  regime: string;
  atr: number | null;
  atr_pct: number | null;
  indicators_json: Record<string, number | null>;
}

export interface Signal {
  id: number;
  symbol: string;
  run_at: string;
  as_of_date: string;
  category: string;
  score: number;
  confidence: number;
  entry: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  invalidation: number | null;
  reasons_json: string[];
}

export interface StockDetail {
  stock: Stock;
  snapshot: Snapshot | null;
  signals: Signal[];
}

export interface ExplainOut {
  symbol: string;
  explanation: string;
  disclaimer: string;
  invalidation_level: number | null;
  confidence: number;
  provider: string;
}

export interface RefreshResult {
  started_at: string;
  finished_at: string;
  fetched_symbols: number;
  signals_generated: number;
  errors: string[];
}

export const CATEGORY_LABELS: Record<string, string> = {
  MOMENTUM_LEADER: "Momentum Leaders",
  FRESH_BREAKOUT: "Fresh Breakouts",
  PULLBACK_ENTRY: "Pullback Entries",
  OVERSOLD_RECOVERING: "Oversold Recovering",
  OVERBOUGHT_AVOID: "Overbought - Avoid Chasing",
  WEAK_AVOID: "Weak - Avoid",
  HIGH_RISK: "High Risk",
  SWING_NEXT_WEEK: "Swing Trade Next Week",
  INTRADAY_WATCH_TOMORROW: "Intraday Watchlist Tomorrow",
};

export const CATEGORY_DESCRIPTIONS: Record<string, string> = {
  MOMENTUM_LEADER: "Strong trend, high relative strength, near 52w-high",
  FRESH_BREAKOUT: "Just broke above multi-week range with volume",
  PULLBACK_ENTRY: "Healthy retrace to EMA support inside an uptrend",
  OVERSOLD_RECOVERING: "RSI bounce setup with confirmation",
  OVERBOUGHT_AVOID: "Overheated indicators - poor risk/reward to chase",
  WEAK_AVOID: "Downtrend stack - avoid long entries",
  HIGH_RISK: "Volatility or volume issues - position size carefully",
  SWING_NEXT_WEEK: "Multi-day swing setup forming",
  INTRADAY_WATCH_TOMORROW: "Volume + range fit for intraday plays",
};

export const CATEGORY_TONE: Record<string, "green" | "red" | "amber" | "blue" | "violet" | "cyan"> = {
  MOMENTUM_LEADER: "green",
  FRESH_BREAKOUT: "green",
  PULLBACK_ENTRY: "blue",
  OVERSOLD_RECOVERING: "cyan",
  OVERBOUGHT_AVOID: "amber",
  WEAK_AVOID: "red",
  HIGH_RISK: "amber",
  SWING_NEXT_WEEK: "violet",
  INTRADAY_WATCH_TOMORROW: "cyan",
};

// =====================================================
// Paper Trading Layer
// =====================================================

export interface PaperBotConfig {
  id: number;
  virtual_capital: number;
  max_trades_per_day: number;
  max_open_positions: number;
  max_risk_per_trade_percent: number;
  max_daily_loss_percent: number;
  min_score: number;
  min_risk_reward: number;
  partial_exit_percent: number;
  trailing_stop_enabled: boolean;
  same_candle_policy: string;
  live_trading_enabled: boolean;
  live_poll_interval_seconds: number;
  created_at: string;
  updated_at: string;
}

export type PaperBotConfigUpdate = Partial<
  Omit<PaperBotConfig, "id" | "created_at" | "updated_at">
>;

export interface PaperStatus {
  bot_status: string;
  virtual_capital: number;
  current_equity: number;
  realized_pnl_today: number;
  unrealized_pnl_today: number;
  realized_pnl_total: number;
  unrealized_pnl_total: number;
  trades_taken_today: number;
  remaining_trades_today: number;
  open_positions: number;
  daily_loss_limit_percent: number;
  live_trading_enabled: boolean;
  is_market_open: boolean;
  last_live_tick_at: string | null;
  disclaimer: string;
}

export interface PaperLiveTick {
  processed_at: string;
  symbols_priced: number;
  entries_filled: number;
  exits_triggered: number;
  realized_pnl_today: number;
  unrealized_pnl: number;
  bot_status: string;
  prices: Record<string, number>;
  events: PaperLedgerEvent[];
  disclaimer: string;
}

export interface PaperLiveDebugGate {
  ok: boolean;
  value: unknown;
  reason?: string;
  fix?: string;
}

export interface PaperLiveDebugPending {
  symbol: string;
  entry_price: number | null;
  last_price: number | null;
  distance_to_entry_pct: number | null;
  would_fill_now: boolean;
}

export interface PaperLiveDebugOpen {
  symbol: string;
  entry_price: number | null;
  last_price: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  remaining_quantity: number;
  breakeven_moved: boolean;
  distance_to_stop_pct: number | null;
  distance_to_t1_pct: number | null;
  distance_to_t2_pct: number | null;
}

export interface PaperLiveDebug {
  now_ist: string;
  today: string;
  blockers: string[];
  summary: string;
  gates: Record<string, PaperLiveDebugGate>;
  last_live_tick_at: string | null;
  last_run_selection: {
    signal_date: string | null;
    selected: number;
    skipped: number;
    top_skip_reasons: Array<{ reason: string; count: number }>;
  };
  prices_fetched: number;
  price_fetch_error: string | null;
  pending_positions: PaperLiveDebugPending[];
  open_positions: PaperLiveDebugOpen[];
  config: Record<string, unknown>;
  disclaimer: string;
}

export interface PaperTradeSignal {
  id: number;
  signal_date: string;
  symbol: string;
  setup_type: string;
  trend: string | null;
  market_regime: string | null;
  screener_score: number;
  automation_score: number;
  confidence: string | null;
  risk_level: string | null;
  risk_reward: number | null;
  entry: number | null;
  entry_zone_low: number | null;
  entry_zone_high: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  rsi: number | null;
  volume_ratio: number | null;
  atr_percent: number | null;
  decision: string;
  skip_reason: string | null;
  ai_reason: string | null;
  created_at: string;
}

export interface PaperOrder {
  id: number;
  signal_id: number;
  symbol: string;
  paper_order_type: string;
  side: string;
  quantity: number;
  planned_price: number;
  filled_price: number | null;
  status: string;
  note: string | null;
  created_at: string;
  filled_at: string | null;
}

export interface PaperPosition {
  id: number;
  signal_id: number;
  symbol: string;
  setup_type: string;
  side: string;
  entry_date: string | null;
  entry_price: number | null;
  quantity: number;
  remaining_quantity: number;
  stop_loss: number;
  target_1: number | null;
  target_2: number | null;
  current_price: number | null;
  status: string;
  realized_pnl: number;
  unrealized_pnl: number;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  holding_days: number | null;
  is_intraday: boolean;
  breakeven_moved: boolean;
  created_at: string;
  updated_at: string;
}

export interface PaperLedgerEvent {
  id: number;
  position_id: number;
  date: string;
  event_type: string;
  symbol: string;
  quantity: number;
  price: number | null;
  pnl: number;
  note: string | null;
  created_at: string;
}

export interface PaperDailyPerformance {
  id: number;
  date: string;
  starting_capital: number;
  ending_capital: number;
  total_trades: number;
  open_trades: number;
  closed_trades: number;
  winning_trades: number;
  losing_trades: number;
  realized_pnl: number;
  unrealized_pnl: number;
  daily_return_percent: number;
  win_rate: number;
  average_win: number;
  average_loss: number;
  profit_factor: number;
  max_drawdown: number;
  bot_status: string;
  created_at: string;
}

export interface PaperSelection {
  date: string;
  market_regime: string;
  candidates_evaluated: number;
  selected: PaperTradeSignal[];
  skipped: PaperTradeSignal[];
}

export interface PaperSimulateDay {
  date: string;
  entries_filled: number;
  exits_triggered: number;
  realized_pnl: number;
  unrealized_pnl: number;
  bot_status: string;
  events: PaperLedgerEvent[];
}

export interface PaperReplaySummary {
  date: string;
  bot_status: string;
  selected: number;
  skipped: number;
  entries_filled: number;
  exits_triggered: number;
  realized_pnl: number;
  ending_equity: number;
}

export interface PaperReplay {
  start: string;
  end: string;
  days_processed: number;
  final_equity: number;
  total_realized_pnl: number;
  summary: PaperReplaySummary[];
}

export interface PaperPerformance {
  from_date: string;
  to_date: string;
  total_trades: number;
  closed_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  average_win: number;
  average_loss: number;
  profit_factor: number;
  expectancy: number;
  max_drawdown_percent: number;
  average_holding_days: number;
  best_setup: string | null;
  worst_setup: string | null;
  by_setup: Record<
    string,
    {
      trades: number;
      wins: number;
      losses: number;
      win_rate: number;
      total_pnl: number;
      average_pnl: number;
    }
  >;
  daily: PaperDailyPerformance[];
  equity_curve: Array<{ date: string; equity: number; daily_pnl: number }>;
}

export interface PaperJournal {
  date: string;
  summary: string;
  provider: string;
  disclaimer: string;
}

export interface PaperReset {
  deleted_signals: number;
  deleted_orders: number;
  deleted_positions: number;
  deleted_ledger: number;
  deleted_daily: number;
  message: string;
}

export const BOT_STATUS_TONE: Record<string, "green" | "red" | "amber" | "blue" | "violet" | "muted"> = {
  ACTIVE: "green",
  PAUSED: "amber",
  DAILY_LIMIT_REACHED: "blue",
  DAILY_LOSS_LIMIT_HIT: "red",
  MAX_OPEN_POSITIONS_REACHED: "amber",
  NO_QUALITY_SETUP: "muted",
  ERROR: "red",
};

export const POSITION_STATUS_TONE: Record<string, "green" | "red" | "amber" | "blue" | "violet" | "muted"> = {
  PENDING_ENTRY: "blue",
  OPEN: "green",
  PARTIAL_EXIT: "violet",
  CLOSED_TARGET: "green",
  CLOSED_STOP_LOSS: "red",
  CLOSED_TRAILING_STOP: "amber",
  CLOSED_TIME_EXIT: "muted",
  CANCELLED: "muted",
  EXPIRED: "muted",
};

// =====================================================
// Index Analysis Layer
// =====================================================

export interface IndexInstrument {
  symbol: string;
  code: string;
  name: string;
  exchange: string;
  lot_size: number;
  strike_step: number;
  has_options: boolean;
  has_nse_option_chain: boolean;
}

export interface IndexCandle {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IndexSnapshot {
  symbol: string;
  as_of_date: string;
  close: number;
  regime: string;
  atr: number | null;
  atr_pct: number | null;
  indicators_json: Record<string, number | null>;
  option_chain_summary_json: Record<string, unknown> | null;
}

export interface IndexSignal {
  id: number;
  symbol: string;
  run_at: string;
  as_of_date: string;
  category: string;
  direction: string;
  score: number;
  confidence: number;
  spot: number;
  entry: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  invalidation: number | null;
  reasons_json: string[];
  option_chain_bias: string | null;
}

export interface IndexDetail {
  instrument: IndexInstrument;
  snapshot: IndexSnapshot | null;
  signals: IndexSignal[];
}

export interface IndexRow {
  symbol: string;
  code: string;
  name: string;
  exchange: string;
  close: number;
  regime: string;
  score: number;
  confidence: number;
  direction: string | null;
  rsi: number | null;
  adx: number | null;
  atr_pct: number | null;
  pivot_p: number | null;
  pivot_r1: number | null;
  pivot_s1: number | null;
  pcr: number | null;
  pcr_volume: number | null;
  max_pain: number | null;
  max_pain_distance_pct: number | null;
  iv_skew: number | null;
  option_chain_bias: string | null;
  entry: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  invalidation: number | null;
  category: string | null;
  reasons: string[];
}

export interface OptionChainRow {
  strike: number;
  ce_oi: number | null;
  ce_change_oi: number | null;
  ce_volume: number | null;
  ce_iv: number | null;
  ce_ltp: number | null;
  pe_oi: number | null;
  pe_change_oi: number | null;
  pe_volume: number | null;
  pe_iv: number | null;
  pe_ltp: number | null;
}

export interface OptionChainSummary {
  pcr: number | null;
  pcr_volume: number | null;
  max_pain: number | null;
  max_pain_distance_pct: number | null;
  total_ce_oi: number;
  total_pe_oi: number;
  total_ce_change_oi: number;
  total_pe_change_oi: number;
  iv_skew: number | null;
  bias: string;
  bias_strength: number;
  notes: string[];
}

export interface OptionChain {
  symbol: string;
  code: string;
  spot: number | null;
  expiry: string;
  expiries: string[];
  fetched_at: string;
  source: string;
  summary: OptionChainSummary;
  rows: OptionChainRow[];
}

export const INDEX_CATEGORY_LABELS: Record<string, string> = {
  TREND_CONTINUATION: "Trend Continuation",
  BREAKOUT_RETEST: "Breakout Retest",
  PULLBACK_TO_EMA: "Pullback to EMA",
  TREND_BREAKDOWN: "Trend Breakdown",
  BREAKDOWN_RETEST: "Breakdown Retest",
  RALLY_TO_RESISTANCE: "Rally to Resistance",
};

export const INDEX_CATEGORY_TONE: Record<
  string,
  "green" | "red" | "amber" | "blue" | "violet" | "cyan"
> = {
  TREND_CONTINUATION: "green",
  BREAKOUT_RETEST: "green",
  PULLBACK_TO_EMA: "blue",
  TREND_BREAKDOWN: "red",
  BREAKDOWN_RETEST: "red",
  RALLY_TO_RESISTANCE: "amber",
};

export const OPTION_BIAS_TONE: Record<
  string,
  "green" | "red" | "amber" | "muted"
> = {
  Bullish: "green",
  Bearish: "red",
  Neutral: "muted",
};

// =====================================================
// Paper Index Trading Layer
// =====================================================

export interface PaperIndexBotConfig {
  id: number;
  virtual_capital: number;
  max_trades_per_day: number;
  max_open_positions: number;
  max_risk_per_trade_percent: number;
  max_daily_loss_percent: number;
  min_score: number;
  min_risk_reward: number;
  partial_exit_percent: number;
  trailing_stop_enabled: boolean;
  same_candle_policy: string;
  option_moneyness: string;
  option_delta_estimate: number;
  use_option_chain_bias: boolean;
  intraday_poll_seconds: number;
  intraday_signal_minutes: number;
  entry_order_expiry_days: number;
  max_holding_days: number;
  intraday_horizon_days: number;
  live_trading_enabled: boolean;
  live_poll_interval_seconds: number;
  created_at: string;
  updated_at: string;
}

export type PaperIndexBotConfigUpdate = Partial<
  Omit<PaperIndexBotConfig, "id" | "created_at" | "updated_at">
>;

export interface PaperIndexStatus {
  bot_status: string;
  virtual_capital: number;
  current_equity: number;
  realized_pnl_today: number;
  unrealized_pnl_today: number;
  realized_pnl_total: number;
  unrealized_pnl_total: number;
  trades_taken_today: number;
  remaining_trades_today: number;
  open_positions: number;
  daily_loss_limit_percent: number;
  live_trading_enabled: boolean;
  is_market_open: boolean;
  last_live_tick_at: string | null;
  market_regime: string;
  reason: string | null;
  disclaimer: string;
}

export interface PaperIndexLiveTick {
  processed_at: string;
  symbols_priced: number;
  exits_triggered: number;
  realized_pnl_today: number;
  unrealized_pnl: number;
  bot_status: string;
  prices: Record<string, number>;
  disclaimer: string;
}

export interface PaperIndexTradeSignal {
  id: number;
  signal_date: string;
  symbol: string;
  code: string;
  setup_type: string;
  direction: string;
  option_type: string;
  trend: string | null;
  market_regime: string | null;
  option_chain_bias: string | null;
  screener_score: number;
  automation_score: number;
  confidence: string | null;
  risk_level: string | null;
  risk_reward: number | null;
  spot: number | null;
  spot_stop_loss: number | null;
  spot_target_1: number | null;
  spot_target_2: number | null;
  spot_invalidation: number | null;
  strike: number | null;
  expiry: string | null;
  lot_size: number | null;
  lots: number | null;
  entry_premium: number | null;
  stop_loss_premium: number | null;
  target_1_premium: number | null;
  target_2_premium: number | null;
  delta_estimate: number | null;
  rsi: number | null;
  atr_percent: number | null;
  pcr: number | null;
  max_pain: number | null;
  decision: string;
  skip_reason: string | null;
  ai_reason: string | null;
  created_at: string;
}

export interface PaperIndexOrder {
  id: number;
  signal_id: number;
  symbol: string;
  code: string;
  option_type: string;
  strike: number;
  expiry: string;
  lot_size: number;
  lots: number;
  paper_order_type: string;
  side: string;
  planned_premium: number;
  filled_premium: number | null;
  status: string;
  note: string | null;
  created_at: string;
  filled_at: string | null;
}

export interface PaperIndexPosition {
  id: number;
  signal_id: number;
  symbol: string;
  code: string;
  setup_type: string;
  direction: string;
  option_type: string;
  strike: number;
  expiry: string;
  lot_size: number;
  lots: number;
  entry_spot: number | null;
  exit_spot: number | null;
  spot_stop_loss: number | null;
  spot_target_1: number | null;
  spot_target_2: number | null;
  entry_date: string | null;
  entry_premium: number | null;
  quantity: number;
  remaining_quantity: number;
  stop_loss: number;
  target_1: number | null;
  target_2: number | null;
  current_price: number | null;
  delta_estimate: number | null;
  status: string;
  realized_pnl: number;
  unrealized_pnl: number;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  holding_days: number | null;
  is_intraday: boolean;
  breakeven_moved: boolean;
  created_at: string;
  updated_at: string;
}

export interface PaperIndexLedgerEvent {
  id: number;
  position_id: number;
  date: string;
  event_type: string;
  symbol: string;
  code: string;
  option_type: string;
  strike: number;
  expiry: string;
  quantity: number;
  price: number | null;
  pnl: number;
  note: string | null;
  created_at: string;
}

export interface PaperIndexDailyPerformance {
  id: number;
  date: string;
  starting_capital: number;
  ending_capital: number;
  total_trades: number;
  open_trades: number;
  closed_trades: number;
  winning_trades: number;
  losing_trades: number;
  realized_pnl: number;
  unrealized_pnl: number;
  daily_return_percent: number;
  win_rate: number;
  average_win: number;
  average_loss: number;
  profit_factor: number;
  max_drawdown: number;
  bot_status: string;
  created_at: string;
}

export interface PaperIndexSelection {
  date: string;
  market_regime: string;
  candidates_evaluated: number;
  selected: PaperIndexTradeSignal[];
  skipped: PaperIndexTradeSignal[];
}

export interface PaperIndexSimulateDay {
  date: string;
  entries_filled: number;
  exits_triggered: number;
  realized_pnl: number;
  unrealized_pnl: number;
  bot_status: string;
  events: PaperIndexLedgerEvent[];
}

export interface PaperIndexReplaySummary {
  date: string;
  bot_status: string;
  selected: number;
  skipped: number;
  entries_filled: number;
  exits_triggered: number;
  realized_pnl: number;
  ending_equity: number;
}

export interface PaperIndexReplay {
  start: string;
  end: string;
  days_processed: number;
  final_equity: number;
  total_realized_pnl: number;
  summary: PaperIndexReplaySummary[];
}

export interface PaperIndexPerformance {
  from_date: string;
  to_date: string;
  total_trades: number;
  closed_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  average_win: number;
  average_loss: number;
  profit_factor: number;
  expectancy: number;
  max_drawdown_percent: number;
  average_holding_days: number;
  best_setup: string | null;
  worst_setup: string | null;
  by_setup: Record<
    string,
    {
      trades: number;
      wins: number;
      losses: number;
      win_rate: number;
      total_pnl: number;
      average_pnl: number;
    }
  >;
  daily: PaperIndexDailyPerformance[];
  equity_curve: Array<{ date: string; equity: number; daily_pnl: number }>;
}

export interface PaperIndexJournal {
  date: string;
  summary: string;
  provider: string;
  disclaimer: string;
}

export interface PaperIndexReset {
  deleted_signals: number;
  deleted_orders: number;
  deleted_positions: number;
  deleted_ledger: number;
  deleted_daily: number;
  message: string;
}

// =====================================================
// Live Analysis Mode
// =====================================================
export type LiveAppMode = "HISTORICAL" | "LIVE";

export interface LiveModeOut {
  mode: LiveAppMode;
  market_open: boolean;
}

export interface LiveWeights {
  w1_z: number;
  w2_slope: number;
  w3_vwap: number;
  w4_ema20: number;
  w5_rvol: number;
  w6_body: number;
  w7_rsi_penalty: number;
}

export interface LiveAnalysisConfig {
  mode: LiveAppMode;
  poll_interval_min: number;
  observation_samples: number;
  top_k_movers: number;
  cooldown_min: number;
  decision_threshold: number;
  confidence_threshold: number;
  regime_risk_on_z: number;
  regime_risk_off_z: number;
  weights: LiveWeights;
}

export interface LiveMover {
  symbol: string;
  last: number;
  pct_change: number;
  rvol: number;
  rank: number;
  score: number;
}

export interface LiveMarketSnapshot {
  id: number;
  ts: string | null;
  regime: "RISK_ON" | "NEUTRAL" | "RISK_OFF" | string;
  nifty_last: number | null;
  nifty_z: number | null;
  nifty_slope: number | null;
  nifty_vwap_dev: number | null;
  top_movers: LiveMover[];
  counters: Record<string, number | string> | null;
}

export interface LiveSample {
  ts: string;
  price: number;
  volume: number;
}

export type LiveObservationStatus =
  | "OBSERVING"
  | "COOLDOWN"
  | "COMPLETED"
  | "CANCELLED"
  | "DECIDED";

export interface LiveObservation {
  id: number;
  symbol: string;
  status: LiveObservationStatus;
  started_at: string | null;
  completed_at: string | null;
  sample_count: number;
  samples: LiveSample[];
  vwap: number | null;
  rvol: number | null;
  atr_3m: number | null;
  rsi_3m: number | null;
  ema20_3m: number | null;
  note: string | null;
}

export interface LiveDecision {
  id: number;
  observation_id: number;
  symbol: string;
  ts: string | null;
  direction: "LONG" | "SHORT" | "HOLD" | string;
  confidence: number;
  long_raw: number;
  short_raw: number;
  invalidation: number | null;
  regime: string | null;
  factors: Record<string, number>;
}

export interface LiveDashboard {
  mode: LiveAppMode;
  market_open: boolean;
  config: LiveAnalysisConfig;
  market_snapshot: LiveMarketSnapshot | null;
  active_observations: LiveObservation[];
  recent_decisions: LiveDecision[];
  disclaimer: string;
}

export interface LiveTickOut {
  processed_at: string;
  mode: LiveAppMode;
  market_open: boolean;
  regime: string;
  symbols_priced: number;
  top_movers_count: number;
  observations_active: number;
  observations_started: number;
  decisions_emitted: number;
  cooldowns_released: number;
  note: string;
}
