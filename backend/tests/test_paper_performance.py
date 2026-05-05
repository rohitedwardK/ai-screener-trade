"""PerformanceService tests with synthetic position objects."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pytest

from app.paper.performance import aggregate, _safe_div  # type: ignore[attr-defined]


@dataclass
class FakePos:
    realized_pnl: float
    setup_type: str = "Pullback to EMA20"
    holding_days: Optional[int] = 5
    exit_date: Optional[date] = date(2026, 5, 5)


def test_empty_metrics():
    m = aggregate([])
    assert m.total_trades == 0
    assert m.win_rate == 0.0
    assert m.profit_factor == 0.0
    assert m.expectancy == 0.0
    assert m.best_setup is None


def test_basic_win_rate_and_profit_factor():
    closed = [
        FakePos(realized_pnl=100.0),
        FakePos(realized_pnl=200.0),
        FakePos(realized_pnl=-50.0),
        FakePos(realized_pnl=-50.0),
    ]
    m = aggregate(closed)
    assert m.total_trades == 4
    assert m.winning_trades == 2
    assert m.losing_trades == 2
    assert m.win_rate == 50.0
    # avg win = 150, avg loss = -50
    assert m.average_win == 150.0
    assert m.average_loss == -50.0
    # profit factor = 300 / 100 = 3.0
    assert m.profit_factor == 3.0
    # expectancy = 0.5*150 - 0.5*50 = 50
    assert m.expectancy == 50.0


def test_per_setup_breakdown_and_best_worst():
    closed = [
        FakePos(realized_pnl=100.0, setup_type="Breakout Retest"),
        FakePos(realized_pnl=80.0, setup_type="Breakout Retest"),
        FakePos(realized_pnl=-200.0, setup_type="Pullback to EMA20"),
        FakePos(realized_pnl=50.0, setup_type="Pullback to EMA20"),
    ]
    m = aggregate(closed)
    assert m.best_setup == "Breakout Retest"
    assert m.worst_setup == "Pullback to EMA20"
    assert m.by_setup["Breakout Retest"]["trades"] == 2
    assert m.by_setup["Breakout Retest"]["wins"] == 2
    assert m.by_setup["Breakout Retest"]["total_pnl"] == 180.0
    assert m.by_setup["Pullback to EMA20"]["total_pnl"] == -150.0


def test_max_drawdown_from_equity_curve():
    # equity goes 100 -> 120 -> 90 -> 110: peak 120, trough 90 -> drawdown = 25%
    curve = [100.0, 120.0, 90.0, 110.0]
    m = aggregate([FakePos(realized_pnl=10.0)], equity_curve=curve)
    assert m.max_drawdown_percent == 25.0


def test_max_drawdown_zero_for_monotonic_curve():
    curve = [100.0, 110.0, 120.0, 130.0]
    m = aggregate([FakePos(realized_pnl=10.0)], equity_curve=curve)
    assert m.max_drawdown_percent == 0.0


def test_holding_days_average():
    closed = [
        FakePos(realized_pnl=10.0, holding_days=2),
        FakePos(realized_pnl=10.0, holding_days=4),
        FakePos(realized_pnl=10.0, holding_days=6),
    ]
    m = aggregate(closed)
    assert m.average_holding_days == 4.0


def test_safe_div_handles_zero():
    assert _safe_div(10.0, 0.0) == 0.0
    assert _safe_div(10.0, 0.0, default=42.0) == 42.0
    assert _safe_div(10.0, 5.0) == 2.0


def test_only_wins_profit_factor_is_total_wins():
    """No losses -> profit_factor degenerates; we return wins / 0 = 0 by convention."""
    closed = [FakePos(realized_pnl=100.0), FakePos(realized_pnl=200.0)]
    m = aggregate(closed)
    assert m.win_rate == 100.0
    # _safe_div uses default=0 when denominator is 0
    assert m.profit_factor == 0.0


def test_only_losses_metrics():
    closed = [FakePos(realized_pnl=-50.0), FakePos(realized_pnl=-100.0)]
    m = aggregate(closed)
    assert m.win_rate == 0.0
    assert m.average_win == 0.0
    assert m.average_loss == -75.0
