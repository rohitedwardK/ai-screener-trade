"""Signed evidence voting (generic, not symbol-specific)."""
from app.analysis import signal_evidence as ev


def test_direction_from_signed_votes_one_sided():
    assert ev.direction_from_signed_votes(2, 0) == ("LONG", None)
    assert ev.direction_from_signed_votes(0, 2) == ("SHORT", None)


def test_direction_from_signed_votes_conflict_is_wait():
    direction, msg = ev.direction_from_signed_votes(1, 1)
    assert direction == "WAIT"
    assert msg is not None
    assert "Conflicting" in msg


def test_direction_confidence_zero_on_conflict():
    assert ev.direction_confidence(1, 1) == 0.0
    assert ev.direction_confidence(2, 0) == 1.0


def test_regime_polarity():
    assert ev.regime_signed_vote("STRONG_DOWNTREND") == (0, 1, "Regime STRONG_DOWNTREND (bearish)")
    assert ev.regime_signed_vote("UPTREND") == (1, 0, "Regime UPTREND (bullish)")
    assert ev.regime_signed_vote("RANGE") == (0, 0, None)
