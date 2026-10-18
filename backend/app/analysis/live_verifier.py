"""Live signal verifier.

Pure functions that take a persisted EOD screener signal and reconcile it
against an intraday-projected today-bar built from the latest live LTP. The
output is a per-signal status (CONFIRMED / WEAKENING / INVALIDATED /
STRENGTHENED) plus the live indicator deltas the UI surfaces next to the
historical thesis.

Design constraints:
    - No DB, no network, no yfinance/Upstox imports here. Everything is
      injected by the caller (`services/live_verification.py`).
    - No look-ahead: the projected bar is appended at today's date and
      built only from data that exists at the moment of evaluation.
    - The half-formed daily bar's RSI / regime are intentionally jumpy.
      We label them `intraday-projected` and use them directionally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd


# ----- Status constants -----------------------------------------------------
STATUS_CONFIRMED = "CONFIRMED"
STATUS_WEAKENING = "WEAKENING"
STATUS_INVALIDATED = "INVALIDATED"
STATUS_STRENGTHENED = "STRENGTHENED"

ALL_STATUSES = (
    STATUS_CONFIRMED,
    STATUS_WEAKENING,
    STATUS_INVALIDATED,
    STATUS_STRENGTHENED,
)


# Categories that point UP (signal expects price to rise above entry).
# Used so we can flip the stop-loss / target-distance arithmetic for shorts.
_LONG_BIASED = frozenset({
    "MOMENTUM_LEADER",
    "FRESH_BREAKOUT",
    "PULLBACK_ENTRY",
    "OVERSOLD_RECOVERING",
    "SWING_NEXT_WEEK",
    "INTRADAY_WATCH_TOMORROW",
})
_SHORT_BIASED = frozenset({"WEAK_AVOID"})
_NEUTRAL = frozenset({"OVERBOUGHT_AVOID", "HIGH_RISK"})

# Regimes that contradict a long thesis (or vice versa).
_BEARISH_REGIMES = frozenset({"DOWNTREND", "STRONG_DOWNTREND"})
_BULLISH_REGIMES = frozenset({"UPTREND", "STRONG_UPTREND"})


@dataclass(frozen=True)
class VerificationRecord:
    """Per-signal output of `verify_signal`."""
    signal_id: int
    symbol: str
    category: str
    status: str
    live_close: float
    live_rsi: Optional[float]
    live_adx: Optional[float]
    live_regime: str
    score_delta: Optional[float]
    distance_to_stop_pct: Optional[float]
    distance_to_t1_pct: Optional[float]
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PersistedSignal:
    """Lightweight projection of `models.orm.Signal` used by the verifier.

    We accept this DTO instead of the ORM object so the module stays
    network/DB-free and unit-testable from synthetic data alone.
    """
    id: int
    symbol: str
    category: str
    score: float
    entry: Optional[float]
    stop_loss: Optional[float]
    target_1: Optional[float]
    persisted_rsi: Optional[float] = None
    persisted_regime: Optional[str] = None
    direction: Optional[str] = None


# ---------------------------------------------------------------------------
# Today-bar projection
# ---------------------------------------------------------------------------
def project_today_bar(
    daily_df: pd.DataFrame,
    ltp: float,
    *,
    session_open: Optional[float] = None,
    intraday_high: Optional[float] = None,
    intraday_low: Optional[float] = None,
    volume: Optional[float] = None,
    today: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Append a synthetic today-bar to `daily_df` using the latest LTP.

    If the last row of `daily_df` is already today's date (markets ran late,
    EOD already cached) the row is *replaced* so we don't double-stamp the
    same trading date in the index — this keeps `compute_all` happy.

    Args:
        daily_df       : Full historical OHLCV with a DatetimeIndex (open,
                         high, low, close, volume columns). Must NOT be empty.
        ltp            : Latest live price; used as today's close.
        session_open   : Today's open if known (e.g. from Upstox quote).
        intraday_high  : Running session high, defaults to max(open, ltp).
        intraday_low   : Running session low, defaults to min(open, ltp).
        volume         : Cumulative session volume; if None we fall back to
                         a proportional estimate from the 20-day average.
        today          : Override "today" (used by tests to pin a date).

    Returns:
        A copy of `daily_df` with one row appended/updated for today.
    """
    if daily_df is None or daily_df.empty:
        raise ValueError("project_today_bar requires non-empty daily_df")
    if ltp is None or not np.isfinite(ltp) or ltp <= 0:
        raise ValueError(f"project_today_bar: invalid ltp={ltp}")

    out = daily_df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out.index = out.index.normalize()

    today_ts = pd.Timestamp(today) if today is not None else pd.Timestamp.today()
    today_ts = today_ts.normalize()

    prev_close = float(out["close"].iloc[-1])

    open_v = float(session_open) if session_open is not None and np.isfinite(session_open) else prev_close
    high_v = float(intraday_high) if intraday_high is not None and np.isfinite(intraday_high) else max(open_v, ltp)
    low_v = float(intraday_low) if intraday_low is not None and np.isfinite(intraday_low) else min(open_v, ltp)
    # Guarantee high >= max(open, close) and low <= min(open, close) so the
    # synthetic bar is internally consistent and compute_all (true_range)
    # never produces a negative range.
    high_v = max(high_v, open_v, float(ltp))
    low_v = min(low_v, open_v, float(ltp))

    if volume is not None and np.isfinite(volume) and volume > 0:
        vol_v = float(volume)
    else:
        # Pro-rate the trailing-20-day average to today's elapsed share of
        # the 6h15m session. We can't know elapsed time from a static dataframe;
        # use a flat 0.5 default which matches "session is roughly half done".
        vol_avg = float(out["volume"].tail(20).mean()) if len(out) >= 5 else 0.0
        vol_v = max(vol_avg * 0.5, 0.0)

    new_row = pd.DataFrame(
        {
            "open": [open_v],
            "high": [high_v],
            "low": [low_v],
            "close": [float(ltp)],
            "volume": [vol_v],
        },
        index=[today_ts],
    )
    new_row.index.name = out.index.name

    # If today's row is already in the index (e.g. EOD ran early), replace it.
    if today_ts in out.index:
        out = out.drop(today_ts)

    return pd.concat([out, new_row])


