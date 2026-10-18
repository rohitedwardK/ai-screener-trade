from datetime import date, datetime

import joblib
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis import ml_quality as q
from app.core import trade_quality as service
from app.data import repository as repo
from app.models.orm import Base, QualityObservation, Signal, Stock


def payload(**overrides):
    return {"symbol": "TEST.NS", "category": "PULLBACK_ENTRY", "score": 60.,
            "confidence": .8, "entry": 150., "stop_loss": 100., "target_1": 220.,
            "invalidation": 110., "direction": "LONG", "as_of_date": "2026-04-20",
            "run_at": "2026-04-20T13:00:00", "verification": None, **overrides}


@pytest.mark.parametrize("short,high,low,expected", [
    (False, 225, 145, 1), (False, 225, 105, 0), (False, 170, 145, 0),
    (True, 155, 95, 1), (True, 185, 95, 0),
])
def test_price_path_labels(short, high, low, expected):
    p = payload(direction="SHORT", target_1=100., stop_loss=190., invalidation=180.) if short else payload()
    bars = pd.DataFrame({"open": [150.] * 5, "close": [150.] * 5,
                         "high": [high] * 5, "low": [low] * 5})
    assert q.outcome(p, bars) == expected
    assert q.outcome(p, bars.iloc[:4]) is None


def test_features_ignore_future_and_same_day_verification(range_df):
    p = payload(verification={"run_at": "2026-04-20T06:00:00", "status": "CONFIRMED", "live_close": 150.})
    feature_day, day = q.observation_dates(p)
    assert feature_day == pd.Timestamp("2026-04-19")
    assert day == pd.Timestamp("2026-04-20")
    first = q.features(p, range_df)
    changed = range_df.copy()
    changed.loc[changed.index > feature_day, "close"] = 99999
    assert first == q.features(p, changed)
    assert first["verification"] == "CONFIRMED"
    assert q.features(payload(invalidation=None), range_df) is None


def test_utc_observation_uses_indian_date():
    _, day = q.observation_dates(payload(run_at="2026-04-20T20:00:00"))
    assert day == pd.Timestamp("2026-04-21")


def test_partial_intraday_signal_is_not_rebuilt_from_final_close(range_df):
    assert q.features(payload(run_at="2026-04-20T05:00:00"), range_df) is None


def test_dataset_uses_only_next_sessions(monkeypatch, range_df):
    monkeypatch.setattr(service.csv_store, "load", lambda symbol: range_df)
    rows, meta = service.build_dataset([payload()])
    assert len(rows) == 1
    assert meta.iloc[0].label_end == pd.Timestamp("2026-04-27")
    rows, _ = service.build_dataset([payload(as_of_date="2026-04-30", run_at="2026-04-30T13:00:00")])
    assert rows == []


def training_data():
    days = pd.bdate_range("2024-01-01", periods=100)
    rows, meta = [], []
    for day in days:
        for label in [0, 1] * 3:
            rows.append({"signal": float(label), "category": "PULLBACK_ENTRY"})
            meta.append({"date": day, "label_end": day + pd.offsets.BDay(5),
                         "label": label, "verified": False})
    return rows, pd.DataFrame(meta)


def test_purged_date_split_keeps_symbols_together():
    _, meta = training_data()
    train, calibration, test = q.chronological_split(meta)
    assert meta.iloc[train].label_end.max() < meta.iloc[calibration].date.min()
    assert meta.iloc[calibration].label_end.max() < meta.iloc[test].date.min()
    assert set(meta.iloc[train].date).isdisjoint(meta.iloc[test].date)


def test_calibrated_model_roundtrip_and_metrics(tmp_path):
    rows, meta = training_data()
    artifact = service.fit(rows, meta)
    assert artifact["metadata"]["test_auc"] == 1.
    assert artifact["metadata"]["test_brier"] < artifact["metadata"]["baseline_brier"]
    path = tmp_path / "quality.pkl"
    joblib.dump(artifact, path)
    reloaded = joblib.load(path)
    X = reloaded["vectorizer"].transform(rows[:2])
    prob = reloaded["forest"].predict_proba(X)[:, 1]
    calibrated = reloaded["calibrator"].predict_proba(prob.reshape(-1, 1))[:, 1]
    assert 0 < calibrated[0] < calibrated[1] < 1


def test_insufficient_and_single_class_data_rejected():
    with pytest.raises(ValueError, match="100"):
        service.fit([], pd.DataFrame())
    rows, meta = training_data()
    meta["label"] = 0
    with pytest.raises(ValueError, match="each outcome"):
        service.fit(rows, meta)


def test_archive_survives_signal_deletion_and_keeps_first_observation():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Stock(symbol="TEST.NS"))
        db.commit()
        p = payload()
        p.pop("verification")
        p["as_of_date"] = date(2026, 4, 20)
        p["run_at"] = datetime(2026, 4, 20, 13)
        repo.save_signals(db, [p])
        signal = db.scalar(select(Signal))
        repo.archive_quality_observation(db, signal)
        v = {"run_at": "2026-04-21T06:00:00", "status": "CONFIRMED", "live_close": 150.}
        repo.archive_quality_observation(db, signal, v)
        repo.archive_quality_observation(db, signal, {**v, "live_close": 155.})
        db.delete(signal)
        db.commit()
        observations = list(db.scalars(select(QualityObservation)))
        assert len(observations) == 2
        assert observations[1].payload["verification"]["live_close"] == 150.


def test_no_artifact_returns_no_probability(monkeypatch):
    monkeypatch.setattr(service, "model", lambda: None)
    result = service.score_signal(None)
    assert result["status"] == "untrained"
    assert result["probability"] is None
    assert result["disclaimer"] == q.DISCLAIMER


def test_reconstruction_is_point_in_time_and_has_future_only_labels(uptrend_df):
    raw = uptrend_df.iloc[:235]
    today = raw.index[-1] + pd.Timedelta(days=1)
    rows, metadata = q.reconstruct_history("TEST.NS", raw, today)
    assert rows
    assert all(item["date"] < item["label_end"] < today for item in metadata)
    assert all(not item["verified"] for item in metadata)
    changed = raw.copy()
    changed.loc[changed.index >= raw.index[225], ["open", "high", "low", "close"]] *= 3
    other_rows, other_meta = q.reconstruct_history("TEST.NS", changed, today)
    before = [(row, meta) for row, meta in zip(rows, metadata) if meta["label_end"] < raw.index[225]]
    after = [(row, meta) for row, meta in zip(other_rows, other_meta) if meta["label_end"] < raw.index[225]]
    assert before == after
    assert before


def test_reconstruction_rejects_incomplete_or_duplicate_prices(uptrend_df):
    today = uptrend_df.index[-1] + pd.Timedelta(days=1)
    bad = uptrend_df.copy()
    bad.iloc[220, 0] = np.nan
    assert q.reconstruct_history("TEST.NS", bad, today) == ([], [])
    duplicate = pd.concat([uptrend_df, uptrend_df.tail(1)])
    assert q.reconstruct_history("TEST.NS", duplicate, today) == ([], [])


def test_history_coverage_exposes_short_and_incomplete_cache(monkeypatch, uptrend_df):
    bad = uptrend_df.copy()
    bad.iloc[10, 0] = np.nan
    monkeypatch.setattr(service.csv_store, "load", lambda symbol: bad)
    record = service.csv_store.history_coverage(["TEST.NS"])[0]
    assert record["rows"] == 300
    assert record["missing_values"] == 1
    assert record["five_year_span"] is False
    assert record["duplicate_dates"] == 0
