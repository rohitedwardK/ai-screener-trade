"""Multi-Factor Confluence Score (MFCS) - the heart of Live Analysis Mode.

Pure mathematical scorer. Given a closed 6-sample / 15-min observation
window plus its derived aggregates (VWAP, RVOL, ATR, RSI, EMA20) and the
current market regime, it produces a `Decision`:

    Decision(direction in {LONG, SHORT, HOLD}, confidence 0-100,
             long_raw, short_raw, invalidation, factors)

The factors mirror the institutional-grade intraday confluence approach
used by quant desks:

    z          : standardized 15-min momentum (P_5 - P_0) / ATR_3m
    slope      : OLS beta from P_t = alpha + beta * t + eps
    vwap_dev   : (P_5 - VWAP) / VWAP
    ema_dev    : (P_5 - EMA20_3m) / EMA20_3m  (the user's literal 20-EMA rule)
    rvol       : log(1 + RVOL) clipped, capturing institutional volume bursts
    body       : last-bar body / range, microstructure conviction proxy
    rsi_pen    : asymmetric overbought/oversold penalty
    regime     : multiplier in [-1, +1] gating LONG vs SHORT

Composite (weights from `LiveAnalysisConfigSnapshot.weights`):

    LONG_raw  = w1*z + w2*slope_n + w3*vwap_dev_n + w4*ema_dev_n
              + w5*rvol_score + w6*body_score - w7*overbought_pen
    LONG_raw *= regime_long_mult
    SHORT_raw = mirror with sign flips and oversold_pen
    confidence = sigmoid(LONG_raw - SHORT_raw) * 100

Decision rule:
    LONG  if (LONG_raw - SHORT_raw) > +decision_threshold and confidence >= conf_thr
    SHORT if (LONG_raw - SHORT_raw) < -decision_threshold and confidence >= conf_thr
    else HOLD

Invalidation (project hard rule, even on analysis-only output):
    LONG  : min(samples) - 0.5 * ATR_3m
    SHORT : max(samples) + 0.5 * ATR_3m

Inputs are plain Python floats / lists - no DB, no network. Fully testable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .config import LiveAnalysisConfigSnapshot


# Regime multipliers. RISK_ON allows full LONG conviction and dampens SHORT;
# RISK_OFF is the mirror; NEUTRAL is symmetric and slightly compressed.
REGIME_LONG_MULT = {
    "RISK_ON":  1.0,
    "NEUTRAL":  0.6,
    "RISK_OFF": 0.0,
}
REGIME_SHORT_MULT = {
    "RISK_ON":  0.0,
    "NEUTRAL":  0.6,
    "RISK_OFF": 1.0,
}


@dataclass(frozen=True)
class ObservationWindow:
    """Inputs to the MFCS scorer for one symbol's closed observation window."""
    symbol: str
    samples: Sequence[float]       # 6 prices, 3 min apart, oldest first
    high_3m: Optional[float] = None  # latest 3-min candle high
    low_3m: Optional[float] = None
    close_3m: Optional[float] = None
    open_3m: Optional[float] = None
    vwap: Optional[float] = None     # intraday VWAP at decision time
    rvol: Optional[float] = None     # observed volume / typical 15m volume
    atr_3m: Optional[float] = None   # ATR(14) on 3-min bars
    rsi_3m: Optional[float] = None   # RSI(14) on 3-min bars
    ema20_3m: Optional[float] = None
    regime: str = "NEUTRAL"


