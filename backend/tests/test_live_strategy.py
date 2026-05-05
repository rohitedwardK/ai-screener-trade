"""Unit tests for the Multi-Factor Confluence Score (MFCS) scorer.

All tests use synthetic 6-sample windows. The scorer is pure so we can
assert directly on (direction, confidence, invalidation, factor breakdown).
"""
from __future__ import annotations

import pytest

from app.live_analysis.config import LiveAnalysisConfigSnapshot
from app.live_analysis.strategy import (
    Decision,
    ObservationWindow,
    score_mfcs,
)


def _cfg(**overrides) -> LiveAnalysisConfigSnapshot:
    """Build a config snapshot with project defaults, optionally overridden."""
    base = LiveAnalysisConfigSnapshot()
    if not overrides:
        return base
    return LiveAnalysisConfigSnapshot(
        mode=overrides.get("mode", base.mode),
        poll_interval_min=overrides.get("poll_interval_min", base.poll_interval_min),
        observation_samples=overrides.get("observation_samples", base.observation_samples),
        top_k_movers=overrides.get("top_k_movers", base.top_k_movers),
        cooldown_min=overrides.get("cooldown_min", base.cooldown_min),
        decision_threshold=overrides.get("decision_threshold", base.decision_threshold),
        confidence_threshold=overrides.get("confidence_threshold", base.confidence_threshold),
        regime_risk_on_z=overrides.get("regime_risk_on_z", base.regime_risk_on_z),
        regime_risk_off_z=overrides.get("regime_risk_off_z", base.regime_risk_off_z),
        weights=overrides.get("weights", dict(base.weights)),
    )


def _strong_uptrend_window(symbol: str = "TEST.NS") -> ObservationWindow:
    """6 samples in a clean +1.5% / 15-min ramp on healthy volume."""
    samples = [100.0, 100.3, 100.6, 100.9, 101.2, 101.5]
    return ObservationWindow(
        symbol=symbol,
        samples=samples,
        open_3m=101.2, high_3m=101.55, low_3m=101.18, close_3m=101.5,
        vwap=100.6,                # price closing well above session VWAP
        rvol=2.0,                  # double the typical volume
        atr_3m=0.4,                # 0.4 absolute, well below the 1.5 move
        rsi_3m=62.0,               # bullish but not overbought
        ema20_3m=100.4,            # close above EMA20
        regime="RISK_ON",
    )


def _strong_downtrend_window(symbol: str = "TEST.NS") -> ObservationWindow:
    """Mirror image: -1.5% / 15-min slide on heavy volume."""
    samples = [200.0, 199.4, 198.8, 198.2, 197.6, 197.0]
    return ObservationWindow(
        symbol=symbol,
        samples=samples,
        open_3m=197.6, high_3m=197.65, low_3m=196.9, close_3m=197.0,
        vwap=198.7,                # price closing well below session VWAP
        rvol=2.0,
        atr_3m=0.8,
        rsi_3m=38.0,
        ema20_3m=199.0,
        regime="RISK_OFF",
    )


def _flat_window(symbol: str = "TEST.NS") -> ObservationWindow:
    """Sideways window: tiny zig-zag, no directional bias."""
    samples = [100.0, 100.05, 99.95, 100.02, 99.98, 100.01]
    return ObservationWindow(
        symbol=symbol,
        samples=samples,
        open_3m=99.98, high_3m=100.04, low_3m=99.96, close_3m=100.01,
        vwap=100.0, rvol=0.9,
        atr_3m=0.1, rsi_3m=50.0, ema20_3m=100.0,
        regime="NEUTRAL",
    )


# ---------------------------------------------------------------------------
# Direction tests
# ---------------------------------------------------------------------------
def test_strong_uptrend_in_risk_on_emits_long():
    obs = _strong_uptrend_window()
    decision = score_mfcs(obs, _cfg())

    assert isinstance(decision, Decision)
    assert decision.direction == "LONG"
    assert decision.confidence >= 65.0
    assert decision.long_raw > decision.short_raw
    # Invalidation is below the lowest observed sample.
    assert decision.invalidation is not None
    assert decision.invalidation < min(obs.samples)


def test_strong_downtrend_in_risk_off_emits_short():
    obs = _strong_downtrend_window()
    decision = score_mfcs(obs, _cfg())

    assert decision.direction == "SHORT"
    assert decision.confidence >= 65.0
    assert decision.short_raw > decision.long_raw
    assert decision.invalidation is not None
    assert decision.invalidation > max(obs.samples)


def test_flat_window_emits_hold():
    decision = score_mfcs(_flat_window(), _cfg())
    assert decision.direction == "HOLD"
    assert decision.invalidation is None


def test_risk_off_kills_long_even_on_uptrend():
    """RISK_OFF zeros the LONG multiplier - no LONG signals during selloffs."""
    obs = _strong_uptrend_window()
    obs = ObservationWindow(**{**obs.__dict__, "regime": "RISK_OFF"})
    decision = score_mfcs(obs, _cfg())
    assert decision.direction != "LONG"
    assert decision.factors["regime_long_mult"] == pytest.approx(0.0)


