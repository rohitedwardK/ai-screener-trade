export interface Stock {
  symbol: string;
  name: string | null;
  sector: string | null;
}

export type LiveVerificationStatus =
  | "CONFIRMED"
  | "WEAKENING"
  | "INVALIDATED"
  | "STRENGTHENED";

export interface LiveVerification {
  status: LiveVerificationStatus;
  live_close: number;
  live_rsi: number | null;
  live_adx: number | null;
  live_regime: string;
  score_delta: number | null;
  distance_to_stop_pct: number | null;
  distance_to_t1_pct: number | null;
  notes: string[];
  source: string | null;
  run_at: string;
}

export const LIVE_STATUS_TONE: Record<LiveVerificationStatus, "green" | "amber" | "red" | "blue"> = {
  CONFIRMED: "green",
  WEAKENING: "amber",
  INVALIDATED: "red",
  STRENGTHENED: "blue",
};

export const LIVE_STATUS_LABEL: Record<LiveVerificationStatus, string> = {
  CONFIRMED: "Confirmed",
  WEAKENING: "Weakening",
  INVALIDATED: "Invalidated",
  STRENGTHENED: "Strengthened",
};

export interface LiveVerificationSummary {
  confirmed: number;
  weakening: number;
  invalidated: number;
  strengthened: number;
  total: number;
  last_run_at: string | null;
  source: string | null;
  disclaimer: string;
}

export interface LiveVerificationRunResult {
  started_at: string;
  finished_at: string;
  signals_evaluated: number;
  rows_upserted: number;
  by_status: Record<string, number>;
  source: string;
  errors: string[];
  disclaimer: string;
}

export interface LiveVerificationSignalRow {
  signal_id: number;
  symbol: string;
  category: string;
  score: number;
  persisted_close: number;
  entry: number | null;
  stop_loss: number | null;
  target_1: number | null;
  status: LiveVerificationStatus;
  live_close: number;
  live_rsi: number | null;
  live_adx: number | null;
  live_regime: string;
  score_delta: number | null;
  distance_to_stop_pct: number | null;
  distance_to_t1_pct: number | null;
  notes: string[];
  source: string | null;
  run_at: string;
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
  live: LiveVerification | null;
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

export interface StrikeLeg {
  option_type: "CE" | "PE" | string;
  strike: number;
  side: "BUY" | "SELL" | string;
  delta_estimate: number;
  premium: number;
  iv: number | null;
  oi: number | null;
  bid: number | null;
  ask: number | null;
}

export type StrikeRecommendationStatus =
  | "ACTIVE"
  | "T1_HIT"
  | "T2_HIT"
  | "STOP_HIT"
  | "INVALIDATED"
  | "EXPIRED"
  | "REJECTED";

export interface ContractRecommendation {
  id: number;
  signal_id: number;
  symbol: string;
  code: string;
  strategy: "SINGLE_LEG" | "DEBIT_SPREAD" | string;
  direction: "LONG" | "SHORT" | string;
  expiry: string;
  legs: StrikeLeg[];
  net_debit: number;
  max_profit: number | null;
  max_loss: number;
  entry_premium: number;
  sl_premium: number;
  t1_premium: number;
  t2_premium: number;
  breakeven: number | null;
  notes: string[];
  rejection_reason: string | null;
  status: StrikeRecommendationStatus | string;
  last_premium: number | null;
  last_checked_at: string | null;
  created_at: string;
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
  expiry: string | null;
  days_to_expiry: number | null;
  horizon: string | null;
  reasons_json: string[];
  option_chain_bias: string | null;
  recommendations: ContractRecommendation[];
}

export const STRIKE_STATUS_LABEL: Record<string, string> = {
  ACTIVE: "Active",
  T1_HIT: "Target 1 hit",
  T2_HIT: "Target 2 hit",
  STOP_HIT: "Stop hit",
  INVALIDATED: "Invalidated",
  EXPIRED: "Expired",
  REJECTED: "Rejected",
};

export const STRIKE_STATUS_TONE: Record<
  string,
  "green" | "amber" | "red" | "blue" | "muted" | "violet"
> = {
  ACTIVE: "blue",
  T1_HIT: "green",
  T2_HIT: "green",
  STOP_HIT: "red",
  INVALIDATED: "red",
  EXPIRED: "muted",
  REJECTED: "amber",
};

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
