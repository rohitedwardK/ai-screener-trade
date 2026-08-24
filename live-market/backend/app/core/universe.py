"""Index universe for the Live Market service.

Mirrors a slim subset of `backend/app/core/index_universe.py`. We only
need the three tradable spot indices and their option-related metadata
(lot size, strike step, weekly expiry day, whether an option chain is
available).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class IndexMeta:
    symbol: str               # Yahoo-style ticker (^NSEI, ^NSEBANK, ^BSESN)
    code: str                 # NIFTY | BANKNIFTY | SENSEX
    name: str
    exchange: str             # NSE | BSE
    lot_size: int
    strike_step: float
    has_options: bool
    has_option_chain: bool    # True only when we can fetch via Upstox /option/chain
    weekly_expiry_day: str


INDICES: List[IndexMeta] = [
    IndexMeta(
        symbol="^NSEI", code="NIFTY", name="Nifty 50",
        exchange="NSE", lot_size=75, strike_step=50.0,
        has_options=True, has_option_chain=True,
        weekly_expiry_day="Tuesday",
    ),
    IndexMeta(
        symbol="^NSEBANK", code="BANKNIFTY", name="Bank Nifty",
        exchange="NSE", lot_size=35, strike_step=100.0,
        has_options=True, has_option_chain=True,
        weekly_expiry_day="Wednesday",
    ),
    IndexMeta(
        symbol="^BSESN", code="SENSEX", name="BSE Sensex",
        exchange="BSE", lot_size=20, strike_step=100.0,
        # SENSEX expiries are now on BSE F&O; Upstox /option/chain coverage
        # for SENSEX is inconsistent, so we treat it as "no chain" and emit
        # spot-only plans.
        has_options=True, has_option_chain=False,
        weekly_expiry_day="Thursday",
    ),
]


_BY_SYMBOL: Dict[str, IndexMeta] = {i.symbol: i for i in INDICES}
_BY_CODE: Dict[str, IndexMeta] = {i.code: i for i in INDICES}


def all_symbols() -> List[str]:
    return [i.symbol for i in INDICES]


def get_meta(symbol_or_code: str) -> Optional[IndexMeta]:
    return _BY_SYMBOL.get(symbol_or_code) or _BY_CODE.get(symbol_or_code.upper())


def round_to_step(spot: float, step: float) -> float:
    if step <= 0:
        return spot
    return round(spot / step) * step


__all__ = ["IndexMeta", "INDICES", "all_symbols", "get_meta", "round_to_step"]
