"""ATM CE/PE strike picker + premium plan derivation.

Two public entry points:

* `pick_atm(...)`  - single ATM plan used by scalp/swing pipeline. Unchanged.
* `recommend_strikes(...)` - returns 3 ranked candidates (OTM / ATM / ITM)
  for the operator to choose by premium budget vs delta.
* `recommend_credit_spread(...)` - a defined-risk credit spread suggestion
  (sell the nearest OI wall, buy one strike further OTM). Carries the
  *real* max-loss and breakeven on the spread, not the single-leg numbers.

All premium plans use a per-moneyness delta heuristic:

  OTM ~ 0.30 delta
  ATM ~ 0.50 delta
  ITM ~ 0.70 delta

This is honest enough for our 5-15 min and 2-3 day horizons. The chain
LTP at exit time is what actually settles the trade; we never claim more
precision than that.

Pure: no DB, no I/O. Returns None when:
  * The index has no option chain (Sensex via this service).
  * No matching strike exists in the chain payload.
  * Premium LTP is missing or zero.

Hard rule: read-only. No order placement, no autonomous trading.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from ..core.universe import IndexMeta, round_to_step
from ..data.option_types import OptionChainPayload, OptionRow

# Approximate deltas by moneyness. Used for the ATM lookup in `pick_atm`
# (kept for backward compatibility) and for the OTM/ATM/ITM ladder in
# `recommend_strikes`.
_ATM_DELTA = 0.5
_OTM_DELTA = 0.30
_ITM_DELTA = 0.70

# Theta decay proxy. We treat option premium as ~ proportional to sqrt(T)
# so theta = -d Premium / d T ≈ Premium / (2 * sqrt(T)). It's tuned for
# the ATM strike; OTM decays slightly faster in % terms (more of its value
# is time premium), ITM slightly slower (mostly intrinsic). Numbers are
# best-effort approximations, not Black-Scholes — see module docstring.
_THETA_FACTOR = {"OTM": 1.2, "ATM": 1.0, "ITM": 0.7}
# Floor to avoid blow-up at expiry: theta on the morning of expiry day is
# huge but bounded, not infinite.
_MIN_DAYS_FOR_THETA = 0.5


def _days_to_expiry(expiry: date, as_of: Optional[date] = None) -> float:
    """Calendar days from `as_of` (default today) to `expiry`, floored at 0."""
    if as_of is None:
        from datetime import date as _date
        as_of = _date.today()
    return max(0.0, (expiry - as_of).days + 0.0)


def _theta_per_day(premium_entry: float, days_to_expiry: float, moneyness: str = "ATM") -> float:
    """Decay-per-day proxy in option premium units.

    Scales with 1/sqrt(dte) so the last day before expiry decays much faster
    than day 5-to-4. Returns a non-negative number (theta is conventionally
    negative, but every call site here SUBTRACTS this, so we keep it positive
    for readability).
    """
    if premium_entry <= 0:
        return 0.0
    dte = max(_MIN_DAYS_FOR_THETA, days_to_expiry)
    factor = _THETA_FACTOR.get(moneyness, 1.0)
    return float(premium_entry / (2.0 * math.sqrt(dte))) * factor


@dataclass(frozen=True)
class OptionPlan:
    strike: float
    type: str                 # CE | PE
    expiry: date
    instrument_key: Optional[str]
    premium_entry: float
    premium_stop: float
    premium_t1: float
    premium_t2: float


def _row_for_strike(chain: OptionChainPayload, strike: float) -> Optional[OptionRow]:
    # The chain is sorted; binary search would be cleaner but for the
    # ~30-50 strike payloads we get back, a linear pass is fine and
    # avoids importing bisect on dataclasses.
    for row in chain.rows:
        if abs(row.strike - strike) < 1e-6:
            return row
    return None


def pick_atm(
    *,
    spot_entry: float,
    spot_stop: float,
    spot_t1: float,
    spot_t2: float,
    direction: str,
    meta: IndexMeta,
    chain: Optional[OptionChainPayload],
    hold_days: float = 0.0,
    as_of: Optional[date] = None,
) -> Optional[OptionPlan]:
    """Build an option plan or return None when no chain is available.

    Args:
        spot_*       : The spot plan from a scalp or swing signal.
        direction    : LONG | SHORT (LONG -> CE, SHORT -> PE).
        meta         : Index metadata (drives strike step, has_option_chain).
        chain        : Latest OptionChainPayload for the index, or None.
        hold_days    : Assumed hold horizon in DAYS. 0 = intraday (no theta
                       adjustment). Use 3 for a typical swing hold. Theta
                       drag is subtracted from each derived target premium.
        as_of        : Reference date for days-to-expiry. None = today.
    """
    if not meta.has_option_chain:
        return None
    if chain is None or not chain.rows:
        return None
    if spot_entry <= 0:
        return None

    leg_type = "CE" if direction == "LONG" else "PE"
    strike = round_to_step(spot_entry, meta.strike_step)
    row = _row_for_strike(chain, strike)
    if row is None:
        return None

    premium_entry = float(row.ce_ltp if leg_type == "CE" else row.pe_ltp or 0.0)
    if premium_entry <= 0:
        return None

    dte = _days_to_expiry(chain.expiry, as_of=as_of)
    theta_drag = _theta_per_day(premium_entry, dte, moneyness="ATM") * max(0.0, hold_days)

    # Apply the 0.5-delta heuristic + theta drag.
    def _derive(spot_target: float) -> float:
        if leg_type == "CE":
            change = (spot_target - spot_entry) * _ATM_DELTA
        else:
            change = (spot_entry - spot_target) * _ATM_DELTA
        return max(0.05, premium_entry + change - theta_drag)

    instrument_key = chain.instrument_keys_by_strike.get(strike, {}).get(leg_type)

    return OptionPlan(
        strike=float(strike),
        type=leg_type,
        expiry=chain.expiry,
        instrument_key=instrument_key,
        premium_entry=round(premium_entry, 2),
        premium_stop=round(_derive(spot_stop), 2),
        premium_t1=round(_derive(spot_t1), 2),
        premium_t2=round(_derive(spot_t2), 2),
    )


# ---------------------------------------------------------------------------
# Strike recommendation ladder (OTM / ATM / ITM)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StrikeCandidate:
    """One ranked strike with full plan + per-moneyness reasoning."""
    moneyness: str            # OTM | ATM | ITM
    strike: float
    type: str                 # CE | PE
    expiry: date
    instrument_key: Optional[str]
    delta_assumed: float
    premium_entry: float
    premium_stop: float
    premium_t1: float
    premium_t2: float
    breakeven_spot: float
    max_loss_per_lot: float   # premium_entry - premium_stop, * 1 (per-share)
    max_profit_per_lot: float # premium_t2 - premium_entry, * 1 (per-share)
    days_to_expiry: float     # calendar days from `as_of` to chain.expiry
    theta_per_day: float      # daily decay proxy at this strike's moneyness
    theta_drag_total: float   # premium subtracted from each target (= theta_per_day * hold_days)
    hold_days: float          # what we assumed when computing theta_drag
    reasons: List[str] = field(default_factory=list)


def _derive_premium(
    *, leg_type: str, premium_entry: float, spot_entry: float,
    spot_target: float, delta: float, theta_drag: float = 0.0,
) -> float:
    """0.05 floor so we never emit a negative or zero target.

    `theta_drag` is in premium units (rupees), already multiplied by
    hold_days. Subtracted from every target so longer holds reach lower
    headline premiums even if spot reaches the same level.
    """
    if leg_type == "CE":
        change = (spot_target - spot_entry) * delta
    else:
        change = (spot_entry - spot_target) * delta
    return max(0.05, premium_entry + change - theta_drag)


def recommend_strikes(
    *,
    spot_entry: float,
    spot_stop: float,
    spot_t1: float,
    spot_t2: float,
    direction: str,
    meta: IndexMeta,
    chain: Optional[OptionChainPayload],
    hold_days: float = 1.0,
    as_of: Optional[date] = None,
) -> List[StrikeCandidate]:
    """Return up to 3 candidates: OTM (cheap), ATM (balanced), ITM (high-delta).

    Same spot plan, three different strike trade-offs. The operator picks
    based on premium budget vs how directional they want the bet to be.

    OTM = 1 step further OTM than ATM. Cheaper premium, lower delta, the
    biggest %-mover if the move materialises.
    ATM = round-to-step on spot. Balanced. Same as `pick_atm`.
    ITM = 1 step in-the-money. Costlier premium, higher delta, behaves
    more like the spot.

    Returns [] when the index has no chain, or the chain lookup fails
    entirely. Partial returns are fine: if ITM has no LTP we drop it
    and still return ATM/OTM.
    """
    if not meta.has_option_chain:
        return []
    if chain is None or not chain.rows:
        return []
    if spot_entry <= 0 or meta.strike_step <= 0:
        return []

    leg_type = "CE" if direction == "LONG" else "PE"
    atm_strike = round_to_step(spot_entry, meta.strike_step)
    step = meta.strike_step

    # For a LONG (CE) trade: OTM = strike ABOVE spot, ITM = strike BELOW spot.
    # For a SHORT (PE) trade: OTM = strike BELOW spot, ITM = strike ABOVE.
    if leg_type == "CE":
        ladder = [
            ("ITM", atm_strike - step, _ITM_DELTA),
            ("ATM", atm_strike,        _ATM_DELTA),
            ("OTM", atm_strike + step, _OTM_DELTA),
        ]
    else:
        ladder = [
            ("ITM", atm_strike + step, _ITM_DELTA),
            ("ATM", atm_strike,        _ATM_DELTA),
            ("OTM", atm_strike - step, _OTM_DELTA),
        ]

    dte = _days_to_expiry(chain.expiry, as_of=as_of)
    hold = max(0.0, hold_days)

    out: List[StrikeCandidate] = []
    for moneyness, strike, delta in ladder:
        row = _row_for_strike(chain, strike)
        if row is None:
            continue
        premium_entry = float((row.ce_ltp if leg_type == "CE" else row.pe_ltp) or 0.0)
        if premium_entry <= 0:
            continue
        theta_per_day = _theta_per_day(premium_entry, dte, moneyness=moneyness)
        theta_drag_total = theta_per_day * hold

        premium_stop = round(_derive_premium(
            leg_type=leg_type, premium_entry=premium_entry,
            spot_entry=spot_entry, spot_target=spot_stop, delta=delta,
            theta_drag=theta_drag_total,
        ), 2)
        premium_t1 = round(_derive_premium(
            leg_type=leg_type, premium_entry=premium_entry,
            spot_entry=spot_entry, spot_target=spot_t1, delta=delta,
            theta_drag=theta_drag_total,
        ), 2)
        premium_t2 = round(_derive_premium(
            leg_type=leg_type, premium_entry=premium_entry,
            spot_entry=spot_entry, spot_target=spot_t2, delta=delta,
            theta_drag=theta_drag_total,
        ), 2)
        # Breakeven for a long option leg: strike +/- premium (intrinsic at expiry).
        # For CE: spot >= strike + premium_entry to break even at expiry.
        # For PE: spot <= strike - premium_entry.
        if leg_type == "CE":
            breakeven_spot = float(strike) + premium_entry
        else:
            breakeven_spot = float(strike) - premium_entry
        instrument_key = chain.instrument_keys_by_strike.get(strike, {}).get(leg_type)
        max_loss = round(max(0.0, premium_entry - premium_stop), 2)
        max_profit = round(max(0.0, premium_t2 - premium_entry), 2)

        reasons = [
            f"{moneyness} {leg_type} {strike:.0f} - delta ~{delta:.2f}",
            f"breakeven at expiry: spot {breakeven_spot:.2f}",
            f"premium {premium_entry:.2f} -> T1 {premium_t1:.2f} / T2 {premium_t2:.2f} (stop {premium_stop:.2f})",
        ]
        if hold > 0 and theta_drag_total > 0.01:
            reasons.append(
                f"theta drag: ~{theta_per_day:.2f}/day x {hold:.1f}d = {theta_drag_total:.2f} "
                f"already subtracted from targets (dte={dte:.1f})"
            )
        out.append(StrikeCandidate(
            moneyness=moneyness,
            strike=float(strike),
            type=leg_type,
            expiry=chain.expiry,
            instrument_key=instrument_key,
            delta_assumed=delta,
            premium_entry=round(premium_entry, 2),
            premium_stop=premium_stop,
            premium_t1=premium_t1,
            premium_t2=premium_t2,
            breakeven_spot=round(breakeven_spot, 2),
            max_loss_per_lot=max_loss,
            max_profit_per_lot=max_profit,
            days_to_expiry=round(dte, 2),
            theta_per_day=round(theta_per_day, 2),
            theta_drag_total=round(theta_drag_total, 2),
            hold_days=round(hold, 2),
            reasons=reasons,
        ))
    return out


# ---------------------------------------------------------------------------
# Defined-risk credit spread
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CreditSpread:
    """Bull-put / bear-call defined-risk spread.

    Sell `short_strike` (collect credit), buy `long_strike` one step further
    OTM (defines max loss). Plan numbers are PER UNIT (multiply by lot size
    for actual rupee exposure).

    Theta math: as a NET-SHORT-PREMIUM position the spread BENEFITS from
    decay. `theta_per_day` is the approximate value (in premium units) by
    which the spread shrinks each calendar day, all else equal. So holding
    one day with spot unchanged is roughly +theta_per_day P&L (you can buy
    it back cheaper). Honest approximation; the real chain LTP at exit is
    what settles you.
    """
    bias: str                 # BULLISH (bull-put) | BEARISH (bear-call)
    short_strike: float
    long_strike: float
    short_type: str           # CE | PE
    expiry: date
    short_instrument_key: Optional[str]
    long_instrument_key: Optional[str]
    short_premium: float      # premium collected (positive)
    long_premium: float       # premium paid (positive)
    net_credit: float         # short_premium - long_premium
    max_profit: float         # = net_credit, ONLY at expiry
    max_loss: float           # = abs(short_strike - long_strike) - net_credit
    breakeven_spot: float
    days_to_expiry: float
    theta_per_day: float      # daily P&L drag on the spread value (good for us)
    projected_value_1d: float # estimated spread value 1 day from now (lower = better)
    projected_value_3d: float
    projected_value_at_expiry: float  # 0.0 on full win, max_loss on full loss
    reasons: List[str] = field(default_factory=list)


def recommend_credit_spread(
    *,
    bias: str,               # BULLISH | BEARISH
    spot: float,
    meta: IndexMeta,
    chain: Optional[OptionChainPayload],
    support_strike: Optional[float] = None,
    resistance_strike: Optional[float] = None,
    as_of: Optional[date] = None,
) -> Optional[CreditSpread]:
    """Build a 1-strike-wide credit spread aligned with the directional bias.

    * BULLISH -> bull-put spread: sell PE at support (or first strike below
      spot if support not supplied), buy PE one step further OTM.
    * BEARISH -> bear-call spread: sell CE at resistance (or first strike
      above spot), buy CE one step further OTM.

    The natural anchor is an OI wall (use `option_chain_signals.compute_oi_walls`
    upstream and pass `support_strike` / `resistance_strike` in). We fall back
    to the nearest non-ATM strike if no wall is provided.

    Returns None when:
      * No option chain (Sensex).
      * Chain lacks LTP for either leg.
      * Net credit is non-positive (the "spread" would actually cost more
        than it pays, which usually means the chain quotes are stale).
    """
    if not meta.has_option_chain or chain is None or not chain.rows:
        return None
    if spot <= 0 or meta.strike_step <= 0:
        return None

    step = meta.strike_step
    if bias == "BULLISH":
        anchor = support_strike if support_strike is not None else round_to_step(spot - step, step)
        short_strike = anchor
        long_strike = anchor - step
        short_type = "PE"
    elif bias == "BEARISH":
        anchor = resistance_strike if resistance_strike is not None else round_to_step(spot + step, step)
        short_strike = anchor
        long_strike = anchor + step
        short_type = "CE"
    else:
        return None

    short_row = _row_for_strike(chain, short_strike)
    long_row = _row_for_strike(chain, long_strike)
    if short_row is None or long_row is None:
        return None

    if short_type == "PE":
        short_premium = float(short_row.pe_ltp or 0.0)
        long_premium = float(long_row.pe_ltp or 0.0)
    else:
        short_premium = float(short_row.ce_ltp or 0.0)
        long_premium = float(long_row.ce_ltp or 0.0)
    if short_premium <= 0 or long_premium <= 0:
        return None

    net_credit = round(short_premium - long_premium, 2)
    width = abs(short_strike - long_strike)
    max_loss = round(max(0.0, width - net_credit), 2)
    if net_credit <= 0 or max_loss <= 0:
        return None

    if short_type == "PE":
        breakeven = float(short_strike) - net_credit  # bull-put: spot must stay above this
    else:
        breakeven = float(short_strike) + net_credit  # bear-call: spot must stay below this

    short_instrument_key = chain.instrument_keys_by_strike.get(short_strike, {}).get(short_type)
    long_instrument_key = chain.instrument_keys_by_strike.get(long_strike, {}).get(short_type)

    # Spread-level theta. Both legs lose value per day; the SHORT leg
    # loses more (higher premium), so the net spread value drops by:
    #   theta_short - theta_long  ~  (short_premium - long_premium) / (2 * sqrt(dte))
    # That's the daily P&L tailwind for the spread seller.
    dte = _days_to_expiry(chain.expiry, as_of=as_of)
    dte_floor = max(_MIN_DAYS_FOR_THETA, dte)
    theta_spread_per_day = round(net_credit / (2.0 * math.sqrt(dte_floor)), 2)

    # Projected spread *buy-back* value at +1d, +3d (spot unchanged
    # assumption). At entry the spread "cost to close" is the net credit;
    # it shrinks toward zero as theta accrues to the seller's benefit.
    projected_1d = round(max(0.0, net_credit - theta_spread_per_day * 1.0), 2)
    projected_3d = round(max(0.0, net_credit - theta_spread_per_day * 3.0), 2)
    # At expiry with spot above (bull-put) / below (bear-call) the short
    # strike, the spread expires worthless and you keep the full credit
    # (value to close = 0). On a full loss it would close at the spread
    # width; we report the WIN-side number here because the operator
    # already sees max_loss separately.
    projected_expiry = 0.0

    reasons = [
        f"{bias} bias -> {'bull-put' if bias == 'BULLISH' else 'bear-call'} {short_strike:.0f}/{long_strike:.0f}",
        f"collect {net_credit:.2f} per unit, risk {max_loss:.2f} per unit",
        f"break-even spot: {breakeven:.2f}",
        f"dte {dte:.1f} | theta ~{theta_spread_per_day:.2f}/day in your favour (spread shrinks)",
        f"buy-back cost projection (spot flat): now {net_credit:.2f} -> +1d {projected_1d:.2f} -> +3d {projected_3d:.2f} -> expiry 0.00",
        f"max loss is CAPPED by the long leg at {long_strike:.0f} - do not run this without both legs",
    ]
    return CreditSpread(
        bias=bias,
        short_strike=float(short_strike),
        long_strike=float(long_strike),
        short_type=short_type,
        expiry=chain.expiry,
        short_instrument_key=short_instrument_key,
        long_instrument_key=long_instrument_key,
        short_premium=round(short_premium, 2),
        long_premium=round(long_premium, 2),
        net_credit=net_credit,
        max_profit=net_credit,
        max_loss=max_loss,
        breakeven_spot=round(breakeven, 2),
        days_to_expiry=round(dte, 2),
        theta_per_day=theta_spread_per_day,
        projected_value_1d=projected_1d,
        projected_value_3d=projected_3d,
        projected_value_at_expiry=projected_expiry,
        reasons=reasons,
    )


__all__ = [
    "OptionPlan",
    "StrikeCandidate",
    "CreditSpread",
    "pick_atm",
    "recommend_strikes",
    "recommend_credit_spread",
]
