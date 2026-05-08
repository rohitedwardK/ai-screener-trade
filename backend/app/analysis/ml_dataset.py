"""Shared ML feature-matrix builder for the Method Analysis demo.

Iterates all cached CSV files, computes indicators once per symbol, and
produces a flat feature matrix suitable for both the Random-Forest and
LSTM trainers.  The label is a 5-day forward return threshold — no
look-ahead: each row i uses only df[:i+1] for indicator computation,
and df[i+FORWARD_DAYS] for the label.

Public API
----------
build_feature_matrix(symbols, forward_days, threshold) -> (X, meta)
build_sequence_matrix(symbols, window, forward_days, threshold)  -> (X_seq, y_seq)
FEATURE_COLS                    ordered list of numeric columns in X
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from ..analysis.indicators import compute_all
from ..analysis.patterns import detect_all
from ..analysis.regime import REGIMES, classify
from ..data import csv_store

log = logging.getLogger(__name__)

FORWARD_DAYS: int = 5
LABEL_THRESHOLD: float = 0.03   # +3 % in 5 trading days → label=1

# Ordered list kept stable so model artifacts always match inference.
FEATURE_COLS: List[str] = [
    "rsi14",
    "macd",
    "macd_signal",
    "macd_hist",
    "adx",
    "plus_di",
    "minus_di",
    "ema20_vs_ema50",
    "ema50_vs_ema200",
    "close_vs_ema20",
    "atr_pct",
    "bb_width",
    "pct_from_52w_high",
    "vol_ratio",
    "return_5d",
    "return_20d",
    "return_60d",
    "pat_breakout_20d",
    "pat_breakout_55d",
    "pat_pullback",
    "pat_oversold_bounce",
    "pat_bullish_engulfing",
    "pat_bearish_engulfing",
    "pat_hammer",
    "pat_volume_surge",
    # Regime one-hot columns appended last
    *[f"regime_{r}" for r in REGIMES],
]


def _feature_row(df_enriched: pd.DataFrame, i: int) -> dict:
    """Build one feature dict from row i of an already-enriched DataFrame."""
    row = df_enriched.iloc[i]

    ema20 = row.get("ema20")
    ema50 = row.get("ema50")
    ema200 = row.get("ema200")
    close = row.get("close")

    ema20_vs_ema50 = (
        (float(ema20) / float(ema50) - 1.0) * 100.0
        if pd.notna(ema20) and pd.notna(ema50) and float(ema50) != 0
        else None
    )
    ema50_vs_ema200 = (
        (float(ema50) / float(ema200) - 1.0) * 100.0
        if pd.notna(ema50) and pd.notna(ema200) and float(ema200) != 0
        else None
    )
    close_vs_ema20 = (
        (float(close) / float(ema20) - 1.0) * 100.0
        if pd.notna(close) and pd.notna(ema20) and float(ema20) != 0
        else None
    )

    # Pattern flags require a slice up to row i — call detect_all on the slice.
    pat = detect_all(df_enriched.iloc[: i + 1])
    regime, _ = classify(df_enriched.iloc[: i + 1])

    feat: dict = {
        "rsi14": _safe(row.get("rsi14")),
        "macd": _safe(row.get("macd")),
        "macd_signal": _safe(row.get("macd_signal")),
        "macd_hist": _safe(row.get("macd_hist")),
        "adx": _safe(row.get("adx")),
        "plus_di": _safe(row.get("+di")),
        "minus_di": _safe(row.get("-di")),
        "ema20_vs_ema50": ema20_vs_ema50,
        "ema50_vs_ema200": ema50_vs_ema200,
        "close_vs_ema20": close_vs_ema20,
        "atr_pct": _safe(row.get("atr_pct")),
        "bb_width": _safe(row.get("bb_width")),
        "pct_from_52w_high": _safe(row.get("pct_from_52w_high")),
        "vol_ratio": _safe(row.get("vol_ratio")),
        "return_5d": _safe(row.get("return_5d")),
        "return_20d": _safe(row.get("return_20d")),
        "return_60d": _safe(row.get("return_60d")),
        "pat_breakout_20d": int(pat["breakout_20d"]),
        "pat_breakout_55d": int(pat["breakout_55d"]),
        "pat_pullback": int(pat["pullback"]),
        "pat_oversold_bounce": int(pat["oversold_bounce"]),
        "pat_bullish_engulfing": int(pat["bullish_engulfing"]),
        "pat_bearish_engulfing": int(pat["bearish_engulfing"]),
        "pat_hammer": int(pat["hammer"]),
        "pat_volume_surge": int(pat["volume_surge"]),
    }
    for r in REGIMES:
        feat[f"regime_{r}"] = int(regime == r)

    return feat


def _safe(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_feature_matrix(
    symbols: Optional[List[str]] = None,
    forward_days: int = FORWARD_DAYS,
    threshold: float = LABEL_THRESHOLD,
    warmup: int = 210,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (X, meta) where X contains FEATURE_COLS and meta has symbol/date/forward_return.

    Rows where any feature is NaN are dropped.  `warmup` controls the minimum
    number of leading rows to skip so EMA-200 and 52-week range are fully warm.
    """
    if symbols is None:
        symbols = csv_store.list_cached_symbols()

    all_feats: List[dict] = []
    all_meta: List[dict] = []

    for sym in symbols:
        df_raw = csv_store.load(sym)
        if len(df_raw) < warmup + forward_days + 1:
            log.debug("Skipping %s — insufficient history (%d rows)", sym, len(df_raw))
            continue

        df = compute_all(df_raw)

        for i in range(warmup, len(df) - forward_days):
            future_close = float(df.iloc[i + forward_days]["close"])
            current_close = float(df.iloc[i]["close"])
            if current_close <= 0:
                continue
            fwd_ret = (future_close - current_close) / current_close
            label = int(fwd_ret >= threshold)

            feat = _feature_row(df, i)
            feat["label"] = label
            all_feats.append(feat)
            all_meta.append({
                "symbol": sym,
                "date": df.index[i],
                "forward_return": fwd_ret,
                "label": label,
            })

        log.debug("Built %d rows for %s", len(df) - warmup - forward_days, sym)

    if not all_feats:
        return pd.DataFrame(columns=FEATURE_COLS + ["label"]), pd.DataFrame()

    full = pd.DataFrame(all_feats)
    meta = pd.DataFrame(all_meta)

    # Drop rows with any NaN feature — warmup rows that still have None fields.
    mask = full[FEATURE_COLS].notna().all(axis=1)
    X = full.loc[mask, FEATURE_COLS + ["label"]].reset_index(drop=True)
    meta = meta.loc[mask].reset_index(drop=True)

    log.info(
        "Dataset built: %d rows, %d features, %.1f%% positive",
        len(X), len(FEATURE_COLS), X["label"].mean() * 100,
    )
    return X, meta


