"""FeatureVector — the canonical per-symbol feature contract.

One immutable record per (symbol, as_of_date, timeframe). Inference engines
(rule, RF/GBM, LSTM) read these instead of recomputing indicators per cycle.

Design notes
------------
* Frozen dataclass: cheap to hash, safe to share across threads, naturally
  serialisable (the LRU cache keys on identity but the cold cache stores
  `to_dict()` output).
* `latest_close` is included so engines that only need the price for stop /
  invalidation math don't have to reload the CSV. The "raw data is forbidden
  to LLM" rule applies only to the LLM context (PR1's LLMContextBuilder); the
  L2 inference layer is allowed to see the latest_close because that's a
  feature, not a "candle".
* `regime_label` and `pattern_flags` are computed at the same time because
  they need the full enriched DataFrame anyway — pulling them in keeps the
  store as the *single* indicator-aware module.
* Everything is `Optional[float]` because real OHLCV slices have NaN tails
  for indicators that need warmup (EMA-200 is undefined for the first 200
  rows, RSI-14 for the first 14, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict
from typing import Any, Dict, List, Optional


# Ordered list — used by tests + the schema-validation guard in LLMContextBuilder
# to assert no raw-data fields ever leak into the LLM payload.
FEATURE_KEYS: List[str] = [
    # raw indicators
    "ema20", "ema50", "ema200",
    "rsi14",
    "macd", "macd_signal", "macd_hist",
    "adx", "plus_di", "minus_di",
    "atr14", "atr_pct",
    "bb_mid", "bb_upper", "bb_lower", "bb_width",
    "obv",
    "vol_avg20", "vol_avg50", "vol_ratio",
    # range / 52w
    "high_252", "low_252", "pct_from_52w_high", "pct_from_52w_low",
    # returns
    "return_5d", "return_20d", "return_60d",
    # pivots (computed from previous day's H/L/C — already look-ahead-safe in
    # `analysis.pivots.compute_pivot_columns`)
    "pivot_p", "pivot_r1", "pivot_r2", "pivot_r3",
    "pivot_s1", "pivot_s2", "pivot_s3",
    "pivot_distance_pct",
    # derived (computed from raw indicators — comparable across symbols)
    "ema20_vs_ema50", "ema50_vs_ema200", "close_vs_ema20",
    # latest OHLC for engines that need it for stop / invalidation math
    "latest_close", "latest_open", "latest_high", "latest_low", "latest_volume",
]


@dataclass(frozen=True)
class FeatureVector:
    """All numeric features for one symbol at one as_of point.

    `pattern_flags` and `regime_label` are non-numeric and live as separate
    fields so the FEATURE_KEYS list above stays the authoritative numeric
    feature contract that ML models consume (their column order must be
    deterministic across train and inference).
    """

    symbol: str
    as_of_date: str                            # ISO YYYY-MM-DD
    timeframe: str                             # 'EOD' | 'INTRADAY_5M' | 'INTRADAY_15M'
    feature_set_version: str                   # auto-versioned hash from `versioning.py`

    # raw indicators
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    ema200: Optional[float] = None
    rsi14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    adx: Optional[float] = None
    plus_di: Optional[float] = None
    minus_di: Optional[float] = None
    atr14: Optional[float] = None
    atr_pct: Optional[float] = None
    bb_mid: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_width: Optional[float] = None
    obv: Optional[float] = None
    vol_avg20: Optional[float] = None
    vol_avg50: Optional[float] = None
    vol_ratio: Optional[float] = None
    high_252: Optional[float] = None
    low_252: Optional[float] = None
    pct_from_52w_high: Optional[float] = None
    pct_from_52w_low: Optional[float] = None
    return_5d: Optional[float] = None
    return_20d: Optional[float] = None
    return_60d: Optional[float] = None
    pivot_p: Optional[float] = None
    pivot_r1: Optional[float] = None
    pivot_r2: Optional[float] = None
    pivot_r3: Optional[float] = None
    pivot_s1: Optional[float] = None
    pivot_s2: Optional[float] = None
    pivot_s3: Optional[float] = None
    pivot_distance_pct: Optional[float] = None

    # derived (cross-symbol-comparable ratios)
    ema20_vs_ema50: Optional[float] = None
    ema50_vs_ema200: Optional[float] = None
    close_vs_ema20: Optional[float] = None

    # latest OHLC — needed by engines for stop / target / invalidation math.
    # Distinct from "raw OHLCV history" which the LLM never sees.
    latest_close: Optional[float] = None
    latest_open: Optional[float] = None
    latest_high: Optional[float] = None
    latest_low: Optional[float] = None
    latest_volume: Optional[float] = None

    # qualitative annotations (also safe to expose to L2 engines).
    pattern_flags: Dict[str, int] = field(default_factory=dict)
    regime_label: Optional[str] = None

    # provenance — `computed_at` is ISO UTC, useful for staleness checks
    # in HealthAgent (not yet wired in PR1, but field exists).
    computed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable dict (used by the cold cache + tests)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "FeatureVector":
        """Inverse of `to_dict`. Tolerant of extra keys (forward-compat with
        future schema additions) — only known fields are passed through."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})

    def numeric_features(self) -> Dict[str, Optional[float]]:
        """Just the numeric feature columns, in `FEATURE_KEYS` order. ML
        engines feed this dict (or its values) into their predict path."""
        d = self.to_dict()
        return {k: d.get(k) for k in FEATURE_KEYS}


__all__ = ["FeatureVector", "FEATURE_KEYS"]
