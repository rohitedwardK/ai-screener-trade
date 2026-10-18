"""Chronological RF evaluation and protection of serving artifacts."""
import json

import numpy as np
import pandas as pd
import pytest

from app.analysis import ml_dataset, ml_rf


def sample_dates():
    dates = pd.bdate_range("2024-01-01", periods=100)
    return pd.DataFrame([
        {"symbol": symbol, "date": day, "label_end": day + pd.offsets.BDay(5)}
        for symbol in ("A", "B") for day in dates
    ])


def test_split_groups_dates_and_purges_actual_label_ends():
    meta = sample_dates()
    # A missing-bar horizon can extend beyond five common trading dates.
    meta.loc[50, "label_end"] = meta.loc[62, "date"]
    parts, boundaries = ml_rf.chronological_split(meta)
    train, validation, test = (meta.iloc[parts[k]] for k in ("train", "validation", "test"))
    assert train.label_end.max() < validation.date.min()
    assert validation.label_end.max() < test.date.min()
    assert 50 not in parts["train"]
    assert len(parts["test"]) == 40
    assert set(train.date).isdisjoint(validation.date)
    assert set(validation.date).isdisjoint(test.date)
    extra = pd.DataFrame([{"symbol": "A", "date": pd.Timestamp("2025-01-01"),
                           "label_end": pd.Timestamp("2025-01-08")}])
    repeated, _ = ml_rf.chronological_split(pd.concat([meta, extra], ignore_index=True), boundaries)
    for name in parts:
        np.testing.assert_array_equal(parts[name], repeated[name])


def test_split_rejects_duplicates_and_invalid_dates():
    meta = sample_dates()
    with pytest.raises(ValueError, match="Duplicate"):
        ml_rf.chronological_split(pd.concat([meta, meta.iloc[:1]], ignore_index=True))
    meta.loc[0, "label_end"] = meta.loc[0, "date"]
    with pytest.raises(ValueError, match="after"):
        ml_rf.chronological_split(meta)


def test_metrics_match_known_probabilities_and_handle_single_class():
    metrics = ml_rf.evaluation_metrics(np.array([0, 0, 1, 1]), np.array([.1, .4, .35, .8]), .5)
    assert metrics["roc_auc"] == .75
    assert metrics["brier"] == pytest.approx(.158125)
    assert metrics["baseline_brier"] == .25
    assert metrics["confusion_matrix"] == [[2, 0], [1, 1]]
    assert metrics["precision"] == 1
    assert metrics["recall"] == .5
    single = ml_rf.evaluation_metrics(np.array([0, 0]), np.array([.1, .2]), .5)
    assert single["roc_auc"] is None
    assert single["average_precision"] is None
    json.dumps(single, allow_nan=False)


def test_training_never_fits_holdout_or_overwrites_serving_model(monkeypatch, tmp_path, range_df):
    from sklearn.ensemble import RandomForestClassifier

    raw = range_df.copy()
    ratio = (150 + (raw.close - 150) * 6) / raw.close
    raw.loc[:, ["open", "high", "low", "close"]] = raw[["open", "high", "low", "close"]].mul(ratio, axis=0)
    monkeypatch.setattr(ml_dataset.csv_store, "load", lambda symbol: raw)
    X, meta = ml_dataset.build_feature_matrix(symbols=["SYNTHETIC"])
    assert (meta.label_end > meta.date).all()
    for row in meta.itertuples():
        pos = raw.index.get_loc(row.date)
        assert row.label_end == raw.index[pos + 5]
        assert row.label == int(raw.close.iloc[pos + 5] / raw.close.iloc[pos] - 1 >= .03)
    monkeypatch.setattr(ml_dataset, "build_feature_matrix", lambda: (
        X.iloc[::-1].reset_index(drop=True), meta.iloc[::-1].reset_index(drop=True)
    ))
    monkeypatch.setattr(ml_rf, "_MODEL_DIR", tmp_path)
    monkeypatch.setattr(ml_rf, "_PKL_PATH", tmp_path / "serving.pkl")
    monkeypatch.setattr(ml_rf, "_META_PATH", tmp_path / "serving.json")
    ml_rf._PKL_PATH.write_bytes(b"original model")
    ml_rf._META_PATH.write_text("original metadata")
    previous_model = ml_rf._MODEL
    fits = []
    original_fit = RandomForestClassifier.fit

    def recording_fit(self, features, labels, *args, **kwargs):
        fits.append((features.copy(), labels.copy()))
        return original_fit(self, features, labels, *args, **kwargs)

    monkeypatch.setattr(RandomForestClassifier, "fit", recording_fit)
    result = ml_rf.train(save_model=False)
    parts, _ = ml_rf.chronological_split(meta, result["boundaries"])
    assert len(fits) == 1
    pd.testing.assert_frame_equal(fits[0][0], X[ml_dataset.FEATURE_COLS].iloc[parts["train"]])
    assert ml_rf._PKL_PATH.read_bytes() == b"original model"
    assert ml_rf._META_PATH.read_text() == "original metadata"
    assert ml_rf._MODEL is previous_model
    assert result["model_params"]["n_estimators"] == 400
    assert result["train_rows"] == len(parts["train"])
    assert result["test_metrics"]["rows"] == len(parts["test"])
    predictions = pd.read_csv(tmp_path / "rf_evaluation/predictions.csv")
    assert set(predictions.partition) == {"validation", "test"}
    saved = json.loads((tmp_path / "rf_evaluation/metrics.json").read_text())
    assert saved["test_metrics"] == result["test_metrics"]