@dataclass(frozen=True)
class Decision:
    """MFCS output. Frozen so `engine` can persist it without surprises."""
    symbol: str
    direction: str              # LONG | SHORT | HOLD
    confidence: float           # 0-100
    long_raw: float
    short_raw: float
    invalidation: Optional[float]
    regime: str
    factors: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def _clip(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _sigmoid(x: float) -> float:
    # Saturating logistic; clamp the exponent so a runaway score doesn't
    # produce inf and contaminate the float arithmetic.
    if x > 50.0:
        return 1.0
    if x < -50.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _ols_slope(prices: Sequence[float]) -> float:
    """OLS beta of P_t = alpha + beta * t + eps with t = 0..n-1.

    Returns 0.0 for fewer than 2 points. Robust to a single late spike vs a
    last-tick endpoint comparison.
    """
    n = len(prices)
    if n < 2:
        return 0.0
    t_mean = (n - 1) / 2.0
    p_mean = sum(prices) / n
    num = 0.0
    den = 0.0
    for i, p in enumerate(prices):
        dt = i - t_mean
        num += dt * (p - p_mean)
        den += dt * dt
    if den == 0:
        return 0.0
    return num / den


# ---------------------------------------------------------------------------
# MFCS scorer
# ---------------------------------------------------------------------------
def score_mfcs(
    obs: ObservationWindow,
    cfg: LiveAnalysisConfigSnapshot,
) -> Decision:
    """Compute the MFCS for a closed observation window.

    Always returns a `Decision`. When the input is degenerate (empty samples,
    zero ATR, etc.) we fall back to HOLD with confidence 0 - the scorer never
    raises. This matches the project's "the engine still runs even when data
    is bad" philosophy.
    """
    n = len(obs.samples)
    if n < 2:
        return Decision(
            symbol=obs.symbol,
            direction="HOLD",
            confidence=0.0,
            long_raw=0.0,
            short_raw=0.0,
            invalidation=None,
            regime=obs.regime,
            factors={"reason_no_samples": 1.0},
        )

    p0 = float(obs.samples[0])
    p_last = float(obs.samples[-1])

    # ATR drives the per-symbol volatility normalisation. If we couldn't
    # compute one (e.g. <14 prior bars on day-1), fall back to the realised
    # range of the window itself - keeps the scorer honest rather than
    # exploding into NaNs.
    atr = float(obs.atr_3m) if obs.atr_3m and obs.atr_3m > 0 else max(
        max(obs.samples) - min(obs.samples), 1e-9,
    )

    # ---- Factor 1: standardized 15-min momentum -------------------------
    z_raw = (p_last - p0) / atr
    z = _clip(z_raw, -3.0, 3.0)

    # ---- Factor 2: OLS slope normalised by ATR per step ----------------
    slope_per_step = _ols_slope(obs.samples)
    # Total slope contribution over the window equals slope_per_step * (n-1).
    # Express it in ATR units so it's directly comparable to z.
    slope_total = slope_per_step * (n - 1)
    slope_n = _clip(slope_total / atr, -3.0, 3.0)

    # Volatility scale for percent-deviation factors. Use the relative ATR
    # (atr / price) as the natural denominator; clamp so a tight stock
    # doesn't produce runaway scores.
    sigma_pct = max(atr / max(p_last, 1e-9), 1e-4)

    # ---- Factor 3: VWAP deviation --------------------------------------
    if obs.vwap and obs.vwap > 0:
        vwap_dev_pct = (p_last - obs.vwap) / obs.vwap
        vwap_dev_n = _clip(vwap_dev_pct / sigma_pct, -3.0, 3.0)
    else:
        vwap_dev_pct = 0.0
        vwap_dev_n = 0.0

    # ---- Factor 4: EMA20 (3-min) deviation -----------------------------
    if obs.ema20_3m and obs.ema20_3m > 0:
        ema_dev_pct = (p_last - obs.ema20_3m) / obs.ema20_3m
        ema_dev_n = _clip(ema_dev_pct / sigma_pct, -3.0, 3.0)
    else:
        ema_dev_pct = 0.0
        ema_dev_n = 0.0

    # ---- Factor 5: relative volume (institutional flow proxy) ----------
    if obs.rvol and obs.rvol > 0:
        # log brings the long tail in; clip caps a single freak print at +2.
        rvol_score = _clip(math.log1p(obs.rvol - 1.0), -1.0, 2.0)
    else:
        rvol_score = 0.0

    # ---- Factor 6: body-to-range microstructure ------------------------
    body_score = 0.0
    if obs.high_3m is not None and obs.low_3m is not None and obs.close_3m is not None and obs.open_3m is not None:
        rng = max(obs.high_3m - obs.low_3m, 1e-9)
        body = obs.close_3m - obs.open_3m
        body_ratio = body / rng       # negative = bearish bar
        # Down-weight indecision: only score when |body_ratio| > 0.3.
        if abs(body_ratio) > 0.3:
            body_score = _clip(body_ratio, -1.0, 1.0)

    # ---- Factor 7: asymmetric RSI penalty ------------------------------
    overbought_pen = 0.0
    oversold_pen = 0.0
    if obs.rsi_3m is not None:
        if obs.rsi_3m > 70.0:
            overbought_pen = (obs.rsi_3m - 70.0) / 30.0  # 0..1 from 70..100
        if obs.rsi_3m < 30.0:
            oversold_pen = (30.0 - obs.rsi_3m) / 30.0    # 0..1 from 30..0

    # ---- Composite -----------------------------------------------------
    w = cfg.weights
    long_core = (
        w["w1_z"] * z
        + w["w2_slope"] * slope_n
        + w["w3_vwap"] * vwap_dev_n
        + w["w4_ema20"] * ema_dev_n
        + w["w5_rvol"] * rvol_score
        + w["w6_body"] * body_score
        - w["w7_rsi_penalty"] * overbought_pen
    )
    short_core = (
        w["w1_z"] * (-z)
        + w["w2_slope"] * (-slope_n)
        + w["w3_vwap"] * (-vwap_dev_n)
        + w["w4_ema20"] * (-ema_dev_n)
        + w["w5_rvol"] * rvol_score              # volume helps both directions
        + w["w6_body"] * (-body_score)
        - w["w7_rsi_penalty"] * oversold_pen
    )

    regime_long_mult = REGIME_LONG_MULT.get(obs.regime, 0.6)
    regime_short_mult = REGIME_SHORT_MULT.get(obs.regime, 0.6)
    long_raw = long_core * regime_long_mult
    short_raw = short_core * regime_short_mult

    # Confidence comes from the SIGNED score gap. sigmoid(net) maps to [0,1];
    # rescaling to [0,100] gives a stable display number.
    net = long_raw - short_raw
    confidence = _sigmoid(net) * 100.0
    # Express confidence as distance from neutral (50) so a HOLD doesn't show
    # as 50% conviction by accident.
    display_conf = abs(confidence - 50.0) * 2.0

    direction = "HOLD"
    # A directional decision additionally requires the corresponding raw score
    # to be positive. Without this check the regime gate (which can zero one
    # side) would still emit a LONG on a strong uptrend during RISK_OFF
    # because the SHORT mirror score would be a large negative number,
    # blowing the (long - short) gap wide open.
    if (
        net > cfg.decision_threshold
        and display_conf >= cfg.confidence_threshold
        and long_raw > 0
    ):
        direction = "LONG"
    elif (
        net < -cfg.decision_threshold
        and display_conf >= cfg.confidence_threshold
        and short_raw > 0
    ):
        direction = "SHORT"

    invalidation: Optional[float] = None
    if direction == "LONG":
        invalidation = min(obs.samples) - 0.5 * atr
    elif direction == "SHORT":
        invalidation = max(obs.samples) + 0.5 * atr

    factors = {
        "z": float(z),
        "slope_n": float(slope_n),
        "vwap_dev_n": float(vwap_dev_n),
        "ema_dev_n": float(ema_dev_n),
        "rvol_score": float(rvol_score),
        "body_score": float(body_score),
        "overbought_pen": float(overbought_pen),
        "oversold_pen": float(oversold_pen),
        "regime_long_mult": float(regime_long_mult),
        "regime_short_mult": float(regime_short_mult),
        "atr_used": float(atr),
        "sigma_pct": float(sigma_pct),
        "raw_pct_change": float((p_last - p0) / max(p0, 1e-9) * 100.0),
    }

    return Decision(
        symbol=obs.symbol,
        direction=direction,
        confidence=round(display_conf, 2),
        long_raw=round(long_raw, 4),
        short_raw=round(short_raw, 4),
        invalidation=invalidation,
        regime=obs.regime,
        factors=factors,
    )


__all__ = [
    "ObservationWindow",
    "Decision",
    "score_mfcs",
    "REGIME_LONG_MULT",
    "REGIME_SHORT_MULT",
]
