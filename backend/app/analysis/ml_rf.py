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
from ..analysis.signal_decision import decide_from_rally_probability
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


def chronological_split(meta: pd.DataFrame, boundaries: dict | None = None) -> tuple[dict, dict]:
    """Split common dates, excluding labels that reach the following partition."""
    if meta.empty or meta[["date", "label_end"]].isna().any().any():
        raise ValueError("Evaluation requires nonempty dates and label-end dates.")
    if meta.duplicated(["symbol", "date"]).any():
        raise ValueError("Duplicate symbol/date samples cannot be evaluated.")
    if (meta["label_end"] <= meta["date"]).any():
        raise ValueError("Every label must end after its feature date.")
    days = sorted(meta["date"].unique())
    if boundaries is None:
        if len(days) < 30:
            raise ValueError("At least 30 unique mature dates are required.")
        boundaries = {
            "train_start": pd.Timestamp(days[0]).isoformat(),
            "validation_start": pd.Timestamp(days[int(len(days) * .6)]).isoformat(),
            "test_start": pd.Timestamp(days[int(len(days) * .8)]).isoformat(),
            "test_end": pd.Timestamp(days[-1]).isoformat(),
            "label_end_max": pd.Timestamp(meta["label_end"].max()).isoformat(),
        }
    start, validation, test, end, label_end = (
        pd.Timestamp(boundaries[key]) for key in
        ("train_start", "validation_start", "test_start", "test_end", "label_end_max")
    )
    if not start < validation < test <= end < label_end:
        raise ValueError("Invalid chronological boundaries.")
    eligible = (meta["date"] >= start) & (meta["date"] <= end) & (meta["label_end"] <= label_end)
    masks = {
        "train": eligible & (meta["date"] < validation) & (meta["label_end"] < validation),
        "validation": eligible & (meta["date"] >= validation) & (meta["date"] < test)
                      & (meta["label_end"] < test),
        "test": eligible & (meta["date"] >= test),
    }
    indices = {name: np.flatnonzero(mask.to_numpy()) for name, mask in masks.items()}
    if any(len(idx) == 0 for idx in indices.values()):
        raise ValueError("An evaluation partition is empty after label purging.")
    return indices, boundaries


def evaluation_metrics(y: np.ndarray, probability: np.ndarray, base_rate: float) -> dict:
    """Use the existing LONG threshold; a negative label is not a short outcome."""
    from sklearn.metrics import (average_precision_score, brier_score_loss,
                                 confusion_matrix, log_loss, precision_score,
                                 recall_score, f1_score, roc_auc_score)

    predicted = probability >= .5
    both_classes = len(np.unique(y)) == 2
    baseline = np.full(len(y), base_rate)
    return {
        "rows": len(y), "positives": int(y.sum()), "positive_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, probability)) if both_classes else None,
        "average_precision": float(average_precision_score(y, probability)) if both_classes else None,
        "brier": float(brier_score_loss(y, probability)),
        "baseline_brier": float(brier_score_loss(y, baseline)),
        "log_loss": float(log_loss(y, probability, labels=[0, 1])),
        "baseline_log_loss": float(log_loss(y, baseline, labels=[0, 1])),
        "threshold": .5, "accuracy": float(np.mean(predicted == y)),
        "always_negative_accuracy": float(1 - y.mean()),
        "precision": float(precision_score(y, predicted, zero_division=0)),
        "recall": float(recall_score(y, predicted, zero_division=0)),
        "f1": float(f1_score(y, predicted, zero_division=0)),
        "predicted_positive": int(predicted.sum()),
        "confusion_matrix": confusion_matrix(y, predicted, labels=[0, 1]).tolist(),
        "undefined_ranking_metrics": not both_classes,
    }


