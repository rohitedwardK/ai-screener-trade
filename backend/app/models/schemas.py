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


class CategoryCount(BaseModel):
    category: str
    count: int
    top: List[ScreenerRow] = []


class ExplainOut(BaseModel):
    symbol: str
    explanation: str
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
