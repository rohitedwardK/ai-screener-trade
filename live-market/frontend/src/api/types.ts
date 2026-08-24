// API DTOs - keep field names in sync with backend/app/models/schemas.py.

export interface IntradayBar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface RegimeSnapshot {
  id: number;
  symbol: string;
  ts: string;
  regime: string;
  spot: number;
  daily_adx: number | null;
  bb_width_pct: number | null;
  ema_spread_pct: number | null;
  realized_range_pct: number | null;
  atr_pct: number | null;
  vwap: number | null;
  reasons: string[];
}

export interface ScalpSetup {
  id: number;
  symbol: string;
  category: string;
  direction: "LONG" | "SHORT";
  status: string;
  score: number;
  reasons: string[];
  spot_entry: number;
  spot_stop: number;
  spot_t1: number;
  spot_t2: number;
  spot_invalidation: number;
  option_strike: number | null;
  option_type: "CE" | "PE" | null;
  option_expiry: string | null;
  option_instrument_key: string | null;
  option_premium_entry: number | null;
  option_premium_stop: number | null;
  option_premium_t1: number | null;
  option_premium_t2: number | null;
  created_at: string;
  expires_at: string;
  resolved_at: string | null;
  resolved_price: number | null;
  note: string | null;
}

export interface SwingSetup extends Omit<ScalpSetup, "id"> {
  id: number;
  days_to_expiry: number;
}

export interface IndexCard {
  symbol: string;
  code: string;
  name: string;
  spot: number | null;
  last_bar_ts: string | null;
  last_bar_age_seconds: number | null;
  regime: string;
  regime_reasons: string[];
  daily_adx: number | null;
  vwap: number | null;
  range_support: number | null;
  range_resistance: number | null;
  active_scalps: number;
  active_swings: number;
  has_option_chain: boolean;
}

export interface Dashboard {
  indices: IndexCard[];
  fetched_at: string;
  disclaimer: string;
}

export interface IndexDetail {
  card: IndexCard;
  bars: IntradayBar[];
  active_scalps: ScalpSetup[];
  active_swings: SwingSetup[];
  recent_history_scalps: ScalpSetup[];
  recent_history_swings: SwingSetup[];
  recent_regimes: RegimeSnapshot[];
  disclaimer: string;
}

export interface Health {
  status: string;
  upstox_configured: boolean;
  upstox_token_dead: boolean;
  last_tick_ts: string | null;
  bar_counts: Record<string, number>;
}

export interface TickResult {
  processed_at: string;
  symbols_priced: number;
  regimes: Record<string, string>;
  scalps_emitted: number;
  swings_emitted: number;
  setups_resolved: number;
  note: string;
}

// ---------------------------------------------------------------------------
// Option-chain analytics DTOs - mirror backend/app/models/schemas.py
// ---------------------------------------------------------------------------
export interface OptionRow {
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

export interface OIWall {
  strike: number;
  oi: number;
  side: "CE" | "PE";
}

export interface OptionBias {
  symbol: string;
  spot: number | null;
  expiry: string | null;
  fetched_at: string | null;
  pcr_oi: number | null;
  pcr_volume: number | null;
  total_ce_oi: number;
  total_pe_oi: number;
  max_pain: number | null;
  atm_iv: number | null;
  iv_skew: number | null;
  ce_oi_added: number;
  pe_oi_added: number;
  flow_direction: "BULLISH" | "BEARISH" | "NEUTRAL";
  resistance_walls: OIWall[];
  support_walls: OIWall[];
  bias_label: "BULLISH" | "BEARISH" | "NEUTRAL";
  bias_score: number;
  bias_reasons: string[];
  disclaimer?: string;
}

export interface OptionChain {
  symbol: string;
  code: string;
  spot: number | null;
  expiry: string | null;
  fetched_at: string | null;
  source: string;
  rows: OptionRow[];
  disclaimer?: string;
}

export interface StrikeCandidate {
  moneyness: "OTM" | "ATM" | "ITM";
  strike: number;
  type: "CE" | "PE";
  expiry: string;
  instrument_key: string | null;
  delta_assumed: number;
  premium_entry: number;
  premium_stop: number;
  premium_t1: number;
  premium_t2: number;
  breakeven_spot: number;
  max_loss_per_unit: number;
  max_profit_per_unit: number;
  days_to_expiry: number;
  theta_per_day: number;
  theta_drag_total: number;
  hold_days: number;
  reasons: string[];
}

export interface CreditSpread {
  bias: "BULLISH" | "BEARISH";
  short_strike: number;
  long_strike: number;
  short_type: "CE" | "PE";
  expiry: string;
  short_instrument_key: string | null;
  long_instrument_key: string | null;
  short_premium: number;
  long_premium: number;
  net_credit: number;
  max_profit: number;
  max_loss: number;
  breakeven_spot: number;
  days_to_expiry: number;
  theta_per_day: number;
  projected_value_1d: number;
  projected_value_3d: number;
  projected_value_at_expiry: number;
  reasons: string[];
  warning: string;
}

export interface StrikeRecommendations {
  symbol: string;
  code: string;
  spot: number | null;
  expiry: string | null;
  bias: OptionBias | null;
  candidates: StrikeCandidate[];
  credit_spread: CreditSpread | null;
  note: string;
  disclaimer?: string;
}

export const REGIME_TONE: Record<string, "green" | "red" | "blue" | "amber" | "muted"> = {
  TRENDING_UP: "green",
  TRENDING_DOWN: "red",
  RANGE_BOUND: "blue",
  CHOPPY: "muted",
};

export const STATUS_TONE: Record<string, "green" | "red" | "amber" | "muted"> = {
  ACTIVE: "amber",
  TARGET_HIT: "green",
  STOPPED: "red",
  INVALIDATED: "red",
  EXPIRED: "muted",
};

export const BIAS_TONE: Record<string, "green" | "red" | "muted"> = {
  BULLISH: "green",
  BEARISH: "red",
  NEUTRAL: "muted",
};
