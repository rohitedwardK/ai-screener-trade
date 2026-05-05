"""Unit tests for the per-symbol observation state machine.

The state machine is a pure function so we feed it (state, sample) tuples
and assert on the returned state plus the `window_closed` flag.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.live_analysis.observer import (
    STATE_COOLDOWN,
    STATE_IDLE,
    STATE_OBSERVING,
    ObserverState,
    Sample,
    append_sample,
    cancel,
    is_eligible,
    mark_decided,
    maybe_release,
    start_observation,
)


T0 = datetime(2026, 5, 5, 10, 0, 0)


def _sample(offset_min: int, price: float, volume: int = 0) -> Sample:
    return Sample(ts=T0 + timedelta(minutes=offset_min), price=price, volume=volume)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def test_idle_to_observing_seeds_first_sample():
    state = ObserverState(symbol="X.NS")
    next_state = start_observation(state, now=T0, first_sample=_sample(0, 100.0))

    assert next_state.state == STATE_OBSERVING
    assert len(next_state.samples) == 1
    assert next_state.samples[0].price == pytest.approx(100.0)
    assert next_state.started_at == T0


def test_append_sample_grows_window():
    state = start_observation(
        ObserverState(symbol="X.NS"),
        now=T0,
        first_sample=_sample(0, 100.0),
    )
    next_state, closed = append_sample(
        state, _sample(3, 100.5),
        target_samples=6, min_step_seconds=150.0,
    )
    assert next_state.state == STATE_OBSERVING
    assert len(next_state.samples) == 2
    assert closed is False


def test_window_closes_on_target_reached():
    state = start_observation(
        ObserverState(symbol="X.NS"),
        now=T0,
        first_sample=_sample(0, 100.0),
    )
    closed_at_six = False
    for i, price in enumerate([100.1, 100.2, 100.3, 100.4, 100.5], start=1):
        state, closed = append_sample(
            state, _sample(i * 3, price),
            target_samples=6, min_step_seconds=150.0,
        )
        if closed:
            closed_at_six = i == 5  # 5 appends after the seed = 6 samples total
    assert closed_at_six
    assert len(state.samples) == 6


def test_decided_transitions_to_cooldown_with_correct_until():
    state = ObserverState(symbol="X.NS", state=STATE_OBSERVING, samples=[_sample(0, 100.0)])
    decided_at = T0 + timedelta(minutes=15)
    next_state = mark_decided(state, decided_at=decided_at, cooldown_min=30)

    assert next_state.state == STATE_COOLDOWN
    assert next_state.decided_at == decided_at
    assert next_state.cooldown_until == decided_at + timedelta(minutes=30)


def test_cooldown_releases_after_window_elapsed():
    state = ObserverState(
        symbol="X.NS", state=STATE_COOLDOWN,
        decided_at=T0, cooldown_until=T0 + timedelta(minutes=30),
    )

    still_locked = maybe_release(state, now=T0 + timedelta(minutes=29))
    assert still_locked.state == STATE_COOLDOWN

    released = maybe_release(state, now=T0 + timedelta(minutes=30))
    assert released.state == STATE_IDLE
    assert released.samples == []
    assert released.started_at is None
    assert released.cooldown_until is None


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def test_append_outside_observing_is_noop():
    state = ObserverState(symbol="X.NS", state=STATE_IDLE)
    next_state, closed = append_sample(
        state, _sample(0, 100.0),
        target_samples=6, min_step_seconds=150.0,
    )
    assert next_state is state
    assert closed is False


def test_append_drops_samples_arriving_too_soon():
    """Two samples 60s apart with min_step=150s: the second is rejected.

    Protects the engine from a re-entrant /tick that would otherwise close
    the window in seconds and produce a meaningless decision.
    """
    state = start_observation(
        ObserverState(symbol="X.NS"),
        now=T0,
        first_sample=Sample(ts=T0, price=100.0),
    )
    next_state, closed = append_sample(
        state,
        Sample(ts=T0 + timedelta(seconds=60), price=100.5),
        target_samples=6, min_step_seconds=150.0,
    )
    assert next_state is state
    assert closed is False


def test_cancel_locks_in_cooldown_without_decision():
    state = ObserverState(symbol="X.NS", state=STATE_OBSERVING, samples=[_sample(0, 100.0)])
    cancelled = cancel(state, now=T0 + timedelta(minutes=5), cooldown_min=10)
    assert cancelled.state == STATE_COOLDOWN
    assert cancelled.cooldown_until == T0 + timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Eligibility for promotion
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "state_kw,now_offset_min,expected",
    [
        ({"state": STATE_IDLE}, 0, True),
        ({"state": STATE_OBSERVING}, 0, False),
        (
            {"state": STATE_COOLDOWN, "cooldown_until": T0 + timedelta(minutes=10)},
            5, False,
        ),
        (
            {"state": STATE_COOLDOWN, "cooldown_until": T0 + timedelta(minutes=10)},
            10, True,
        ),
    ],
)
def test_is_eligible_respects_state(state_kw, now_offset_min, expected):
    state = ObserverState(symbol="X.NS", **state_kw)
    assert is_eligible(state, now=T0 + timedelta(minutes=now_offset_min)) is expected
