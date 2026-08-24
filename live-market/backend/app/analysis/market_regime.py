"""Intraday regime classifier: TRENDING_UP / TRENDING_DOWN / RANGE_BOUND / CHOPPY.

This is the central gate: SCALP setups only fire while the regime is
RANGE_BOUND, SWING setups only while TRENDING_UP / TRENDING_DOWN. CHOPPY
deliberately emits nothing - silence is better than noise.

Inputs
------
* `bars_1m`   - DataFrame of 1-min OHLCV for the current session, ASC time.
* `daily_atr` - latest daily ATR(14) read from the parent app's CSV cache.
* `daily_adx` - latest daily ADX(14) read from the same source.
* `vwap`      - latest intraday VWAP (None to skip the VWAP-alignment check).

Output
------
`RegimeResult` with the label, a list of human reasons, and the raw
metrics that drove the decision (also persisted on `RegimeSnapshot` for
the dashboard).

Pure function. No DB / no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from ..config import get_settings
from . import indicators

REGIME_TRENDING_UP = "TRENDING_UP"
REGIME_TRENDING_DOWN = "TRENDING_DOWN"
REGIME_RANGE_BOUND = "RANGE_BOUND"
REGIME_CHOPPY = "CHOPPY"


@dataclass(frozen=True)
class RegimeResult:
    regime: str
    spot: float
    daily_adx: Optional[float]
    bb_width_pct: Optional[float]
    ema_spread_pct: Optional[float]
    realized_range_pct: Optional[float]
    atr_pct: Optional[float]
    vwap: Optional[float]
    reasons: List[str] = field(default_factory=list)


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    return f


def classify(
    bars_1m: pd.DataFrame,
    *,
    daily_atr: Optional[float],
    daily_adx: Optional[float],
    vwap: Optional[float] = None,
) -> RegimeResult:
    """Classify the current intraday regime for one index.

    Falls back to CHOPPY (the safest option) whenever:
      * Fewer than 30 1-min bars are available (early in the session).
      * Daily ADX is missing (parent app's daily CSV not yet refreshed).
      * Conflicting signals (e.g. trending_strength satisfied but EMAs
        crossed against the daily trend direction).
    """
    cfg = get_settings()

    if bars_1m is None or bars_1m.empty:
        return RegimeResult(
            regime=REGIME_CHOPPY, spot=0.0,
            daily_adx=daily_adx, bb_width_pct=None, ema_spread_pct=None,
            realized_range_pct=None, atr_pct=None, vwap=vwap,
            reasons=["no intraday bars yet"],
        )

    spot = float(bars_1m["close"].iloc[-1])
    n_bars = len(bars_1m)

    if n_bars < 30:
        return RegimeResult(
            regime=REGIME_CHOPPY, spot=spot,
            daily_adx=daily_adx, bb_width_pct=None, ema_spread_pct=None,
            realized_range_pct=None, atr_pct=None, vwap=vwap,
            reasons=[f"only {n_bars} 1-min bars (need >=30)"],
        )

    close = bars_1m["close"]
    ema9 = indicators.ema(close, 9).iloc[-1]
    ema21 = indicators.ema(close, 21).iloc[-1]

    bb = indicators.bollinger(close, 20, 2.0)
    bb_upper = bb["bb_upper"].iloc[-1]
    bb_lower = bb["bb_lower"].iloc[-1]
    bb_width_pct = (bb_upper - bb_lower) / spot if spot > 0 else 0.0
    bb_width_avg20 = bb["bb_width"].tail(20).mean() if not bb["bb_width"].empty else float("nan")

    realized_range = float(bars_1m["high"].max() - bars_1m["low"].min())
    realized_range_pct = realized_range / spot if spot > 0 else 0.0
    atr_pct = (daily_atr / spot) if (daily_atr and spot > 0) else 0.0
    ema_spread_pct = abs(float(ema9) - float(ema21)) / spot if spot > 0 else 0.0

    reasons: List[str] = []
    daily_adx_f = _safe_float(daily_adx)

    # ---- Trending gate ----
    trending = (
        daily_adx_f is not None and daily_adx_f >= cfg.REGIME_TREND_ADX_MIN
        and ema_spread_pct > cfg.REGIME_TREND_EMA_SPREAD_PCT
        and atr_pct > 0 and realized_range_pct > 0.5 * atr_pct
    )

    # ---- Range-bound gate ----
    bb_squeeze = (
        bb_width_avg20 == bb_width_avg20  # NaN-check
        and bb_width_avg20 > 0
        and bb["bb_width"].iloc[-1] < cfg.REGIME_RANGE_BB_SQUEEZE * bb_width_avg20
    )
    range_bound = (
        daily_adx_f is not None and daily_adx_f < cfg.REGIME_RANGE_ADX_MAX
        and bb_squeeze
        and atr_pct > 0 and realized_range_pct < 0.7 * atr_pct
    )

    if trending:
        if ema9 > ema21 and (vwap is None or spot >= vwap):
            reasons.append(f"daily ADX {daily_adx_f:.1f} >= {cfg.REGIME_TREND_ADX_MIN:.0f}")
            reasons.append(f"EMA9>EMA21 spread {ema_spread_pct*100:.2f}%")
            if vwap is not None:
                reasons.append("price above VWAP")
            reasons.append(f"session range {realized_range_pct*100:.2f}% > 0.5x daily ATR%")
            return RegimeResult(
                regime=REGIME_TRENDING_UP, spot=spot,
                daily_adx=daily_adx_f, bb_width_pct=float(bb_width_pct),
                ema_spread_pct=float(ema_spread_pct),
                realized_range_pct=float(realized_range_pct), atr_pct=float(atr_pct),
                vwap=vwap, reasons=reasons,
            )
        if ema9 < ema21 and (vwap is None or spot <= vwap):
            reasons.append(f"daily ADX {daily_adx_f:.1f} >= {cfg.REGIME_TREND_ADX_MIN:.0f}")
            reasons.append(f"EMA9<EMA21 spread {ema_spread_pct*100:.2f}%")
            if vwap is not None:
                reasons.append("price below VWAP")
            reasons.append(f"session range {realized_range_pct*100:.2f}% > 0.5x daily ATR%")
            return RegimeResult(
                regime=REGIME_TRENDING_DOWN, spot=spot,
                daily_adx=daily_adx_f, bb_width_pct=float(bb_width_pct),
                ema_spread_pct=float(ema_spread_pct),
                realized_range_pct=float(realized_range_pct), atr_pct=float(atr_pct),
                vwap=vwap, reasons=reasons,
            )
        # Trending strength present but EMA / VWAP disagree -> conflicting,
        # fall through to choppy.
        reasons.append("trending strength present but EMA/VWAP disagree")

    if range_bound:
        reasons.append(f"daily ADX {daily_adx_f:.1f} < {cfg.REGIME_RANGE_ADX_MAX:.0f}")
        reasons.append(f"BB width squeeze ({cfg.REGIME_RANGE_BB_SQUEEZE:.2f}x avg)")
        reasons.append(f"session range {realized_range_pct*100:.2f}% < 0.7x daily ATR%")
        return RegimeResult(
            regime=REGIME_RANGE_BOUND, spot=spot,
            daily_adx=daily_adx_f, bb_width_pct=float(bb_width_pct),
            ema_spread_pct=float(ema_spread_pct),
            realized_range_pct=float(realized_range_pct), atr_pct=float(atr_pct),
            vwap=vwap, reasons=reasons,
        )

    if not reasons:
        if daily_adx_f is None:
            reasons.append("daily ADX unavailable")
        else:
            reasons.append(f"no trending or range gate satisfied (ADX={daily_adx_f:.1f})")
    return RegimeResult(
        regime=REGIME_CHOPPY, spot=spot,
        daily_adx=daily_adx_f, bb_width_pct=float(bb_width_pct),
        ema_spread_pct=float(ema_spread_pct),
        realized_range_pct=float(realized_range_pct), atr_pct=float(atr_pct),
        vwap=vwap, reasons=reasons,
    )


__all__ = [
    "REGIME_TRENDING_UP",
    "REGIME_TRENDING_DOWN",
    "REGIME_RANGE_BOUND",
    "REGIME_CHOPPY",
    "RegimeResult",
    "classify",
]