def test_risk_on_kills_short_even_on_downtrend():
    obs = _strong_downtrend_window()
    obs = ObservationWindow(**{**obs.__dict__, "regime": "RISK_ON"})
    decision = score_mfcs(obs, _cfg())
    assert decision.direction != "SHORT"
    assert decision.factors["regime_short_mult"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Factor sanity
# ---------------------------------------------------------------------------
def test_factors_are_normalised_into_clip_band():
    """Every clip'd factor stays in [-3, +3] regardless of input magnitude."""
    obs = ObservationWindow(
        symbol="X.NS",
        samples=[100.0] + [110.0] * 5,   # 10% jump on the first step
        atr_3m=0.01,                     # tiny ATR -> raw z would explode
        regime="NEUTRAL",
    )
    decision = score_mfcs(obs, _cfg())
    assert -3.0 <= decision.factors["z"] <= 3.0
    assert -3.0 <= decision.factors["slope_n"] <= 3.0


def test_overbought_penalty_applied_only_on_long_side():
    """RSI > 70 reduces LONG conviction; SHORT side untouched."""
    obs = _strong_uptrend_window()
    obs_overbought = ObservationWindow(**{**obs.__dict__, "rsi_3m": 85.0})
    base = score_mfcs(obs, _cfg())
    overbought = score_mfcs(obs_overbought, _cfg())

    assert overbought.factors["overbought_pen"] > 0
    assert overbought.long_raw < base.long_raw


def test_oversold_penalty_applied_only_on_short_side():
    obs = _strong_downtrend_window()
    obs_oversold = ObservationWindow(**{**obs.__dict__, "rsi_3m": 15.0})
    base = score_mfcs(obs, _cfg())
    oversold = score_mfcs(obs_oversold, _cfg())

    assert oversold.factors["oversold_pen"] > 0
    assert oversold.short_raw < base.short_raw


def test_invalidation_uses_atr_buffer():
    """LONG invalidation = min(samples) - 0.5 * ATR_3m."""
    obs = _strong_uptrend_window()
    decision = score_mfcs(obs, _cfg())
    assert decision.direction == "LONG"
    expected = min(obs.samples) - 0.5 * (obs.atr_3m or 0)
    assert decision.invalidation == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# Degenerate input handling
# ---------------------------------------------------------------------------
def test_too_few_samples_returns_hold_zero_confidence():
    obs = ObservationWindow(symbol="X.NS", samples=[100.0])
    decision = score_mfcs(obs, _cfg())
    assert decision.direction == "HOLD"
    assert decision.confidence == pytest.approx(0.0)
    assert decision.invalidation is None


def test_zero_atr_falls_back_to_realised_range_without_crashing():
    """ATR == 0 (e.g. day 1, no history) must not divide-by-zero."""
    obs = ObservationWindow(
        symbol="X.NS",
        samples=[100.0, 100.5, 101.0, 101.5, 102.0, 102.5],
        atr_3m=0.0,
    )
    decision = score_mfcs(obs, _cfg())
    # No crash + a finite confidence.
    assert decision.confidence >= 0.0


# ---------------------------------------------------------------------------
# Threshold tunability
# ---------------------------------------------------------------------------
def test_higher_confidence_threshold_downgrades_marginal_signals():
    """A true marginal window (small net score, sigmoid not saturated) flips
    from LONG to HOLD when the operator raises the confidence floor."""
    # Tiny linear ramp: the gap between long_raw and short_raw is small
    # enough that sigmoid output is well under 1.0.
    obs = ObservationWindow(
        symbol="MARG.NS",
        samples=[100.00, 100.02, 100.04, 100.06, 100.08, 100.10],
        atr_3m=0.5,            # small move relative to ATR -> z ~= 0.2
        rvol=1.0, vwap=100.0, ema20_3m=100.0, rsi_3m=55.0,
        regime="NEUTRAL",      # 0.6x multiplier shrinks raw further
        open_3m=100.08, high_3m=100.11, low_3m=100.07, close_3m=100.10,
    )
    permissive = score_mfcs(obs, _cfg(confidence_threshold=10.0, decision_threshold=0.1))
    strict = score_mfcs(obs, _cfg(confidence_threshold=99.0, decision_threshold=0.1))

    assert permissive.direction == "LONG"
    assert strict.direction == "HOLD"
    # Raw scores are deterministic - only the threshold gate moved.
    assert permissive.long_raw == pytest.approx(strict.long_raw, rel=1e-9)
    assert permissive.short_raw == pytest.approx(strict.short_raw, rel=1e-9)


def test_higher_decision_threshold_also_downgrades_signals():
    """Raising `decision_threshold` (the gap floor) is the other lever."""
    obs = _strong_uptrend_window()
    permissive = score_mfcs(obs, _cfg(decision_threshold=0.5))
    strict = score_mfcs(obs, _cfg(decision_threshold=999.0))

    assert permissive.direction == "LONG"
    assert strict.direction == "HOLD"
