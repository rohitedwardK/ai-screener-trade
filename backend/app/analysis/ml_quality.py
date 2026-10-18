"""Point-in-time features and price-path labels for recorded stock setups."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import compute_all
from .signals import CATEGORIES
from .signals import evaluate_symbol, signal_to_dict

HORIZON = 5
DISCLAIMER = "Research and decision-support only. Not financial advice."
TARGET = "Target 1 before stop/invalidation within the next 5 complete trading sessions"


def observation_dates(payload: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    verification = payload.get("verification")
    observed = pd.Timestamp(verification["run_at"] if verification else payload["run_at"])
    observed = observed.tz_localize("UTC") if observed.tzinfo is None else observed
    local = observed.tz_convert("Asia/Kolkata").tz_localize(None)
    day = local.normalize()
    as_of = pd.Timestamp(payload["as_of_date"])
    # An intraday verification cannot use that day's final daily candle.
    intraday = verification or local < day + pd.Timedelta(hours=15, minutes=30)
    feature_day = min(as_of, day - pd.Timedelta(days=1)) if intraday else as_of
    return feature_day, max(day, as_of)


def features(payload: dict, raw: pd.DataFrame, *, enriched: pd.DataFrame | None = None) -> dict | None:
    if payload["category"] not in CATEGORIES:
        return None
    if payload["category"] in {"OVERBOUGHT_AVOID", "HIGH_RISK"}:
        return None
    feature_day, day = observation_dates(payload)
    # A retained intraday signal may have used a partial candle that is now gone.
    if not payload.get("verification") and feature_day < pd.Timestamp(payload["as_of_date"]):
        return None
    history = raw.loc[raw.index <= feature_day]
    if len(history) < 210:
        return None
    if (day - history.index[-1]).days > 7:
        return None
    if enriched is None:
        enriched = compute_all(history)
    elif not enriched.index.equals(history.index):
        raise ValueError("Enriched features must match the point-in-time history slice")
    row = enriched.iloc[-1]
    verification = payload.get("verification") or {}
    price = verification.get("live_close", float(row["close"]))
    direction = payload.get("direction") or ("SHORT" if payload["category"] == "WEAK_AVOID" else "LONG")
    if direction not in {"LONG", "SHORT"}:
        return None
    sign = 1 if direction == "LONG" else -1
    levels = [price, payload.get("entry"), payload.get("target_1"),
              payload.get("stop_loss"), payload.get("invalidation")]
    if any(v is None or not np.isfinite(v) or v <= 0 for v in levels):
        return None
    price, entry, target, stop, invalidation = map(float, levels)
    if min(sign * (target - price), sign * (price - stop), sign * (price - invalidation)) <= 0:
        return None
    if verification.get("status") == "INVALIDATED":
        return None
    result = {
        "category": payload["category"], "direction": direction,
        "score": payload["score"], "rule_confidence": payload["confidence"],
        "entry_distance_pct": sign * (entry / price - 1) * 100,
        "target_distance_pct": sign * (target / price - 1) * 100,
        "stop_distance_pct": sign * (1 - stop / price) * 100,
        "invalidation_distance_pct": sign * (1 - invalidation / price) * 100,
        "signal_age_days": (day - pd.Timestamp(payload["as_of_date"])).days,
        "verification": verification.get("status", "UNVERIFIED"),
    }
    for key in ("rsi14", "adx", "atr_pct", "vol_ratio", "return_5d", "return_20d", "bb_width"):
        value = row.get(key)
        if value is None or not np.isfinite(value):
            return None
        result[key] = float(value)
    for key in ("live_rsi", "live_adx", "score_delta"):
        value = verification.get(key)
        result[f"has_{key}"] = int(value is not None and np.isfinite(value))
        result[key] = float(value) if result[f"has_{key}"] else 0.0
    return result


def outcome(payload: dict, future: pd.DataFrame) -> int | None:
    """Price-path event only; no assumed entries, fills, positions, or P&L."""
    if len(future) < HORIZON:
        return None
    short = (payload.get("direction") or ("SHORT" if payload["category"] == "WEAK_AVOID" else "LONG")) == "SHORT"
    stop = min(payload["stop_loss"], payload["invalidation"]) if short else max(payload["stop_loss"], payload["invalidation"])
    target = payload["target_1"]
    for _, bar in future.iloc[:HORIZON].iterrows():
        if not np.isfinite(bar[["open", "high", "low", "close"]].to_numpy(dtype=float)).all():
            return None
        stopped = bar["high"] >= stop if short else bar["low"] <= stop
        reached = bar["low"] <= target if short else bar["high"] >= target
        # Daily OHLC cannot establish order when both levels are touched.
        if stopped:
            return 0
        if reached:
            return 1
    return 0


def chronological_split(meta: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    days = sorted(meta["date"].unique())
    if len(days) < 30:
        raise ValueError(f"Only {len(days)} mature observation dates; at least 30 required. Price-history dates are not recorded signal observations. Choose historical reconstruction to train from cached prices.")
    calibration_start, test_start = days[int(len(days) * .6)], days[int(len(days) * .8)]
    train = (meta["date"] < calibration_start) & (meta["label_end"] < calibration_start)
    calibration = (meta["date"] >= calibration_start) & (meta["date"] < test_start) & (meta["label_end"] < test_start)
    test = meta["date"] >= test_start
    return tuple(np.flatnonzero(mask) for mask in (train, calibration, test))


def reconstruct_history(symbol: str, raw: pd.DataFrame, today: pd.Timestamp) -> tuple[list[dict], list[dict]]:
    """Rebuild weekly EOD setups, never indicators from future candles."""
    raw = raw.sort_index().loc[lambda df: df.index < today]
    rows, metadata = [], []
    if raw.empty or raw.index.has_duplicates or not np.isfinite(raw.to_numpy(dtype=float)).all():
        return rows, metadata
    start = today - pd.DateOffset(years=5)
    for i in range(209, len(raw) - HORIZON, 5):
        day = raw.index[i]
        if day < start:
            continue
        history = raw.iloc[:i + 1]
        future = raw.iloc[i + 1:i + 1 + HORIZON]
        enriched = compute_all(history)
        for signal in evaluate_symbol(symbol, history, df_enriched=enriched):
            payload = signal_to_dict(signal)
            payload.update(as_of_date=day.date().isoformat(),
                           run_at=f"{day.date().isoformat()}T12:00:00+00:00", verification=None)
            feat = features(payload, history, enriched=enriched)
            if feat is None:
                continue
            label = outcome(payload, future)
            if label is None:
                continue
            rows.append(feat)
            metadata.append({"date": day, "label_end": future.index[-1], "label": label,
                             "symbol": symbol, "verified": False})
    return rows, metadata
