"""Pure tests for the option-chain metrics module."""
from __future__ import annotations

from app.analysis.option_chain_metrics import (
    OCRow,
    derive_bias,
    iv_skew,
    max_pain,
    max_pain_distance_pct,
    pcr,
    pcr_volume,
    pick_strike,
    premium_at_strike,
    summarise,
    total_change_oi,
    total_oi,
)


def _chain_neutral():
    """A balanced symmetric chain centred at 20000."""
    return [
        OCRow(
            strike=19800,
            ce_oi=1000, ce_change_oi=100, ce_volume=200, ce_iv=14.0, ce_ltp=210,
            pe_oi=1000, pe_change_oi=100, pe_volume=200, pe_iv=14.0, pe_ltp=15,
        ),
        OCRow(
            strike=19900,
            ce_oi=2000, ce_change_oi=100, ce_volume=300, ce_iv=13.5, ce_ltp=130,
            pe_oi=2000, pe_change_oi=100, pe_volume=300, pe_iv=13.5, pe_ltp=40,
        ),
        OCRow(
            strike=20000,
            ce_oi=3000, ce_change_oi=200, ce_volume=400, ce_iv=13.0, ce_ltp=80,
            pe_oi=3000, pe_change_oi=200, pe_volume=400, pe_iv=13.0, pe_ltp=80,
        ),
        OCRow(
            strike=20100,
            ce_oi=2000, ce_change_oi=100, ce_volume=300, ce_iv=12.5, ce_ltp=40,
            pe_oi=2000, pe_change_oi=100, pe_volume=300, pe_iv=12.5, pe_ltp=130,
        ),
        OCRow(
            strike=20200,
            ce_oi=1000, ce_change_oi=100, ce_volume=200, ce_iv=12.0, ce_ltp=15,
            pe_oi=1000, pe_change_oi=100, pe_volume=200, pe_iv=12.0, pe_ltp=210,
        ),
    ]


def _chain_bullish():
    """Heavy put-writing => high PCR, max pain above spot."""
    return [
        OCRow(
            strike=19800,
            ce_oi=500, ce_change_oi=20, ce_volume=100, ce_iv=14.0, ce_ltp=240,
            pe_oi=2500, pe_change_oi=400, pe_volume=600, pe_iv=14.0, pe_ltp=18,
        ),
        OCRow(
            strike=19900,
            ce_oi=800, ce_change_oi=30, ce_volume=200, ce_iv=13.5, ce_ltp=160,
            pe_oi=4000, pe_change_oi=500, pe_volume=800, pe_iv=13.5, pe_ltp=45,
        ),
        OCRow(
            strike=20000,
            ce_oi=1200, ce_change_oi=50, ce_volume=350, ce_iv=13.0, ce_ltp=100,
            pe_oi=3500, pe_change_oi=300, pe_volume=700, pe_iv=13.0, pe_ltp=95,
        ),
        OCRow(
            strike=20100,
            ce_oi=900, ce_change_oi=40, ce_volume=250, ce_iv=12.5, ce_ltp=55,
            pe_oi=1800, pe_change_oi=150, pe_volume=400, pe_iv=12.5, pe_ltp=150,
        ),
        OCRow(
            strike=20200,
            ce_oi=600, ce_change_oi=30, ce_volume=150, ce_iv=12.0, ce_ltp=20,
            pe_oi=900, pe_change_oi=100, pe_volume=200, pe_iv=12.0, pe_ltp=235,
        ),
    ]


def _chain_bearish():
    return [
        OCRow(
            strike=19800,
            ce_oi=2500, ce_change_oi=400, ce_volume=600, ce_iv=14.0, ce_ltp=240,
            pe_oi=500, pe_change_oi=20, pe_volume=100, pe_iv=16.5, pe_ltp=18,
        ),
        OCRow(
            strike=19900,
            ce_oi=4000, ce_change_oi=500, ce_volume=800, ce_iv=13.5, ce_ltp=160,
            pe_oi=800, pe_change_oi=30, pe_volume=200, pe_iv=16.0, pe_ltp=45,
        ),
        OCRow(
            strike=20000,
            ce_oi=3500, ce_change_oi=300, ce_volume=700, ce_iv=13.0, ce_ltp=100,
            pe_oi=1200, pe_change_oi=50, pe_volume=350, pe_iv=15.5, pe_ltp=95,
        ),
        OCRow(
            strike=20100,
            ce_oi=1800, ce_change_oi=150, ce_volume=400, ce_iv=12.5, ce_ltp=55,
            pe_oi=900, pe_change_oi=40, pe_volume=250, pe_iv=15.0, pe_ltp=150,
        ),
        OCRow(
            strike=20200,
            ce_oi=900, ce_change_oi=100, ce_volume=200, ce_iv=12.0, ce_ltp=20,
            pe_oi=600, pe_change_oi=30, pe_volume=150, pe_iv=14.5, pe_ltp=235,
        ),
    ]


