"""Compute one FeatureVector from a price-history DataFrame.

This wraps the existing hand-rolled indicators in `analysis/indicators.py`
into the canonical FeatureVector shape — no new math, just the contract
boundary between "raw indicators on a DataFrame" and "the typed feature
record every inference engine consumes".

Look-ahead-free guarantee
-------------------------
Callers must slice the DataFrame BEFORE calling `compute_features`:

    df = csv_store.load(symbol)
    df_at = df.loc[: as_of_date]                # slice first
    fv = compute_features(symbol, df_at, "EOD") # then compute

This is what enables OutcomeAgent (PR2) and any backtest to evaluate
historical signals using only data that was knowable at the time. The
function itself never reads beyond the slice it's given.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from ..analysis.indicators import compute_all
from ..analysis.patterns import detect_all
from ..analysis.regime import classify
from .vectors import FeatureVector
from .versioning import FEATURE_SET_VERSION

log = logging.getLogger(__name__)


def _f(value) -> Optional[float]:
    """Best-effort cast to float; returns None for NaN/None/non-numeric.

    The FeatureVector schema is `Optional[float]` everywhere because indicator
    warmup periods produce NaN tails (RSI-14 NaN for the first 14 rows,
    EMA-200 NaN for the first 200, etc.).
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(f) or np.isinf(f):
        return None
    return f


def _ratio_pct(numer, denom) -> Optional[float]:
    """`(numer / denom - 1) * 100`, defensive about zero/NaN."""
    n = _f(numer)
    d = _f(denom)
    if n is None or d is None or d == 0.0:
        return None
    return (n / d - 1.0) * 100.0


def compute_features(
    symbol: str,
    df: pd.DataFrame,
    timeframe: str = "EOD",
    *,
    as_of_date: Optional[str] = None,
) -> FeatureVector:
    """Build one FeatureVector from a (pre-sliced) price history.

    Args:
        symbol: ticker
        df: OHLCV DataFrame indexed by date. Must contain at least
            `open, high, low, close, volume` columns. Empty df → an
            all-None FeatureVector (the engines will skip it).
        timeframe: 'EOD' / 'INTRADAY_5M' / 'INTRADAY_15M' — used as a cache
            partition key and as the FeatureVector's `timeframe` field.
        as_of_date: ISO date string. Defaults to the last index of `df`.
            Override only for backtest snapshots when you want to label the
            vector by a specific historical date.

    Returns:
        FeatureVector with the current `FEATURE_SET_VERSION` stamped on it.
        On any failure (malformed df, indicator math blew up), returns a
        skeleton FeatureVector with only `symbol`, `as_of_date`, `timeframe`,
        and `feature_set_version` populated — callers can detect this by
        checking `fv.latest_close is None`.
    """
    if df is None or df.empty:
        return _empty_vector(symbol, as_of_date or "", timeframe)

    # Resolve as_of_date from the last row if not provided.
    if as_of_date is None:
        try:
            last_idx = df.index[-1]
            as_of_date = (
                last_idx.strftime("%Y-%m-%d")
                if hasattr(last_idx, "strftime")
                else str(last_idx)[:10]
            )
        except Exception:  # noqa: BLE001 — bad index shouldn't kill the cycle
            as_of_date = ""

    try:
        enriched = compute_all(df)
    except Exception:  # noqa: BLE001 — indicator math should never crash
        log.exception("compute_features: compute_all failed for %s", symbol)
        return _empty_vector(symbol, as_of_date, timeframe)

    if enriched.empty:
        return _empty_vector(symbol, as_of_date, timeframe)

    row = enriched.iloc[-1]

    # Pattern flags + regime are computed against the full enriched slice
    # (they're already look-ahead-safe because we only passed in df[: as_of]).
    try:
        patterns = {k: int(v) for k, v in detect_all(enriched).items()}
    except Exception:  # noqa: BLE001
        log.warning("compute_features: detect_all failed for %s", symbol)
        patterns = {}

    try:
        regime, _ = classify(enriched)
    except Exception:  # noqa: BLE001
        log.warning("compute_features: regime classify failed for %s", symbol)
        regime = None

    return FeatureVector(
        symbol=symbol,
        as_of_date=as_of_date,
        timeframe=timeframe,
        feature_set_version=FEATURE_SET_VERSION,
        ema20=_f(row.get("ema20")),
        ema50=_f(row.get("ema50")),
        ema200=_f(row.get("ema200")),
        rsi14=_f(row.get("rsi14")),
        macd=_f(row.get("macd")),
        macd_signal=_f(row.get("macd_signal")),
        macd_hist=_f(row.get("macd_hist")),
        adx=_f(row.get("adx")),
        plus_di=_f(row.get("+di")),
        minus_di=_f(row.get("-di")),
        atr14=_f(row.get("atr14")),
        atr_pct=_f(row.get("atr_pct")),
        bb_mid=_f(row.get("bb_mid")),
        bb_upper=_f(row.get("bb_upper")),
        bb_lower=_f(row.get("bb_lower")),
        bb_width=_f(row.get("bb_width")),
        obv=_f(row.get("obv")),
        vol_avg20=_f(row.get("vol_avg20")),
        vol_avg50=_f(row.get("vol_avg50")),
        vol_ratio=_f(row.get("vol_ratio")),
        high_252=_f(row.get("high_252")),
        low_252=_f(row.get("low_252")),
        pct_from_52w_high=_f(row.get("pct_from_52w_high")),
        pct_from_52w_low=_f(row.get("pct_from_52w_low")),
        return_5d=_f(row.get("return_5d")),
        return_20d=_f(row.get("return_20d")),
        return_60d=_f(row.get("return_60d")),
        pivot_p=_f(row.get("pivot_p")),
        pivot_r1=_f(row.get("pivot_r1")),
        pivot_r2=_f(row.get("pivot_r2")),
        pivot_r3=_f(row.get("pivot_r3")),
        pivot_s1=_f(row.get("pivot_s1")),
        pivot_s2=_f(row.get("pivot_s2")),
        pivot_s3=_f(row.get("pivot_s3")),
        pivot_distance_pct=_f(row.get("pivot_distance_pct")),
        ema20_vs_ema50=_ratio_pct(row.get("ema20"), row.get("ema50")),
        ema50_vs_ema200=_ratio_pct(row.get("ema50"), row.get("ema200")),
        close_vs_ema20=_ratio_pct(row.get("close"), row.get("ema20")),
        latest_close=_f(row.get("close")),
        latest_open=_f(row.get("open")),
        latest_high=_f(row.get("high")),
        latest_low=_f(row.get("low")),
        latest_volume=_f(row.get("volume")),
        pattern_flags=patterns,
        regime_label=regime,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


def _empty_vector(symbol: str, as_of_date: str, timeframe: str) -> FeatureVector:
    """Skeleton vector for failure / empty-input paths. Callers detect via
    `fv.latest_close is None`."""
    return FeatureVector(
        symbol=symbol,
        as_of_date=as_of_date,
        timeframe=timeframe,
        feature_set_version=FEATURE_SET_VERSION,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


__all__ = ["compute_features"]
