"""Tests for the option-chain strike picker."""
from __future__ import annotations

from typing import List

import pytest

from app.analysis.option_chain_metrics import OCRow
from app.analysis.strike_picker import (
    ContractRecommendation,
    DEFAULT_MIN_OI,
    recommend_contracts,
)


def _build_chain(spot: float = 22500.0, step: float = 50.0) -> List[OCRow]:
    """Symmetric synthetic chain centred on `spot` with realistic premiums.

    11 strikes (ATM ± 5). Premiums come from a simple linear approximation
    around the ATM so the deltas implied by the LTPs roughly match the
    constants in `strike_picker.py`.
    """
    rows: List[OCRow] = []
    atm = round(spot / step) * step
    for i in range(-5, 6):
        strike = atm + i * step
        # Nominal CE/PE LTPs decay linearly away from ATM, both sides.
        ce_intrinsic = max(spot - strike, 0.0)
        pe_intrinsic = max(strike - spot, 0.0)
        ce_extrinsic = max(80.0 - abs(i) * 12.0, 5.0)
        pe_extrinsic = max(80.0 - abs(i) * 12.0, 5.0)
        ce_ltp = ce_intrinsic + ce_extrinsic
        pe_ltp = pe_intrinsic + pe_extrinsic
        rows.append(OCRow(
            strike=strike,
            ce_oi=50_000.0, ce_change_oi=1_000.0, ce_volume=10_000.0,
            ce_iv=15.0, ce_ltp=ce_ltp,
            pe_oi=50_000.0, pe_change_oi=1_000.0, pe_volume=10_000.0,
            pe_iv=15.0, pe_ltp=pe_ltp,
            # Tight 2-rupee bid/ask around LTP — well within 8 % spread cap.
            **_quotes(ce_ltp, pe_ltp),
        ))
    return rows


def _quotes(ce_ltp: float, pe_ltp: float) -> dict:
    """Return the bid/ask kwargs for an OCRow with a tight ±1 rupee spread."""
    return {
        "ce_bid": max(ce_ltp - 1.0, 0.5),
        "ce_ask": ce_ltp + 1.0,
        "pe_bid": max(pe_ltp - 1.0, 0.5),
        "pe_ask": pe_ltp + 1.0,
    }


# ---------- Single-leg path -------------------------------------------------

def test_long_picks_atm_ce_when_liquid():
    rows = _build_chain(spot=22500.0)
    recs = recommend_contracts(
        direction="LONG", spot=22500.0,
        spot_entry=22500.0, spot_sl=22400.0, spot_t1=22600.0, spot_t2=22700.0,
        rows=rows, strike_step=50.0,
    )
    single = next(r for r in recs if r.strategy == "SINGLE_LEG")
    assert single.rejection_reason is None
    assert len(single.legs) == 1
    leg = single.legs[0]
    assert leg.option_type == "CE"
    assert leg.side == "BUY"
    assert leg.strike == 22500.0  # ATM
    assert leg.premium > 0


def test_short_picks_atm_pe_when_liquid():
    rows = _build_chain(spot=22500.0)
    recs = recommend_contracts(
        direction="SHORT", spot=22500.0,
        spot_entry=22500.0, spot_sl=22600.0, spot_t1=22400.0, spot_t2=22300.0,
        rows=rows, strike_step=50.0,
    )
    single = next(r for r in recs if r.strategy == "SINGLE_LEG")
    assert single.rejection_reason is None
    leg = single.legs[0]
    assert leg.option_type == "PE"
    assert leg.strike == 22500.0


def test_falls_back_to_itm_when_atm_illiquid():
    """When ATM has no quotes & low OI, picker reaches for ITM-1."""
    rows = _build_chain(spot=22500.0)
    # Wreck the ATM: zero bid/ask AND no LTP so liquidity check rejects it.
    for r in rows:
        if r.strike == 22500.0:
            r.ce_bid = 0.0
            r.ce_ask = 0.0
            r.ce_ltp = 0.0
            r.ce_oi = 0.0
            break
    recs = recommend_contracts(
        direction="LONG", spot=22500.0,
        spot_entry=22500.0, spot_sl=22400.0, spot_t1=22600.0, spot_t2=22700.0,
        rows=rows, strike_step=50.0,
    )
    single = next(r for r in recs if r.strategy == "SINGLE_LEG")
    assert single.rejection_reason is None
    assert single.legs[0].strike == 22450.0  # ITM-1 for CE = lower strike
    assert single.legs[0].delta_estimate == pytest.approx(0.65)


# ---------- Spread invariants -----------------------------------------------

def test_bull_call_spread_invariant():
    rows = _build_chain(spot=22500.0)
    recs = recommend_contracts(
        direction="LONG", spot=22500.0,
        spot_entry=22500.0, spot_sl=22400.0, spot_t1=22600.0, spot_t2=22700.0,
        rows=rows, strike_step=50.0,
    )
    spread = next(r for r in recs if r.strategy == "DEBIT_SPREAD")
    assert spread.rejection_reason is None
    assert len(spread.legs) == 2
    long_leg, short_leg = spread.legs
    assert long_leg.side == "BUY" and long_leg.option_type == "CE"
    assert short_leg.side == "SELL" and short_leg.option_type == "CE"
    width = abs(long_leg.strike - short_leg.strike)
    assert width == pytest.approx(100.0)  # 2 × strike_step
    # Algebraic invariant: net_debit + max_profit == strike_width.
    assert spread.max_profit is not None
    assert spread.net_debit + spread.max_profit == pytest.approx(width, rel=1e-6)
    # Breakeven sits between long_strike and short_strike for a Bull Call.
    assert spread.breakeven is not None
    assert long_leg.strike < spread.breakeven < short_leg.strike