def test_pcr_neutral_is_one():
    rows = _chain_neutral()
    val = pcr(rows)
    assert val is not None
    assert abs(val - 1.0) < 1e-6


def test_pcr_bullish_high():
    val = pcr(_chain_bullish())
    assert val is not None and val > 1.5


def test_pcr_bearish_low():
    val = pcr(_chain_bearish())
    assert val is not None and val < 0.7


def test_pcr_volume_matches_volumes():
    rows = _chain_neutral()
    val = pcr_volume(rows)
    assert val is not None and abs(val - 1.0) < 1e-6


def test_total_oi_and_change_split():
    rows = _chain_neutral()
    ce_oi, pe_oi = total_oi(rows)
    ce_d, pe_d = total_change_oi(rows)
    assert ce_oi == 9000 and pe_oi == 9000
    assert ce_d == 600 and pe_d == 600


def test_max_pain_returns_min_payoff_strike():
    rows = _chain_neutral()
    mp = max_pain(rows)
    assert mp == 20000.0


def test_max_pain_above_spot_for_bullish_chain():
    rows = _chain_bullish()
    mp = max_pain(rows)
    spot = 19950.0
    assert mp is not None and mp >= spot


def test_iv_skew_picks_atm_row_difference():
    rows = _chain_neutral()
    skew = iv_skew(rows, spot=20000.0)
    assert skew is not None and abs(skew) < 1e-6


def test_derive_bias_neutral():
    bias, strength, _ = derive_bias(_chain_neutral(), spot=20000)
    assert bias == "Neutral"
    assert 0.0 <= strength <= 1.0


def test_derive_bias_bullish():
    bias, strength, notes = derive_bias(_chain_bullish(), spot=19950)
    assert bias == "Bullish"
    assert strength > 0
    assert any("PCR" in n for n in notes)


def test_derive_bias_bearish():
    bias, _, _ = derive_bias(_chain_bearish(), spot=20050)
    assert bias == "Bearish"


def test_derive_bias_empty_returns_neutral():
    bias, strength, notes = derive_bias([], spot=20000)
    assert bias == "Neutral" and strength == 0.0 and notes


def test_summarise_round_trip():
    s = summarise(_chain_neutral(), spot=20000)
    assert s.bias in {"Bullish", "Bearish", "Neutral"}
    assert s.total_ce_oi == 9000 and s.total_pe_oi == 9000
    assert s.pcr is not None
    assert isinstance(s.notes, list)


def test_pick_strike_atm():
    rows = _chain_neutral()
    s = pick_strike(rows, spot=20040.0, option_type="CE", strike_step=100.0)
    assert s == 20000.0


def test_pick_strike_itm_ce_below_atm():
    rows = _chain_neutral()
    s = pick_strike(rows, spot=20000.0, option_type="CE", moneyness="ITM1", strike_step=100.0)
    assert s == 19900.0


def test_pick_strike_otm_ce_above_atm():
    rows = _chain_neutral()
    s = pick_strike(rows, spot=20000.0, option_type="CE", moneyness="OTM1", strike_step=100.0)
    assert s == 20100.0


def test_pick_strike_itm_pe_above_atm():
    rows = _chain_neutral()
    s = pick_strike(rows, spot=20000.0, option_type="PE", moneyness="ITM1", strike_step=100.0)
    assert s == 20100.0


def test_premium_at_strike():
    rows = _chain_neutral()
    ce = premium_at_strike(rows, 20000.0, option_type="CE")
    pe = premium_at_strike(rows, 20000.0, option_type="PE")
    assert ce == 80
    assert pe == 80


def test_premium_at_missing_strike_returns_none():
    rows = _chain_neutral()
    assert premium_at_strike(rows, 99999.0, option_type="CE") is None


def test_max_pain_distance_pct_zero_when_at_max_pain():
    rows = _chain_neutral()
    # Neutral chain pegs max-pain at 20000; spot at 20000 => 0% distance.
    assert max_pain_distance_pct(rows, spot=20000.0) == 0.0


def test_max_pain_distance_pct_positive_when_mp_above_spot():
    rows = _chain_bullish()
    spot = 19800.0
    pct = max_pain_distance_pct(rows, spot=spot)
    assert pct is not None and pct > 0


def test_max_pain_distance_pct_none_when_spot_missing():
    rows = _chain_neutral()
    assert max_pain_distance_pct(rows, spot=None) is None
    assert max_pain_distance_pct(rows, spot=0.0) is None


def test_summarise_includes_max_pain_distance():
    s = summarise(_chain_bullish(), spot=19800.0)
    assert s.max_pain_distance_pct is not None
    assert s.max_pain_distance_pct > 0
