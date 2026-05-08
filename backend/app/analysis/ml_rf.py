"""Random Forest (bagging) for the Method Analysis demo.

Trains `RandomForestClassifier` on the shared feature matrix — independent of
`ml_gbm.py` (gradient boosting) so both can be compared on the same labels.

Artifacts: `backend/data/models/signal_ranker_rf.pkl` + `signal_ranker_rf_meta.json`.

Note: An older project version stored a GBM in this path; re-train after upgrade
if you need a pure RF artefact.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from ..analysis.indicators import compute_all
from ..analysis.patterns import detect_all
from ..analysis.regime import REGIMES, classify
from ..data import csv_store

log = logging.getLogger(__name__)

_MODEL_DIR = Path(__file__).parent.parent.parent / "data" / "models"
_PKL_PATH = _MODEL_DIR / "signal_ranker_rf.pkl"
_META_PATH = _MODEL_DIR / "signal_ranker_rf_meta.json"

_FEATURE_COLS: List[str] = []
_MODEL = None


def is_ready() -> bool:
    return _PKL_PATH.exists() and _META_PATH.exists()


def _model_dir() -> Path:
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    return _MODEL_DIR


def train(progress_cb: Optional[Callable[[float, str], None]] = None) -> Dict:
    """Train Random Forest on all cached CSVs."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import roc_auc_score
    import joblib

    from ..analysis.ml_dataset import build_feature_matrix, FEATURE_COLS

    def _cb(pct: float, msg: str = "") -> None:
        if progress_cb:
            progress_cb(pct, msg)

    _cb(0.02, "Building feature matrix from CSVs…")
    X_full, _meta = build_feature_matrix()

    if X_full.empty:
        raise RuntimeError("No training data — run data refresh first.")

    y = X_full["label"]
    X = X_full[FEATURE_COLS]

    _cb(0.25, f"Dataset ready: {len(X):,} rows, {len(FEATURE_COLS)} features")

    tscv = TimeSeriesSplit(n_splits=3)
    aucs: List[float] = []
    n_jobs_rf = -1
    for fold, (tr_idx, te_idx) in enumerate(tscv.split(X)):
        X_tr, X_te = X.iloc[tr_idx], X.iloc[te_idx]
        y_tr, y_te = y.iloc[tr_idx], y.iloc[te_idx]
        m = RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            min_samples_leaf=50,
            max_features="sqrt",
            n_jobs=n_jobs_rf,
            random_state=42,
        )
        m.fit(X_tr, y_tr)
        fold_auc = roc_auc_score(y_te, m.predict_proba(X_te)[:, 1])
        aucs.append(fold_auc)
        _cb(0.25 + 0.20 * (fold + 1), f"CV fold {fold + 1}/3 → AUC {fold_auc:.3f}")

    mean_auc = float(np.mean(aucs))
    _cb(0.70, f"CV mean AUC {mean_auc:.3f} — training final model…")

    final = RandomForestClassifier(
        n_estimators=400,
        max_depth=14,
        min_samples_leaf=40,
        max_features="sqrt",
        n_jobs=n_jobs_rf,
        random_state=42,
    )
    final.fit(X, y)

    _cb(0.92, "Saving artefact…")
    _model_dir()
    joblib.dump(final, _PKL_PATH)

    fi_pairs = sorted(
        zip(FEATURE_COLS, final.feature_importances_),
        key=lambda x: -x[1],
    )

    meta_dict = {
        "feature_cols": FEATURE_COLS,
        "mean_auc": mean_auc,
        "fold_aucs": aucs,
        "train_rows": len(X),
        "positive_rate": float(y.mean()),
        "top_features": [f for f, _ in fi_pairs[:10]],
        "model_kind": "random_forest",
    }
    with open(_META_PATH, "w") as fh:
        json.dump(meta_dict, fh, indent=2)

    global _MODEL, _FEATURE_COLS
    _MODEL = final
    _FEATURE_COLS = FEATURE_COLS[:]

    _cb(1.0, f"Done — AUC {mean_auc:.3f}")
    log.info("Random Forest saved (AUC %.3f, %d rows)", mean_auc, len(X))
    return meta_dict


def _load() -> None:
    global _MODEL, _FEATURE_COLS
    if _MODEL is not None:
        return
    if not is_ready():
        raise RuntimeError("Model not trained yet — call train() first.")
    import joblib

    _MODEL = joblib.load(_PKL_PATH)
    with open(_META_PATH) as fh:
        _FEATURE_COLS = json.load(fh)["feature_cols"]
    log.info("Random Forest loaded from %s", _PKL_PATH)