def test_bear_put_spread_invariant():
    rows = _build_chain(spot=22500.0)
    recs = recommend_contracts(
        direction="SHORT", spot=22500.0,
        spot_entry=22500.0, spot_sl=22600.0, spot_t1=22400.0, spot_t2=22300.0,
        rows=rows, strike_step=50.0,
    )
    spread = next(r for r in recs if r.strategy == "DEBIT_SPREAD")
    assert spread.rejection_reason is None
    long_leg, short_leg = spread.legs
    assert long_leg.option_type == "PE" and long_leg.side == "BUY"
    assert short_leg.option_type == "PE" and short_leg.side == "SELL"
    # PE spread: long strike > short strike (we sell the lower one).
    assert long_leg.strike > short_leg.strike
    width = long_leg.strike - short_leg.strike
    assert spread.max_profit is not None
    assert spread.net_debit + spread.max_profit == pytest.approx(width, rel=1e-6)


# ---------- Premium projection ---------------------------------------------

def test_long_premium_sl_floors_at_half_debit():
    """A wide spot SL must not blow the premium SL below 50 % of debit."""
    rows = _build_chain(spot=22500.0)
    # Spot SL implies a -200 point move ⇒ delta 0.5 ⇒ -100 premium hit, which
    # would imply a negative premium for an entry around 80. The floor guards
    # against this.
    recs = recommend_contracts(
        direction="LONG", spot=22500.0,
        spot_entry=22500.0, spot_sl=22300.0, spot_t1=22600.0, spot_t2=22700.0,
        rows=rows, strike_step=50.0,
    )
    single = next(r for r in recs if r.strategy == "SINGLE_LEG")
    assert single.sl_premium >= 0.5 * single.net_debit - 0.01


def test_long_targets_increase_with_spot():
    rows = _build_chain(spot=22500.0)
    recs = recommend_contracts(
        direction="LONG", spot=22500.0,
        spot_entry=22500.0, spot_sl=22400.0, spot_t1=22600.0, spot_t2=22700.0,
        rows=rows, strike_step=50.0,
    )
    single = next(r for r in recs if r.strategy == "SINGLE_LEG")
    assert single.t1_premium > single.net_debit
    assert single.t2_premium > single.t1_premium


# ---------- Liquidity guard -------------------------------------------------

def test_low_oi_sets_rejection_reason():
    rows = _build_chain(spot=22500.0)
    # Drop OI on every CE strike so neither ATM nor ITM-1 can pass the floor.
    for r in rows:
        r.ce_oi = 100.0
    recs = recommend_contracts(
        direction="LONG", spot=22500.0,
        spot_entry=22500.0, spot_sl=22400.0, spot_t1=22600.0, spot_t2=22700.0,
        rows=rows, strike_step=50.0,
        min_oi=DEFAULT_MIN_OI,
    )
    single = next(r for r in recs if r.strategy == "SINGLE_LEG")
    assert single.rejection_reason is not None
    assert "OI" in single.rejection_reason
    assert single.legs == []


def test_wide_spread_rejects_atm_and_falls_back():
    rows = _build_chain(spot=22500.0)
    # Force a 50 % bid/ask spread on ATM — far above the 8 % cap.
    for r in rows:
        if r.strike == 22500.0:
            r.ce_bid = 50.0
            r.ce_ask = 110.0  # 60 mid → 60 / 60 = 100 % spread; well over cap
            break
    recs = recommend_contracts(
        direction="LONG", spot=22500.0,
        spot_entry=22500.0, spot_sl=22400.0, spot_t1=22600.0, spot_t2=22700.0,
        rows=rows, strike_step=50.0,
    )
    single = next(r for r in recs if r.strategy == "SINGLE_LEG")
    # Picker must move to ITM-1 instead of failing outright.
    assert single.rejection_reason is None
    assert single.legs[0].strike == 22450.0


# ---------- Graceful degradation -------------------------------------------

def test_empty_chain_returns_empty_list():
    assert recommend_contracts(
        direction="LONG", spot=22500.0,
        spot_entry=22500.0, spot_sl=22400.0, spot_t1=22600.0, spot_t2=22700.0,
        rows=[], strike_step=50.0,
    ) == []


def test_invalid_direction_returns_empty_list():
    rows = _build_chain(spot=22500.0)
    assert recommend_contracts(
        direction="HOLD", spot=22500.0,
        spot_entry=22500.0, spot_sl=22400.0, spot_t1=22600.0, spot_t2=22700.0,
        rows=rows, strike_step=50.0,
    ) == []


def test_returns_two_recommendations_in_order():
    """API contract: caller can rely on [single_leg, debit_spread] order."""
    rows = _build_chain(spot=22500.0)
    recs = recommend_contracts(
        direction="LONG", spot=22500.0,
        spot_entry=22500.0, spot_sl=22400.0, spot_t1=22600.0, spot_t2=22700.0,
        rows=rows, strike_step=50.0,
    )
    assert len(recs) == 2
    assert recs[0].strategy == "SINGLE_LEG"
    assert recs[1].strategy == "DEBIT_SPREAD"
    assert all(isinstance(r, ContractRecommendation) for r in recs)
