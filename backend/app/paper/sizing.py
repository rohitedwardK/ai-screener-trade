"""PaperPositionSizingService.

Implements the spec sizing formula plus four reduction adjustments and
rejection conditions. Pure / deterministic so it is trivial to unit test.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Optional

from ..models.paper_schemas import ScreenerSignal
from .config import PaperConfigSnapshot


# Adjustment magnitudes (spec).
CONFIDENCE_REDUCTION = {"Low": 0.50, "Medium": 0.25, "High": 0.0}
RISK_LEVEL_REDUCTION = {"Low": 0.0, "Medium": 0.20, "High": 0.50}
OVERSOLD_REDUCTION = 0.50
HIGH_ATR_THRESHOLD_PCT = 4.5
HIGH_ATR_REDUCTION = 0.25

MAX_POSITION_VALUE_FRACTION = 0.25  # reject if a single trade > 25% of capital
MAX_STOP_DISTANCE_PCT = 8.0          # reject if stop distance > 8% of entry


@dataclass
class SizingResult:
    quantity: int
    risk_amount: float
    risk_per_share: float
    position_value: float
    adjustments: dict
    rejected: bool = False
    reject_reason: Optional[str] = None


def _safe_pos(x: Optional[float]) -> float:
    return float(x) if (x is not None and x > 0) else 0.0


def size(
    sig: ScreenerSignal,
    cfg: PaperConfigSnapshot,
) -> SizingResult:
    """Return a SizingResult for the candidate or a rejection."""
    entry = _safe_pos(sig.entry)
    stop = _safe_pos(sig.stop_loss)
    capital = max(0.0, cfg.virtual_capital)

    if entry <= 0 or stop <= 0 or stop >= entry:
        return SizingResult(
            quantity=0, risk_amount=0.0, risk_per_share=0.0, position_value=0.0,
            adjustments={}, rejected=True,
            reject_reason="invalid entry/stop (entry must be > stop > 0)",
        )

    risk_per_share = entry - stop
    risk_pct_of_entry = (risk_per_share / entry) * 100.0
    if risk_pct_of_entry > MAX_STOP_DISTANCE_PCT:
        return SizingResult(
            quantity=0, risk_amount=0.0,
            risk_per_share=risk_per_share, position_value=0.0,
            adjustments={"stop_pct": round(risk_pct_of_entry, 2)},
            rejected=True,
            reject_reason=f"stop too wide: {risk_pct_of_entry:.1f}% > {MAX_STOP_DISTANCE_PCT}%",
        )

    risk_amount = capital * (cfg.max_risk_per_trade_percent / 100.0)
    if risk_amount <= 0:
        return SizingResult(
            quantity=0, risk_amount=0.0, risk_per_share=risk_per_share, position_value=0.0,
            adjustments={}, rejected=True, reject_reason="non-positive risk budget",
        )

    base_qty = floor(risk_amount / risk_per_share)
    if base_qty <= 0:
        return SizingResult(
            quantity=0, risk_amount=risk_amount, risk_per_share=risk_per_share,
            position_value=0.0, adjustments={"base_qty": base_qty},
            rejected=True,
            reject_reason="risk budget too small for one share at this stop distance",
        )

    # --- adjustments ---
    adjustments: dict = {"base_qty": base_qty}

    factor = 1.0
    conf_red = CONFIDENCE_REDUCTION.get(sig.confidence, 0.0)
    if conf_red:
        factor *= (1.0 - conf_red)
        adjustments[f"confidence_{sig.confidence}"] = -conf_red

    risk_red = RISK_LEVEL_REDUCTION.get(sig.risk_level, 0.0)
    if risk_red:
        factor *= (1.0 - risk_red)
        adjustments[f"risk_level_{sig.risk_level}"] = -risk_red

    if sig.setup_type == "Oversold Recovery":
        factor *= (1.0 - OVERSOLD_REDUCTION)
        adjustments["oversold_recovery"] = -OVERSOLD_REDUCTION

    if sig.atr_percent is not None and sig.atr_percent >= HIGH_ATR_THRESHOLD_PCT:
        factor *= (1.0 - HIGH_ATR_REDUCTION)
        adjustments[f"high_atr_{sig.atr_percent:.1f}%"] = -HIGH_ATR_REDUCTION

    qty = max(0, floor(base_qty * factor))
    if qty <= 0:
        return SizingResult(
            quantity=0, risk_amount=risk_amount, risk_per_share=risk_per_share,
            position_value=0.0, adjustments=adjustments,
            rejected=True,
            reject_reason="quantity rounded to zero after adjustments",
        )

    position_value = qty * entry
    if capital > 0 and position_value > MAX_POSITION_VALUE_FRACTION * capital:
        return SizingResult(
            quantity=qty, risk_amount=risk_amount, risk_per_share=risk_per_share,
            position_value=position_value, adjustments=adjustments,
            rejected=True,
            reject_reason=(
                f"position value {position_value:,.0f} > "
                f"{MAX_POSITION_VALUE_FRACTION*100:.0f}% of capital"
            ),
        )

    realized_risk = qty * risk_per_share
    if realized_risk > risk_amount * 1.01:  # tiny float slack
        return SizingResult(
            quantity=qty, risk_amount=risk_amount, risk_per_share=risk_per_share,
            position_value=position_value, adjustments=adjustments,
            rejected=True,
            reject_reason="realised risk exceeds configured per-trade limit",
        )

    return SizingResult(
        quantity=qty,
        risk_amount=risk_amount,
        risk_per_share=risk_per_share,
        position_value=position_value,
        adjustments=adjustments,
    )
