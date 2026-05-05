"""Historical / replay engine.

For a given as-of date, slice each cached symbol's CSV to `df[: as_of]`,
compute indicators on the slice (no look-ahead), evaluate signals, adapt
to ScreenerSignal, run the decision engine, and feed survivors to sizing
and the order simulator.

Used for both *replay* (multi-day loop) and *historical simulation* of a
single day from `data/ohlcv` CSVs.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from ..analysis import indicators as ind_mod
from ..analysis.regime import classify
from ..analysis.signals import evaluate_symbol
from ..core.universe import all_symbols
from ..data import csv_store
from ..models.paper_schemas import ScreenerSignal
from .adapter import (
    ALLOWED_SETUPS,
    CATEGORY_TO_SETUP,
    REGIME_TO_TREND,
    confidence_bucket,
    risk_level_from_atr_pct,
    risk_reward,
    _entry_zone,
)
from .regime import aggregate as aggregate_regime
from .config import PaperConfigSnapshot

log = logging.getLogger(__name__)


@dataclass
class DaySnapshot:
    """Candles + signals + per-stock regimes for a single as-of date."""
    as_of: date
    candidates: List[ScreenerSignal]
    market_regime: str
    last_close_by_symbol: Dict[str, float]
    next_candle_by_symbol: Dict[str, pd.DataFrame]


def _signal_record_to_screener(
    rec, *, market_regime: str, snapshot_close: float, atr_pct: Optional[float],
) -> ScreenerSignal:
    """Reuse the screener SignalRecord -> ScreenerSignal shape locally
    (without writing rows to the screener DB)."""
    setup = CATEGORY_TO_SETUP.get(rec.category, rec.category)
    plan = rec.plan
    indicators = rec.indicators or {}
    atr14 = indicators.get("atr14")
    rsi = indicators.get("rsi14")
    vol_ratio = indicators.get("vol_ratio")
    trend = REGIME_TO_TREND.get(rec.regime, "Sideways")

    entry = float(plan.entry) if plan else None
    stop = float(plan.stop_loss) if plan else None
    t1 = float(plan.target_1) if plan else None
    t2 = float(plan.target_2) if plan else None

    entry_low, entry_high = _entry_zone(entry, atr14)
    rr = risk_reward(entry, stop, t1)

    return ScreenerSignal(
        symbol=rec.symbol,
        date=rec.as_of_date,
        close=float(snapshot_close),
        trend=trend,
        setup_type=setup,
        score=float(rec.score),
        confidence=confidence_bucket(float(rec.confidence)),
        risk_level=risk_level_from_atr_pct(atr_pct),
        risk_reward=rr,
        entry=entry,
        entry_zone_low=entry_low,
        entry_zone_high=entry_high,
        stop_loss=stop,
        target_1=t1,
        target_2=t2,
        rsi=float(rsi) if rsi is not None else None,
        volume_ratio=float(vol_ratio) if vol_ratio is not None else None,
        atr_percent=float(atr_pct) if atr_pct is not None else None,
        market_regime=market_regime,
    )


def _slice_to(df: pd.DataFrame, as_of: date) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = pd.Timestamp(as_of)
    return df.loc[df.index <= cutoff]


def _candles_after(df: pd.DataFrame, as_of: date, *, n: int = 30) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = pd.Timestamp(as_of)
    return df.loc[df.index > cutoff].head(n)


def _last_trading_date(df: pd.DataFrame, as_of: date) -> Optional[date]:
    sliced = _slice_to(df, as_of)
    if sliced.empty:
        return None
    return sliced.index[-1].date()


def build_day_snapshot(
    as_of: date,
    *,
    symbols: Optional[List[str]] = None,
    lookback_after_days: int = 30,
) -> DaySnapshot:
    """Return everything needed to run paper-bot logic *as if* it were `as_of`."""
    syms = symbols or all_symbols()

    candidates: List[ScreenerSignal] = []
    last_close: Dict[str, float] = {}
    next_candles: Dict[str, pd.DataFrame] = {}
    regimes: List[str] = []
    chosen_per_symbol: Dict[str, ScreenerSignal] = {}

    for symbol in syms:
        full = csv_store.load(symbol)
        if full.empty:
            continue
        sliced = _slice_to(full, as_of)
        if sliced.empty or len(sliced) < 200:
            continue

        try:
            enriched = ind_mod.compute_all(sliced)
        except Exception:  # noqa: BLE001
            log.exception("indicators failed for %s on %s", symbol, as_of)
            continue
        regime, _detail = classify(enriched)
        regimes.append(regime)
        atr_pct = float(enriched.iloc[-1].get("atr_pct")) if enriched.iloc[-1].get("atr_pct") is not None else None
        last_close_v = float(enriched.iloc[-1]["close"])
        last_close[symbol] = last_close_v
        next_candles[symbol] = _candles_after(full, as_of, n=lookback_after_days)

        recs = evaluate_symbol(symbol, sliced, df_enriched=enriched)
        # Keep only the *best* actionable setup per symbol (max screener score).
        best: Optional[ScreenerSignal] = None
        for rec in recs:
            if rec.plan is None:
                continue
            ss = _signal_record_to_screener(
                rec,
                market_regime="Sideways",  # placeholder; finalised after aggregation
                snapshot_close=last_close_v,
                atr_pct=atr_pct,
            )
            if ss.setup_type not in ALLOWED_SETUPS:
                continue
            if best is None or ss.score > best.score:
                best = ss
        if best is not None:
            chosen_per_symbol[symbol] = best

    market_regime = aggregate_regime(regimes)
    for ss in chosen_per_symbol.values():
        ss.market_regime = market_regime
        candidates.append(ss)
    candidates.sort(key=lambda s: s.score, reverse=True)

    return DaySnapshot(
        as_of=as_of,
        candidates=candidates,
        market_regime=market_regime,
        last_close_by_symbol=last_close,
        next_candle_by_symbol=next_candles,
    )


def _next_business_day(d: date) -> date:
    # CSV is daily candles; we don't know the calendar, so just step forward.
    return d + timedelta(days=1)


def replay_dates(start: date, end: date) -> List[date]:
    out: List[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur = _next_business_day(cur)
    return out
