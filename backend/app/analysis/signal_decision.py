"""Map model/rule proposals to LONG / SHORT / WAIT.

RF (and the other classifiers) still output P(+3% within 5 days). This module
is the decision engine: it must not treat a failed rally label as a short,
and it must not emit an unsupported countertrend LONG. Reversal setups stay
out of this path until they have their own confirmation rules.
"""
from __future__ import annotations

from typing import Optional, Tuple

DIRECTION_LONG = "LONG"
DIRECTION_SHORT = "SHORT"
DIRECTION_WAIT = "WAIT"
DIRECTIONS = (DIRECTION_LONG, DIRECTION_SHORT, DIRECTION_WAIT)

# P(+3% in 5 sessions) is a long-event probability, not a signed trade score.
RALLY_LONG_THRESHOLD = 0.5

# Safety only. DOWNTREND (not strong) is left alone until a dedicated
# COUNTERTREND_REVERSAL strategy exists.
UNSUPPORTED_COUNTERTREND_LONG_REGIMES = frozenset({"STRONG_DOWNTREND"})

_VETO_LONG_IN_STRONG_DOWNTREND = (
    "LONG rejected: STRONG_DOWNTREND without a supported reversal strategy. WAIT."
)


def direction_from_rally_probability(probability: float) -> str:
    """Class 0 is 'did not rally +3%'. That is WAIT, never SHORT."""
    if probability >= RALLY_LONG_THRESHOLD:
        return DIRECTION_LONG
    return DIRECTION_WAIT


def apply_regime_safety(proposed: str, regime: str) -> Tuple[str, Optional[str]]:
    """Keep SHORT if a rule proposed it. Never auto-flip a blocked LONG to SHORT."""
    direction = (proposed or DIRECTION_WAIT).upper()
    if direction == "NEUTRAL":
        direction = DIRECTION_WAIT
    if direction not in DIRECTIONS:
        return DIRECTION_WAIT, None
    if direction == DIRECTION_LONG and regime in UNSUPPORTED_COUNTERTREND_LONG_REGIMES:
        return DIRECTION_WAIT, _VETO_LONG_IN_STRONG_DOWNTREND
    return direction, None


def decide_from_rally_probability(probability: float, regime: str) -> Tuple[str, Optional[str]]:
    return apply_regime_safety(direction_from_rally_probability(probability), regime)


def category_proposed_direction(category: str) -> str:
    """Rule categories that attach a long_plan vs explicit short vs no-trade."""
    if category == "WEAK_AVOID":
        return DIRECTION_SHORT
    if category in {"OVERBOUGHT_AVOID", "HIGH_RISK"}:
        return DIRECTION_WAIT
    return DIRECTION_LONG
