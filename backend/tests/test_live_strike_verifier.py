"""Tests for the pure live strike-recommendation verifier."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.analysis.live_strike_verifier import (
    PersistedRecommendation,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_INVALIDATED,
    STATUS_STOP_HIT,
    STATUS_T1_HIT,
    STATUS_T2_HIT,
    evaluate,
)


def _rec(**overrides) -> PersistedRecommendation:
    """Default tradable recommendation: entry 100, SL 50, T1 150, T2 200."""
    base = dict(
        id=1,
        expiry=date.today() + timedelta(days=3),
        entry_premium=100.0,
        sl_premium=50.0,
        t1_premium=150.0,
        t2_premium=200.0,
        current_status=STATUS_ACTIVE,
    )
    base.update(overrides)
    return PersistedRecommendation(**base)


def test_active_when_premium_inside_window():
    out = evaluate(
        _rec(), current_premium=120.0, today=date.today(), spot_sl_violated=False,
    )
    assert out.status == STATUS_ACTIVE
    assert out.last_premium == 120.0
    assert out.pnl_pct == pytest.approx(20.0)


def test_t1_hit_takes_precedence_over_active():
    out = evaluate(
        _rec(), current_premium=160.0, today=date.today(), spot_sl_violated=False,
    )
    assert out.status == STATUS_T1_HIT
    assert out.pnl_pct == pytest.approx(60.0)


def test_t2_hit_takes_precedence_over_t1():
    """When premium is at/above T2 the verifier must report T2_HIT, not T1."""
    out = evaluate(
        _rec(), current_premium=210.0, today=date.today(), spot_sl_violated=False,
    )
    assert out.status == STATUS_T2_HIT


def test_stop_hit_when_premium_at_or_below_sl():
    out = evaluate(
        _rec(), current_premium=50.0, today=date.today(), spot_sl_violated=False,
    )
    assert out.status == STATUS_STOP_HIT
    assert out.pnl_pct == pytest.approx(-50.0)


def test_expired_beats_everything():
    """Expiry day is the hard ceiling — no more transitions, even on T2."""
    expired = _rec(expiry=date.today() - timedelta(days=1))
    out = evaluate(
        expired, current_premium=300.0,  # would normally be T2_HIT
        today=date.today(), spot_sl_violated=True,
    )
    assert out.status == STATUS_EXPIRED


def test_invalidated_beats_target_and_stop_when_alive():
    """Spot SL breach trumps premium gates so we surface the broken thesis."""
    out = evaluate(
        _rec(), current_premium=180.0,  # would otherwise be T1_HIT
        today=date.today(), spot_sl_violated=True,
    )
    assert out.status == STATUS_INVALIDATED


def test_missing_premium_keeps_status_unchanged():
    """No price ⇒ leave the recommendation in its previous status."""
    rec = _rec(current_status=STATUS_T1_HIT)
    out = evaluate(
        rec, current_premium=None, today=date.today(), spot_sl_violated=False,
    )
    assert out.status == STATUS_T1_HIT
    assert out.last_premium is None
    assert out.pnl_pct is None


def test_pnl_pct_rounding():
    out = evaluate(
        _rec(entry_premium=100.0), current_premium=123.456,
        today=date.today(), spot_sl_violated=False,
    )
    assert out.pnl_pct == pytest.approx(23.46)
