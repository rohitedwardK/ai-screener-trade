"""Paper-index position sizing — option lot-aware, premium-stop-aware.

Risk per trade is defined on the OPTION PREMIUM stop (a fraction of the
entry premium): if a stop loss equates to losing X rupees per option share,
risk-per-trade-rupees / X / lot_size = number of lots.

Defaults assume buying ATM CE/PE so the option-premium stop is set as a
fraction of entry premium (default 50% of premium = stop). The simulator
later converts spot moves into premium moves using a delta estimate.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Optional

from ..models.index_schemas import IndexScreenerSignal
from .config import PaperIndexConfigSnapshot


# How much of the option premium we are willing to lose before stopping out.
# 50% of entry premium ~ a typical retail directional option trade with
# managed risk; configurable via the ConfigSnapshot if needed in future.
DEFAULT_PREMIUM_STOP_FRACTION = 0.50

# Reject lots that would consume more than this fraction of capital as premium.
MAX_PREMIUM_VALUE_FRACTION = 0.50

# Reject if implied option-premium stop distance > this fraction of premium.
MAX_PREMIUM_STOP_FRACTION = 0.80


@dataclass
class IndexSizingResult:
    lots: int
    quantity: int                 # lots * lot_size
    risk_amount: float
    risk_per_unit: float          # premium-level risk per option share (entry - stop_premium)
    premium_value: float          # lots * lot_size * entry_premium
    entry_premium: float
    stop_premium: float
    target_1_premium: float
    target_2_premium: float
    delta_estimate: float
    adjustments: dict
    rejected: bool = False
    reject_reason: Optional[str] = None


def estimate_entry_premium(
    spot: float,
    strike: float,
    *,
    option_type: str,
    atr_percent: Optional[float],
    delta_estimate: float,
) -> float:
    """Crude premium estimate when option chain LTP is unknown.

    Uses intrinsic value plus a time-value approximation derived from ATR%.
    This is a deliberately simplified model documented as such — Black-Scholes
    requires IV which we don't always have. Good enough for paper simulation.
    """
    intrinsic = max(spot - strike, 0.0) if option_type.upper() == "CE" else max(strike - spot, 0.0)
    # Time value ~ ATR% of spot * delta (broad approximation).
    atr_pct = max(0.5, min(3.0, atr_percent or 1.5))
    time_value = spot * (atr_pct / 100.0) * max(0.3, delta_estimate)
    return round(intrinsic + time_value, 2)


def derive_premium_levels(
    sig: IndexScreenerSignal,
    *,
    entry_premium: float,
    delta_estimate: float,
    premium_stop_fraction: float = DEFAULT_PREMIUM_STOP_FRACTION,
) -> tuple[float, float, float]:
    """Convert spot stop / targets into option premium levels.

    Stop is the *worse* of (premium_stop_fraction × entry_premium) and the
    delta-implied premium when spot reaches `spot_stop_loss`. We never let
    the premium stop fall below 5% of entry premium (effectively a sanity
    floor for very low-priced options).

    For LONG (CE buy): spot ↑ → premium ↑.
    For SHORT (PE buy): spot ↓ → premium ↑.
    """
    if entry_premium <= 0:
        return 0.0, 0.0, 0.0

    floor_stop = entry_premium * 0.05
    cap_stop = entry_premium * (1.0 - premium_stop_fraction)
    cap_stop = max(floor_stop, cap_stop)

    if sig.spot_entry is None or sig.spot_stop_loss is None:
        stop_prem = cap_stop
    else:
        sign = 1 if sig.direction == "LONG" else -1
        spot_move_to_stop = sign * (sig.spot_stop_loss - sig.spot_entry)
        prem_move_at_stop = delta_estimate * spot_move_to_stop
        # delta-implied stop loses prem_move_at_stop in premium (negative move).
        delta_stop = max(floor_stop, entry_premium + prem_move_at_stop)
        # Keep the worse of the two so we don't underestimate downside.
        stop_prem = min(delta_stop, cap_stop)

    sign = 1 if sig.direction == "LONG" else -1
    if sig.spot_target_1 is not None and sig.spot_entry is not None:
        prem_move_at_t1 = delta_estimate * sign * (sig.spot_target_1 - sig.spot_entry)
        t1_prem = max(entry_premium, entry_premium + prem_move_at_t1)
    else:
        # Default: 1.5x premium-risk reward
        t1_prem = entry_premium + 1.5 * (entry_premium - stop_prem)

    if sig.spot_target_2 is not None and sig.spot_entry is not None:
        prem_move_at_t2 = delta_estimate * sign * (sig.spot_target_2 - sig.spot_entry)
        t2_prem = max(t1_prem, entry_premium + prem_move_at_t2)
    else:
        t2_prem = entry_premium + 3.0 * (entry_premium - stop_prem)

    return round(stop_prem, 2), round(t1_prem, 2), round(t2_prem, 2)


def size(
    sig: IndexScreenerSignal,
    cfg: PaperIndexConfigSnapshot,
    *,
    lot_size: int,
    strike: float,
    entry_premium: Optional[float] = None,
    delta_estimate: Optional[float] = None,
) -> IndexSizingResult:
    """Compute lot-aware sizing; returns either a sizing or a rejection."""
    capital = max(0.0, cfg.virtual_capital)
    delta = delta_estimate if delta_estimate is not None else cfg.option_delta_estimate
    delta = max(0.1, min(0.95, float(delta)))

    if entry_premium is None or entry_premium <= 0:
        entry_premium = estimate_entry_premium(
            sig.spot, strike,
            option_type=sig.option_type,
            atr_percent=sig.atr_percent,
            delta_estimate=delta,
        )

    if entry_premium <= 0:
        return IndexSizingResult(
            lots=0, quantity=0, risk_amount=0.0, risk_per_unit=0.0,
            premium_value=0.0, entry_premium=0.0, stop_premium=0.0,
            target_1_premium=0.0, target_2_premium=0.0, delta_estimate=delta,
            adjustments={}, rejected=True,
            reject_reason="entry premium estimate is zero or negative",
        )

    stop_prem, t1_prem, t2_prem = derive_premium_levels(
        sig, entry_premium=entry_premium, delta_estimate=delta,
    )

    risk_per_unit = entry_premium - stop_prem
    if risk_per_unit <= 0:
        return IndexSizingResult(
            lots=0, quantity=0, risk_amount=0.0, risk_per_unit=0.0,
            premium_value=0.0, entry_premium=entry_premium, stop_premium=stop_prem,
            target_1_premium=t1_prem, target_2_premium=t2_prem, delta_estimate=delta,
            adjustments={}, rejected=True,
            reject_reason="non-positive premium risk-per-share",
        )

    risk_pct_of_premium = risk_per_unit / entry_premium
    if risk_pct_of_premium > MAX_PREMIUM_STOP_FRACTION:
        return IndexSizingResult(
            lots=0, quantity=0, risk_amount=0.0,
            risk_per_unit=risk_per_unit, premium_value=0.0,
            entry_premium=entry_premium, stop_premium=stop_prem,
            target_1_premium=t1_prem, target_2_premium=t2_prem, delta_estimate=delta,
            adjustments={"premium_stop_pct": round(risk_pct_of_premium * 100.0, 2)},
            rejected=True,
            reject_reason=(
                f"premium stop too wide: {risk_pct_of_premium*100:.1f}% > "
                f"{MAX_PREMIUM_STOP_FRACTION*100:.0f}%"
            ),
        )

    risk_amount = capital * (cfg.max_risk_per_trade_percent / 100.0)
    if risk_amount <= 0:
        return IndexSizingResult(
            lots=0, quantity=0, risk_amount=0.0, risk_per_unit=risk_per_unit,
            premium_value=0.0, entry_premium=entry_premium, stop_premium=stop_prem,
            target_1_premium=t1_prem, target_2_premium=t2_prem, delta_estimate=delta,
            adjustments={}, rejected=True, reject_reason="non-positive risk budget",
        )

    base_qty = floor(risk_amount / risk_per_unit)
    base_lots = max(0, base_qty // max(1, lot_size))
    if base_lots <= 0:
        return IndexSizingResult(
            lots=0, quantity=0, risk_amount=risk_amount, risk_per_unit=risk_per_unit,
            premium_value=0.0, entry_premium=entry_premium, stop_premium=stop_prem,
            target_1_premium=t1_prem, target_2_premium=t2_prem, delta_estimate=delta,
            adjustments={"base_qty": base_qty, "lot_size": lot_size},
            rejected=True,
            reject_reason="risk budget too small for one lot at this premium-stop distance",
        )

    adjustments: dict = {"base_qty": base_qty, "base_lots": base_lots, "lot_size": lot_size}

    # Confidence / risk_level reductions (lots, not shares).
    factor = 1.0
    if sig.confidence == "Medium":
        factor *= 0.75
        adjustments["confidence_Medium"] = -0.25
    if sig.risk_level == "Medium":
        factor *= 0.80
        adjustments["risk_level_Medium"] = -0.20
    if sig.atr_percent is not None and sig.atr_percent >= 2.5:
        factor *= 0.80
        adjustments[f"high_atr_{sig.atr_percent:.1f}%"] = -0.20

    lots = max(0, floor(base_lots * factor))
    if lots <= 0:
        return IndexSizingResult(
            lots=0, quantity=0, risk_amount=risk_amount, risk_per_unit=risk_per_unit,
            premium_value=0.0, entry_premium=entry_premium, stop_premium=stop_prem,
            target_1_premium=t1_prem, target_2_premium=t2_prem, delta_estimate=delta,
            adjustments=adjustments, rejected=True,
            reject_reason="lots rounded to zero after adjustments",
        )

    quantity = lots * lot_size
    premium_value = quantity * entry_premium
    if capital > 0 and premium_value > MAX_PREMIUM_VALUE_FRACTION * capital:
        return IndexSizingResult(
            lots=lots, quantity=quantity, risk_amount=risk_amount,
            risk_per_unit=risk_per_unit, premium_value=premium_value,
            entry_premium=entry_premium, stop_premium=stop_prem,
            target_1_premium=t1_prem, target_2_premium=t2_prem, delta_estimate=delta,
            adjustments=adjustments, rejected=True,
            reject_reason=(
                f"premium value {premium_value:,.0f} > "
                f"{MAX_PREMIUM_VALUE_FRACTION*100:.0f}% of capital"
            ),
        )

    realized_risk = quantity * risk_per_unit
    if realized_risk > risk_amount * 1.01:
        return IndexSizingResult(
            lots=lots, quantity=quantity, risk_amount=risk_amount,
            risk_per_unit=risk_per_unit, premium_value=premium_value,
            entry_premium=entry_premium, stop_premium=stop_prem,
            target_1_premium=t1_prem, target_2_premium=t2_prem, delta_estimate=delta,
            adjustments=adjustments, rejected=True,
            reject_reason="realised premium risk exceeds configured per-trade limit",
        )

    return IndexSizingResult(
        lots=lots,
        quantity=quantity,
        risk_amount=risk_amount,
        risk_per_unit=risk_per_unit,
        premium_value=premium_value,
        entry_premium=entry_premium,
        stop_premium=stop_prem,
        target_1_premium=t1_prem,
        target_2_premium=t2_prem,
        delta_estimate=delta,
        adjustments=adjustments,
    )
