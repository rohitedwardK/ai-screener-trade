"""Tests for the paper-INDEX sizing module (option lot-aware)."""
from __future__ import annotations

from datetime import date

from app.models.index_schemas import IndexScreenerSignal
from app.paper_index.config import PaperIndexConfigSnapshot
from app.paper_index.sizing import (
    DEFAULT_PREMIUM_STOP_FRACTION,
    derive_premium_levels,
    estimate_entry_premium,
    size,
)


def _sig(**overrides) -> IndexScreenerSignal:
    base = dict(
        symbol="^NSEI", code="NIFTY", date=date(2026, 5, 5),
        spot=20000.0, direction="LONG", option_type="CE",
        setup_type="Trend Continuation", score=85.0,
        confidence="High", risk_level="Medium", risk_reward=2.5,
        spot_entry=20000.0, spot_stop_loss=19850.0,
        spot_target_1=20300.0, spot_target_2=20500.0,
        spot_invalidation=19850.0,
        rsi=60.0, atr_percent=1.5,
        market_regime="Bullish", option_chain_bias="Bullish",
    )
    base.update(overrides)
    return IndexScreenerSignal(**base)


def _cfg(**overrides) -> PaperIndexConfigSnapshot:
    # Capital is large enough that 1% risk-per-trade buys at least one Nifty
    # lot of 75 at our test premium grid (entry 120, stop 45 => 75/share).
    base = dict(
        virtual_capital=1_000_000.0,
        max_risk_per_trade_percent=1.0,
        option_delta_estimate=0.5,
    )
    base.update(overrides)
    return PaperIndexConfigSnapshot(**base)


def test_sizing_happy_path_long_ce():
    res = size(
        _sig(risk_level="Low"), _cfg(),
        lot_size=75, strike=20000.0, entry_premium=120.0, delta_estimate=0.5,
    )
    assert not res.rejected
    assert res.lots >= 1
    assert res.quantity == res.lots * 75
    # Realised premium-risk per option <= entry_premium - stop_premium.
    assert res.risk_per_unit > 0
    assert res.entry_premium == 120.0
    assert res.stop_premium < res.entry_premium
    # Premium value never exceeds 50% of capital.
    assert res.premium_value <= 0.5 * 1_000_000.0 + 1e-6


def test_sizing_happy_path_short_pe():
    s = _sig(
        direction="SHORT", option_type="PE",
        spot_entry=20000.0, spot_stop_loss=20150.0,
        spot_target_1=19700.0, spot_target_2=19500.0,
        risk_level="Low",
    )
    res = size(s, _cfg(), lot_size=75, strike=20000.0, entry_premium=120.0)
    assert not res.rejected
    assert res.lots >= 1


def test_sizing_zero_capital_rejected():
    res = size(
        _sig(), _cfg(virtual_capital=0.0),
        lot_size=75, strike=20000.0, entry_premium=120.0,
    )
    assert res.rejected
    assert "risk budget" in res.reject_reason


def test_sizing_too_small_capital_rejected():
    res = size(
        _sig(), _cfg(virtual_capital=2_000.0),
        lot_size=75, strike=20000.0, entry_premium=200.0,
    )
    assert res.rejected
    assert "risk budget too small" in res.reject_reason


def test_sizing_premium_estimate_when_chain_unknown():
    """When entry_premium is None, estimator should produce a positive value."""
    res = size(
        _sig(), _cfg(),
        lot_size=75, strike=20000.0, entry_premium=None,
    )
    if not res.rejected:
        assert res.entry_premium > 0


def test_estimate_entry_premium_intrinsic_plus_time_value():
    # ATM: intrinsic = 0, only time value.
    p = estimate_entry_premium(20000.0, 20000.0, option_type="CE", atr_percent=1.5, delta_estimate=0.5)
    assert p > 0
    # ITM CE: spot > strike => intrinsic > 0 => premium clearly higher.
    p_itm = estimate_entry_premium(20100.0, 20000.0, option_type="CE", atr_percent=1.5, delta_estimate=0.5)
    assert p_itm > p + 50  # roughly +100 intrinsic
    # OTM CE: intrinsic = 0 — premium is just slightly less than ATM (time value
    # scales with spot, so ~99% of ATM premium).
    p_otm = estimate_entry_premium(19900.0, 20000.0, option_type="CE", atr_percent=1.5, delta_estimate=0.5)
    assert p_otm < p
    assert abs(p_otm - p) <= p * 0.02


def test_derive_premium_levels_long():
    s = _sig()  # entry 20000, stop 19850, t1 20300, t2 20500
    stop_p, t1_p, t2_p = derive_premium_levels(
        s, entry_premium=120.0, delta_estimate=0.5,
        premium_stop_fraction=DEFAULT_PREMIUM_STOP_FRACTION,
    )
    assert 0 <= stop_p < 120.0
    assert t1_p > 120.0
    assert t2_p >= t1_p


def test_derive_premium_levels_short():
    s = _sig(
        direction="SHORT", option_type="PE",
        spot_entry=20000.0, spot_stop_loss=20150.0,
        spot_target_1=19700.0, spot_target_2=19500.0,
    )
    stop_p, t1_p, t2_p = derive_premium_levels(
        s, entry_premium=120.0, delta_estimate=0.5,
    )
    # premium goes UP for SHORT/PE-buy as spot DROPS.
    assert 0 <= stop_p < 120.0
    assert t1_p > 120.0
    assert t2_p >= t1_p


def test_sizing_high_risk_atr_reduces_lots():
    cfg = _cfg(virtual_capital=5_000_000.0)
    base = size(
        _sig(atr_percent=1.0, risk_level="Low"), cfg,
        lot_size=75, strike=20000.0, entry_premium=120.0,
    )
    high = size(
        _sig(atr_percent=3.0, risk_level="Low"), cfg,
        lot_size=75, strike=20000.0, entry_premium=120.0,
    )
    assert not base.rejected and not high.rejected
    assert high.lots <= base.lots


def test_sizing_medium_confidence_reduces_lots():
    cfg = _cfg(virtual_capital=5_000_000.0)
    high_conf = size(
        _sig(confidence="High", risk_level="Low"), cfg,
        lot_size=75, strike=20000.0, entry_premium=120.0,
    )
    med_conf = size(
        _sig(confidence="Medium", risk_level="Low"), cfg,
        lot_size=75, strike=20000.0, entry_premium=120.0,
    )
    assert not high_conf.rejected and not med_conf.rejected
    assert med_conf.lots <= high_conf.lots
