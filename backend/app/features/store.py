"""FeatureStore — three-tier cache for FeatureVectors.

    L1: hot LRU (process-local, ~MB, lock-protected, fastest path)
    L2: cold SQLite (`features` table, durable, survives restarts)
    L3: compute path — `compute_features(symbol, df)` from CSV

Read order on `get_or_compute`:
    L1 hit         → return immediately
    L1 miss, L2 hit → promote into L1 → return
    Both miss      → compute from CSV, write to L2 + L1, return

Invalidation is the only non-trivial method: when the CSV refresh job
appends new candles for a symbol, the stored FeatureVector for that symbol
is now stale (a new "latest row" exists). Pipelines call
`invalidate(symbol)` after refresh; the next read recomputes.

Auto-invalidation on schema change: a `FeatureVector.feature_set_version`
mismatch is treated as a miss — we never trust an L2 row whose version
doesn't equal `FEATURE_SET_VERSION`. Stale rows linger harmlessly in the
DB until pruned by AuditAgent (PR2+).

Concurrency: the LRU is guarded by an internal RLock so the orchestrator's
threadpool can call `get_features_batch` from multiple workers without
double-computing. The DB session uses `session_scope()` per call which
already handles thread-safety via SQLAlchemy's connection pool.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select, delete

from ..data import csv_store
from ..db import session_scope
from ..models.feature_orm import FeatureRow
from .compute import compute_features
from .vectors import FeatureVector
from .versioning import FEATURE_SET_VERSION

log = logging.getLogger(__name__)

# Sized for ~250 NSE constituents × 3 timeframes — gives us full-universe
# coverage without thrashing. RSS impact is small (~80B per FeatureVector
# field × 50 fields ≈ 4KB; 1024 entries ≈ 4MB).
DEFAULT_LRU_MAX = 1024


class FeatureStore:
    """Thread-safe three-tier feature cache.

    Use the module-level singleton `get_default_store()` for normal app
    code; instantiate directly only in tests where you need an isolated
    cache (the singleton's hot LRU survives between tests in the same
    process and can mask cache-miss bugs).
    """

    def __init__(self, lru_max: int = DEFAULT_LRU_MAX) -> None:
        self._lru: "OrderedDict[Tuple[str, str, str], FeatureVector]" = OrderedDict()
        self._lru_max = lru_max
        self._lock = threading.RLock()
        # Counters are useful for HealthAgent (PR3+) and tests.
        self.stats: Dict[str, int] = {
            "hits_l1": 0,
            "hits_l2": 0,
            "misses": 0,
            "computes": 0,
            "invalidations": 0,
            "writes_l2": 0,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_or_compute(
        self,
        symbol: str,
        *,
        timeframe: str = "EOD",
        as_of_date: Optional[str] = None,
    ) -> Optional[FeatureVector]:
        """Fetch (cache-or-compute) the FeatureVector for one symbol.

        `as_of_date=None` means "latest available" — the live serving path.
        Pass an explicit `as_of_date` for backtests / OutcomeAgent (PR2+)
        when you want a historical snapshot.

        Returns None only when the symbol has no CSV at all (genuinely
        unknown ticker). An empty CSV returns a skeleton FeatureVector so
        engines can detect failure via `fv.latest_close is None`.
        """
        # We resolve as_of_date from the CSV when not provided so the cache
        # key is deterministic (otherwise two same-day calls would miss).
        resolved_date = as_of_date
        if resolved_date is None:
            resolved_date = _latest_date_for(symbol)
            if resolved_date is None:
                return None

        key = (symbol, resolved_date, timeframe)

        with self._lock:
            if key in self._lru:
                self._lru.move_to_end(key)
                self.stats["hits_l1"] += 1
                return self._lru[key]

        l2_hit = self._read_l2(symbol, resolved_date, timeframe)
        if l2_hit is not None:
            self._promote_l1(key, l2_hit)
            self.stats["hits_l2"] += 1
            return l2_hit

        self.stats["misses"] += 1
        fv = self._compute_and_store(symbol, resolved_date, timeframe)
        return fv

    def get_features_batch(
        self,
        symbols: Iterable[str],
        *,
        timeframe: str = "EOD",
        as_of_date: Optional[str] = None,
    ) -> Dict[str, FeatureVector]:
        """Vector-friendly bulk fetch. Returns only successful entries —
        symbols with no CSV are silently skipped (consistent with the
        single-symbol path returning None)."""
        out: Dict[str, FeatureVector] = {}
        for s in symbols:
            fv = self.get_or_compute(s, timeframe=timeframe, as_of_date=as_of_date)
            if fv is not None:
                out[s] = fv
        return out

    def invalidate(self, symbol: str, *, timeframe: Optional[str] = None) -> int:
        """Drop cached entries for a symbol. Called after CSV refresh.

        `timeframe=None` invalidates all timeframes (typical EOD pipeline
        path). Returns the number of L1 entries dropped (handy for tests).
        L2 rows are NOT deleted on invalidate — they're keyed by
        (symbol, as_of_date, timeframe, version) so a new as_of_date will
        be a fresh row anyway, and old snapshots stay around for backtests.
        """
        dropped = 0
        with self._lock:
            for key in list(self._lru.keys()):
                if key[0] != symbol:
                    continue
                if timeframe is not None and key[2] != timeframe:
                    continue
                del self._lru[key]
                dropped += 1
        if dropped:
            self.stats["invalidations"] += dropped
            log.debug("FeatureStore: invalidated %d entries for %s", dropped, symbol)
        return dropped

    def invalidate_all(self) -> int:
        """Drop the entire L1 cache. Used after a full retrain or CSV
        bulk-refresh. L2 untouched (snapshots survive)."""
        with self._lock:
            n = len(self._lru)
            self._lru.clear()
        if n:
            self.stats["invalidations"] += n
            log.info("FeatureStore: invalidated all %d L1 entries", n)
        return n

    def prune_stale_l2(self, *, current_version: Optional[str] = None) -> int:
        """Delete L2 rows whose feature_set_version != current. Returns
        deleted count. Safe to run anytime — the next read of any pruned
        symbol triggers a recompute."""
        version = current_version or FEATURE_SET_VERSION
        try:
            with session_scope() as db:
                result = db.execute(
                    delete(FeatureRow).where(FeatureRow.feature_set_version != version)
                )
                deleted = result.rowcount or 0
                if deleted:
                    log.info(
                        "FeatureStore: pruned %d stale L2 rows (current_version=%s)",
                        deleted,
                        version,
                    )
                return int(deleted)
        except Exception:  # noqa: BLE001
            log.exception("FeatureStore: prune_stale_l2 failed")
            return 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _promote_l1(self, key: Tuple[str, str, str], fv: FeatureVector) -> None:
        with self._lock:
            self._lru[key] = fv
            self._lru.move_to_end(key)
            while len(self._lru) > self._lru_max:
                self._lru.popitem(last=False)

    def _read_l2(
        self, symbol: str, as_of_date: str, timeframe: str
    ) -> Optional[FeatureVector]:
        try:
            with session_scope() as db:
                row = db.execute(
                    select(FeatureRow).where(
                        FeatureRow.symbol == symbol,
                        FeatureRow.as_of_date == as_of_date,
                        FeatureRow.timeframe == timeframe,
                        FeatureRow.feature_set_version == FEATURE_SET_VERSION,
                    )
                ).scalar_one_or_none()
                if row is None:
                    return None
                return FeatureVector.from_dict(row.payload_json)
        except Exception:  # noqa: BLE001 — DB quirks must not kill inference
            log.exception("FeatureStore: L2 read failed for %s/%s", symbol, as_of_date)
            return None

    def _write_l2(self, fv: FeatureVector) -> None:
        if not fv.as_of_date:
            return
        try:
            payload = fv.to_dict()
            with session_scope() as db:
                # Idempotent upsert via merge — avoids "UNIQUE constraint
                # failed" if two threads race to compute the same key.
                row = FeatureRow(
                    symbol=fv.symbol,
                    as_of_date=fv.as_of_date,
                    timeframe=fv.timeframe,
                    feature_set_version=fv.feature_set_version,
                    payload_json=payload,
                    bytes_size=len(repr(payload)),
                )
                db.merge(row)
            self.stats["writes_l2"] += 1
        except Exception:  # noqa: BLE001
            log.exception("FeatureStore: L2 write failed for %s", fv.symbol)

    def _compute_and_store(
        self, symbol: str, as_of_date: str, timeframe: str
    ) -> Optional[FeatureVector]:
        df = csv_store.load(symbol)
        if df.empty:
            return None
        # Slice to as_of_date so backtest snapshots are look-ahead-free.
        # `_latest_date_for` already gave us the last index for live calls;
        # the slice is a no-op in that case but cheap.
        try:
            df_slice = df.loc[: as_of_date]
        except Exception:  # noqa: BLE001 — odd index types fall through
            df_slice = df
        if df_slice.empty:
            return None

        fv = compute_features(symbol, df_slice, timeframe, as_of_date=as_of_date)
        self.stats["computes"] += 1
        self._write_l2(fv)
        self._promote_l1((symbol, fv.as_of_date, timeframe), fv)
        return fv


def _latest_date_for(symbol: str) -> Optional[str]:
    """Resolve the last as_of_date from the CSV, ISO-formatted. Used to
    derive a deterministic cache key when the caller didn't pin a date."""
    df = csv_store.load(symbol)
    if df.empty:
        return None
    last = df.index[-1]
    try:
        return last.strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return str(last)[:10]


# ---------------------------------------------------------------------------
# Module-level singleton — apps want one shared cache across all callers.
# ---------------------------------------------------------------------------
_default_store: Optional[FeatureStore] = None
_default_lock = threading.Lock()


def get_default_store() -> FeatureStore:
    global _default_store
    if _default_store is None:
        with _default_lock:
            if _default_store is None:
                _default_store = FeatureStore()
    return _default_store


def reset_default_store() -> None:
    """Test helper — drops the singleton so the next `get_default_store()`
    call returns a fresh instance. Don't call from app code."""
    global _default_store
    with _default_lock:
        _default_store = None


__all__ = [
    "FeatureStore",
    "get_default_store",
    "reset_default_store",
    "DEFAULT_LRU_MAX",
]
