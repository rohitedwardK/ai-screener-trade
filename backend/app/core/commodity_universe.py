"""Commodity universe — MCX Gold and Silver.

Yahoo Finance does not list MCX GOLD / SILVER futures. App symbols are
therefore `GOLD.MCX` / `SILVER.MCX` and resolve at runtime to the nearest
monthly GOLDM / SILVERM FUT via the Upstox instrument master. COMEX
`GC=F` / `SI=F` × `INR=X` is only a fallback series when Upstox is
unavailable.
They share Stock/Candle/Snapshot/Signal tables with Nifty names so the
pipeline is reused, but they are excluded from the Nifty screener.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional


@dataclass(frozen=True)
class CommodityMeta:
    symbol: str
    name: str
    venue: str
    currency: str
    unit: str
    mcx_asset: str          # GOLDM | SILVERM — monthly MCX mini futures
    comex_symbol: str       # yfinance fallback underlying
    sector: str = "Commodity"


COMMODITIES: List[CommodityMeta] = [
    CommodityMeta(
        symbol="GOLD.MCX",
        name="Gold MCX",
        venue="MCX",
        currency="INR",
        unit="INR / 10 g",
        mcx_asset="GOLDM",
        comex_symbol="GC=F",
    ),
    CommodityMeta(
        symbol="SILVER.MCX",
        name="Silver MCX",
        venue="MCX",
        currency="INR",
        unit="INR / kg",
        mcx_asset="SILVERM",
        comex_symbol="SI=F",
    ),
]

COMMODITY_BY_SYMBOL: Dict[str, CommodityMeta] = {c.symbol: c for c in COMMODITIES}
_SYMBOLS: FrozenSet[str] = frozenset(COMMODITY_BY_SYMBOL)


def all_commodity_symbols() -> List[str]:
    return [c.symbol for c in COMMODITIES]


def commodity_stock_meta() -> List[dict]:
    """Shape expected by `repository.upsert_stocks`."""
    return [
        {"symbol": c.symbol, "name": c.name, "sector": c.sector}
        for c in COMMODITIES
    ]


def commodity_meta() -> List[Dict]:
    return [
        {
            "symbol": c.symbol,
            "name": c.name,
            "venue": c.venue,
            "currency": c.currency,
            "unit": c.unit,
            "mcx_asset": c.mcx_asset,
            "sector": c.sector,
        }
        for c in COMMODITIES
    ]


def get_commodity(symbol: str) -> Optional[CommodityMeta]:
    if symbol in COMMODITY_BY_SYMBOL:
        return COMMODITY_BY_SYMBOL[symbol]
    u = symbol.strip().upper()
    for c in COMMODITIES:
        if c.mcx_asset == u or c.mcx_asset.rstrip("M") == u.rstrip("M"):
            return c
        if c.name.upper() == u or u in c.name.upper():
            return c
    return None


def is_commodity_symbol(symbol: str) -> bool:
    return symbol in _SYMBOLS
