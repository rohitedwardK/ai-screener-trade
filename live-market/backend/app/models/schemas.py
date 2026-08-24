"""Pydantic v2 DTOs returned by the API."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# Verbatim disclaimer per project rule. Echoed in payloads that surface
# trade plans so the user-facing UI never strips it.
DISCLAIMER = "Research and decision-support only. Not financial advice."


class IntradayBarDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class RegimeSnapshotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    symbol: str
    ts: datetime
    regime: str
    spot: float
    daily_adx: Optional[float] = None
    bb_width_pct: Optional[float] = None
    ema_spread_pct: Optional[float] = None
    realized_range_pct: Optional[float] = None
    atr_pct: Optional[float] = None
    vwap: Optional[float] = None
    reasons: List[str] = []


class ScalpSetupDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    symbol: str
    category: str
    direction: str
    status: str
    score: float
    reasons: List[str] = []
    spot_entry: float
    spot_stop: float
    spot_t1: float
    spot_t2: float
    spot_invalidation: float
    option_strike: Optional[float] = None
    option_type: Optional[str] = None
    option_expiry: Optional[datetime] = None
    option_instrument_key: Optional[str] = None
    option_premium_entry: Optional[float] = None
    option_premium_stop: Optional[float] = None
    option_premium_t1: Optional[float] = None
    option_premium_t2: Optional[float] = None
    created_at: datetime
    expires_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_price: Optional[float] = None
    note: Optional[str] = None


class SwingSetupDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    symbol: str
    category: str
    direction: str
    status: str
    score: float
    reasons: List[str] = []
    spot_entry: float
    spot_stop: float
    spot_t1: float
    spot_t2: float
    spot_invalidation: float
    option_strike: Optional[float] = None
    option_type: Optional[str] = None
    option_expiry: Optional[datetime] = None
    option_instrument_key: Optional[str] = None
    option_premium_entry: Optional[float] = None
    option_premium_stop: Optional[float] = None
    option_premium_t1: Optional[float] = None
    option_premium_t2: Optional[float] = None
    days_to_expiry: int
    created_at: datetime
    expires_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_price: Optional[float] = None
    note: Optional[str] = None


class IndexCardDTO(BaseModel):
    """One row on the dashboard."""
    symbol: str
    code: str
    name: str
    spot: Optional[float] = None
    last_bar_ts: Optional[datetime] = None
    last_bar_age_seconds: Optional[float] = None
    regime: str
    regime_reasons: List[str] = []
    daily_adx: Optional[float] = None
    vwap: Optional[float] = None
    range_support: Optional[float] = None
    range_resistance: Optional[float] = None
    active_scalps: int = 0
    active_swings: int = 0
    has_option_chain: bool = True


class DashboardDTO(BaseModel):
    indices: List[IndexCardDTO]
    fetched_at: datetime
    disclaimer: str = DISCLAIMER


class IndexDetailDTO(BaseModel):
    """All info needed by the per-index page."""
    card: IndexCardDTO
    bars: List[IntradayBarDTO]
    active_scalps: List[ScalpSetupDTO]
    active_swings: List[SwingSetupDTO]
    recent_history_scalps: List[ScalpSetupDTO]
    recent_history_swings: List[SwingSetupDTO]
    recent_regimes: List[RegimeSnapshotDTO]
    disclaimer: str = DISCLAIMER


class HealthDTO(BaseModel):
    status: str
    upstox_configured: bool
    upstox_token_dead: bool
    last_tick_ts: Optional[datetime] = None
    bar_counts: dict


class TickResultDTO(BaseModel):
    processed_at: datetime
    symbols_priced: int
    regimes: dict
    scalps_emitted: int
    swings_emitted: int
    setups_resolved: int
    note: str = ""


# ---------------------------------------------------------------------------
# Option-chain analytics DTOs
# ---------------------------------------------------------------------------
class OptionRowDTO(BaseModel):
    """One strike row of the live chain - mirrors `data/option_types.OptionRow`."""
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


class OIWallDTO(BaseModel):
    strike: float
    oi: float
    side: str   # CE | PE


class OptionBiasDTO(BaseModel):
    """All five derived signals + the combined bias label/score/reasons."""
    symbol: str
    spot: Optional[float] = None
    expiry: Optional[datetime] = None
    fetched_at: Optional[datetime] = None

    pcr_oi: Optional[float] = None
    pcr_volume: Optional[float] = None
    total_ce_oi: float = 0.0
    total_pe_oi: float = 0.0

    max_pain: Optional[float] = None
    atm_iv: Optional[float] = None
    iv_skew: Optional[float] = None

    ce_oi_added: float = 0.0
    pe_oi_added: float = 0.0
    flow_direction: str = "NEUTRAL"

    resistance_walls: List[OIWallDTO] = []
    support_walls: List[OIWallDTO] = []

    bias_label: str = "NEUTRAL"
    bias_score: float = 0.0
    bias_reasons: List[str] = []
    disclaimer: str = DISCLAIMER


class OptionChainDTO(BaseModel):
    """Full chain rows for the index, plus a few summary numbers."""
    symbol: str
    code: str
    spot: Optional[float] = None
    expiry: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    source: str = "upstox"
    rows: List[OptionRowDTO] = []
    disclaimer: str = DISCLAIMER


class StrikeCandidateDTO(BaseModel):
    moneyness: str   # OTM | ATM | ITM
    strike: float
    type: str        # CE | PE
    expiry: datetime
    instrument_key: Optional[str] = None
    delta_assumed: float
    premium_entry: float
    premium_stop: float
    premium_t1: float
    premium_t2: float
    breakeven_spot: float
    max_loss_per_unit: float
    max_profit_per_unit: float
    days_to_expiry: float = 0.0
    theta_per_day: float = 0.0
    theta_drag_total: float = 0.0
    hold_days: float = 0.0
    reasons: List[str] = []


class CreditSpreadDTO(BaseModel):
    bias: str        # BULLISH | BEARISH
    short_strike: float
    long_strike: float
    short_type: str  # CE | PE
    expiry: datetime
    short_instrument_key: Optional[str] = None
    long_instrument_key: Optional[str] = None
    short_premium: float
    long_premium: float
    net_credit: float
    max_profit: float
    max_loss: float
    breakeven_spot: float
    days_to_expiry: float = 0.0
    theta_per_day: float = 0.0
    projected_value_1d: float = 0.0
    projected_value_3d: float = 0.0
    projected_value_at_expiry: float = 0.0
    reasons: List[str] = []
    warning: str = (
        "Defined-risk spread. Max loss is CAPPED only when BOTH legs are filled. "
        "Never execute the short leg alone."
    )


class StrikeRecommendationsDTO(BaseModel):
    """Full recommendation payload for one index.

    Contains the derived bias (so the UI can show the rationale alongside),
    the OTM/ATM/ITM single-leg ladder, and an optional credit spread when
    the bias is directional enough to justify it.
    """
    symbol: str
    code: str
    spot: Optional[float] = None
    expiry: Optional[datetime] = None
    bias: Optional[OptionBiasDTO] = None
    candidates: List[StrikeCandidateDTO] = []
    credit_spread: Optional[CreditSpreadDTO] = None
    note: str = ""
    disclaimer: str = DISCLAIMER


__all__ = [
    "DISCLAIMER",
    "IntradayBarDTO",
    "RegimeSnapshotDTO",
    "ScalpSetupDTO",
    "SwingSetupDTO",
    "IndexCardDTO",
    "DashboardDTO",
    "IndexDetailDTO",
    "HealthDTO",
    "TickResultDTO",
    "OptionRowDTO",
    "OIWallDTO",
    "OptionBiasDTO",
    "OptionChainDTO",
    "StrikeCandidateDTO",
    "CreditSpreadDTO",
    "StrikeRecommendationsDTO",
]
