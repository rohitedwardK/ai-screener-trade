"""Per-symbol observation-window state machine.

Pure - no DB, no clock. Takes (state, sample) and returns the next state.
The engine is responsible for time semantics (which sample is "due", what
COOLDOWN means in wall-clock terms) by passing in the relevant timestamps.

States
------
IDLE       : not currently being observed; eligible for promotion via movers.
OBSERVING  : in a 6-sample window; engine appends a sample on each tick.
DECIDED    : window closed and a decision has been emitted (transient -
             flipped to COOLDOWN by the engine in the same tick).
COOLDOWN   : decision was emitted; symbol is locked out until
             (decided_at + cooldown_min) elapses, then it returns to IDLE.

The state machine deliberately accepts a "tick spacing" so the engine can
enforce the 3-min cadence: a sample is appended only if at least
`min_step_seconds` (default 150s) have elapsed since the last sample. This
prevents a re-entrant tick (e.g. manual /tick fired twice in a row) from
filling the window in a few seconds and producing a meaningless decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import List, Optional, Tuple


# State labels also persisted as `live_observations.status` strings.
STATE_IDLE = "IDLE"
STATE_OBSERVING = "OBSERVING"
STATE_DECIDED = "DECIDED"
STATE_COOLDOWN = "COOLDOWN"


@dataclass(frozen=True)
class Sample:
    ts: datetime
    price: float
    volume: int = 0


@dataclass(frozen=True)
class ObserverState:
    """Immutable per-symbol state. Engine swaps it out on every transition."""
    symbol: str
    state: str = STATE_IDLE
    samples: List[Sample] = field(default_factory=list)
    started_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None


def start_observation(state: ObserverState, *, now: datetime, first_sample: Sample) -> ObserverState:
    """Promote IDLE -> OBSERVING and seed the window with sample 0.

    Caller is expected to check `state.state == STATE_IDLE` and that any
    previous COOLDOWN has expired. We do not re-validate that here so the
    engine can also force-restart a stuck symbol (e.g. via manual /tick).
    """
    return replace(
        state,
        state=STATE_OBSERVING,
        samples=[first_sample],
        started_at=now,
        decided_at=None,
        cooldown_until=None,
    )


def append_sample(
    state: ObserverState,
    sample: Sample,
    *,
    target_samples: int,
    min_step_seconds: float = 150.0,
) -> Tuple[ObserverState, bool]:
    """Try to add `sample` to an OBSERVING window.

    Returns `(new_state, window_closed)`. `window_closed` is True when this
    append brings the count up to `target_samples`; the engine should then
    invoke the MFCS scorer and call `mark_decided`.

    If `state` is not OBSERVING, or if the new sample is closer than
    `min_step_seconds` to the previous one, it is dropped silently (returns
    the unchanged state). Mirrors the live-tick engine pattern in
    `paper/live_engine.py` of "engine still runs even on a no-op tick".
    """
    if state.state != STATE_OBSERVING:
        return state, False

    if state.samples:
        last = state.samples[-1]
        if (sample.ts - last.ts).total_seconds() < min_step_seconds:
            return state, False

    new_samples = list(state.samples) + [sample]
    new_state = replace(state, samples=new_samples)
    return new_state, len(new_samples) >= target_samples


def mark_decided(
    state: ObserverState,
    *,
    decided_at: datetime,
    cooldown_min: int,
) -> ObserverState:
    """Close the window: OBSERVING -> COOLDOWN. Engine called the scorer."""
    return replace(
        state,
        state=STATE_COOLDOWN,
        decided_at=decided_at,
        cooldown_until=decided_at + timedelta(minutes=int(cooldown_min)),
    )


def cancel(state: ObserverState, *, now: datetime, cooldown_min: int) -> ObserverState:
    """Close the window without a decision (e.g. data went stale).

    The symbol still serves out a COOLDOWN so we don't immediately re-enter
    a flaky state and burn cycles on the same broken feed.
    """
    return replace(
        state,
        state=STATE_COOLDOWN,
        decided_at=now,
        cooldown_until=now + timedelta(minutes=int(cooldown_min)),
    )


def maybe_release(state: ObserverState, *, now: datetime) -> ObserverState:
    """Flip COOLDOWN back to IDLE once `cooldown_until` has passed."""
    if state.state != STATE_COOLDOWN or state.cooldown_until is None:
        return state
    if now >= state.cooldown_until:
        return replace(
            state,
            state=STATE_IDLE,
            samples=[],
            started_at=None,
            decided_at=None,
            cooldown_until=None,
        )
    return state


def is_eligible(state: ObserverState, *, now: datetime) -> bool:
    """True when the symbol can be promoted into a fresh OBSERVING window."""
    if state.state == STATE_IDLE:
        return True
    if state.state == STATE_COOLDOWN and state.cooldown_until is not None:
        return now >= state.cooldown_until
    return False


__all__ = [
    "Sample",
    "ObserverState",
    "STATE_IDLE",
    "STATE_OBSERVING",
    "STATE_DECIDED",
    "STATE_COOLDOWN",
    "start_observation",
    "append_sample",
    "mark_decided",
    "cancel",
    "maybe_release",
    "is_eligible",
]
