"""Best-strike picker for index option trades.

Pure module — no I/O, no DB. Given a spot-level trade plan (entry, SL, T1, T2)
and an option-chain slice, produces up to two contract recommendations:

  1. SINGLE_LEG  — buy ATM CE (LONG) or ATM PE (SHORT). Falls back to ITM-1
                   when the ATM strike is illiquid (wide bid/ask spread).
  2. DEBIT_SPREAD — Bull Call Spread (LONG: buy ATM CE, sell OTM-2 CE) or
                    Bear Put Spread (SHORT: buy ATM PE, sell OTM-2 PE).
                    Strike width = 2 × strike_step.

Both expose stop-loss and target levels in **option premium points** (the
representation a retail option buyer can place a limit order on). Premium
SL/T are derived from the spot SL/T via a delta projection — approximate but
good enough for a "where do I exit" guideline.

Liquidity guard: if either leg has a non-positive bid/ask, OI below the
configured floor, or a bid/ask spread above the configured percentage of the
mid, the recommendation is returned with `rejection_reason` populated and
zeroed prices instead of being silently dropped. This lets the UI show the
operator *why* a setup didn't generate a tradable contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .option_chain_metrics import OCRow


# ---------------------------------------------------------------------------
# Constants — tuned for retail liquidity on weekly NIFTY/BANKNIFTY/SENSEX
# ---------------------------------------------------------------------------

# Min open interest below which we treat a strike as untradable for a retail
# operator. Weekly index ATM contracts routinely show >50k OI, so 1k is a
# generous floor that only filters truly dead far-OTM strikes.
DEFAULT_MIN_OI = 1000

# Max bid/ask spread expressed as a fraction of the mid price. 8 % covers the
# normal end-of-day NSE display width; anything wider points at a stale quote
# or a near-zero premium where the spread is mechanical, not informational.
DEFAULT_MAX_SPREAD_PCT = 0.08

# Approximate Black-Scholes deltas at the moneyness levels we choose. These
# are intentionally constants (not Greeks computed from IV) — the picker is a
# heuristic and the chain itself doesn't always carry IV. Premium SL/T using
# these deltas is accurate to within ~10 % which is fine for a "where do I
# get out" guideline; tightening this would require a full pricer that
# violates the "no new dependency" constraint.
DELTA_ATM = 0.50
DELTA_ITM1 = 0.65
DELTA_OTM1 = 0.35
DELTA_OTM2 = 0.25  # short leg of the debit spread


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrikeLeg:
    """One leg of a recommendation. Premium uses bid/ask mid when available."""
    option_type: str          # CE | PE
    strike: float
    side: str                 # BUY | SELL
    delta_estimate: float
    premium: float
    iv: Optional[float] = None
    oi: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass(frozen=True)
class ContractRecommendation:
    """A buy-side recommendation with premium-based SL / T1 / T2."""
    strategy: str             # SINGLE_LEG | DEBIT_SPREAD
    direction: str            # LONG | SHORT
    legs: List[StrikeLeg]
    net_debit: float          # what the trade costs at entry (premium points)
    max_profit: Optional[float]  # capped for spreads, None for single-leg
    max_loss: float           # = net_debit for both
    sl_premium: float
    t1_premium: float
    t2_premium: float
    breakeven: Optional[float]   # spot at which trade breaks even at expiry
    notes: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_at_strike(rows: Sequence[OCRow], strike: float) -> Optional[OCRow]:
    for r in rows:
        if abs(r.strike - strike) < 1e-6:
            return r
    return None


def _mid_or_ltp(bid: Optional[float], ask: Optional[float], ltp: Optional[float]) -> float:
    """Best estimate of executable premium.

    Prefer the bid/ask midpoint when both sides are quoted (this is what an
    operator would actually receive on a marketable order). Fall back to LTP
    when the chain only has the last trade — typical for the yfinance and
    NSE fallbacks which omit bid/ask.
    """
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return round((float(bid) + float(ask)) / 2.0, 2)
    if ltp is not None and ltp > 0:
        return round(float(ltp), 2)
    return 0.0


def _spread_pct(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (float(bid) + float(ask)) / 2.0
    if mid <= 0:
        return None
    return (float(ask) - float(bid)) / mid


def _atm_strike(rows: Sequence[OCRow], spot: float) -> Optional[float]:
    if not rows:
        return None
    return min(rows, key=lambda r: abs(r.strike - spot)).strike


def _check_liquidity(
    leg_row: Optional[OCRow], side_label: str, *,
    option_type: str,
    min_oi: int, max_spread_pct: float,
) -> Optional[str]:
    """Return a rejection reason string, or None if the leg is tradable."""
    if leg_row is None:
        return f"{side_label} {option_type}: strike not in chain"
    bid = leg_row.ce_bid if option_type == "CE" else leg_row.pe_bid
    ask = leg_row.ce_ask if option_type == "CE" else leg_row.pe_ask
    oi = leg_row.ce_oi if option_type == "CE" else leg_row.pe_oi
    ltp = leg_row.ce_ltp if option_type == "CE" else leg_row.pe_ltp

    # When bid/ask are missing entirely, fall back to LTP availability so the
    # NSE/yfinance fallbacks (which omit quotes) still produce a recommendation.
    has_quotes = bid is not None and ask is not None and bid > 0 and ask > 0
    if not has_quotes and (ltp is None or ltp <= 0):
        return f"{side_label} {option_type} {leg_row.strike:.0f}: no premium data"
    if oi is not None and oi < min_oi:
        return (
            f"{side_label} {option_type} {leg_row.strike:.0f}: OI {oi:.0f} < "
            f"{min_oi} liquidity floor"
        )
    if has_quotes:
        spread = _spread_pct(bid, ask)
        if spread is not None and spread > max_spread_pct:
            return (
                f"{side_label} {option_type} {leg_row.strike:.0f}: bid/ask spread "
                f"{spread * 100:.1f}% > {max_spread_pct * 100:.0f}% liquidity cap"
            )
    return None


def _build_leg(
    row: OCRow, *, option_type: str, side: str, delta: float,
) -> StrikeLeg:
    bid = row.ce_bid if option_type == "CE" else row.pe_bid
    ask = row.ce_ask if option_type == "CE" else row.pe_ask
    ltp = row.ce_ltp if option_type == "CE" else row.pe_ltp
    iv = row.ce_iv if option_type == "CE" else row.pe_iv
    oi = row.ce_oi if option_type == "CE" else row.pe_oi
    return StrikeLeg(
        option_type=option_type,
        strike=row.strike,
        side=side,
        delta_estimate=delta,
        premium=_mid_or_ltp(bid, ask, ltp),
        iv=iv,
        oi=oi,
        bid=bid,
        ask=ask,
    )


def _project_premium_levels(
    *, entry_premium: float, delta: float, spot: float,
    spot_sl: float, spot_t1: float, spot_t2: float, direction: str,
) -> Tuple[float, float, float]:
    """Convert spot SL/T1/T2 to premium SL/T1/T2 via delta projection.

    For a long CE: ΔP_premium ≈ delta × ΔP_spot.
    For a long PE: same magnitude, opposite sign w.r.t. spot move.
    """
    sign = 1.0 if direction == "LONG" else -1.0
    sl_move = (spot_sl - spot) * sign  # negative for both LONG (down) and SHORT (up)
    t1_move = (spot_t1 - spot) * sign  # positive
    t2_move = (spot_t2 - spot) * sign

    sl_prem = entry_premium + delta * sl_move
    t1_prem = entry_premium + delta * t1_move
    t2_prem = entry_premium + delta * t2_move

    # Floor the SL at 50 % of debit so a too-aggressive spot stop doesn't
    # imply an unrecoverable -100 % premium hit; floor at zero absolutely.
    sl_prem = max(sl_prem, 0.5 * entry_premium, 0.0)
    t1_prem = max(t1_prem, 0.0)
    t2_prem = max(t2_prem, 0.0)
    return round(sl_prem, 2), round(t1_prem, 2), round(t2_prem, 2)


# ---------------------------------------------------------------------------
# Single-leg recommendation
# ---------------------------------------------------------------------------

def _single_leg_recommendation(
    *, direction: str, spot: float,
    spot_sl: float, spot_t1: float, spot_t2: float,
    rows: Sequence[OCRow], strike_step: float,
    min_oi: int, max_spread_pct: float,
) -> ContractRecommendation:
    option_type = "CE" if direction == "LONG" else "PE"
    atm = _atm_strike(rows, spot)
    if atm is None:
        return ContractRecommendation(
            strategy="SINGLE_LEG", direction=direction, legs=[],
            net_debit=0.0, max_profit=None, max_loss=0.0,
            sl_premium=0.0, t1_premium=0.0, t2_premium=0.0, breakeven=None,
            notes=[], rejection_reason="empty option chain",
        )

    # Try ATM first, fall back to ITM-1 if illiquid. ITM is one strike towards
    # the money: closer to spot for CE means a *lower* strike, for PE a *higher*.
    atm_row = _row_at_strike(rows, atm)
    itm_strike = atm - strike_step if option_type == "CE" else atm + strike_step
    itm_row = _row_at_strike(rows, itm_strike)

    chosen_row: Optional[OCRow] = None
    chosen_delta = DELTA_ATM
    chosen_label = "ATM"
    notes: List[str] = []

    atm_reject = _check_liquidity(
        atm_row, "BUY", option_type=option_type,
        min_oi=min_oi, max_spread_pct=max_spread_pct,
    )
    if atm_reject is None:
        chosen_row = atm_row
    else:
        notes.append(f"ATM rejected: {atm_reject}")
        itm_reject = _check_liquidity(
            itm_row, "BUY", option_type=option_type,
            min_oi=min_oi, max_spread_pct=max_spread_pct,
        )
        if itm_reject is None:
            chosen_row = itm_row
            chosen_delta = DELTA_ITM1
            chosen_label = "ITM-1"
        else:
            return ContractRecommendation(
                strategy="SINGLE_LEG", direction=direction, legs=[],
                net_debit=0.0, max_profit=None, max_loss=0.0,
                sl_premium=0.0, t1_premium=0.0, t2_premium=0.0, breakeven=None,
                notes=notes, rejection_reason=f"ATM and ITM-1 illiquid: {itm_reject}",
            )

    assert chosen_row is not None  # narrowed by the branch above
    leg = _build_leg(chosen_row, option_type=option_type, side="BUY", delta=chosen_delta)
    if leg.premium <= 0:
        return ContractRecommendation(
            strategy="SINGLE_LEG", direction=direction, legs=[leg],
            net_debit=0.0, max_profit=None, max_loss=0.0,
            sl_premium=0.0, t1_premium=0.0, t2_premium=0.0, breakeven=None,
            notes=notes, rejection_reason=f"{chosen_label} {option_type} premium unavailable",
        )

    sl_prem, t1_prem, t2_prem = _project_premium_levels(
        entry_premium=leg.premium, delta=chosen_delta, spot=spot,
        spot_sl=spot_sl, spot_t1=spot_t1, spot_t2=spot_t2, direction=direction,
    )
    breakeven = (
        leg.strike + leg.premium if option_type == "CE"
        else leg.strike - leg.premium
    )
    notes.append(
        f"{chosen_label} {option_type} {leg.strike:.0f} @ {leg.premium:.2f} "
        f"(δ≈{chosen_delta:.2f})"
    )
    return ContractRecommendation(
        strategy="SINGLE_LEG", direction=direction, legs=[leg],
        net_debit=leg.premium,
        max_profit=None,                # uncapped for a long single leg
        max_loss=leg.premium,           # max loss = debit paid
        sl_premium=sl_prem,
        t1_premium=t1_prem,
        t2_premium=t2_prem,
        breakeven=round(breakeven, 2),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Debit spread recommendation
# ---------------------------------------------------------------------------

def _debit_spread_recommendation(
    *, direction: str, spot: float,
    rows: Sequence[OCRow], strike_step: float,
    min_oi: int, max_spread_pct: float,
) -> ContractRecommendation:
    """Build a Bull Call (LONG) or Bear Put (SHORT) debit spread.

    Width fixed at 2 × strike_step:
      - Bull Call : BUY ATM CE, SELL OTM-2 CE  (long_strike < short_strike)
      - Bear Put  : BUY ATM PE, SELL OTM-2 PE  (long_strike > short_strike)
    """
    option_type = "CE" if direction == "LONG" else "PE"
    atm = _atm_strike(rows, spot)
    if atm is None:
        return ContractRecommendation(
            strategy="DEBIT_SPREAD", direction=direction, legs=[],
            net_debit=0.0, max_profit=None, max_loss=0.0,
            sl_premium=0.0, t1_premium=0.0, t2_premium=0.0, breakeven=None,
            notes=[], rejection_reason="empty option chain",
        )

    long_strike = atm
    short_offset = 2.0 * strike_step
    short_strike = (
        long_strike + short_offset if option_type == "CE"
        else long_strike - short_offset
    )
    long_row = _row_at_strike(rows, long_strike)
    short_row = _row_at_strike(rows, short_strike)

    long_reject = _check_liquidity(
        long_row, "BUY", option_type=option_type,
        min_oi=min_oi, max_spread_pct=max_spread_pct,
    )
    short_reject = _check_liquidity(
        short_row, "SELL", option_type=option_type,
        min_oi=min_oi, max_spread_pct=max_spread_pct,
    )
    if long_reject or short_reject:
        return ContractRecommendation(
            strategy="DEBIT_SPREAD", direction=direction, legs=[],
            net_debit=0.0, max_profit=None, max_loss=0.0,
            sl_premium=0.0, t1_premium=0.0, t2_premium=0.0, breakeven=None,
            notes=[],
            rejection_reason=long_reject or short_reject,
        )

    assert long_row is not None and short_row is not None
    long_leg = _build_leg(long_row, option_type=option_type, side="BUY", delta=DELTA_ATM)
    short_leg = _build_leg(short_row, option_type=option_type, side="SELL", delta=DELTA_OTM2)

    if long_leg.premium <= 0 or short_leg.premium <= 0:
        return ContractRecommendation(
            strategy="DEBIT_SPREAD", direction=direction, legs=[long_leg, short_leg],
            net_debit=0.0, max_profit=None, max_loss=0.0,
            sl_premium=0.0, t1_premium=0.0, t2_premium=0.0, breakeven=None,
            notes=[], rejection_reason="spread leg premium unavailable",
        )

    width = abs(long_leg.strike - short_leg.strike)
    net_debit = round(long_leg.premium - short_leg.premium, 2)
    if net_debit <= 0:
        # Defensive: a non-positive debit means the chain is inconsistent
        # (e.g. a stale OTM quote priced higher than ATM). Drop the rec
        # rather than recommending a "free" trade that won't fill.
        return ContractRecommendation(
            strategy="DEBIT_SPREAD", direction=direction, legs=[long_leg, short_leg],
            net_debit=net_debit, max_profit=None, max_loss=0.0,
            sl_premium=0.0, t1_premium=0.0, t2_premium=0.0, breakeven=None,
            notes=[], rejection_reason=f"non-positive net debit {net_debit:.2f}",
        )

    max_profit = round(width - net_debit, 2)
    sl_prem = round(0.5 * net_debit, 2)
    t1_prem = round(net_debit + 0.5 * max_profit, 2)
    t2_prem = round(net_debit + 0.85 * max_profit, 2)
    breakeven = (
        long_leg.strike + net_debit if option_type == "CE"
        else long_leg.strike - net_debit
    )
    spread_label = "Bull Call Spread" if direction == "LONG" else "Bear Put Spread"
    notes = [
        f"{spread_label} {long_leg.strike:.0f}/{short_leg.strike:.0f} "
        f"net debit {net_debit:.2f}, max profit {max_profit:.2f}",
    ]
    return ContractRecommendation(
        strategy="DEBIT_SPREAD", direction=direction, legs=[long_leg, short_leg],
        net_debit=net_debit,
        max_profit=max_profit,
        max_loss=net_debit,
        sl_premium=sl_prem,
        t1_premium=t1_prem,
        t2_premium=t2_prem,
        breakeven=round(breakeven, 2),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def recommend_contracts(
    *, direction: str, spot: float,
    spot_entry: float, spot_sl: float, spot_t1: float, spot_t2: float,
    rows: Sequence[OCRow], strike_step: float,
    min_oi: int = DEFAULT_MIN_OI,
    max_spread_pct: float = DEFAULT_MAX_SPREAD_PCT,
) -> List[ContractRecommendation]:
    """Return up to two contract recommendations for the given signal.

    Always emits both a SINGLE_LEG and a DEBIT_SPREAD entry — even if one is
    rejected — so the UI can surface *why* a strategy isn't tradable instead
    of silently dropping it.

    `spot_entry` is accepted for symmetry with the IndexTradePlan but is not
    used directly: premium projection is done from `spot` (the live underlying
    used to look up the strike) so the recommendation reflects the chain
    snapshot being analysed.
    """
    if not rows or strike_step <= 0:
        return []
    if direction not in ("LONG", "SHORT"):
        return []
    _ = spot_entry  # kept for API symmetry; see docstring

    return [
        _single_leg_recommendation(
            direction=direction, spot=spot,
            spot_sl=spot_sl, spot_t1=spot_t1, spot_t2=spot_t2,
            rows=rows, strike_step=strike_step,
            min_oi=min_oi, max_spread_pct=max_spread_pct,
        ),
        _debit_spread_recommendation(
            direction=direction, spot=spot,
            rows=rows, strike_step=strike_step,
            min_oi=min_oi, max_spread_pct=max_spread_pct,
        ),
    ]


def leg_to_dict(leg: StrikeLeg) -> dict:
    return {
        "option_type": leg.option_type,
        "strike": leg.strike,
        "side": leg.side,
        "delta_estimate": leg.delta_estimate,
        "premium": leg.premium,
        "iv": leg.iv,
        "oi": leg.oi,
        "bid": leg.bid,
        "ask": leg.ask,
    }


def recommendation_to_dict(rec: ContractRecommendation) -> dict:
    return {
        "strategy": rec.strategy,
        "direction": rec.direction,
        "legs": [leg_to_dict(l) for l in rec.legs],
        "net_debit": rec.net_debit,
        "max_profit": rec.max_profit,
        "max_loss": rec.max_loss,
        "sl_premium": rec.sl_premium,
        "t1_premium": rec.t1_premium,
        "t2_premium": rec.t2_premium,
        "breakeven": rec.breakeven,
        "notes": list(rec.notes),
        "rejection_reason": rec.rejection_reason,
    }


__all__ = [
    "DEFAULT_MIN_OI",
    "DEFAULT_MAX_SPREAD_PCT",
    "ContractRecommendation",
    "StrikeLeg",
    "leg_to_dict",
    "recommend_contracts",
    "recommendation_to_dict",
]
