"""ATR-based entry / stop / target / invalidation calculator."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class TradePlan:
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    invalidation: float
    risk_pct: float
    rr_1: float
    rr_2: float


def long_plan(close: float, atr: float, stop_mult: float = 1.5, rr1: float = 1.5, rr2: float = 3.0) -> TradePlan:
    """Long trade plan around the latest close with ATR-based stop and 2 targets."""
    stop = close - stop_mult * atr
    risk = close - stop
    t1 = close + rr1 * risk
    t2 = close + rr2 * risk
    return TradePlan(
        entry=round(close, 2),
        stop_loss=round(stop, 2),
        target_1=round(t1, 2),
        target_2=round(t2, 2),
        invalidation=round(stop, 2),
        risk_pct=round((risk / close) * 100.0, 2) if close else 0.0,
        rr_1=rr1,
        rr_2=rr2,
    )


def short_plan(close: float, atr: float, stop_mult: float = 1.5, rr1: float = 1.5, rr2: float = 3.0) -> TradePlan:
    stop = close + stop_mult * atr
    risk = stop - close
    t1 = close - rr1 * risk
    t2 = close - rr2 * risk
    return TradePlan(
        entry=round(close, 2),
        stop_loss=round(stop, 2),
        target_1=round(t1, 2),
        target_2=round(t2, 2),
        invalidation=round(stop, 2),
        risk_pct=round((risk / close) * 100.0, 2) if close else 0.0,
        rr_1=rr1,
        rr_2=rr2,
    )


def position_size(account_size: float, risk_per_trade_pct: float, entry: float, stop: float) -> Optional[int]:
    """Return a suggested integer share quantity given account and stop distance."""
    if entry <= 0 or stop <= 0 or account_size <= 0:
        return None
    risk_per_share = abs(entry - stop)
    if risk_per_share == 0:
        return None
    risk_amount = account_size * (risk_per_trade_pct / 100.0)
    qty = int(risk_amount // risk_per_share)
    return max(qty, 0)
