"""Feature engineering layer (L1.5).

Centralised computation, caching, and persistence of per-symbol feature vectors.
Replaces ad-hoc `compute_all` calls scattered across rule-based, RF, GBM, and
LSTM scoring paths — every inference engine reads from this layer instead of
recomputing indicators inline.

See `AGENTS.md` Architecture > L1.5 for design notes.

Public surface:

    from app.features import FeatureStore, FeatureVector, compute_features
    from app.features.versioning import FEATURE_SET_VERSION

    store = FeatureStore()
    fv = store.get_or_compute("RELIANCE.NS")          # cache hit OR compute
    fvs = store.get_features_batch(["RELIANCE.NS", "TCS.NS"])
    store.invalidate("RELIANCE.NS")                    # after CSV refresh
"""
from .vectors import FeatureVector, FEATURE_KEYS
from .versioning import FEATURE_SET_VERSION
from .compute import compute_features
from .store import FeatureStore

__all__ = [
    "FeatureVector",
    "FEATURE_KEYS",
    "FEATURE_SET_VERSION",
    "compute_features",
    "FeatureStore",
]
