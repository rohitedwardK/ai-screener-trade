"""Index universe — Nifty 50, Sensex, Bank Nifty.

These are non-tradable spot indices. The paper-index bot trades them via
**index options** (CE/PE) using the lot sizes defined here. Lot sizes are
revised periodically by the exchange; update this table when NSE/BSE
publishes a circular.

Yahoo tickers:
  ^NSEI    — Nifty 50 (NSE)
  ^BSESN   — BSE Sensex
  ^NSEBANK — Bank Nifty (NSE)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class IndexMeta:
    symbol: str               # Yahoo ticker (e.g. ^NSEI)
    code: str                 # short trading code (NIFTY, SENSEX, BANKNIFTY) used by NSE/BSE
    name: str
    exchange: str             # NSE | BSE
    lot_size: int             # contract multiplier per lot (FY26)
    strike_step: float        # ATM strike rounding step
    has_options: bool
    has_nse_option_chain: bool  # True only for NSE-listed indices
    weekly_expiry_day: Optional[str] = None  # human-readable note; not used by simulator


# Lot sizes are accurate as of late 2025 / early 2026. NSE has been raising
# index option lot sizes in stages; refresh this list whenever the exchange
# publishes a "Revision in Market Lots of Derivative Contracts" circular.
INDICES: List[IndexMeta] = [
    IndexMeta(
        symbol="^NSEI",
        code="NIFTY",
        name="Nifty 50",
        exchange="NSE",
        lot_size=75,
        strike_step=50.0,
        has_options=True,
        has_nse_option_chain=True,
        weekly_expiry_day="Tuesday",
    ),
    IndexMeta(
        symbol="^NSEBANK",
        code="BANKNIFTY",
        name="Bank Nifty",
        exchange="NSE",
        lot_size=35,
        strike_step=100.0,
        has_options=True,
        has_nse_option_chain=True,
        weekly_expiry_day="Wednesday",
    ),
    IndexMeta(
        symbol="^BSESN",
        code="SENSEX",
        name="BSE Sensex",
        exchange="BSE",
        lot_size=20,
        strike_step=100.0,
        has_options=True,
        has_nse_option_chain=False,  # NSE option-chain endpoint covers NIFTY/BANKNIFTY/FINNIFTY only
        weekly_expiry_day="Thursday",
    ),
]


def all_index_symbols() -> List[str]:
    return [i.symbol for i in INDICES]


def index_meta() -> List[Dict]:
    return [
        {
            "symbol": i.symbol,
            "code": i.code,
            "name": i.name,
            "exchange": i.exchange,
            "lot_size": i.lot_size,
            "strike_step": i.strike_step,
            "has_options": i.has_options,
            "has_nse_option_chain": i.has_nse_option_chain,
            "weekly_expiry_day": i.weekly_expiry_day,
        }
        for i in INDICES
    ]


def get_index(symbol: str) -> Optional[IndexMeta]:
    for i in INDICES:
        if i.symbol == symbol or i.code.upper() == symbol.upper():
            return i
    return None


def lot_size_for(symbol: str) -> Optional[int]:
    m = get_index(symbol)
    return m.lot_size if m else None


def strike_step_for(symbol: str) -> Optional[float]:
    m = get_index(symbol)
    return m.strike_step if m else None


def round_to_step(spot: float, step: float) -> float:
    """Round spot to the nearest strike step (ATM strike)."""
    if step <= 0:
        return spot
    return round(spot / step) * step