def build_sequence_matrix(
    symbols: Optional[List[str]] = None,
    window: int = 20,
    forward_days: int = FORWARD_DAYS,
    threshold: float = LABEL_THRESHOLD,
    warmup: int = 210,
    seq_features: Optional[List[str]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (X_seq, y) for LSTM training.

    X_seq shape: (N, window, len(seq_features))
    y shape: (N,)

    `seq_features` defaults to the 6 most time-relevant numeric columns
    that work well as sequences.  Pattern-flag columns are omitted because
    they are computed on a rolling window and would introduce redundancy.
    """
    if seq_features is None:
        seq_features = [
            "rsi14",
            "macd_hist",
            "vol_ratio",
            "atr_pct",
            "close_vs_ema20",
            "return_5d",
        ]

    if symbols is None:
        symbols = csv_store.list_cached_symbols()

    X_list: List[np.ndarray] = []
    y_list: List[int] = []

    for sym in symbols:
        df_raw = csv_store.load(sym)
        min_rows = warmup + window + forward_days + 1
        if len(df_raw) < min_rows:
            continue

        df = compute_all(df_raw)

        # Pre-compute the derived ratio columns used in seq_features
        ema20 = df["ema20"]
        close = df["close"]
        df = df.copy()
        df["close_vs_ema20"] = ((close / ema20.replace(0, float("nan"))) - 1.0) * 100.0

        for i in range(warmup + window, len(df) - forward_days):
            window_slice = df.iloc[i - window: i][seq_features]
            if window_slice.isnull().any().any():
                continue
            future_close = float(df.iloc[i + forward_days]["close"])
            current_close = float(df.iloc[i]["close"])
            if current_close <= 0:
                continue
            fwd_ret = (future_close - current_close) / current_close
            label = int(fwd_ret >= threshold)

            X_list.append(window_slice.values.astype(np.float32))
            y_list.append(label)

    if not X_list:
        return np.empty((0, window, len(seq_features)), dtype=np.float32), np.empty(0)

    X_seq = np.stack(X_list, axis=0)   # (N, window, features)
    y = np.array(y_list, dtype=np.int64)
    log.info(
        "Sequence dataset: %d samples, window=%d, features=%d, %.1f%% positive",
        len(y), window, len(seq_features), y.mean() * 100,
    )
    return X_seq, y


# Expose seq feature names so LSTM trainer and inference use the same list.
SEQ_FEATURE_COLS: List[str] = [
    "rsi14",
    "macd_hist",
    "vol_ratio",
    "atr_pct",
    "close_vs_ema20",
    "return_5d",
]
