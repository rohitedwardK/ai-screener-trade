"""Pydantic response/request schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class StockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None


class CandleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    run_at: datetime
    as_of_date: date
    category: str
    score: float
    confidence: float
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    invalidation: Optional[float] = None
    reasons_json: List[str] = []
    direction: Optional[str] = None
    expiry: Optional[date] = None
    days_to_expiry: Optional[int] = None
    horizon: Optional[str] = None


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    as_of_date: date
    close: float
    regime: str
    atr: Optional[float] = None
    atr_pct: Optional[float] = None
    indicators_json: Dict[str, Any] = {}


class StockDetailOut(BaseModel):
    stock: StockOut
    snapshot: Optional[SnapshotOut] = None
    signals: List[SignalOut] = []
    # MCX detail uses the same live quote as the commodity card. The snapshot
    # close stays the last daily bar so indicators are not mixed with the LTP.
    live_price: Optional[float] = None
    quote_source: Optional[str] = None
    contract_label: Optional[str] = None
    watch_notes: List[str] = []


class ForecastMetricOut(BaseModel):
    brier: float
    log_loss: float
    baseline_accuracy: float
    accuracy_at_50: float
    auc: float


class CalibrationBinOut(BaseModel):
    lower: float
    upper: float
    count: int
    mean_probability: float
    observed_frequency: float


class DailyForecastMetricsOut(BaseModel):
    samples: int
    train_samples: int
    validation_samples: int
    test_samples: int
    validation: ForecastMetricOut
    test: ForecastMetricOut
    test_baseline_brier: float
    calibration_bins: List[CalibrationBinOut] = []


class DailyForecastOut(BaseModel):
    symbol: str
    as_of: Optional[str] = None
    probability_up: Optional[float] = None
    latest_features: Dict[str, float] = {}
    baseline_probability: Optional[float] = None
    metrics: Optional[DailyForecastMetricsOut] = None
    coefficients: Dict[str, float] = {}
    data_quality: Dict[str, Any] = {}
    notes: List[str] = []
    disclaimer: str = "Research and decision-support only. Not financial advice."


class MA20CrossingOut(BaseModel):
    symbol: str
    name: str
    sector: str
    direction: str
    crossed_at: str
    as_of: str
    sessions_since_cross: int
    status: str
    close: float
    cross_close: float
    ma20: float
    invalidation: float
    distance_pct: float
    since_cross_pct: float
    daily_return_pct: float
    relative_volume: Optional[float] = None


class MA20WatchlistOut(BaseModel):
    lookback: int
    scanned: int
    rows: List[MA20CrossingOut]
    skipped: List[Dict[str, str]]
    generated_at: str
    disclaimer: str


class LiveVerificationView(BaseModel):
    """Inline live cross-check attached to a screener row (when present)."""
    status: str
    live_close: float
    live_rsi: Optional[float] = None
    live_adx: Optional[float] = None
    live_regime: str
    score_delta: Optional[float] = None
    distance_to_stop_pct: Optional[float] = None
    distance_to_t1_pct: Optional[float] = None
    notes: List[str] = []
    source: Optional[str] = None
    run_at: datetime


class TradeQualityOut(BaseModel):
    status: str
    probability: Optional[float] = None
    quality_score: Optional[float] = None
    target: str
    as_of: Optional[str] = None
    disclaimer: str = "Research and decision-support only. Not financial advice."


class ScreenerRow(BaseModel):
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    category: str
    regime: str
    score: float
    confidence: float
    close: float
    rsi: Optional[float] = None
    adx: Optional[float] = None
    atr_pct: Optional[float] = None
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    invalidation: Optional[float] = None
    reasons: List[str] = []
    live: Optional[LiveVerificationView] = None
    trade_quality: Optional[TradeQualityOut] = None
    direction: Optional[str] = None
    expiry: Optional[date] = None
    days_to_expiry: Optional[int] = None
    horizon: Optional[str] = None


class CategoryCount(BaseModel):
    category: str
    count: int
    top: List[ScreenerRow] = []


class ExplainSections(BaseModel):
    setup: str
    indicators: str = ""
    rules: List[str] = []
    plan: str = ""
    risks: str = ""


class ExplainOut(BaseModel):
    symbol: str
    explanation: str
    sections: ExplainSections
    disclaimer: str
    invalidation_level: Optional[float] = None
    confidence: float
    provider: str


class RefreshResult(BaseModel):
    started_at: datetime
    finished_at: datetime
    fetched_symbols: int
    signals_generated: int
    errors: List[str] = []


class CommodityItem(BaseModel):
    symbol: str
    name: str
    venue: str
    currency: str
    unit: str
    close: float
    live_price: Optional[float] = None
    quote_source: str
    regime: str
    rsi: Optional[float] = None
    adx: Optional[float] = None
    atr_pct: Optional[float] = None
    as_of_date: Optional[date] = None
    contract_label: Optional[str] = None
    monthly_expiry: Optional[date] = None
    days_to_expiry: Optional[int] = None
    week_hold_days: Optional[int] = None
    setup_horizon: Optional[str] = None  # weekly | monthly | None
    watch_notes: List[str] = []
    signals: List[ScreenerRow] = []


class CommodityDashboard(BaseModel):
    market_open: bool
    quote_source: str
    items: List[CommodityItem]
    disclaimer: str = "Research and decision-support only. Not financial advice."


class IntradayCandleOut(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class IntradayScalpOut(BaseModel):
    category: str
    direction: str
    score: float
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    invalidation: float
    hold_minutes: int
    reasons: List[str] = []


class IntradayAnalysisOut(BaseModel):
    symbol: str
    interval: str = "15m"
    source: str
    regime: str
    bars: List[IntradayCandleOut] = []
    support: Optional[float] = None
    resistance: Optional[float] = None
    vwap: Optional[float] = None
    atr: Optional[float] = None
    rsi: Optional[float] = None
    patterns: List[str] = []
    scalps: List[IntradayScalpOut] = []
    signal_id: Optional[int] = None
    signal_category: Optional[str] = None
    signal_direction: Optional[str] = None
    aligned_with_signal: Optional[bool] = None
    disclaimer: str = "Research and decision-support only. Not financial advice."
