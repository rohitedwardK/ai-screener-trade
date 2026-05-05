"""Pure option-chain analytics — PCR, max-pain, OI shift, IV skew, bias.

Inputs are dataclass rows mirroring `data/option_chain.OptionRow`. Pure
functions only: no I/O, no DB. Easy to unit test.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


@dataclass
class OCRow:
    """Lightweight option-chain row used by analytics."""
    strike: float
    ce_oi: Optional[float] = None
    ce_change_oi: Optional[float] = None
    ce_volume: Optional[float] = None
    ce_iv: Optional[float] = None
    ce_ltp: Optional[float] = None
    pe_oi: Optional[float] = None
    pe_change_oi: Optional[float] = None
    pe_volume: Optional[float] = None
    pe_iv: Optional[float] = None
    pe_ltp: Optional[float] = None


@dataclass
class ChainSummary:
    pcr: Optional[float]              # OI-weighted put/call ratio (raw)
    pcr_volume: Optional[float]       # volume-weighted put/call ratio
    max_pain: Optional[float]
    max_pain_distance_pct: Optional[float]  # signed % gap of max-pain vs spot
    total_ce_oi: float
    total_pe_oi: float
    total_ce_change_oi: float
    total_pe_change_oi: float
    iv_skew: Optional[float]          # ATM PE IV - ATM CE IV (positive => puts richer)
    bias: str                         # Bullish | Bearish | Neutral
    bias_strength: float              # 0..1
    notes: List[str]


def _f(x: Optional[float]) -> float:
    return float(x) if x is not None else 0.0


def _safe_div(a: float, b: float) -> Optional[float]:
    if b == 0:
        return None
    return a / b


def total_oi(rows: Sequence[OCRow]) -> tuple[float, float]:
    return (
        sum(_f(r.ce_oi) for r in rows),
        sum(_f(r.pe_oi) for r in rows),
    )


def total_change_oi(rows: Sequence[OCRow]) -> tuple[float, float]:
    return (
        sum(_f(r.ce_change_oi) for r in rows),
        sum(_f(r.pe_change_oi) for r in rows),
    )


def total_volume(rows: Sequence[OCRow]) -> tuple[float, float]:
    return (
        sum(_f(r.ce_volume) for r in rows),
        sum(_f(r.pe_volume) for r in rows),
    )


def pcr(rows: Sequence[OCRow]) -> Optional[float]:
    ce_oi, pe_oi = total_oi(rows)
    return _safe_div(pe_oi, ce_oi)


def pcr_volume(rows: Sequence[OCRow]) -> Optional[float]:
    ce_v, pe_v = total_volume(rows)
    return _safe_div(pe_v, ce_v)


def max_pain(rows: Sequence[OCRow]) -> Optional[float]:
    """Strike that minimises total payoff to option holders.

    For each strike S, payoff = sum_K[ CE_oi(K) * max(S - K, 0)
                                      + PE_oi(K) * max(K - S, 0) ].
    The strike with the smallest total is "max pain".
    """
    if not rows:
        return None
    strikes = [r.strike for r in rows]
    best: Optional[float] = None
    best_strike: Optional[float] = None
    for cand in strikes:
        total = 0.0
        for r in rows:
            ce_oi = _f(r.ce_oi)
            pe_oi = _f(r.pe_oi)
            if cand > r.strike:
                total += ce_oi * (cand - r.strike)
            if cand < r.strike:
                total += pe_oi * (r.strike - cand)
        if best is None or total < best:
            best = total
            best_strike = cand
    return best_strike


def _atm(rows: Sequence[OCRow], spot: Optional[float]) -> Optional[OCRow]:
    if not rows or spot is None:
        return None
    return min(rows, key=lambda r: abs(r.strike - spot))


def iv_skew(rows: Sequence[OCRow], spot: Optional[float]) -> Optional[float]:
    """Positive skew (PE IV - CE IV at ATM) suggests downside protection demand."""
    atm = _atm(rows, spot)
    if atm is None:
        return None
    if atm.pe_iv is None or atm.ce_iv is None:
        return None
    return float(atm.pe_iv) - float(atm.ce_iv)


def max_pain_distance_pct(
    rows: Sequence[OCRow], *, spot: Optional[float],
) -> Optional[float]:
    """Signed % distance of the max-pain strike vs spot.

    Positive => max pain sits above spot (bullish drift bias under the
    standard interpretation). Negative => below spot.
    """
    if spot is None or spot == 0:
        return None
    mp = max_pain(rows)
    if mp is None:
        return None
    return float((float(mp) - float(spot)) / float(spot) * 100.0)


def derive_bias(
    rows: Sequence[OCRow],
    *,
    spot: Optional[float] = None,
) -> tuple[str, float, List[str]]:
    """Bias from PCR + change-in-OI + IV skew. Returns (bias, strength, notes).

    Heuristics (simulation-grade — not financial advice):
      - PCR > 1.30 + CE change-OI > PE change-OI ........ Bullish (writers selling calls?)
      - PCR < 0.70 + PE change-OI > CE change-OI ........ Bearish
      - IV skew strongly positive (PE > CE by >2pp) ..... lean Bearish
      - max_pain materially above spot .................. Bullish drift bias
      - max_pain materially below spot .................. Bearish drift bias
    """
    notes: List[str] = []
    if not rows:
        return "Neutral", 0.0, ["empty option chain"]

    pcr_v = pcr(rows) or 0.0
    ce_d, pe_d = total_change_oi(rows)
    skew = iv_skew(rows, spot)
    mp = max_pain(rows)
    score = 0.0

    if pcr_v >= 1.30:
        score += 0.30
        notes.append(f"PCR {pcr_v:.2f} (high)")
    elif pcr_v <= 0.70 and pcr_v > 0:
        score -= 0.30
        notes.append(f"PCR {pcr_v:.2f} (low)")
    elif pcr_v:
        notes.append(f"PCR {pcr_v:.2f} (neutral)")

    if ce_d or pe_d:
        if ce_d > pe_d * 1.5 and ce_d > 0:
            score -= 0.20
            notes.append("CE change-OI dominates: call writing")
        elif pe_d > ce_d * 1.5 and pe_d > 0:
            score += 0.20
            notes.append("PE change-OI dominates: put writing")

    if skew is not None and abs(skew) >= 2.0:
        if skew > 0:
            score -= 0.15
            notes.append(f"IV skew +{skew:.1f}: puts richer")
        else:
            score += 0.10
            notes.append(f"IV skew {skew:.1f}: calls richer")

    if mp is not None and spot is not None and spot > 0:
        diff_pct = (mp - spot) / spot * 100.0
        if diff_pct >= 1.0:
            score += 0.15
            notes.append(f"max-pain {mp:.0f} above spot ({diff_pct:+.1f}%)")
        elif diff_pct <= -1.0:
            score -= 0.15
            notes.append(f"max-pain {mp:.0f} below spot ({diff_pct:+.1f}%)")

    score = max(-1.0, min(1.0, score))
    if score >= 0.30:
        return "Bullish", round(abs(score), 2), notes
    if score <= -0.30:
        return "Bearish", round(abs(score), 2), notes
    return "Neutral", round(abs(score), 2), notes


def summarise(
    rows: Sequence[OCRow],
    *,
    spot: Optional[float] = None,
) -> ChainSummary:
    ce_oi, pe_oi = total_oi(rows)
    ce_d, pe_d = total_change_oi(rows)
    bias, strength, notes = derive_bias(rows, spot=spot)
    return ChainSummary(
        pcr=pcr(rows),
        pcr_volume=pcr_volume(rows),
        max_pain=max_pain(rows),
        max_pain_distance_pct=max_pain_distance_pct(rows, spot=spot),
        total_ce_oi=ce_oi,
        total_pe_oi=pe_oi,
        total_ce_change_oi=ce_d,
        total_pe_change_oi=pe_d,
        iv_skew=iv_skew(rows, spot),
        bias=bias,
        bias_strength=strength,
        notes=notes,
    )


# ---------- Strike picking ----------

def pick_strike(
    rows: Sequence[OCRow],
    *,
    spot: float,
    option_type: str,
    moneyness: str = "ATM",
    strike_step: float = 50.0,
) -> Optional[float]:
    """Pick a strike close to ATM for buying CE/PE.

    moneyness:
      ATM   — closest strike to spot
      ITM1  — one strike in-the-money
      OTM1  — one strike out-of-the-money
    """
    if not rows:
        return None
    atm = min(rows, key=lambda r: abs(r.strike - spot)).strike
    if moneyness == "ATM":
        return atm
    sign = 1 if option_type.upper() == "CE" else -1
    if moneyness == "ITM1":
        return atm - sign * strike_step
    if moneyness == "OTM1":
        return atm + sign * strike_step
    return atm


def premium_at_strike(
    rows: Sequence[OCRow], strike: float, *, option_type: str,
) -> Optional[float]:
    for r in rows:
        if abs(r.strike - strike) < 1e-6:
            return r.ce_ltp if option_type.upper() == "CE" else r.pe_ltp
    return None
