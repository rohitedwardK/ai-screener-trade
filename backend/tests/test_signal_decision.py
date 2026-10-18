"""Decision-engine semantics: rally probability is not a short, WAIT is first-class."""
from app.analysis.signal_decision import (
    apply_regime_safety,
    decide_from_rally_probability,
    direction_from_rally_probability,
)


def test_rally_probability_never_maps_class_zero_to_short():
    assert direction_from_rally_probability(0.0) == "WAIT"
    assert direction_from_rally_probability(0.34) == "WAIT"
    assert direction_from_rally_probability(0.49) == "WAIT"
    assert direction_from_rally_probability(0.5) == "LONG"
    assert direction_from_rally_probability(0.99) == "LONG"


def test_strong_downtrend_rejects_long_as_wait_not_short():
    direction, note = apply_regime_safety("LONG", "STRONG_DOWNTREND")
    assert direction == "WAIT"
    assert note is not None
    assert "WAIT" in note


def test_strong_downtrend_does_not_rewrite_explicit_short():
    direction, note = apply_regime_safety("SHORT", "STRONG_DOWNTREND")
    assert direction == "SHORT"
    assert note is None


def test_uptrend_long_passes():
    direction, note = apply_regime_safety("LONG", "STRONG_UPTREND")
    assert direction == "LONG"
    assert note is None


def test_plain_downtrend_is_not_the_safety_veto():
    direction, note = apply_regime_safety("LONG", "DOWNTREND")
    assert direction == "LONG"
    assert note is None


def test_decide_from_rally_probability_applies_both_layers():
    direction, note = decide_from_rally_probability(0.72, "STRONG_DOWNTREND")
    assert direction == "WAIT"
    assert note is not None
    direction, note = decide_from_rally_probability(0.2, "UPTREND")
    assert direction == "WAIT"
    assert note is None
