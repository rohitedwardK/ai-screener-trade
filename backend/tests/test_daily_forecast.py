from __future__ import annotations

import numpy as np
import pandas as pd


def _pattern_df(rows: int = 1300) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2021-01-01", periods=rows, freq="B")
    close = [100.0]
    for i in range(1, rows):
        cycle = np.sin(i / 6)
        drift = 0.003 if cycle > 0 else -0.0025
        close.append(close[-1] * (1.0 + drift + rng.normal(0, 0.004)))
    closes = np.array(close)
    opens = np.r_[closes[0], closes[:-1]]
    high = np.maximum(opens, closes) * 1.006
    low = np.minimum(opens, closes) * 0.994
    volume = 1_000_000 + (np.sin(np.arange(rows) / 11) + 1.2) * 120_000
    return pd.DataFrame(
        {"open": opens, "high": high, "low": low, "close": closes, "volume": volume},
        index=idx,
    )


def test_build_daily_examples_has_next_day_labels_without_latest_row():
    from app.analysis.daily_forecast import FEATURE_COLUMNS, build_daily_examples

    df = _pattern_df(80)
    Xy, meta = build_daily_examples(df)

    assert list(Xy.columns) == FEATURE_COLUMNS + ["label"]
    assert len(Xy) == len(meta)
    assert meta["date"].max() < df.index.max()
    assert (pd.to_datetime(meta["label_end"]) > pd.to_datetime(meta["date"])).all()


def test_chronological_split_excludes_labels_crossing_window_boundaries():
    from app.analysis.daily_forecast import build_daily_examples, chronological_split

    Xy, meta = build_daily_examples(_pattern_df(260))
    train_idx, validation_idx, test_idx = chronological_split(meta)

    assert len(train_idx) > 0
    assert len(validation_idx) > 0
    assert len(test_idx) > 0
    assert meta.loc[train_idx, "label_end"].max() < meta.loc[validation_idx, "date"].min()
    assert meta.loc[validation_idx, "label_end"].max() < meta.loc[test_idx, "date"].min()
    assert len(Xy) == len(meta)


def test_evaluate_daily_forecast_returns_probability_and_diagnostics():
    from app.analysis.daily_forecast import DISCLAIMER, evaluate_daily_forecast

    result = evaluate_daily_forecast("TEST.NS", _pattern_df())

    assert result.disclaimer == DISCLAIMER
    assert result.probability_up is not None
    assert 0.0 <= result.probability_up <= 1.0
    assert result.metrics["train_samples"] > result.metrics["validation_samples"] > 0
    assert result.metrics["test_samples"] > 0
    assert result.metrics["test"]["brier"] >= 0.0
    assert set(result.latest_features) == {
        "daily_return",
        "return_5d",
        "close_vs_ma20",
        "volatility_20d",
        "relative_volume",
    }
    assert result.data_quality["duplicate_dates"] == 0


def test_evaluate_daily_forecast_short_history_omits_metrics():
    from app.analysis.daily_forecast import evaluate_daily_forecast
    from app.models.schemas import DailyForecastOut

    result = evaluate_daily_forecast("TEST.NS", _pattern_df(254))

    assert result.probability_up is None
    assert result.metrics is None
    assert "254 daily bars" in result.notes[0]
    assert "756" in result.notes[0]
    DailyForecastOut(**{**result.__dict__, "metrics": result.metrics or None})


def test_evaluate_daily_forecast_mcx_one_year_cache_returns_probability():
    from app.analysis.daily_forecast import evaluate_daily_forecast

    result = evaluate_daily_forecast("GOLD.MCX", _pattern_df(268))

    assert result.probability_up is not None
    assert 0.0 <= result.probability_up <= 1.0
    assert result.metrics["test_samples"] >= 30
    assert any("one year of Upstox" in note for note in result.notes)


def test_evaluate_daily_forecast_mcx_below_one_year_omits_probability():
    from app.analysis.daily_forecast import evaluate_daily_forecast

    result = evaluate_daily_forecast("SILVER.MCX", _pattern_df(180))

    assert result.probability_up is None
    assert "180 daily bars" in result.notes[0]
    assert "220" in result.notes[0]
