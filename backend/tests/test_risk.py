"""Trade-plan math tests."""
from __future__ import annotations

import pytest

from app.analysis.risk import long_plan, position_size, short_plan


def test_long_plan_stop_below_entry():
    p = long_plan(close=100.0, atr=2.0)
    assert p.stop_loss < p.entry
    assert p.target_1 > p.entry
    assert p.target_2 > p.target_1
    assert p.invalidation == p.stop_loss


def test_long_plan_rr_ratios_correct():
    p = long_plan(close=100.0, atr=2.0, stop_mult=1.0, rr1=2.0, rr2=4.0)
    risk = p.entry - p.stop_loss
    assert p.target_1 == pytest.approx(p.entry + 2 * risk, rel=1e-3)
    assert p.target_2 == pytest.approx(p.entry + 4 * risk, rel=1e-3)


def test_short_plan_stop_above_entry():
    p = short_plan(close=200.0, atr=4.0)
    assert p.stop_loss > p.entry
    assert p.target_1 < p.entry


def test_position_size_respects_risk():
    qty = position_size(account_size=100_000, risk_per_trade_pct=1.0, entry=500.0, stop=490.0)
    assert qty is not None
    risk_per_share = 10.0
    assert qty * risk_per_share <= 1_000.0


def test_position_size_zero_when_invalid():
    assert position_size(0, 1.0, 100, 95) is None
    assert position_size(100_000, 1.0, 100, 100) is None
