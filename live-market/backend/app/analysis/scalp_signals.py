"""Scalp setup catalog (RANGE_BOUND regime only).

Six setups, three pairs LONG/SHORT, all targeting 5-15 minute holds:

  RANGE_BOUNCE_LONG / SHORT      - bounce off intraday support / resistance
  FALSE_BREAKOUT_LONG / SHORT    - whipsaw back inside the range
  VWAP_RECLAIM_LONG / SHORT      - reclaim of intraday VWAP from the wrong side

Sizing (config-driven):

  target = SCALP_TARGET_SPOT_PCT * spot       (default 0.5%)
  stop   = SCALP_STOP_SPOT_PCT  * spot        (default 0.3%)

T1 is half-target (mid-range or 0.25% spot, whichever is closer); T2 is
the full target.

Each setup carries an `invalidation` level (== stop). The pipeline rejects
setups missing one (defensive; not expected to fire from this module).

Pure: no DB, no I/O. Returns a list of `ScalpSetupRecord`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from ..config import get_settings
from . import indicators
from .range_detector import RangeLevels


@dataclass(frozen=True)
class ScalpSetupRecord:
    symbol: str
    category: str
    direction: str         # LONG | SHORT
    score: float           # 0..100
    spot_entry: float
    spot_stop: float
    spot_t1: float
    spot_t2: float
    spot_invalidation: float
    reasons: List[str] = field(default_factory=list)


def _round(x: float) -> float:
    return round(float(x), 2)


def _long_plan(
    spot: float, *, stop_anchor: float, target_anchor: Optional[float] = None,
) -> tuple[float, float, float, float]:
    """Build (entry, stop, t1, t2) for a LONG scalp.

    `stop_anchor` is the level the setup invalidates below (e.g. range
    support minus a buffer). The actual stop is the wider of (stop_anchor,
    spot - cfg stop %).

    `target_anchor` is the natural target (e.g. range mid). If supplied
    and tighter than the cfg target, we use it for T1 and place T2 at the
    cfg target. Otherwise T1 = halfway, T2 = cfg target.
    """
    cfg = get_settings()
    stop_pct = cfg.SCALP_STOP_SPOT_PCT
    tgt_pct = cfg.SCALP_TARGET_SPOT_PCT

    stop_pct_dist = spot - spot * (1 - stop_pct)
    stop = min(stop_anchor, spot - stop_pct_dist)

    cfg_target = spot * (1 + tgt_pct)
    if target_anchor is not None and target_anchor < cfg_target:
        t1 = target_anchor
        t2 = cfg_target
    else:
        t1 = spot + (cfg_target - spot) * 0.5
        t2 = cfg_target
    return _round(spot), _round(stop), _round(t1), _round(t2)


def _short_plan(
    spot: float, *, stop_anchor: float, target_anchor: Optional[float] = None,
) -> tuple[float, float, float, float]:
    cfg = get_settings()
    stop_pct = cfg.SCALP_STOP_SPOT_PCT
    tgt_pct = cfg.SCALP_TARGET_SPOT_PCT

    stop_pct_dist = spot * (1 + stop_pct) - spot
    stop = max(stop_anchor, spot + stop_pct_dist)

    cfg_target = spot * (1 - tgt_pct)
    if target_anchor is not None and target_anchor > cfg_target:
        t1 = target_anchor
        t2 = cfg_target
    else:
        t1 = spot - (spot - cfg_target) * 0.5
        t2 = cfg_target
    return _round(spot), _round(stop), _round(t1), _round(t2)


def _score(reasons: List[str], cap: int = 4) -> float:
    if not reasons:
        return 0.0
    return min(100.0, (len(reasons) / cap) * 100.0)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def evaluate(
    symbol: str,
    bars_1m: pd.DataFrame,
    *,
    levels: RangeLevels,
    vwap_value: Optional[float] = None,
) -> List[ScalpSetupRecord]:
    """Run the scalp catalog. Returns matching setups only.

    Caller is responsible for gating this on `regime == RANGE_BOUND` -
    we don't re-check here. The function still validates inputs and is
    safe to call with any frame; it just won't emit anything if the
    market state doesn't match a known setup.
    """
    out: List[ScalpSetupRecord] = []
    if bars_1m is None or len(bars_1m) < 5 or levels is None:
        return out

    last = bars_1m.iloc[-1]
    prev = bars_1m.iloc[-2]
    last3 = bars_1m.tail(3)
    spot = float(last["close"])
    if spot <= 0:
        return out

    rsi_series = indicators.rsi(bars_1m["close"], 14)
    rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0

    support_dist_pct = (spot - levels.support) / spot
    resistance_dist_pct = (levels.resistance - spot) / spot

    # ---- RANGE_BOUNCE_LONG ----
    if (
        0 <= support_dist_pct <= 0.0015            # within 0.15% of support
        and last3["low"].min() >= levels.support * 0.999
        and rsi_val < 50
    ):
        reasons = [
            f"price within {support_dist_pct*100:.2f}% of intraday support",
            f"last 3 bars holding above support {levels.support:.2f}",
            f"RSI {rsi_val:.0f} below midline",
        ]
        stop_anchor = levels.support - 0.001 * spot   # 0.1% below support
        entry, stop, t1, t2 = _long_plan(
            spot, stop_anchor=stop_anchor, target_anchor=levels.mid,
        )
        out.append(ScalpSetupRecord(
            symbol=symbol, category="RANGE_BOUNCE_LONG", direction="LONG",
            score=_score(reasons),
            spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
            spot_invalidation=stop, reasons=reasons,
        ))

    # ---- RANGE_BOUNCE_SHORT ----
    if (
        0 <= resistance_dist_pct <= 0.0015
        and last3["high"].max() <= levels.resistance * 1.001
        and rsi_val > 50
    ):
        reasons = [
            f"price within {resistance_dist_pct*100:.2f}% of intraday resistance",
            f"last 3 bars capped below resistance {levels.resistance:.2f}",
            f"RSI {rsi_val:.0f} above midline",
        ]
        stop_anchor = levels.resistance + 0.001 * spot
        entry, stop, t1, t2 = _short_plan(
            spot, stop_anchor=stop_anchor, target_anchor=levels.mid,
        )
        out.append(ScalpSetupRecord(
            symbol=symbol, category="RANGE_BOUNCE_SHORT", direction="SHORT",
            score=_score(reasons),
            spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
            spot_invalidation=stop, reasons=reasons,
        ))

    # ---- FALSE_BREAKOUT_LONG (whipsaw below support) ----
    if (
        prev["low"] < levels.support
        and last["close"] > levels.support
        and last["close"] > last["open"]            # bullish body
    ):
        reasons = [
            f"prev bar broke {levels.support:.2f} support to {prev['low']:.2f}",
            f"current bar reclaimed support, close {last['close']:.2f}",
            "bullish body confirms reclaim",
        ]
        stop_anchor = float(prev["low"]) - 0.001 * spot
        entry, stop, t1, t2 = _long_plan(
            spot, stop_anchor=stop_anchor, target_anchor=levels.mid,
        )
        out.append(ScalpSetupRecord(
            symbol=symbol, category="FALSE_BREAKOUT_LONG", direction="LONG",
            score=_score(reasons),
            spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
            spot_invalidation=stop, reasons=reasons,
        ))

    # ---- FALSE_BREAKOUT_SHORT (whipsaw above resistance) ----
    if (
        prev["high"] > levels.resistance
        and last["close"] < levels.resistance
        and last["close"] < last["open"]            # bearish body
    ):
        reasons = [
            f"prev bar broke {levels.resistance:.2f} resistance to {prev['high']:.2f}",
            f"current bar rejected, close {last['close']:.2f}",
            "bearish body confirms rejection",
        ]
        stop_anchor = float(prev["high"]) + 0.001 * spot
        entry, stop, t1, t2 = _short_plan(
            spot, stop_anchor=stop_anchor, target_anchor=levels.mid,
        )
        out.append(ScalpSetupRecord(
            symbol=symbol, category="FALSE_BREAKOUT_SHORT", direction="SHORT",
            score=_score(reasons),
            spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
            spot_invalidation=stop, reasons=reasons,
        ))

    # ---- VWAP_RECLAIM (only when we have a VWAP) ----
    if vwap_value is not None and vwap_value > 0:
        # LONG: prev bar closed below VWAP, current bar back above.
        if (
            prev["close"] < vwap_value
            and last["close"] > vwap_value
            and last["close"] > last["open"]
        ):
            reasons = [
                f"prev close {prev['close']:.2f} < VWAP {vwap_value:.2f}",
                f"current close {last['close']:.2f} reclaimed VWAP",
                "bullish body on reclaim bar",
            ]
            stop_anchor = float(prev["low"]) - 0.001 * spot
            target = max(vwap_value + (levels.resistance - vwap_value) * 0.6, vwap_value + 0.002 * spot)
            entry, stop, t1, t2 = _long_plan(
                spot, stop_anchor=stop_anchor, target_anchor=target,
            )
            out.append(ScalpSetupRecord(
                symbol=symbol, category="VWAP_RECLAIM_LONG", direction="LONG",
                score=_score(reasons),
                spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
                spot_invalidation=stop, reasons=reasons,
            ))
        # SHORT: prev close above VWAP, current bar lost it.
        if (
            prev["close"] > vwap_value
            and last["close"] < vwap_value
            and last["close"] < last["open"]
        ):
            reasons = [
                f"prev close {prev['close']:.2f} > VWAP {vwap_value:.2f}",
                f"current close {last['close']:.2f} lost VWAP",
                "bearish body on rejection bar",
            ]
            stop_anchor = float(prev["high"]) + 0.001 * spot
            target = min(vwap_value - (vwap_value - levels.support) * 0.6, vwap_value - 0.002 * spot)
            entry, stop, t1, t2 = _short_plan(
                spot, stop_anchor=stop_anchor, target_anchor=target,
            )
            out.append(ScalpSetupRecord(
                symbol=symbol, category="VWAP_RECLAIM_SHORT", direction="SHORT",
                score=_score(reasons),
                spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
                spot_invalidation=stop, reasons=reasons,
            ))

    return out


__all__ = ["ScalpSetupRecord", "evaluate"]
