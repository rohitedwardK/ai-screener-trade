"""AnalysisAgent — runs Random Forest and the rule-based baseline and finds consensus picks.

Backed by `tools.rank_methods_impl`, `tools.consensus_picks_impl`, and
`tools.screener_signals_impl`. Returns a single dict the orchestrator
uses for the final synthesis."""
from __future__ import annotations

import logging
from typing import Any, Dict

from .tools import (
    consensus_picks_impl,
    rank_methods_impl,
    screener_signals_impl,
)

log = logging.getLogger(__name__)


def run(top_k: int = 10, min_votes: int = 2) -> Dict[str, Any]:
    log.info("AnalysisAgent: consensus top_k=%d min_votes=%d", top_k, min_votes)
    methods = rank_methods_impl(top_k=15)
    consensus = consensus_picks_impl(top_k=top_k, min_votes=min_votes)
    screener = screener_signals_impl(min_score=0.0, limit=30)
    return {
        "methods": methods.get("methods", {}),
        "consensus_picks": consensus,
        "screener_signals_sample": screener[:10],
    }


run_deterministic = run


__all__ = ["run", "run_deterministic"]
