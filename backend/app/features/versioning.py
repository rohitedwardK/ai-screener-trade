"""Auto-versioning for the feature set.

`FEATURE_SET_VERSION` is a 12-char hex hash of the source files that define
how features are computed. Bump = "the math changed, cached rows are stale".

Why auto-derive instead of bumping a constant manually:

1. Developer ergonomics — editing `compute.py` or `indicators.py` is a
   common change; remembering to bump `FEATURE_SET_VERSION_V7` manually is
   not. Forgotten bumps cause silent stale-feature bugs (the worst kind).
2. Deterministic across machines — the hash is over file content, not
   wall-clock or git, so dev/staging/prod all converge to the same version
   when the source matches.
3. Old rows aren't deleted on bump — the FeatureStore filters by version on
   read, so stale rows linger harmlessly until pruned by AuditAgent (PR2+).

The hash inputs deliberately exclude this `versioning.py` itself (would
self-reference and never settle) and `__init__.py` (re-exports only).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# Only files whose content actually changes the math. Don't include test
# files, READMEs, or this module itself.
_VERSIONED_PATHS = [
    Path(__file__).parent / "vectors.py",
    Path(__file__).parent / "compute.py",
    Path(__file__).parent.parent / "analysis" / "indicators.py",
    Path(__file__).parent.parent / "analysis" / "patterns.py",
    Path(__file__).parent.parent / "analysis" / "pivots.py",
    Path(__file__).parent.parent / "analysis" / "regime.py",
]


def _compute_version() -> str:
    h = hashlib.sha256()
    for p in _VERSIONED_PATHS:
        try:
            h.update(p.read_bytes())
        except FileNotFoundError:
            # During interpreter startup before all modules are present, or
            # in odd test layouts. Fall back to a constant so the system
            # still boots — old cached rows just won't be invalidated.
            h.update(b"missing:" + p.name.encode())
    return h.hexdigest()[:12]


FEATURE_SET_VERSION: str = _compute_version()


__all__ = ["FEATURE_SET_VERSION"]
