"""Deterministic tests for option-chain analytics.

Builds synthetic chains with known shape and asserts that PCR, max-pain,
OI walls, change-OI flow, IV skew and the combined bias all read off
the way they should.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from app.analysis.option_chain_signals import (
    compute_change_oi_bias,
    compute_iv_metrics,
    compute_max_pain,
    compute_oi_walls,
    compute_pcr,
    derive_bias,
)
from app.data.option_types import OptionChainPayload, OptionRow


def _chain(
    spot: float,
    *,
    strikes_step: float = 50.0,
    ce_oi_per_strike: Optional[List[float]] = None,
    pe_oi_per_strike: Optional[List[float]] = None,
    ce_change_oi_per_strike: Optional[List[float]] = None,
    pe_change_oi_per_strike: Optional[List[float]] = None,
    ce_iv_per_strike: Optional[List[float]] = None,
    pe_iv_per_strike: Optional[List[float]] = None,
    ce_vol_per_strike: Optional[List[float]] = None,
    pe_vol_per_strike: Optional[List[float]] = None,
    n_each_side: int = 5,
) -> OptionChainPayload:
    """Build a chain with `n_each_side` strikes on either side of spot."""
    strikes = [
        round((spot // strikes_step + offset) * strikes_step)
        for offset in range(-n_each_side, n_each_side + 1)
    ]
    rows: List[OptionRow] = []
    for i, k in enumerate(strikes):
        rows.append(OptionRow(
            strike=float(k),
            ce_ltp=max(2.0, 100.0 - (k - spot) * 0.5),
            pe_ltp=max(2.0, 100.0 + (k - spot) * 0.5),
            ce_oi=(ce_oi_per_strike[i] if ce_oi_per_strike else 1000.0),
            pe_oi=(pe_oi_per_strike[i] if pe_oi_per_strike else 1000.0),
            ce_change_oi=(ce_change_oi_per_strike[i] if ce_change_oi_per_strike else 0.0),
            pe_change_oi=(pe_change_oi_per_strike[i] if pe_change_oi_per_strike else 0.0),
            ce_iv=(ce_iv_per_strike[i] if ce_iv_per_strike else 18.0),
            pe_iv=(pe_iv_per_strike[i] if pe_iv_per_strike else 18.0),
            ce_volume=(ce_vol_per_strike[i] if ce_vol_per_strike else 500.0),
            pe_volume=(pe_vol_per_strike[i] if pe_vol_per_strike else 500.0),
        ))
    keys = {float(k): {"CE": f"NSE_FO|CE-{int(k)}", "PE": f"NSE_FO|PE-{int(k)}"} for k in strikes}
    return OptionChainPayload(
        code="NIFTY", spot=spot, expiry=date(2026, 1, 13),
        expiries=[date(2026, 1, 13)],
        fetched_at=datetime(2026, 1, 6, 10, 0),
        source="upstox", rows=rows, instrument_keys_by_strike=keys,
    )


# ---------------------------------------------------------------------------
# PCR
# ---------------------------------------------------------------------------
def test_pcr_balanced_chain():
    chain = _chain(20000.0)
    pcr = compute_pcr(chain)
    assert pcr.pcr_oi == 1.0
    assert pcr.pcr_volume == 1.0


def test_pcr_heavy_put_writing_is_high():
    # PE OI 3x larger than CE OI -> PCR-OI = 3.0 -> contrarian bullish
    pe = [3000.0] * 11
    ce = [1000.0] * 11
    chain = _chain(20000.0, ce_oi_per_strike=ce, pe_oi_per_strike=pe)
    pcr = compute_pcr(chain)
    assert pcr.pcr_oi is not None
    assert abs(pcr.pcr_oi - 3.0) < 1e-6


def test_pcr_zero_ce_oi_returns_none():
    chain = _chain(20000.0, ce_oi_per_strike=[0.0] * 11)
    pcr = compute_pcr(chain)
    assert pcr.pcr_oi is None


# ---------------------------------------------------------------------------
# Max pain
# ---------------------------------------------------------------------------
def test_max_pain_concentrated_at_one_strike():
    # Heavy OI parked at one specific strike -> max pain should sit near it.
    # CE OI is heaviest at 20100, PE OI is heaviest at 19900.
    ce_oi = [100, 100, 100, 100, 100, 100, 200, 5000, 200, 100, 100]
    pe_oi = [100, 100, 5000, 200, 100, 100, 100, 100, 100, 100, 100]
    chain = _chain(20000.0, ce_oi_per_strike=ce_oi, pe_oi_per_strike=pe_oi)
    mp = compute_max_pain(chain)
    assert mp is not None
    # Max pain should sit at or very close to 20000 (between the two walls).
    assert 19900 <= mp <= 20100


def test_max_pain_none_when_no_oi():
    chain = _chain(20000.0, ce_oi_per_strike=[0.0] * 11, pe_oi_per_strike=[0.0] * 11)
    mp = compute_max_pain(chain)
    assert mp is None


# ---------------------------------------------------------------------------
# OI walls
# ---------------------------------------------------------------------------
def test_oi_walls_returns_resistance_above_spot_only():
    # PE OI heavy at 19800 (support), CE OI heavy at 20200 (resistance).
    ce_oi = [100, 100, 100, 100, 100, 100, 100, 5000, 200, 100, 100]
    pe_oi = [100, 5000, 200, 100, 100, 100, 100, 100, 100, 100, 100]
    chain = _chain(20000.0, ce_oi_per_strike=ce_oi, pe_oi_per_strike=pe_oi)
    resistance, support = compute_oi_walls(chain, 20000.0, k=2)
    assert all(w.side == "CE" and w.strike >= 20000 for w in resistance)
    assert all(w.side == "PE" and w.strike <= 20000 for w in support)
    # Strongest resistance is the 5000-OI strike at +200 offset (=20200 area).
    assert resistance[0].oi == 5000.0
    assert support[0].oi == 5000.0


# ---------------------------------------------------------------------------
# Change-in-OI flow
# ---------------------------------------------------------------------------
def test_change_oi_bullish_when_pe_writers_dominate():
    # PE writers added 80% of new OI today.
    pe_change = [0.0, 0.0, 5000.0, 5000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    ce_change = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 500.0, 500.0, 0.0, 0.0]
    chain = _chain(
        20000.0,
        ce_change_oi_per_strike=ce_change,
        pe_change_oi_per_strike=pe_change,
    )
    flow = compute_change_oi_bias(chain)
    assert flow.direction == "BULLISH"
    assert flow.pe_oi_added > flow.ce_oi_added


def test_change_oi_bearish_when_ce_writers_dominate():
    ce_change = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5000.0, 5000.0, 0.0, 0.0]
    pe_change = [0.0, 0.0, 500.0, 500.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    chain = _chain(
        20000.0,
        ce_change_oi_per_strike=ce_change,
        pe_change_oi_per_strike=pe_change,
    )
    flow = compute_change_oi_bias(chain)
    assert flow.direction == "BEARISH"


def test_change_oi_neutral_when_balanced():
    ce_change = [1000.0] * 11
    pe_change = [1000.0] * 11
    chain = _chain(
        20000.0,
        ce_change_oi_per_strike=ce_change,
        pe_change_oi_per_strike=pe_change,
    )
    flow = compute_change_oi_bias(chain)
    assert flow.direction == "NEUTRAL"


# ---------------------------------------------------------------------------
# IV metrics
# ---------------------------------------------------------------------------
def test_iv_skew_detects_fear_when_puts_richer():
    # PE wing IV 25, CE wing IV 15, ATM IV 18 -> skew = (25-15)/18 ~ 0.55 -> FEAR
    ce_iv = [15.0, 15.0, 15.0, 15.0, 15.0, 18.0, 15.0, 15.0, 15.0, 15.0, 15.0]
    pe_iv = [25.0, 25.0, 25.0, 25.0, 25.0, 18.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    chain = _chain(20000.0, ce_iv_per_strike=ce_iv, pe_iv_per_strike=pe_iv)
    metrics = compute_iv_metrics(chain, 20000.0)
    assert metrics.atm_iv == 18.0
    assert metrics.skew is not None
    assert metrics.skew > 0.10
    assert metrics.direction == "FEAR"


def test_iv_skew_detects_greed_when_calls_richer():
    ce_iv = [25.0, 25.0, 25.0, 25.0, 25.0, 18.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    pe_iv = [15.0, 15.0, 15.0, 15.0, 15.0, 18.0, 15.0, 15.0, 15.0, 15.0, 15.0]
    chain = _chain(20000.0, ce_iv_per_strike=ce_iv, pe_iv_per_strike=pe_iv)
    metrics = compute_iv_metrics(chain, 20000.0)
    assert metrics.direction == "GREED"


def test_iv_metrics_handles_missing_data():
    chain = _chain(
        20000.0,
        ce_iv_per_strike=[0.0] * 11,
        pe_iv_per_strike=[0.0] * 11,
    )
    metrics = compute_iv_metrics(chain, 20000.0)
    assert metrics.atm_iv is None
    assert metrics.skew is None
    assert metrics.direction == "NEUTRAL"


# ---------------------------------------------------------------------------
# Combined bias
# ---------------------------------------------------------------------------
def test_bias_bullish_when_signals_align():
    # PE writers heavy (PCR 2.0, bullish flow, fear skew).
    pe_oi = [3000.0] * 11
    ce_oi = [1000.0] * 11
    pe_change = [0.0, 0.0, 5000.0, 5000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    ce_change = [0.0] * 11
    ce_iv = [15.0, 15.0, 15.0, 15.0, 15.0, 18.0, 15.0, 15.0, 15.0, 15.0, 15.0]
    pe_iv = [25.0, 25.0, 25.0, 25.0, 25.0, 18.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    chain = _chain(
        20000.0,
        ce_oi_per_strike=ce_oi, pe_oi_per_strike=pe_oi,
        ce_change_oi_per_strike=ce_change, pe_change_oi_per_strike=pe_change,
        ce_iv_per_strike=ce_iv, pe_iv_per_strike=pe_iv,
    )
    bias = derive_bias(chain, 20000.0)
    assert bias.label == "BULLISH"
    assert bias.score > 0
    assert any("PCR-OI" in r for r in bias.reasons)


def test_bias_bearish_when_signals_align():
    pe_oi = [1000.0] * 11
    ce_oi = [3000.0] * 11   # PCR 0.33 -> bearish
    pe_change = [0.0] * 11
    ce_change = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5000.0, 5000.0, 0.0, 0.0]
    ce_iv = [25.0, 25.0, 25.0, 25.0, 25.0, 18.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    pe_iv = [15.0, 15.0, 15.0, 15.0, 15.0, 18.0, 15.0, 15.0, 15.0, 15.0, 15.0]
    chain = _chain(
        20000.0,
        ce_oi_per_strike=ce_oi, pe_oi_per_strike=pe_oi,
        ce_change_oi_per_strike=ce_change, pe_change_oi_per_strike=pe_change,
        ce_iv_per_strike=ce_iv, pe_iv_per_strike=pe_iv,
    )
    bias = derive_bias(chain, 20000.0)
    assert bias.label == "BEARISH"
    assert bias.score > 0


def test_bias_neutral_when_balanced():
    chain = _chain(20000.0)  # all defaults -> perfectly balanced
    bias = derive_bias(chain, 20000.0)
    assert bias.label == "NEUTRAL"
