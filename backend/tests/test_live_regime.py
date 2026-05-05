"""Unit tests for the live market-regime classifier."""
from __future__ import annotations

import pytest

from app.live_analysis.config import LiveAnalysisConfigSnapshot
from app.live_analysis.regime import classify_market


def _cfg(**overrides) -> LiveAnalysisConfigSnapshot:
    base = LiveAnalysisConfigSnapshot()
    if not overrides:
        return base
    return LiveAnalysisConfigSnapshot(
        regime_risk_on_z=overrides.get("regime_risk_on_z", base.regime_risk_on_z),
        regime_risk_off_z=overrides.get("regime_risk_off_z", base.regime_risk_off_z),
        weights=dict(base.weights),
    )


def test_steady_uptrend_classified_risk_on():
    """Six steady up-prints on the index should flip RISK_ON."""
    samples = [22000.0, 22020.0, 22040.0, 22060.0, 22080.0, 22100.0]
    result = classify_market(samples, cfg=_cfg(), nifty_atr_3m=20.0)
    assert result.regime == "RISK_ON"
    assert result.z > 0
    assert result.slope > 0


def test_steady_downtrend_classified_risk_off():
    samples = [22000.0, 21980.0, 21960.0, 21940.0, 21920.0, 21900.0]
    result = classify_market(samples, cfg=_cfg(), nifty_atr_3m=20.0)
    assert result.regime == "RISK_OFF"
    assert result.z < 0
    assert result.slope < 0


def test_choppy_classified_neutral():
    samples = [22000.0, 22005.0, 21995.0, 22002.0, 21998.0, 22001.0]
    result = classify_market(samples, cfg=_cfg(), nifty_atr_3m=10.0)
    assert result.regime == "NEUTRAL"


def test_insufficient_history_returns_neutral():
    """Less than two samples -> we can't compute z / slope at all."""
    result = classify_market([22000.0], cfg=_cfg())
    assert result.regime == "NEUTRAL"
    assert result.z == pytest.approx(0.0)
    assert result.last is None


def test_vwap_alignment_amplifies_uptrend_signal():
    """Two identical price paths but different VWAP positions: the one
    closing further above VWAP should land in (or further into) RISK_ON."""
    samples = [22000.0, 22010.0, 22020.0, 22030.0, 22040.0, 22050.0]
    no_vwap = classify_market(samples, cfg=_cfg(), nifty_atr_3m=15.0)
    above_vwap = classify_market(
        samples, cfg=_cfg(), nifty_atr_3m=15.0, nifty_vwap=21950.0,
    )
    # Both are bullish; the VWAP-aligned one shouldn't be weaker.
    assert above_vwap.regime == "RISK_ON"
    assert no_vwap.regime in ("RISK_ON", "NEUTRAL")


def test_threshold_overrides_change_classification():
    """Operator can require a stronger composite z before flipping bucket."""
    samples = [22000.0, 22005.0, 22010.0, 22015.0, 22020.0, 22025.0]
    permissive = classify_market(samples, cfg=_cfg(regime_risk_on_z=0.1), nifty_atr_3m=10.0)
    strict = classify_market(samples, cfg=_cfg(regime_risk_on_z=10.0), nifty_atr_3m=10.0)
    assert permissive.regime == "RISK_ON"
    assert strict.regime != "RISK_ON"
