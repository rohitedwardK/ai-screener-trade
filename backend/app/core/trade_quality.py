"""Local research archive training and calibrated quality inference."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import logging
import os
from pathlib import Path
import tempfile
import threading
import time

import numpy as np
import pandas as pd

from ..analysis import ml_quality as quality
from ..data import csv_store, repository as repo
from ..db import session_scope
from .universe import all_symbols

log = logging.getLogger(__name__)
ARTIFACT = Path(__file__).resolve().parents[2] / "data/models/trade_quality_rf.pkl"
_LOCK = threading.Lock()
_STATE = {"status": "idle", "message": "No quality training run yet"}


@lru_cache(maxsize=1)
def _diagnostics(minute: int) -> dict:
    with session_scope() as db:
        payloads = repo.quality_observations(db)
    days = {quality.observation_dates(p)[1] for p in payloads}
    return {"archive_observations": len(payloads), "archive_dates": len(days),
            "required_dates": 30, "coverage": csv_store.history_coverage(all_symbols())}


@lru_cache(maxsize=1)
def _load(path: str, modified: int) -> dict:
    import joblib
    return joblib.load(path)


def model() -> dict | None:
    if not ARTIFACT.exists():
        return None
    return _load(str(ARTIFACT), ARTIFACT.stat().st_mtime_ns)


def status() -> dict:
    with _LOCK:
        state = dict(_STATE)
    artifact = model()
    if state["status"] == "idle" and artifact:
        state = {"status": "ready" if artifact["metadata"]["usable"] else "insufficient_skill",
                 "message": "Saved quality model loaded"}
    return {**state, "model": artifact["metadata"] if artifact else None,
            "target": quality.TARGET, "disclaimer": quality.DISCLAIMER,
            "data": _diagnostics(int(time.time() // 60))}


def build_dataset(payloads: list[dict]) -> tuple[list[dict], pd.DataFrame]:
    rows, metadata, cache = [], [], {}
    today = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
    for payload in payloads:
        symbol = payload["symbol"]
        if symbol not in cache:
            cache[symbol] = csv_store.load(symbol).sort_index()
        raw = cache[symbol]
        feature_day, day = quality.observation_dates(payload)
        if feature_day >= today:
            continue
        future = raw.loc[(raw.index > day) & (raw.index < today)].head(quality.HORIZON)
        if len(future) < quality.HORIZON:
            continue
        feat = quality.features(payload, raw)
        if feat is None:
            continue
        label = quality.outcome(payload, future)
        if label is None:
            continue
        rows.append(feat)
        metadata.append({"date": day, "label_end": future.index[-1], "label": label,
                         "symbol": symbol, "verified": bool(payload.get("verification"))})
    return rows, pd.DataFrame(metadata)


def fit(rows: list[dict], meta: pd.DataFrame) -> dict:
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score

    if len(rows) < 100:
        raise ValueError(f"Insufficient data: {len(rows)} mature samples; at least 100 required.")
    train, calibration, test = quality.chronological_split(meta)
    y = meta["label"].to_numpy()
    for name, indices in (("training", train), ("calibration", calibration), ("test", test)):
        counts = np.bincount(y[indices], minlength=2)
        if min(counts) < 5:
            raise ValueError(f"Insufficient data: {name} needs at least 5 examples of each outcome after date purging.")
    vectorizer = DictVectorizer(sparse=False)
    X_train = vectorizer.fit_transform([rows[i] for i in train])
    forest = RandomForestClassifier(n_estimators=200, max_depth=6, min_samples_leaf=10,
                                    random_state=42, n_jobs=1)
    forest.fit(X_train, y[train])
    cal_prob = forest.predict_proba(vectorizer.transform([rows[i] for i in calibration]))[:, 1]
    calibrator = LogisticRegression(random_state=42)
    calibrator.fit(cal_prob.reshape(-1, 1), y[calibration])
    test_prob = forest.predict_proba(vectorizer.transform([rows[i] for i in test]))[:, 1]
    probabilities = calibrator.predict_proba(test_prob.reshape(-1, 1))[:, 1]
    brier = float(brier_score_loss(y[test], probabilities))
    baseline = float(brier_score_loss(y[test], np.full(len(test), y[train].mean())))
    metadata = {
        "version": 1, "model_kind": "calibrated_random_forest", "target": quality.TARGET,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "samples": len(rows), "train_rows": len(train), "calibration_rows": len(calibration),
        "test_rows": len(test), "verified_samples": int(meta["verified"].sum()),
        "test_auc": float(roc_auc_score(y[test], probabilities)),
        "test_brier": brier, "baseline_brier": baseline,
        "usable": brier < baseline,
        "label_end": pd.Timestamp(meta["label_end"].max()).date().isoformat(),
        "disclaimer": quality.DISCLAIMER,
    }
    return {"vectorizer": vectorizer, "forest": forest, "calibrator": calibrator, "metadata": metadata}


def train(source: str = "archive") -> dict:
    import joblib
    if source == "historical":
        rows, metadata = [], []
        symbols = all_symbols()
        today = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
        for index, symbol in enumerate(symbols):
            with _LOCK:
                _STATE.update(message=f"Reconstructing historical setups: {symbol} ({index + 1}/{len(symbols)})")
            symbol_rows, symbol_meta = quality.reconstruct_history(symbol, csv_store.load(symbol), today)
            rows.extend(symbol_rows)
            metadata.extend(symbol_meta)
        meta = pd.DataFrame(metadata)
    elif source == "archive":
        with session_scope() as db:
            repo.backfill_quality_observations(db)
            db.flush()
            payloads = repo.quality_observations(db)
        rows, meta = build_dataset(payloads)
    else:
        raise ValueError("Unknown training source")
    artifact = fit(rows, meta)
    artifact["metadata"].update(source=source, observation_dates=int(meta["date"].nunique()),
                                symbols=int(meta["symbol"].nunique()),
                                limitations=("Reconstructed weekly EOD setups using today's configured universe; survivorship bias and adjusted-price revisions remain. No historical live verification." if source == "historical" else "Recorded signal and verification observations."))
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=ARTIFACT.parent, suffix=".tmp", delete=False) as fh:
        temporary = Path(fh.name)
    try:
        joblib.dump(artifact, temporary)
        os.replace(temporary, ARTIFACT)
    finally:
        temporary.unlink(missing_ok=True)
    return artifact["metadata"]


def start_training(source: str = "archive") -> dict:
    with _LOCK:
        if _STATE["status"] != "training":
            _STATE.update(status="training", message="Training on archived observations")
            threading.Thread(target=_train_worker, args=(source,), daemon=True, name="train-quality").start()
    return status()


def _train_worker(source: str = "archive") -> None:
    try:
        metadata = train(source)
        state = {"status": "ready" if metadata["usable"] else "insufficient_skill",
                 "message": "Training complete" if metadata["usable"] else "Model did not beat the base-rate probability on held-out dates"}
    except ValueError as exc:
        state = {"status": "insufficient_data", "message": str(exc)}
    except Exception:
        log.exception("Trade-quality training failed")
        state = {"status": "error", "message": "Training failed; check backend logs"}
    with _LOCK:
        _STATE.update(state)


def score_signal(signal, verification=None) -> dict:
    result = {"status": "untrained", "probability": None, "quality_score": None,
              "target": quality.TARGET, "as_of": None, "disclaimer": quality.DISCLAIMER}
    artifact = model()
    if artifact is None:
        return result
    if not artifact["metadata"]["usable"]:
        return {**result, "status": "insufficient_skill"}
    v = None if verification is None else {
        "run_at": verification.run_at.isoformat(), "status": verification.status,
        "live_close": verification.live_close, "live_rsi": verification.live_rsi,
        "live_adx": verification.live_adx, "score_delta": verification.score_delta,
    }
    payload = repo.quality_payload(signal, v)
    feature_day, day = quality.observation_dates(payload)
    today = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
    if feature_day >= today:
        return {**result, "status": "awaiting_completed_bar"}
    if day <= pd.Timestamp(artifact["metadata"]["label_end"]):
        return {**result, "status": "historical_sample"}
    if (today - day).days > 7:
        return {**result, "status": "stale_observation"}
    feat = quality.features(payload, csv_store.load(signal.symbol))
    if feat is None:
        return {**result, "status": "ineligible"}
    if any(f"{key}={feat[key]}" not in artifact["vectorizer"].vocabulary_
           for key in ("category", "direction", "verification")):
        return {**result, "status": "unsupported_sample"}
    X = artifact["vectorizer"].transform([feat])
    raw_probability = artifact["forest"].predict_proba(X)[:, 1]
    probability = float(artifact["calibrator"].predict_proba(raw_probability.reshape(-1, 1))[0, 1])
    return {**result, "status": "ready", "probability": round(probability, 4),
            "quality_score": round(probability * 100, 1), "as_of": day.date().isoformat()}
