"""FeatureStoreAgent — L1.5 wrapper around the FeatureStore.

The agent layer wraps the underlying store so the orchestrator and
HealthAgent (PR3+) get a uniform interface (`run_deterministic`, status
counters) consistent with every other worker agent (data, analysis,
context, informant). The store itself is library code — fine to call
directly from infrastructure paths like the EOD pipeline's
post-refresh hook.

Two responsibilities here:

1. **Warm path** — pre-populate the cache for the active universe so the
   first inference cycle of the day doesn't hit a thundering herd of
   cold computes on every symbol. Triggered after EOD CSV refresh.
2. **Status surface** — return `{ok, computed, hit_rate, l2_rows}` for
   the Agents page so operators can see the cache is healthy.

This agent NEVER computes new features synchronously on the request path —
that's the inference engines' job (they'll call `store.get_or_compute`
inline). The agent's job is observability + warming.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select

from ..core.universe import all_symbols
from ..db import session_scope
from ..features import FEATURE_SET_VERSION
from ..features.store import FeatureStore, get_default_store
from ..models.feature_orm import FeatureRow

log = logging.getLogger(__name__)


def warm_cache(
    symbols: Optional[Sequence[str]] = None,
    *,
    timeframe: str = "EOD",
    store: Optional[FeatureStore] = None,
) -> Dict[str, Any]:
    """Compute (or read-through) FeatureVectors for every symbol in
    `symbols`. Defaults to the full active universe.

    Returns a structured status dict the orchestrator records into
    `worker_statuses_json`.
    """
    s = store or get_default_store()
    syms: List[str] = list(symbols) if symbols is not None else list(all_symbols())

    before = dict(s.stats)
    fvs = s.get_features_batch(syms, timeframe=timeframe)

    delta = {k: s.stats[k] - before.get(k, 0) for k in s.stats}
    log.info(
        "FeatureStoreAgent: warmed %d/%d symbols (computes=%d, l2_hits=%d, l1_hits=%d)",
        len(fvs), len(syms),
        delta["computes"], delta["hits_l2"], delta["hits_l1"],
    )

    return {
        "ok": True,
        "warmed": len(fvs),
        "requested": len(syms),
        "feature_set_version": FEATURE_SET_VERSION,
        "delta": delta,
        "stats_snapshot": dict(s.stats),
    }


def status() -> Dict[str, Any]:
    """Read-only snapshot of cache health for the Agents page."""
    s = get_default_store()
    l2_rows: Optional[int] = None
    l2_versions: Dict[str, int] = {}
    try:
        with session_scope() as db:
            l2_rows = int(
                db.execute(select(func.count()).select_from(FeatureRow)).scalar() or 0
            )
            rows = db.execute(
                select(FeatureRow.feature_set_version, func.count())
                .group_by(FeatureRow.feature_set_version)
            ).all()
            l2_versions = {str(v): int(c) for v, c in rows}
    except Exception:  # noqa: BLE001
        log.exception("FeatureStoreAgent.status: L2 query failed")

    total_reads = (
        s.stats["hits_l1"] + s.stats["hits_l2"] + s.stats["misses"]
    )
    hit_rate = (
        (s.stats["hits_l1"] + s.stats["hits_l2"]) / total_reads
        if total_reads > 0 else None
    )

    return {
        "feature_set_version": FEATURE_SET_VERSION,
        "l1_size": len(s._lru),  # noqa: SLF001 — intentional introspection
        "l2_rows": l2_rows,
        "l2_versions": l2_versions,
        "hit_rate": hit_rate,
        "stats": dict(s.stats),
    }


def run(symbols: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Standard agent entry-point used by the orchestrator. Warms the
    cache and returns combined warm-result + status."""
    warm_result = warm_cache(symbols=symbols)
    return {**warm_result, "status": status()}


run_deterministic = run


__all__ = ["warm_cache", "status", "run", "run_deterministic"]
