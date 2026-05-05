"""Top-K intraday movers ranking.

Pure function. Ranks symbols by `|intraday_pct_change| * log1p(rvol)` so a
symbol making a small move on huge volume can still beat one making a flashy
move on no flow. This mirrors how desks scan the tape.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class MoverInput:
    """One symbol's snapshot at the current tick."""
    symbol: str
    last_price: float
    prev_close: float
    volume: int = 0           # cumulative session volume
    avg_volume: int = 0       # 20-day average daily volume (proxy for RVOL)


@dataclass(frozen=True)
class Mover:
    """Ranked output row."""
    symbol: str
    last_price: float
    pct_change: float
    rvol: float
    score: float
    rank: int


def _rvol(observed: int, baseline: int) -> float:
    """Relative volume = session_volume / typical_session_volume."""
    if observed <= 0 or baseline <= 0:
        return 0.0
    return observed / baseline


def rank_top_k(
    inputs: Iterable[MoverInput],
    *,
    k: int,
    min_abs_pct_change: float = 0.1,
) -> List[Mover]:
    """Return the top K movers by `|pct_change| * log1p(max(rvol-1, 0))`.

    `min_abs_pct_change` filters out micro-noise so a symbol up 0.02% on a
    hot tape doesn't displace genuine movers. Default 0.1% is conservative.
    """
    scored: List[Mover] = []
    for row in inputs:
        if row.last_price <= 0 or row.prev_close <= 0:
            continue
        pct = (row.last_price - row.prev_close) / row.prev_close * 100.0
        if abs(pct) < min_abs_pct_change:
            continue
        rvol = _rvol(row.volume, row.avg_volume)
        # log1p(rvol-1) is 0 when rvol == 1 (typical day); positive when above
        # typical, mildly negative below. Floor at 0 so quiet days don't get
        # ranked artificially low.
        rvol_factor = max(math.log1p(max(rvol - 1.0, 0.0)), 0.0)
        # Constant +0.5 keeps the score comparable across symbols whose
        # avg_volume is unknown (rvol_factor == 0).
        score = abs(pct) * (0.5 + rvol_factor)
        scored.append(Mover(
            symbol=row.symbol,
            last_price=round(float(row.last_price), 4),
            pct_change=round(float(pct), 4),
            rvol=round(float(rvol), 4),
            score=round(float(score), 4),
            rank=0,
        ))

    scored.sort(key=lambda m: m.score, reverse=True)
    out: List[Mover] = []
    for i, m in enumerate(scored[:k], start=1):
        out.append(Mover(
            symbol=m.symbol,
            last_price=m.last_price,
            pct_change=m.pct_change,
            rvol=m.rvol,
            score=m.score,
            rank=i,
        ))
    return out


__all__ = ["MoverInput", "Mover", "rank_top_k"]