def _build_latest_row(symbol: str) -> Optional[pd.DataFrame]:
    df_raw = csv_store.load(symbol)
    if len(df_raw) < 210:
        return None
    df = compute_all(df_raw)

    row = df.iloc[-1]
    ema20 = row.get("ema20")
    ema50 = row.get("ema50")
    ema200 = row.get("ema200")
    close_val = row.get("close")

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
        (float(close_val) / float(ema20) - 1.0) * 100.0
        if pd.notna(close_val) and pd.notna(ema20) and float(ema20) != 0
        else None
    )

    pat = detect_all(df)
    regime, _ = classify(df)

    feat: dict = {
        "rsi14": _sf(row.get("rsi14")),
        "macd": _sf(row.get("macd")),
        "macd_signal": _sf(row.get("macd_signal")),
        "macd_hist": _sf(row.get("macd_hist")),
        "adx": _sf(row.get("adx")),
        "plus_di": _sf(row.get("+di")),
        "minus_di": _sf(row.get("-di")),
        "ema20_vs_ema50": ema20_vs_ema50,
        "ema50_vs_ema200": ema50_vs_ema200,
        "close_vs_ema20": close_vs_ema20,
        "atr_pct": _sf(row.get("atr_pct")),
        "bb_width": _sf(row.get("bb_width")),
        "pct_from_52w_high": _sf(row.get("pct_from_52w_high")),
        "vol_ratio": _sf(row.get("vol_ratio")),
        "return_5d": _sf(row.get("return_5d")),
        "return_20d": _sf(row.get("return_20d")),
        "return_60d": _sf(row.get("return_60d")),
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

    feat["_close"] = float(close_val) if close_val else 0.0
    feat["_regime"] = regime

    return pd.DataFrame([feat]), df


def _sf(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def infer(
    symbols: Optional[List[str]] = None,
    name_map: Optional[Dict[str, str]] = None,
    top_k: int = 15,
) -> List[dict]:
    """Run inference on the latest bar for each symbol."""
    _load()

    if symbols is None:
        symbols = csv_store.list_cached_symbols()

    with open(_META_PATH) as fh:
        meta = json.load(fh)
    top_features: List[str] = meta.get("top_features", _FEATURE_COLS[:5])

    cards: List[dict] = []
    for sym in symbols:
        result = _build_latest_row(sym)
        if result is None:
            continue
        feat_df, _df_full = result
        X = feat_df[_FEATURE_COLS]
        if X.isnull().any().any():
            continue

        prob = float(_MODEL.predict_proba(X)[0, 1])
        close_val = float(feat_df["_close"].iloc[0])
        regime = str(feat_df["_regime"].iloc[0])
        macd_hist = _sf(feat_df["macd_hist"].iloc[0]) or 0.0
        direction = "LONG" if prob >= 0.5 else ("SHORT" if prob < 0.35 else "NEUTRAL")

        factor_map = {
            "rsi14": f"RSI {_sf(feat_df['rsi14'].iloc[0]):.0f}" if _sf(feat_df.get("rsi14", pd.Series([None])).iloc[0]) else "RSI",
            "macd_hist": f"MACD hist {'▲' if macd_hist > 0 else '▼'} {macd_hist:+.3f}",
            "vol_ratio": f"Volume {_sf(feat_df['vol_ratio'].iloc[0]):.1f}x avg" if _sf(feat_df["vol_ratio"].iloc[0]) else "Volume",
            "atr_pct": f"ATR {_sf(feat_df['atr_pct'].iloc[0]):.1f}%" if _sf(feat_df["atr_pct"].iloc[0]) else "ATR",
            "return_20d": f"20d return {_sf(feat_df['return_20d'].iloc[0]):.1f}%" if _sf(feat_df["return_20d"].iloc[0]) else "20d return",
            "ema20_vs_ema50": f"EMA20/50 {_sf(feat_df['ema20_vs_ema50'].iloc[0]):+.1f}%" if _sf(feat_df["ema20_vs_ema50"].iloc[0]) else "EMA stack",
            "adx": f"ADX {_sf(feat_df['adx'].iloc[0]):.0f}" if _sf(feat_df["adx"].iloc[0]) else "ADX",
            "pct_from_52w_high": f"{_sf(feat_df['pct_from_52w_high'].iloc[0]):.1f}% from 52w high" if _sf(feat_df["pct_from_52w_high"].iloc[0]) else "52w high",
            "return_5d": f"5d return {_sf(feat_df['return_5d'].iloc[0]):.1f}%" if _sf(feat_df["return_5d"].iloc[0]) else "5d return",
            "bb_width": f"BB width {_sf(feat_df['bb_width'].iloc[0]):.3f}" if _sf(feat_df["bb_width"].iloc[0]) else "BB width",
        }
        top_factors = [factor_map[f] for f in top_features if f in factor_map][:5]

        cards.append({
            "symbol": sym,
            "name": (name_map or {}).get(sym),
            "confidence": round(prob, 3),
            "direction": direction,
            "category": None,
            "regime": regime,
            "close": close_val,
            "top_factors": top_factors,
        })

    cards.sort(key=lambda c: -c["confidence"])
    return cards[:top_k]
