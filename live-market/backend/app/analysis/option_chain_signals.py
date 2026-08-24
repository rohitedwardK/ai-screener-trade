"""Option-chain analytics: derive directional bias from OI / IV / volume.

Five deterministic signals, all pure functions over an `OptionChainPayload`:

* `compute_pcr`         - Put/Call ratio on OI and on volume (contrarian read).
* `compute_max_pain`    - Strike minimising total option-writer payout at expiry.
* `compute_oi_walls`    - Top-K CE (resistance) + PE (support) strikes by OI.
* `compute_change_oi_bias` - Net CE-writing vs PE-writing flow today.
* `compute_iv_metrics`  - ATM IV + put-vs-call wing skew.

`derive_bias()` fans all five into a single `OptionBias` dataclass with a
BULLISH / BEARISH / NEUTRAL label, 0-100 confidence score, and a list of
human-readable reasons that the UI surfaces verbatim.

Hard rule: read-only analysis. No order placement, no autonomous trading.

These are positioning indicators, NOT predictions. We surface them so the
operator can decide; we never claim "the chain says X will happen".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..data.option_types import OptionChainPayload, OptionRow

# Contrarian PCR-OI thresholds. Tuned for Indian index options where typical
# weekly PCR-OI sits in [0.7, 1.3]. Values outside that envelope are the
# interesting ones; the inside band is treated as neutral noise.
_PCR_BULLISH_MIN = 1.30
_PCR_BEARISH_MAX = 0.70

# Change-in-OI flow thresholds (today's session). Asymmetry above 20% is
# considered directional; below that we don't infer anything.
_FLOW_BIAS_PCT = 0.20

# IV skew threshold (PE wing IV - CE wing IV) as a fraction of ATM IV.
# Positive skew (puts pricier than calls) classically signals fear / risk-off.
_IV_SKEW_THRESHOLD = 0.10  # 10% IV premium on the put side


@dataclass(frozen=True)
class OIWall:
    strike: float
    oi: float
    side: str   # "CE" | "PE"


@dataclass(frozen=True)
class PCRResult:
    pcr_oi: Optional[float]
    pcr_volume: Optional[float]
    total_ce_oi: float
    total_pe_oi: float
    total_ce_vol: float
    total_pe_vol: float


@dataclass(frozen=True)
class ChangeOIBias:
    """Today's CE vs PE OI-add flow. Positive ratios mean *new* OI built today.

    `direction`: BULLISH | BEARISH | NEUTRAL. Heuristic:
      * Net new CE-OI >> net new PE-OI → call writers dominate → BEARISH
        (writers expect spot to stay below their strikes).
      * Net new PE-OI >> net new CE-OI → put writers dominate → BULLISH.
      * Both sides roughly balanced → NEUTRAL.
    """
    ce_oi_added: float
    pe_oi_added: float
    ce_oi_unwound: float
    pe_oi_unwound: float
    direction: str   # BULLISH | BEARISH | NEUTRAL


@dataclass(frozen=True)
class IVMetrics:
    atm_iv: Optional[float]
    ce_wing_iv: Optional[float]   # avg IV of CE strikes 2-4 steps OTM
    pe_wing_iv: Optional[float]   # avg IV of PE strikes 2-4 steps OTM
    skew: Optional[float]         # (pe_wing_iv - ce_wing_iv) / atm_iv
    direction: str                # FEAR | GREED | NEUTRAL (interpretation only)


@dataclass(frozen=True)
class OptionBias:
    label: str          # BULLISH | BEARISH | NEUTRAL
    score: float        # 0..100
    reasons: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_sum(values) -> float:
    return float(sum(v for v in values if v is not None and v > 0))


def _atm_row(chain: OptionChainPayload, spot: float) -> Optional[OptionRow]:
    if not chain.rows or spot <= 0:
        return None
    return min(chain.rows, key=lambda r: abs(r.strike - spot))


# ---------------------------------------------------------------------------
# PCR
# ---------------------------------------------------------------------------
def compute_pcr(chain: OptionChainPayload) -> PCRResult:
    """Total PE OI / total CE OI, and the volume-based counterpart.

    Returns None ratios when the denominator is zero (no CE OI at all).
    """
    rows = chain.rows or []
    total_ce_oi = _safe_sum(r.ce_oi for r in rows)
    total_pe_oi = _safe_sum(r.pe_oi for r in rows)
    total_ce_vol = _safe_sum(r.ce_volume for r in rows)
    total_pe_vol = _safe_sum(r.pe_volume for r in rows)

    pcr_oi = (total_pe_oi / total_ce_oi) if total_ce_oi > 0 else None
    pcr_vol = (total_pe_vol / total_ce_vol) if total_ce_vol > 0 else None
    return PCRResult(
        pcr_oi=pcr_oi,
        pcr_volume=pcr_vol,
        total_ce_oi=total_ce_oi,
        total_pe_oi=total_pe_oi,
        total_ce_vol=total_ce_vol,
        total_pe_vol=total_pe_vol,
    )


# ---------------------------------------------------------------------------
# Max pain
# ---------------------------------------------------------------------------
def compute_max_pain(chain: OptionChainPayload) -> Optional[float]:
    """Strike K that minimises total option-writer payout if spot expires at K.

    For each candidate strike K we sum:
      sum_i max(0, K - K_i) * CE_OI_i      # CE writers pay (K - K_i) when ITM
    + sum_i max(0, K_i - K) * PE_OI_i      # PE writers pay (K_i - K) when ITM

    Max pain = arg min over K of that total. None when no OI data exists.
    """
    rows = [r for r in chain.rows if (r.ce_oi or 0) > 0 or (r.pe_oi or 0) > 0]
    if not rows:
        return None

    best_strike: Optional[float] = None
    best_loss = float("inf")
    for candidate in rows:
        k = candidate.strike
        total_loss = 0.0
        for r in rows:
            ce_oi = r.ce_oi or 0.0
            pe_oi = r.pe_oi or 0.0
            if k > r.strike:
                total_loss += (k - r.strike) * ce_oi
            if r.strike > k:
                total_loss += (r.strike - k) * pe_oi
        if total_loss < best_loss:
            best_loss = total_loss
            best_strike = k
    return best_strike


# ---------------------------------------------------------------------------
# OI walls
# ---------------------------------------------------------------------------
def compute_oi_walls(
    chain: OptionChainPayload, spot: float, *, k: int = 3,
) -> Tuple[List[OIWall], List[OIWall]]:
    """Top-K CE strikes ABOVE spot (resistance) and PE strikes BELOW spot (support).

    Returns `(resistance_walls, support_walls)`, both sorted by OI descending.
    Wall strength = total OI parked there. We deliberately filter "above-spot
    CE" and "below-spot PE" because *the same strike's OI on the other side
    is the wrong wall* (it's writers betting against the spot's current
    position, not for it).
    """
    if not chain.rows or spot <= 0:
        return [], []

    above_ce = [
        OIWall(strike=r.strike, oi=float(r.ce_oi or 0.0), side="CE")
        for r in chain.rows
        if r.strike >= spot and (r.ce_oi or 0.0) > 0
    ]
    below_pe = [
        OIWall(strike=r.strike, oi=float(r.pe_oi or 0.0), side="PE")
        for r in chain.rows
        if r.strike <= spot and (r.pe_oi or 0.0) > 0
    ]
    above_ce.sort(key=lambda w: w.oi, reverse=True)
    below_pe.sort(key=lambda w: w.oi, reverse=True)
    return above_ce[:k], below_pe[:k]


# ---------------------------------------------------------------------------
# Change-in-OI flow
# ---------------------------------------------------------------------------
def compute_change_oi_bias(chain: OptionChainPayload) -> ChangeOIBias:
    """Net OI added today on CE side vs PE side -> directional flow read.

    Convention used here:
      * `change_oi > 0` at a strike means writers ADDED contracts.
      * `change_oi < 0` means existing OI was UNWOUND (buy-to-close).
    """
    rows = chain.rows or []
    ce_added = float(sum((r.ce_change_oi or 0.0) for r in rows if (r.ce_change_oi or 0.0) > 0))
    pe_added = float(sum((r.pe_change_oi or 0.0) for r in rows if (r.pe_change_oi or 0.0) > 0))
    ce_unwound = float(-sum((r.ce_change_oi or 0.0) for r in rows if (r.ce_change_oi or 0.0) < 0))
    pe_unwound = float(-sum((r.pe_change_oi or 0.0) for r in rows if (r.pe_change_oi or 0.0) < 0))

    total = ce_added + pe_added
    if total <= 0:
        return ChangeOIBias(
            ce_oi_added=ce_added, pe_oi_added=pe_added,
            ce_oi_unwound=ce_unwound, pe_oi_unwound=pe_unwound,
            direction="NEUTRAL",
        )
    pe_share = pe_added / total
    if pe_share > 0.5 + _FLOW_BIAS_PCT / 2:
        direction = "BULLISH"           # put writers dominate -> floor expected
    elif pe_share < 0.5 - _FLOW_BIAS_PCT / 2:
        direction = "BEARISH"           # call writers dominate -> ceiling expected
    else:
        direction = "NEUTRAL"
    return ChangeOIBias(
        ce_oi_added=ce_added, pe_oi_added=pe_added,
        ce_oi_unwound=ce_unwound, pe_oi_unwound=pe_unwound,
        direction=direction,
    )


# ---------------------------------------------------------------------------
# IV metrics
# ---------------------------------------------------------------------------
def compute_iv_metrics(chain: OptionChainPayload, spot: float) -> IVMetrics:
    """ATM IV + wing skew. Honest about None when IV data is missing."""
    atm = _atm_row(chain, spot)
    if atm is None:
        return IVMetrics(None, None, None, None, "NEUTRAL")

    atm_ivs = [v for v in (atm.ce_iv, atm.pe_iv) if v is not None and v > 0]
    atm_iv = sum(atm_ivs) / len(atm_ivs) if atm_ivs else None

    # 2-4 step OTM wings (excluding ATM). We pick by index distance not by
    # absolute step so this works for both Nifty (50 step) and BankNifty (100).
    sorted_rows = sorted(chain.rows, key=lambda r: r.strike)
    atm_idx = next(
        (i for i, r in enumerate(sorted_rows) if abs(r.strike - atm.strike) < 1e-6),
        None,
    )
    ce_wing_ivs: List[float] = []
    pe_wing_ivs: List[float] = []
    if atm_idx is not None:
        # Calls 2-4 strikes above ATM are the relevant OTM wing for CE.
        for i in range(atm_idx + 2, min(atm_idx + 5, len(sorted_rows))):
            iv = sorted_rows[i].ce_iv
            if iv is not None and iv > 0:
                ce_wing_ivs.append(float(iv))
        # Puts 2-4 strikes below ATM are the relevant OTM wing for PE.
        for i in range(max(atm_idx - 4, 0), atm_idx - 1):
            iv = sorted_rows[i].pe_iv
            if iv is not None and iv > 0:
                pe_wing_ivs.append(float(iv))

    ce_wing_iv = sum(ce_wing_ivs) / len(ce_wing_ivs) if ce_wing_ivs else None
    pe_wing_iv = sum(pe_wing_ivs) / len(pe_wing_ivs) if pe_wing_ivs else None

    skew: Optional[float] = None
    direction = "NEUTRAL"
    if (
        atm_iv is not None and atm_iv > 0
        and ce_wing_iv is not None and pe_wing_iv is not None
    ):
        skew = (pe_wing_iv - ce_wing_iv) / atm_iv
        if skew > _IV_SKEW_THRESHOLD:
            direction = "FEAR"          # put-side priced richer; classic risk-off
        elif skew < -_IV_SKEW_THRESHOLD:
            direction = "GREED"         # call-side priced richer; FOMO buying
    return IVMetrics(
        atm_iv=atm_iv, ce_wing_iv=ce_wing_iv, pe_wing_iv=pe_wing_iv,
        skew=skew, direction=direction,
    )


# ---------------------------------------------------------------------------
# Derive a single bias from all five signals
# ---------------------------------------------------------------------------
def derive_bias(
    chain: OptionChainPayload,
    spot: float,
    *,
    pcr: Optional[PCRResult] = None,
    max_pain: Optional[float] = None,
    flow: Optional[ChangeOIBias] = None,
    iv: Optional[IVMetrics] = None,
) -> OptionBias:
    """Combine PCR / max-pain / OI flow / IV skew into one directional read.

    Voting model: each signal contributes +1 (bullish), -1 (bearish), or 0
    (neutral / missing). Final label = sign of the sum. Score = (|votes
    cast| / 4) * 100, so a 4-of-4 confirmation reads as 100, a single
    informative signal reads as 25.
    """
    if pcr is None:
        pcr = compute_pcr(chain)
    if max_pain is None:
        max_pain = compute_max_pain(chain)
    if flow is None:
        flow = compute_change_oi_bias(chain)
    if iv is None:
        iv = compute_iv_metrics(chain, spot)

    votes: List[int] = []
    reasons: List[str] = []

    # --- PCR-OI vote ---
    if pcr.pcr_oi is not None:
        if pcr.pcr_oi >= _PCR_BULLISH_MIN:
            votes.append(+1)
            reasons.append(f"PCR-OI {pcr.pcr_oi:.2f} >= {_PCR_BULLISH_MIN} (excess fear -> contrarian bullish)")
        elif pcr.pcr_oi <= _PCR_BEARISH_MAX:
            votes.append(-1)
            reasons.append(f"PCR-OI {pcr.pcr_oi:.2f} <= {_PCR_BEARISH_MAX} (excess greed -> contrarian bearish)")
        else:
            reasons.append(f"PCR-OI {pcr.pcr_oi:.2f} in neutral band")

    # --- Max pain vote ---
    if max_pain is not None and spot > 0:
        gap_pct = (max_pain - spot) / spot
        if gap_pct > 0.005:
            votes.append(+1)
            reasons.append(f"max-pain {max_pain:.0f} is {gap_pct*100:.2f}% above spot (gravity up)")
        elif gap_pct < -0.005:
            votes.append(-1)
            reasons.append(f"max-pain {max_pain:.0f} is {abs(gap_pct)*100:.2f}% below spot (gravity down)")
        else:
            reasons.append(f"max-pain {max_pain:.0f} sits ~at spot (no expiry pull)")

    # --- Change-OI flow vote ---
    if flow.direction == "BULLISH":
        votes.append(+1)
        reasons.append(
            f"net new PE-OI {flow.pe_oi_added:,.0f} > CE-OI {flow.ce_oi_added:,.0f} (put writers floor)"
        )
    elif flow.direction == "BEARISH":
        votes.append(-1)
        reasons.append(
            f"net new CE-OI {flow.ce_oi_added:,.0f} > PE-OI {flow.pe_oi_added:,.0f} (call writers cap)"
        )
    else:
        reasons.append("CE/PE OI flow balanced")

    # --- IV skew vote ---
    if iv.skew is not None:
        if iv.direction == "FEAR":
            # Fear in IV = puts richer. Two interpretations: outright bearish
            # (the market is paying for downside protection) OR contrarian
            # bullish (the move may be over-priced). We side with the
            # short-horizon contrarian read since this whole service operates
            # on intraday-to-3-day horizons.
            votes.append(+1)
            reasons.append(f"IV skew +{iv.skew*100:.1f}% (put wing rich -> contrarian bullish)")
        elif iv.direction == "GREED":
            votes.append(-1)
            reasons.append(f"IV skew {iv.skew*100:.1f}% (call wing rich -> contrarian bearish)")
        else:
            reasons.append(f"IV skew {iv.skew*100:.1f}% (neutral)")

    net = sum(votes)
    cast = len(votes)
    if cast == 0:
        return OptionBias(label="NEUTRAL", score=0.0, reasons=reasons)

    if net > 0:
        label = "BULLISH"
    elif net < 0:
        label = "BEARISH"
    else:
        label = "NEUTRAL"
    score = round(min(100.0, (cast / 4.0) * 100.0 * (abs(net) / max(cast, 1))), 1)
    return OptionBias(label=label, score=score, reasons=reasons)


__all__ = [
    "OIWall",
    "PCRResult",
    "ChangeOIBias",
    "IVMetrics",
    "OptionBias",
    "compute_pcr",
    "compute_max_pain",
    "compute_oi_walls",
    "compute_change_oi_bias",
    "compute_iv_metrics",
    "derive_bias",
]
