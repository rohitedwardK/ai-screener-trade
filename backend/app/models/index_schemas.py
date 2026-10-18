"""Pydantic schemas for the index-analysis API.

Includes the read-only weekly-expiry strike recommendation surface
(`StrikeLegOut`, `ContractRecommendationOut`) attached to each
`IndexSignalOut`. The paper-index trading schemas were removed when the
auto-trading layer was retired — this file is now read-only-analysis only.
"""
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


class StrikeLegOut(BaseModel):
    """One leg of a contract recommendation."""
    option_type: str
    strike: float
    side: str
    delta_estimate: float
    premium: float
    iv: Optional[float] = None
    oi: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None


class ContractRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_id: int
    symbol: str
    code: str
    strategy: str                          # SINGLE_LEG | DEBIT_SPREAD
    direction: str                         # LONG | SHORT
    expiry: date
    legs: List[StrikeLegOut] = Field(default_factory=list)
    net_debit: float
    max_profit: Optional[float] = None
    max_loss: float
    entry_premium: float
    sl_premium: float
    t1_premium: float
    t2_premium: float
    breakeven: Optional[float] = None
    notes: List[str] = Field(default_factory=list)
    rejection_reason: Optional[str] = None
    status: str
    last_premium: Optional[float] = None
    last_checked_at: Optional[datetime] = None
    created_at: datetime


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
    expiry: Optional[date] = None
    days_to_expiry: Optional[int] = None
    horizon: Optional[str] = None
    reasons_json: List[str] = Field(default_factory=list)
    option_chain_bias: Optional[str] = None
    recommendations: List[ContractRecommendationOut] = Field(default_factory=list)


class IndexForecastOut(BaseModel):
    weekly_bias: str = "Neutral"
    hourly_bias: str = "Neutral"
    fifteen_minute_bias: str = "Neutral"
    next_5m_bias: str = "WAIT"
    setup: str = "NO_TRADE"
    breakout_state: str = "INSIDE_RANGE"
    breakout_level: Optional[float] = None
    breakdown_level: Optional[float] = None
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    invalidation: Optional[float] = None
    confidence: float = 0.0
    reasons: List[str] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)
    as_of: Optional[str] = None


class IndexForecastChartOut(BaseModel):
    timeframe: str
    bars: List[Dict[str, Any]] = Field(default_factory=list)
    support: Optional[float] = None
    resistance: Optional[float] = None


class IndexDetailOut(BaseModel):
    instrument: IndexInstrumentOut
    snapshot: Optional[IndexSnapshotOut] = None
    signals: List[IndexSignalOut] = Field(default_factory=list)
    forecast: Optional[IndexForecastOut] = None
    forecast_chart: Dict[str, IndexForecastChartOut] = Field(default_factory=dict)


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

