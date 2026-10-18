"""One-symbol daily probability forecast with chronological validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from ..core.commodity_universe import is_commodity_symbol

DISCLAIMER = "Research and decision-support only. Not financial advice."

# Equity forecasts keep a three-year gate so each chronological fold is large.
# MCX gold/silver only retain about one year of Upstox front-month bars; 220
# sessions still leaves a 60/20/20 split with at least 30 bars in each fold
# after the 20-day feature warmup.
EQUITY_MIN_BARS = 252 * 3
COMMODITY_MIN_BARS = 220
EQUITY_MIN_LABELLED = 252 * 2
COMMODITY_MIN_LABELLED = 150

FEATURE_COLUMNS = [
    "daily_return",
    "return_5d",
    "close_vs_ma20",
    "volatility_20d",
    "relative_volume",
]


@dataclass
class DailyForecastResult:
    symbol: str
    as_of: str | None
    probability_up: float | None
    latest_features: dict[str, float] = field(default_factory=dict)
    baseline_probability: float | None = None
    metrics: dict[str, Any] | None = None
    coefficients: dict[str, float] = field(default_factory=dict)
    data_quality: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER


def build_daily_examples(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return feature rows and metadata; each row uses only same-day close data."""
    df = _normalise_ohlcv(raw)
    if df.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS), pd.DataFrame()

    features = pd.DataFrame(index=df.index)
    features["daily_return"] = df["close"].pct_change()
    features["return_5d"] = df["close"].pct_change(5)
    features["close_vs_ma20"] = df["close"] / df["close"].rolling(20).mean() - 1.0
    features["volatility_20d"] = features["daily_return"].rolling(20).std()
    features["relative_volume"] = df["volume"] / df["volume"].rolling(20).mean()
    features = features.replace([np.inf, -np.inf], np.nan)

    next_close = df["close"].shift(-1)
    labels = (next_close > df["close"]).astype(int)
    label_end = pd.Series(df.index, index=df.index).shift(-1)

    full = features.copy()
    full["label"] = labels
    full["label_end"] = label_end
    full = full.dropna(subset=FEATURE_COLUMNS + ["label_end"])
    full = full.iloc[:-1] if not full.empty and full.index[-1] == df.index[-1] else full

    meta = pd.DataFrame({
        "date": full.index,
        "label": full["label"].astype(int).to_numpy(),
        "label_end": pd.to_datetime(full["label_end"]).to_numpy(),
    })
    return full[FEATURE_COLUMNS + ["label"]].reset_index(drop=True), meta


def _history_limits(symbol: str) -> tuple[int, int, str]:
    if is_commodity_symbol(symbol):
        return (
            COMMODITY_MIN_BARS,
            COMMODITY_MIN_LABELLED,
            "about one year of MCX front-month sessions",
        )
    return EQUITY_MIN_BARS, EQUITY_MIN_LABELLED, "about three years of business days"


def evaluate_daily_forecast(symbol: str, raw: pd.DataFrame) -> DailyForecastResult:
    df = _normalise_ohlcv(raw)
    quality = data_quality_report(raw)
    required, min_labelled, window_label = _history_limits(symbol)
    if len(df) < required:
        return DailyForecastResult(
            symbol=symbol,
            as_of=df.index[-1].date().isoformat() if not df.empty else None,
            probability_up=None,
            data_quality=quality,
            notes=[
                f"Cached {len(df)} daily bars; chronological validation needs at least {required} "
                f"({window_label})."
            ],
        )

    Xy, meta = build_daily_examples(df)
    if len(Xy) < min_labelled or Xy["label"].nunique() < 2:
        return DailyForecastResult(
            symbol=symbol,
            as_of=df.index[-1].date().isoformat(),
            probability_up=None,
            data_quality=quality,
            notes=["Not enough labelled examples with both up and down days."],
        )

    train_idx, val_idx, test_idx = chronological_split(meta)
    if min(len(train_idx), len(val_idx), len(test_idx)) < 30:
        return DailyForecastResult(
            symbol=symbol,
            as_of=df.index[-1].date().isoformat(),
            probability_up=None,
            data_quality=quality,
            notes=["Chronological train/validation/test windows are too small after label-boundary checks."],
        )

    X = Xy[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = Xy["label"].to_numpy(dtype=int)

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X[train_idx])
    X_val = scaler.transform(X[val_idx])
    X_test = scaler.transform(X[test_idx])

    model = LogisticRegression(C=0.5, penalty="l2", solver="lbfgs", max_iter=1000)
    model.fit(X_train, y[train_idx])

    val_prob = model.predict_proba(X_val)[:, 1]
    test_prob = model.predict_proba(X_test)[:, 1]
    baseline = float(y[train_idx].mean())
    baseline_test = np.full(len(test_idx), baseline)

    latest = latest_feature_row(df)
    probability = None
    if latest:
        latest_x = pd.DataFrame([latest], columns=FEATURE_COLUMNS).to_numpy(dtype=float)
        probability = float(model.predict_proba(scaler.transform(latest_x))[0, 1])

    return DailyForecastResult(
        symbol=symbol,
        as_of=df.index[-1].date().isoformat(),
        probability_up=probability,
        latest_features=latest,
        baseline_probability=baseline,
        metrics={
            "samples": int(len(Xy)),
            "train_samples": int(len(train_idx)),
            "validation_samples": int(len(val_idx)),
            "test_samples": int(len(test_idx)),
            "validation": _score(y[val_idx], val_prob, baseline),
            "test": _score(y[test_idx], test_prob, baseline),
            "test_baseline_brier": float(brier_score_loss(y[test_idx], baseline_test)),
            "calibration_bins": calibration_bins(y[test_idx], test_prob),
        },
        coefficients=dict(zip(FEATURE_COLUMNS, model.coef_[0].round(6).tolist())),
        data_quality=quality,
        notes=_forecast_notes(symbol),
    )