def train(progress_cb: Optional[Callable[[float, str], None]] = None, *,
          save_model: bool = True) -> Dict:
    """Fit on earlier dates only; report validation and a reserved future test.

    save_model=False writes evaluation files without replacing inference artifacts.
    Boundaries persist across reruns so a former holdout cannot slide into training.
    """
    from datetime import datetime, timezone
    import hashlib
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    import sklearn
    from ..analysis.ml_dataset import build_feature_matrix, FEATURE_COLS, FORWARD_DAYS, LABEL_THRESHOLD

    def _cb(pct: float, msg: str = "") -> None:
        if progress_cb:
            progress_cb(pct, msg)

    _cb(.02, "Building feature matrix from CSVs...")
    X_full, meta = build_feature_matrix()
    if X_full.empty:
        raise RuntimeError("No training data - run data refresh first.")
    if len(X_full) != len(meta) or not np.array_equal(X_full["label"], meta["label"]):
        raise ValueError("Features and sample metadata are not aligned.")
    order = meta.sort_values(["date", "symbol"], kind="stable").index
    X_full, meta = X_full.loc[order].reset_index(drop=True), meta.loc[order].reset_index(drop=True)
    X, y = X_full[FEATURE_COLS], X_full["label"].to_numpy()
    evaluation_dir = _model_dir() / "rf_evaluation"
    evaluation_dir.mkdir(exist_ok=True)
    split_path = evaluation_dir / "split.json"
    # Exclusive creation preserves the original boundaries, including on concurrent calls.
    try:
        with split_path.open("r", encoding="utf-8") as fh:
            boundaries = json.load(fh)
    except FileNotFoundError:
        _, proposed = chronological_split(meta)
        try:
            with split_path.open("x", encoding="utf-8") as fh:
                json.dump(proposed, fh, indent=2)
        except FileExistsError:
            pass
        with split_path.open("r", encoding="utf-8") as fh:
            boundaries = json.load(fh)
    partitions, boundaries = chronological_split(meta, boundaries)
    tr = partitions["train"]
    if len(np.unique(y[tr])) != 2:
        raise ValueError("Training requires both target classes after purging.")
    params = dict(n_estimators=400, max_depth=14, min_samples_leaf=40,
                  max_features="sqrt", n_jobs=-1, random_state=42)
    _cb(.30, f"Fitting unchanged RF configuration on {len(tr):,} training rows...")
    final = RandomForestClassifier(**params)
    final.fit(X.iloc[tr], y[tr])
    base_rate = float(y[tr].mean())
    metrics, split_summary, prediction_frames = {}, {}, []
    for name, idx in partitions.items():
        part = meta.iloc[idx]
        split_summary[name] = {
            "rows": len(idx), "dates": int(part["date"].nunique()),
            "date_start": part["date"].min().date().isoformat(),
            "date_end": part["date"].max().date().isoformat(),
            "label_end_max": part["label_end"].max().date().isoformat(),
            "positive_rate": float(y[idx].mean()),
        }
        if name == "train":
            continue
        _cb(.65 if name == "validation" else .80, f"Evaluating {name}; no refitting or threshold tuning...")
        probability = final.predict_proba(X.iloc[idx])[:, 1]
        metrics[name] = evaluation_metrics(y[idx], probability, base_rate)
        predictions = part.copy()
        predictions["probability"] = probability
        predictions["partition"] = name
        prediction_frames.append(predictions)
    fi_pairs = sorted(zip(FEATURE_COLS, final.feature_importances_), key=lambda pair: -pair[1])
    fingerprint = hashlib.sha256(
        pd.util.hash_pandas_object(pd.concat([meta, X], axis=1), index=False).values.tobytes()
    ).hexdigest()
    meta_dict = {
        "evaluation_version": 1, "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_cols": FEATURE_COLS, "model_kind": "random_forest",
        "target": {"forward_days": FORWARD_DAYS, "return_threshold": LABEL_THRESHOLD},
        "model_params": params, "sklearn_version": sklearn.__version__,
        "dataset_sha256": fingerprint, "dataset_rows": len(X), "train_rows": len(tr),
        "positive_rate": base_rate, "top_features": [f for f, _ in fi_pairs[:10]],
        "boundaries": boundaries, "splits": split_summary,
        "excluded_rows": len(X) - sum(len(idx) for idx in partitions.values()),
        "validation_metrics": metrics["validation"], "test_metrics": metrics["test"],
        "test_auc": metrics["test"]["roc_auc"],
        "inference_artifact_updated": save_model,
        "limitations": [
            "Retrospective holdout for this fresh fit; the prior model used historical holdout dates.",
            "Current cached universe and adjusted prices retain survivorship and revision risks.",
            "Test results must not guide tuning; repeated inspection is not a new independent test.",
            "Rows share dates and overlapping five-session outcomes; counts are not independent trials.",
        ],
        "disclaimer": "Research and decision-support only. Not financial advice.",
    }
    _cb(.92, "Saving evaluation report and held-out predictions...")
    pd.concat(prediction_frames, ignore_index=True).to_csv(evaluation_dir / "predictions.csv", index=False)
    with (evaluation_dir / "metrics.json").open("w", encoding="utf-8") as fh:
        json.dump(meta_dict, fh, indent=2, allow_nan=False)
    if save_model:
        joblib.dump(final, _PKL_PATH)
        with _META_PATH.open("w", encoding="utf-8") as fh:
            json.dump(meta_dict, fh, indent=2, allow_nan=False)
        global _MODEL, _FEATURE_COLS
        _MODEL, _FEATURE_COLS = final, FEATURE_COLS[:]
    _cb(1.0, f"Done - held-out test AUC {meta_dict['test_auc']}")
    log.info("Random Forest chronological evaluation complete: test AUC %s", meta_dict["test_auc"])
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
        # predict_proba[:, 1] is P(+3% in 5d), not a short score.
        direction, veto = decide_from_rally_probability(prob, regime)

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
        if veto:
            top_factors = [veto, *top_factors][:5]

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