# ---------------------------------------------------------------------------
# Per-signal verification
# ---------------------------------------------------------------------------
def _signal_direction(category: str, persisted_direction: Optional[str] = None) -> str:
    """Prefer the persisted decision; category is only a legacy fallback."""
    if persisted_direction:
        mapped = persisted_direction.strip().upper()
        if mapped == "LONG":
            return "long"
        if mapped == "SHORT":
            return "short"
        if mapped in {"WAIT", "NEUTRAL"}:
            return "neutral"
    if category in _LONG_BIASED:
        return "long"
    if category in _SHORT_BIASED:
        return "short"
    return "neutral"


def _distance_pct(price: float, level: Optional[float]) -> Optional[float]:
    if level is None or not np.isfinite(level) or level <= 0:
        return None
    return (price / level - 1.0) * 100.0


def _stop_violated(direction: str, live_price: float, stop: Optional[float]) -> bool:
    if stop is None or not np.isfinite(stop):
        return False
    if direction == "long":
        return live_price <= stop
    if direction == "short":
        return live_price >= stop
    return False


def _regime_contradicts(direction: str, live_regime: str) -> bool:
    if direction == "long":
        return live_regime in _BEARISH_REGIMES
    if direction == "short":
        return live_regime in _BULLISH_REGIMES
    return False


def _atr_progress(
    direction: str,
    live_price: float,
    entry: Optional[float],
    atr: Optional[float],
) -> Optional[float]:
    """Signed ATR multiples of progress from entry toward target.

    Positive = moved in the thesis direction by N x ATR.
    Negative = moved against the thesis.
    None when we don't have an entry / ATR.
    """
    if entry is None or atr is None or atr <= 0 or not np.isfinite(entry):
        return None
    if direction == "long":
        sign = 1.0
    elif direction == "short":
        sign = -1.0
    else:
        return None
    return ((live_price - entry) * sign) / atr


