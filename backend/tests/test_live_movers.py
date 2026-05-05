"""Unit tests for the top-K movers ranker."""
from __future__ import annotations

from app.live_analysis.movers import MoverInput, Mover, rank_top_k


def _mk(symbol: str, last: float, prev: float, vol: int = 1_000_000, avg: int = 1_000_000) -> MoverInput:
    return MoverInput(
        symbol=symbol, last_price=last, prev_close=prev,
        volume=vol, avg_volume=avg,
    )


def test_returns_top_k_sorted_by_score_desc():
    inputs = [
        _mk("A.NS", 102.0, 100.0),   # +2.0%
        _mk("B.NS", 101.0, 100.0),   # +1.0%
        _mk("C.NS", 99.0, 100.0),    # -1.0%
        _mk("D.NS", 95.0, 100.0),    # -5.0%
    ]
    out = rank_top_k(inputs, k=3)
    assert [m.symbol for m in out] == ["D.NS", "A.NS", "B.NS"]
    assert all(isinstance(m, Mover) for m in out)
    assert [m.rank for m in out] == [1, 2, 3]


def test_volume_burst_amplifies_a_tied_pct_change():
    """Same percent move, double the relative volume -> ranked higher."""
    inputs = [
        _mk("CALM.NS", 102.0, 100.0, vol=1_000_000, avg=1_000_000),
        _mk("HOT.NS",  102.0, 100.0, vol=4_000_000, avg=1_000_000),
    ]
    out = rank_top_k(inputs, k=2)
    assert out[0].symbol == "HOT.NS"
    assert out[1].symbol == "CALM.NS"
    assert out[0].score > out[1].score


def test_filters_below_min_pct_change():
    """Default 0.1% noise floor drops trivial movers."""
    inputs = [
        _mk("MICRO.NS", 100.05, 100.0),   # +0.05% -> dropped
        _mk("REAL.NS",  101.0, 100.0),    # +1.0%
    ]
    out = rank_top_k(inputs, k=5)
    assert [m.symbol for m in out] == ["REAL.NS"]


def test_drops_invalid_rows():
    """Zero or negative prices / prev_close yield no mover entry."""
    inputs = [
        _mk("BAD.NS", 0.0, 100.0),
        _mk("BAD2.NS", 100.0, 0.0),
        _mk("OK.NS", 110.0, 100.0),
    ]
    out = rank_top_k(inputs, k=5)
    assert [m.symbol for m in out] == ["OK.NS"]


def test_pct_change_sign_preserved_for_short_candidates():
    inputs = [_mk("DOWN.NS", 90.0, 100.0)]
    out = rank_top_k(inputs, k=1)
    assert out[0].pct_change < 0
    assert out[0].score > 0   # |pct| drives the score, not signed pct


def test_k_zero_returns_empty():
    inputs = [_mk("A.NS", 102.0, 100.0)]
    assert rank_top_k(inputs, k=0) == []
