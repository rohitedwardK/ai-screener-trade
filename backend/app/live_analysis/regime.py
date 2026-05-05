"""Live market regime classifier (Nifty 50 spot).

Pure function. Reuses the same z-score / VWAP-deviation / OLS-slope language
as the per-symbol MFCS so the regime gate is internally consistent with the
factors it modulates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .config import LiveAnalysisConfigSnapshot
from .strategy import _ols_slope


@dataclass(frozen=True)
class RegimeResult:
    """Output of `classify_market`."""
    regime: str            # RISK_ON | NEUTRAL | RISK_OFF
    z: float
    slope: float
    vwap_dev: float
    last: Optional[float]


def classify_market(
    nifty_samples: Sequence[float],
    *,
    cfg: LiveAnalysisConfigSnapshot,
    nifty_vwap: Optional[float] = None,
    nifty_atr_3m: Optional[float] = None,
) -> RegimeResult:
    """Map Nifty 50 spot 3-min samples to a regime label.

    With insufficient data (< 2 samples or zero ATR proxy) we return NEUTRAL
    so the engine can still emit (heavily dampened) decisions.
    """
    n = len(nifty_samples)
    if n < 2:
        return RegimeResult(regime="NEUTRAL", z=0.0, slope=0.0, vwap_dev=0.0, last=None)

    p0 = float(nifty_samples[0])
    p_last = float(nifty_samples[-1])

    # ATR fallback: realised range when we don't have a precomputed ATR.
    # Index moves are tiny in absolute terms so a tiny floor avoids div-by-0.
    atr = float(nifty_atr_3m) if nifty_atr_3m and nifty_atr_3m > 0 else max(
        max(nifty_samples) - min(nifty_samples), 1e-9,
    )

    z = (p_last - p0) / atr
    slope = _ols_slope(nifty_samples) * (n - 1) / atr
    vwap_dev = 0.0
    if nifty_vwap and nifty_vwap > 0:
        vwap_dev = (p_last - nifty_vwap) / nifty_vwap

    # Combine z with a small VWAP tilt: VWAP-aligned moves get a bonus, those
    # fading into VWAP get penalised. Slope is already directional so we sum.
    composite = z + 0.5 * slope + 5.0 * vwap_dev * (1 if z >= 0 else -1)

    if composite >= cfg.regime_risk_on_z:
        regime = "RISK_ON"
    elif composite <= cfg.regime_risk_off_z:
        regime = "RISK_OFF"
    else:
        regime = "NEUTRAL"

    return RegimeResult(
        regime=regime,
        z=round(float(z), 4),
        slope=round(float(slope), 4),
        vwap_dev=round(float(vwap_dev), 6),
        last=p_last,
    )


__all__ = ["RegimeResult", "classify_market"]
