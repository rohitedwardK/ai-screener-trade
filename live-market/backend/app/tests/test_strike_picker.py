"""Unit tests for the strike picker + premium plan derivation."""
from __future__ import annotations

from datetime import date, datetime

from app.analysis.strike_picker import pick_atm
from app.core.universe import get_meta
from app.data.option_types import OptionChainPayload, OptionRow


def _chain(spot: float, strikes_step: float = 50.0) -> OptionChainPayload:
    """Build a synthetic chain with strikes around spot."""
    strikes = [round((spot // strikes_step + offset) * strikes_step)
               for offset in range(-3, 4)]
    rows = []
    for k in strikes:
        # Toy CE/PE LTPs: ATM ~ 100, deep ITM/OTM linearly off.
        ce = max(2.0, 100.0 - (k - spot) * 0.5)
        pe = max(2.0, 100.0 + (k - spot) * 0.5)
        rows.append(OptionRow(strike=float(k), ce_ltp=ce, pe_ltp=pe))
    keys = {float(k): {"CE": f"NSE_FO|CE-{int(k)}", "PE": f"NSE_FO|PE-{int(k)}"} for k in strikes}
    return OptionChainPayload(
        code="NIFTY", spot=spot, expiry=date(2026, 1, 13),
        expiries=[date(2026, 1, 13)],
        fetched_at=datetime(2026, 1, 6, 10, 0),
        source="upstox", rows=rows, instrument_keys_by_strike=keys,
    )


def test_returns_none_when_no_chain():
    meta = get_meta("^NSEI")
    out = pick_atm(
        spot_entry=20000, spot_stop=19940, spot_t1=20060, spot_t2=20100,
        direction="LONG", meta=meta, chain=None,
    )
    assert out is None


def test_sensex_returns_none_even_with_chain():
    meta = get_meta("^BSESN")
    chain = _chain(80000.0, strikes_step=100.0)
    out = pick_atm(
        spot_entry=80000, spot_stop=79800, spot_t1=80200, spot_t2=80400,
        direction="LONG", meta=meta, chain=chain,
    )
    assert out is None


def test_long_picks_ce_at_atm():
    meta = get_meta("^NSEI")
    chain = _chain(20007.0, strikes_step=50.0)
    out = pick_atm(
        spot_entry=20007, spot_stop=19960, spot_t1=20055, spot_t2=20100,
        direction="LONG", meta=meta, chain=chain,
    )
    assert out is not None
    assert out.type == "CE"
    assert out.strike == 20000.0
    assert out.premium_entry > 0
    # T2 > entry should give a higher CE premium target.
    assert out.premium_t2 > out.premium_entry
    # Stop should be a lower CE premium (clamped at >= 0.05).
    assert out.premium_stop < out.premium_entry


def test_short_picks_pe_at_atm():
    meta = get_meta("^NSEI")
    chain = _chain(20007.0, strikes_step=50.0)
    out = pick_atm(
        spot_entry=20007, spot_stop=20055, spot_t1=19955, spot_t2=19900,
        direction="SHORT", meta=meta, chain=chain,
    )
    assert out is not None
    assert out.type == "PE"
    assert out.strike == 20000.0
    # SHORT plan: spot falls -> PE premium rises.
    assert out.premium_t2 > out.premium_entry
    assert out.premium_stop < out.premium_entry


def test_premium_floor():
    meta = get_meta("^NSEI")
    chain = _chain(20007.0, strikes_step=50.0)
    # Choose extreme stop deep against the trade -> derived premium would
    # be negative without the clamp.
    out = pick_atm(
        spot_entry=20000, spot_stop=18000, spot_t1=21000, spot_t2=22000,
        direction="LONG", meta=meta, chain=chain,
    )
    assert out is not None
    assert out.premium_stop >= 0.05