def verify_signal(
    persisted: PersistedSignal,
    *,
    live_price: float,
    live_rsi: Optional[float],
    live_adx: Optional[float],
    live_regime: str,
    live_atr: Optional[float],
    live_categories: Iterable[str],
    live_score: Optional[float] = None,
) -> VerificationRecord:
    """Reconcile one persisted signal against the live re-evaluation.

    Generic decision tree (works across all 9 categories):

        1. INVALIDATED if live price has crossed the persisted stop OR if
           the live regime now flatly contradicts the thesis direction.
        2. STRENGTHENED if the same category fires on the live re-evaluation
           AND price has progressed >= 0.5 * ATR toward target AND RSI
           moved deeper into thesis territory by >= 3 points.
        3. CONFIRMED if the same category still fires on live data and the
           stop-loss / regime gates haven't escalated.
        4. WEAKENING otherwise (the thesis hasn't broken yet but the market
           isn't validating it either).
    """
    direction = _signal_direction(persisted.category, persisted.direction)
    notes: List[str] = []
    live_categories_set = set(live_categories)

    distance_to_stop_pct = _distance_pct(live_price, persisted.stop_loss)
    distance_to_t1_pct = _distance_pct(live_price, persisted.target_1)

    score_delta: Optional[float] = None
    if live_score is not None and persisted.score is not None:
        score_delta = float(live_score) - float(persisted.score)

    # ----- Hard invalidation gates -----
    if _stop_violated(direction, live_price, persisted.stop_loss):
        notes.append(
            f"Live price {live_price:.2f} breached stop {persisted.stop_loss:.2f}"
        )
        return VerificationRecord(
            signal_id=persisted.id,
            symbol=persisted.symbol,
            category=persisted.category,
            status=STATUS_INVALIDATED,
            live_close=float(live_price),
            live_rsi=live_rsi,
            live_adx=live_adx,
            live_regime=live_regime,
            score_delta=score_delta,
            distance_to_stop_pct=distance_to_stop_pct,
            distance_to_t1_pct=distance_to_t1_pct,
            notes=notes,
        )

    if _regime_contradicts(direction, live_regime):
        notes.append(f"Regime flipped to {live_regime} against thesis")
        return VerificationRecord(
            signal_id=persisted.id,
            symbol=persisted.symbol,
            category=persisted.category,
            status=STATUS_INVALIDATED,
            live_close=float(live_price),
            live_rsi=live_rsi,
            live_adx=live_adx,
            live_regime=live_regime,
            score_delta=score_delta,
            distance_to_stop_pct=distance_to_stop_pct,
            distance_to_t1_pct=distance_to_t1_pct,
            notes=notes,
        )

    same_category_fires = persisted.category in live_categories_set

    # ----- STRENGTHENED gate -----
    progress_atr = _atr_progress(direction, live_price, persisted.entry, live_atr)
    rsi_delta: Optional[float] = None
    if live_rsi is not None and persisted.persisted_rsi is not None:
        rsi_delta = float(live_rsi) - float(persisted.persisted_rsi)

    if (
        same_category_fires
        and progress_atr is not None
        and progress_atr >= 0.5
        and rsi_delta is not None
        and (
            (direction == "long" and rsi_delta >= 3.0)
            or (direction == "short" and rsi_delta <= -3.0)
            # Neutral categories don't have a thesis direction; we never
            # promote them to STRENGTHENED.
        )
    ):
        notes.append(
            f"Price advanced {progress_atr:.1f} ATR; RSI shifted {rsi_delta:+.1f}"
        )
        return VerificationRecord(
            signal_id=persisted.id,
            symbol=persisted.symbol,
            category=persisted.category,
            status=STATUS_STRENGTHENED,
            live_close=float(live_price),
            live_rsi=live_rsi,
            live_adx=live_adx,
            live_regime=live_regime,
            score_delta=score_delta,
            distance_to_stop_pct=distance_to_stop_pct,
            distance_to_t1_pct=distance_to_t1_pct,
            notes=notes,
        )

    # ----- CONFIRMED vs WEAKENING -----
    if same_category_fires:
        notes.append(f"{persisted.category} still fires on live re-evaluation")
        return VerificationRecord(
            signal_id=persisted.id,
            symbol=persisted.symbol,
            category=persisted.category,
            status=STATUS_CONFIRMED,
            live_close=float(live_price),
            live_rsi=live_rsi,
            live_adx=live_adx,
            live_regime=live_regime,
            score_delta=score_delta,
            distance_to_stop_pct=distance_to_stop_pct,
            distance_to_t1_pct=distance_to_t1_pct,
            notes=notes,
        )

    notes.append(f"{persisted.category} no longer fires on live data; stop intact")
    return VerificationRecord(
        signal_id=persisted.id,
        symbol=persisted.symbol,
        category=persisted.category,
        status=STATUS_WEAKENING,
        live_close=float(live_price),
        live_rsi=live_rsi,
        live_adx=live_adx,
        live_regime=live_regime,
        score_delta=score_delta,
        distance_to_stop_pct=distance_to_stop_pct,
        distance_to_t1_pct=distance_to_t1_pct,
        notes=notes,
    )


__all__ = [
    "STATUS_CONFIRMED",
    "STATUS_WEAKENING",
    "STATUS_INVALIDATED",
    "STATUS_STRENGTHENED",
    "ALL_STATUSES",
    "PersistedSignal",
    "VerificationRecord",
    "project_today_bar",
    "verify_signal",
]