def _forecast_notes(symbol: str) -> list[str]:
    notes = [
        "Features use data available after the daily close; the label is whether the next close is higher.",
        "Scaling is fitted on the training window only.",
        "Cached prices are expected to be split/dividend adjusted by the data refresh pipeline.",
    ]
    if is_commodity_symbol(symbol):
        notes.append(
            "MCX history is about one year of Upstox front-month bars. "
            "Train, validation, and test are chronological slices of that shorter window."
        )
    return notes


def chronological_split(meta: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    days = sorted(pd.to_datetime(meta["date"]).unique())
    if len(days) < 90:
        raise ValueError("At least 90 labelled dates are required.")
    validation_start = days[int(len(days) * 0.6)]
    test_start = days[int(len(days) * 0.8)]
    date = pd.to_datetime(meta["date"])
    label_end = pd.to_datetime(meta["label_end"])
    train = (date < validation_start) & (label_end < validation_start)
    validation = (date >= validation_start) & (date < test_start) & (label_end < test_start)
    test = date >= test_start
    return tuple(np.flatnonzero(mask.to_numpy()) for mask in (train, validation, test))


def latest_feature_row(df: pd.DataFrame) -> dict[str, float]:
    frame = _normalise_ohlcv(df)
    if frame.empty:
        return {}
    daily_return = frame["close"].pct_change()
    row = {
        "daily_return": daily_return.iloc[-1],
        "return_5d": frame["close"].pct_change(5).iloc[-1],
        "close_vs_ma20": frame["close"].iloc[-1] / frame["close"].rolling(20).mean().iloc[-1] - 1.0,
        "volatility_20d": daily_return.rolling(20).std().iloc[-1],
        "relative_volume": frame["volume"].iloc[-1] / frame["volume"].rolling(20).mean().iloc[-1],
    }
    if any(not np.isfinite(value) for value in row.values()):
        return {}
    return {key: float(row[key]) for key in FEATURE_COLUMNS}


def data_quality_report(raw: pd.DataFrame) -> dict[str, Any]:
    df = _normalise_ohlcv(raw, drop_duplicate_dates=False)
    if df.empty:
        return {"rows": 0, "duplicate_dates": 0, "missing_business_days": 0}
    duplicate_dates = int(df.index.duplicated().sum())
    unique_index = df.index[~df.index.duplicated(keep="last")]
    expected = pd.bdate_range(unique_index.min(), unique_index.max())
    missing = expected.difference(unique_index)
    required = ["open", "high", "low", "close", "volume"]
    missing_values = int(df[required].isna().sum().sum())
    return {
        "rows": int(len(df)),
        "start": unique_index.min().date().isoformat(),
        "end": unique_index.max().date().isoformat(),
        "duplicate_dates": duplicate_dates,
        "missing_business_days": int(len(missing)),
        "missing_values": missing_values,
        "corporate_actions": "handled_by_adjusted_cache_refresh_overlap",
    }


def calibration_bins(y_true: np.ndarray, prob: np.ndarray, bins: int = 5) -> list[dict[str, float | int]]:
    out: list[dict[str, float | int]] = []
    edges = np.linspace(0.0, 1.0, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (prob >= lo) & (prob <= hi if hi == 1.0 else prob < hi)
        if not mask.any():
            continue
        out.append({
            "lower": float(lo),
            "upper": float(hi),
            "count": int(mask.sum()),
            "mean_probability": float(prob[mask].mean()),
            "observed_frequency": float(y_true[mask].mean()),
        })
    return out


def _score(y_true: np.ndarray, prob: np.ndarray, baseline: float) -> dict[str, float]:
    score = {
        "brier": float(brier_score_loss(y_true, prob)),
        "log_loss": float(log_loss(y_true, prob, labels=[0, 1])),
        "baseline_accuracy": float(max(baseline, 1.0 - baseline)),
        "accuracy_at_50": float(((prob >= 0.5).astype(int) == y_true).mean()),
    }
    score["auc"] = float(roc_auc_score(y_true, prob)) if len(np.unique(y_true)) == 2 else float("nan")
    return score


def _normalise_ohlcv(raw: pd.DataFrame, drop_duplicate_dates: bool = True) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = raw.copy()
    df.index = pd.to_datetime(df.index).normalize()
    columns = {col: col.lower() for col in df.columns}
    df = df.rename(columns=columns)
    required = ["open", "high", "low", "close", "volume"]
    df = df[[col for col in required if col in df.columns]]
    if set(required) - set(df.columns):
        return pd.DataFrame(columns=required)
    df = df.sort_index()
    if drop_duplicate_dates:
        df = df[~df.index.duplicated(keep="last")]
    return df[required].astype(float)


__all__ = [
    "DailyForecastResult",
    "FEATURE_COLUMNS",
    "build_daily_examples",
    "chronological_split",
    "data_quality_report",
    "evaluate_daily_forecast",
]
