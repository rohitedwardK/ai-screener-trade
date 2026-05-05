"""PaperPositionSizingService tests."""
from __future__ import annotations

from datetime import date

import pytest

from app.models.paper_schemas import ScreenerSignal
from app.paper.config import PaperConfigSnapshot
from app.paper.sizing import (
    HIGH_ATR_REDUCTION,
    MAX_POSITION_VALUE_FRACTION,
    OVERSOLD_REDUCTION,
    size,
)


def _sig(**overrides) -> ScreenerSignal:
    base = dict(
        symbol="TEST.NS",
        date=date(2026, 5, 5),
        close=1000.0,
        trend="Uptrend",
        setup_type="Pullback to EMA20",
        score=80.0,
        confidence="High",
        risk_level="Low",
        risk_reward=2.5,
        entry=1000.0,
        stop_loss=980.0,
        target_1=1050.0,
        target_2=1080.0,
        atr_percent=2.0,
    )
    base.update(overrides)
    return ScreenerSignal(**base)


def _cfg(**overrides) -> PaperConfigSnapshot:
    base = dict(
        virtual_capital=100_000.0,
        max_risk_per_trade_percent=0.5,
    )
    base.update(overrides)
    return PaperConfigSnapshot(**base)


def test_basic_quantity_uses_risk_budget():
    # capital 100k, risk 0.5% = 500 budget; risk_per_share = 20 -> 25 shares
    r = size(_sig(), _cfg())
    assert not r.rejected
    assert r.quantity == 25
    assert r.risk_per_share == 20.0
    assert r.risk_amount == 500.0


def test_invalid_plan_rejected():
    r = size(_sig(stop_loss=1010.0), _cfg())
    assert r.rejected
    assert "entry" in (r.reject_reason or "")


def test_stop_too_wide_rejected():
    r = size(_sig(entry=100.0, stop_loss=80.0, target_1=140.0), _cfg())
    # 20% stop distance > 8%
    assert r.rejected
    assert "stop too wide" in (r.reject_reason or "")


def test_confidence_medium_reduces_quantity_25pct():
    base = size(_sig(confidence="High"), _cfg())
    med = size(_sig(confidence="Medium"), _cfg())
    assert med.quantity < base.quantity
    # 25% reduction -> 25 * 0.75 = 18 (floor)
    assert med.quantity == int(base.quantity * 0.75)


def test_risk_level_medium_reduces_quantity_20pct():
    base = size(_sig(risk_level="Low"), _cfg())
    med = size(_sig(risk_level="Medium"), _cfg())
    # 25 * 0.80 = 20
    assert med.quantity == int(base.quantity * 0.80)


def test_oversold_recovery_reduces_quantity_50pct():
    base = size(_sig(setup_type="Pullback to EMA20"), _cfg())
    osr = size(_sig(setup_type="Oversold Recovery"), _cfg())
    # 25 * 0.50 = 12 (floor)
    assert osr.quantity == int(base.quantity * (1.0 - OVERSOLD_REDUCTION))


def test_high_atr_reduces_quantity_25pct():
    base = size(_sig(atr_percent=2.0), _cfg())
    high = size(_sig(atr_percent=5.0), _cfg())
    assert high.quantity == int(base.quantity * (1.0 - HIGH_ATR_REDUCTION))


def test_quantity_zero_rejected_after_reductions():
    # tiny capital + medium confidence + medium risk + oversold + high ATR
    s = _sig(confidence="Medium", risk_level="Medium", setup_type="Oversold Recovery", atr_percent=5.0)
    cfg = _cfg(virtual_capital=5_000.0, max_risk_per_trade_percent=0.5)
    r = size(s, cfg)
    # 25 budget / 20 = 1, then 1 * 0.75 * 0.80 * 0.50 * 0.75 = 0.225 -> 0
    assert r.rejected


def test_position_value_cap_rejected():
    # Risk only 1 share (very tight stop), but each share is huge -> oversize
    s = _sig(entry=10_000.0, stop_loss=9_950.0, target_1=10_150.0, atr_percent=1.0)
    # capital 100k, 0.5% = 500 risk; risk per share = 50 -> 10 shares -> 100k position
    r = size(s, _cfg(virtual_capital=100_000.0, max_risk_per_trade_percent=0.5))
    # 10 shares * 10,000 = 100k > 25% of capital
    assert r.rejected
    assert "position value" in (r.reject_reason or "")


def test_combined_adjustments_applied_multiplicatively():
    # High atr + Medium confidence -> 0.75 * 0.75 = 0.5625
    base = size(_sig(confidence="High", risk_level="Low", atr_percent=2.0), _cfg())
    combo = size(_sig(confidence="Medium", risk_level="Low", atr_percent=5.0), _cfg())
    expected = int(base.quantity * 0.75 * 0.75)
    assert combo.quantity == expected
