"""Tests for recommend_strikes (OTM/ATM/ITM) + recommend_credit_spread."""
from __future__ import annotations

from datetime import date, datetime

from app.analysis.strike_picker import (
    recommend_credit_spread,
    recommend_strikes,
)
from app.core.universe import get_meta
from app.data.option_types import OptionChainPayload, OptionRow


def _chain(spot: float, strikes_step: float = 50.0) -> OptionChainPayload:
    """Synthetic chain with monotonic CE/PE LTPs around spot."""
    strikes = [round((spot // strikes_step + offset) * strikes_step)
               for offset in range(-3, 4)]
    rows = []
    for k in strikes:
        # CE: ATM ~ 100, OTM cheaper, ITM dearer (relative to spot).
        ce = max(2.0, 100.0 - (k - spot) * 0.5)
        pe = max(2.0, 100.0 + (k - spot) * 0.5)
        rows.append(OptionRow(
            strike=float(k),
            ce_ltp=ce,
            pe_ltp=pe,
            ce_oi=1000.0,
            pe_oi=1000.0,
        ))
    keys = {float(k): {"CE": f"NSE_FO|CE-{int(k)}", "PE": f"NSE_FO|PE-{int(k)}"} for k in strikes}
    return OptionChainPayload(
        code="NIFTY", spot=spot, expiry=date(2026, 1, 13),
        expiries=[date(2026, 1, 13)],
        fetched_at=datetime(2026, 1, 6, 10, 0),
        source="upstox", rows=rows, instrument_keys_by_strike=keys,
    )


# ---------------------------------------------------------------------------
# recommend_strikes
# ---------------------------------------------------------------------------
def test_recommend_strikes_returns_three_for_long():
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    out = recommend_strikes(
        spot_entry=20000, spot_stop=19940, spot_t1=20050, spot_t2=20100,
        direction="LONG", meta=meta, chain=chain,
    )
    assert len(out) == 3
    moneynesses = {c.moneyness for c in out}
    assert moneynesses == {"OTM", "ATM", "ITM"}
    # All CE for LONG.
    assert all(c.type == "CE" for c in out)


def test_recommend_strikes_long_strike_ladder_correct():
    """LONG/CE: OTM > ATM > ITM by strike (calls priced higher OTM is wrong; OTM has lower premium)."""
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    out = recommend_strikes(
        spot_entry=20000, spot_stop=19940, spot_t1=20050, spot_t2=20100,
        direction="LONG", meta=meta, chain=chain,
    )
    by_moneyness = {c.moneyness: c for c in out}
    assert by_moneyness["OTM"].strike > by_moneyness["ATM"].strike > by_moneyness["ITM"].strike
    # ITM CE costs more than ATM costs more than OTM.
    assert by_moneyness["ITM"].premium_entry > by_moneyness["ATM"].premium_entry
    assert by_moneyness["ATM"].premium_entry > by_moneyness["OTM"].premium_entry


def test_recommend_strikes_short_uses_pe():
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    out = recommend_strikes(
        spot_entry=20000, spot_stop=20060, spot_t1=19950, spot_t2=19900,
        direction="SHORT", meta=meta, chain=chain,
    )
    assert len(out) == 3
    assert all(c.type == "PE" for c in out)
    # SHORT/PE: OTM strike < ATM strike < ITM strike.
    by_moneyness = {c.moneyness: c for c in out}
    assert by_moneyness["OTM"].strike < by_moneyness["ATM"].strike < by_moneyness["ITM"].strike


def test_recommend_strikes_no_chain_returns_empty():
    meta = get_meta("^NSEI")
    out = recommend_strikes(
        spot_entry=20000, spot_stop=19940, spot_t1=20050, spot_t2=20100,
        direction="LONG", meta=meta, chain=None,
    )
    assert out == []


def test_recommend_strikes_sensex_returns_empty():
    meta = get_meta("^BSESN")
    chain = _chain(80000.0, strikes_step=100.0)
    out = recommend_strikes(
        spot_entry=80000, spot_stop=79800, spot_t1=80200, spot_t2=80400,
        direction="LONG", meta=meta, chain=chain,
    )
    assert out == []


def test_recommend_strikes_breakeven_makes_sense():
    """For a LONG/CE: breakeven = strike + premium_entry."""
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    out = recommend_strikes(
        spot_entry=20000, spot_stop=19940, spot_t1=20050, spot_t2=20100,
        direction="LONG", meta=meta, chain=chain,
    )
    for c in out:
        assert abs(c.breakeven_spot - (c.strike + c.premium_entry)) < 1e-6


def test_recommend_strikes_premium_floor():
    """Stop should never drop below 0.05 even with an extreme adverse spot."""
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    out = recommend_strikes(
        spot_entry=20000, spot_stop=18000, spot_t1=21000, spot_t2=22000,
        direction="LONG", meta=meta, chain=chain,
    )
    for c in out:
        assert c.premium_stop >= 0.05


# ---------------------------------------------------------------------------
# recommend_credit_spread
# ---------------------------------------------------------------------------
def test_credit_spread_bullish_is_bull_put():
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    spread = recommend_credit_spread(
        bias="BULLISH", spot=20000.0, meta=meta, chain=chain,
        support_strike=19900.0,
    )
    assert spread is not None
    assert spread.bias == "BULLISH"
    assert spread.short_type == "PE"
    # Bull-put: short higher strike, long lower strike.
    assert spread.short_strike > spread.long_strike
    # Credit must be positive, max loss strictly positive too.
    assert spread.net_credit > 0
    assert spread.max_loss > 0
    # Breakeven below short strike (spot must stay above this).
    assert spread.breakeven_spot < spread.short_strike


def test_credit_spread_bearish_is_bear_call():
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    spread = recommend_credit_spread(
        bias="BEARISH", spot=20000.0, meta=meta, chain=chain,
        resistance_strike=20100.0,
    )
    assert spread is not None
    assert spread.bias == "BEARISH"
    assert spread.short_type == "CE"
    # Bear-call: short lower strike, long higher strike.
    assert spread.short_strike < spread.long_strike
    assert spread.net_credit > 0
    assert spread.max_loss > 0
    # Breakeven above short strike (spot must stay below this).
    assert spread.breakeven_spot > spread.short_strike


def test_credit_spread_returns_none_for_sensex():
    meta = get_meta("^BSESN")
    chain = _chain(80000.0, strikes_step=100.0)
    spread = recommend_credit_spread(
        bias="BULLISH", spot=80000.0, meta=meta, chain=chain,
        support_strike=79900.0,
    )
    assert spread is None


def test_credit_spread_anchor_fallback_when_no_wall_supplied():
    """Without an explicit anchor, we fall back to the first strike below/above spot."""
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    bull = recommend_credit_spread(bias="BULLISH", spot=20000.0, meta=meta, chain=chain)
    bear = recommend_credit_spread(bias="BEARISH", spot=20000.0, meta=meta, chain=chain)
    assert bull is not None
    assert bear is not None
    assert bull.short_strike < 20000.0
    assert bear.short_strike > 20000.0


def test_credit_spread_warning_present_in_reasons():
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    spread = recommend_credit_spread(
        bias="BULLISH", spot=20000.0, meta=meta, chain=chain,
        support_strike=19900.0,
    )
    assert spread is not None
    assert any("CAPPED" in r for r in spread.reasons)


# ---------------------------------------------------------------------------
# Theta decay behaviour
# ---------------------------------------------------------------------------
def test_hold_days_zero_matches_legacy_no_theta_behaviour():
    """hold_days=0 must produce the same targets as the pre-theta version."""
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    out = recommend_strikes(
        spot_entry=20000, spot_stop=19940, spot_t1=20050, spot_t2=20100,
        direction="LONG", meta=meta, chain=chain, hold_days=0.0,
        as_of=date(2026, 1, 6),
    )
    atm = next(c for c in out if c.moneyness == "ATM")
    # With hold_days=0, theta_drag_total = 0, so premium_t2 must equal the
    # pure delta projection: entry + delta*(spot_t2 - spot_entry).
    expected_t2 = atm.premium_entry + 0.5 * (20100 - 20000)
    assert abs(atm.premium_t2 - expected_t2) < 1e-6
    assert atm.theta_drag_total == 0.0


def test_longer_hold_yields_lower_targets():
    """3-day hold must drop premium_t2 below 0-day target by exactly theta_drag_total."""
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    intraday = recommend_strikes(
        spot_entry=20000, spot_stop=19940, spot_t1=20050, spot_t2=20100,
        direction="LONG", meta=meta, chain=chain, hold_days=0.0,
        as_of=date(2026, 1, 6),
    )
    swing = recommend_strikes(
        spot_entry=20000, spot_stop=19940, spot_t1=20050, spot_t2=20100,
        direction="LONG", meta=meta, chain=chain, hold_days=3.0,
        as_of=date(2026, 1, 6),
    )
    intra_atm = next(c for c in intraday if c.moneyness == "ATM")
    swing_atm = next(c for c in swing if c.moneyness == "ATM")
    assert swing_atm.premium_t2 < intra_atm.premium_t2
    assert swing_atm.theta_drag_total > 0
    # Theta drag should account for the full delta between the two.
    assert abs((intra_atm.premium_t2 - swing_atm.premium_t2) - swing_atm.theta_drag_total) < 0.05


def test_theta_scales_with_dte_inverse_sqrt():
    """Theta on a same-day expiry must be much larger than on a 5-day expiry."""
    meta = get_meta("^NSEI")
    chain_today = _chain(20000.0)
    chain_today_obj = OptionChainPayload(
        code=chain_today.code, spot=chain_today.spot,
        expiry=date(2026, 1, 6),  # SAME day as as_of
        expiries=[date(2026, 1, 6)],
        fetched_at=chain_today.fetched_at,
        source=chain_today.source, rows=chain_today.rows,
        instrument_keys_by_strike=chain_today.instrument_keys_by_strike,
    )
    chain_5d_obj = OptionChainPayload(
        code=chain_today.code, spot=chain_today.spot,
        expiry=date(2026, 1, 11),  # 5 days from as_of
        expiries=[date(2026, 1, 11)],
        fetched_at=chain_today.fetched_at,
        source=chain_today.source, rows=chain_today.rows,
        instrument_keys_by_strike=chain_today.instrument_keys_by_strike,
    )
    same_day = recommend_strikes(
        spot_entry=20000, spot_stop=19940, spot_t1=20050, spot_t2=20100,
        direction="LONG", meta=meta, chain=chain_today_obj, hold_days=0.5,
        as_of=date(2026, 1, 6),
    )
    five_day = recommend_strikes(
        spot_entry=20000, spot_stop=19940, spot_t1=20050, spot_t2=20100,
        direction="LONG", meta=meta, chain=chain_5d_obj, hold_days=0.5,
        as_of=date(2026, 1, 6),
    )
    same_atm = next(c for c in same_day if c.moneyness == "ATM")
    five_atm = next(c for c in five_day if c.moneyness == "ATM")
    # Same hold (0.5 day) but 10x less time on the clock -> much higher theta.
    assert same_atm.theta_per_day > five_atm.theta_per_day * 2


def test_otm_decays_faster_than_itm_in_pct_terms():
    """OTM theta factor (1.2) > ITM theta factor (0.7) per dollar of premium."""
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    out = recommend_strikes(
        spot_entry=20000, spot_stop=19940, spot_t1=20050, spot_t2=20100,
        direction="LONG", meta=meta, chain=chain, hold_days=2.0,
        as_of=date(2026, 1, 6),
    )
    by_m = {c.moneyness: c for c in out}
    otm_pct = by_m["OTM"].theta_per_day / by_m["OTM"].premium_entry
    atm_pct = by_m["ATM"].theta_per_day / by_m["ATM"].premium_entry
    itm_pct = by_m["ITM"].theta_per_day / by_m["ITM"].premium_entry
    assert otm_pct > atm_pct > itm_pct


def test_credit_spread_carries_theta_and_projections():
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    spread = recommend_credit_spread(
        bias="BULLISH", spot=20000.0, meta=meta, chain=chain,
        support_strike=19900.0, as_of=date(2026, 1, 6),
    )
    assert spread is not None
    # Expiry is 2026-01-13 -> 7 days from as_of
    assert abs(spread.days_to_expiry - 7.0) < 1e-6
    # theta works in our favour: positive number representing daily decay
    assert spread.theta_per_day > 0
    # Projections shrink toward zero as we approach expiry.
    assert spread.projected_value_1d <= spread.net_credit
    assert spread.projected_value_3d <= spread.projected_value_1d
    assert spread.projected_value_at_expiry == 0.0


def test_credit_spread_theta_compounds_to_zero_at_expiry():
    """3-day projection should be smaller than 1-day (more decay collected)."""
    meta = get_meta("^NSEI")
    chain = _chain(20000.0)
    spread = recommend_credit_spread(
        bias="BEARISH", spot=20000.0, meta=meta, chain=chain,
        resistance_strike=20100.0, as_of=date(2026, 1, 6),
    )
    assert spread is not None
    # 1-day projection means buy-back is 1*theta cheaper, 3-day means 3*theta.
    one_day_decay = spread.net_credit - spread.projected_value_1d
    three_day_decay = spread.net_credit - spread.projected_value_3d
    assert three_day_decay > one_day_decay
    # Roughly 3x, but with the 0.0 floor it can be less if theta exceeds credit.
    assert three_day_decay <= 3.0 * one_day_decay + 0.05
