"""Minimal option-chain value objects.

Mirrors the shape used by the parent app's `data/option_chain.py` so the
strike picker code reads the same way, but keeps the live-market service
free of the parent's `requests` / `yfinance` dependencies. We only ever
fetch from Upstox here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional


@dataclass
class OptionRow:
    strike: float
    ce_oi: Optional[float] = None
    ce_change_oi: Optional[float] = None
    ce_volume: Optional[float] = None
    ce_iv: Optional[float] = None
    ce_ltp: Optional[float] = None
    ce_bid: Optional[float] = None
    ce_ask: Optional[float] = None
    pe_oi: Optional[float] = None
    pe_change_oi: Optional[float] = None
    pe_volume: Optional[float] = None
    pe_iv: Optional[float] = None
    pe_ltp: Optional[float] = None
    pe_bid: Optional[float] = None
    pe_ask: Optional[float] = None


@dataclass
class OptionChainPayload:
    code: str                              # NIFTY | BANKNIFTY | SENSEX
    spot: Optional[float]
    expiry: date
    expiries: List[date]
    fetched_at: datetime
    source: str                            # always "upstox" in this service
    rows: List[OptionRow] = field(default_factory=list)
    instrument_keys_by_strike: Dict[float, Dict[str, str]] = field(default_factory=dict)
