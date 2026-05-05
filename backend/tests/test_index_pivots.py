"""Pure tests for the classical pivot module + indicator integration."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.analysis.indicators import compute_all, latest_indicator_dict
from app.analysis.pivots import (
    compute_classical,
    compute_pivot_columns,
    distance_pct,
    nearest_level,
)


# --- compute_classical numerics ---

def test_compute_classical_known_triplet():
    # H=120, L=100, C=110 => P=110, R1=120, S1=100, R2=130, S2=90, R3=140, S3=80
    p = compute_classical(120.0, 100.0, 110.0)
    assert p["pivot_p"] == pytest.approx(110.0)
    assert p["pivot_r1"] == pytest.approx(120.0)
    assert p["pivot_s1"] == pytest.approx(100.0)
    assert p["pivot_r2"] == pytest.approx(130.0)
    assert p["pivot_s2"] == pytest.approx(90.0)
    assert p["pivot_r3"] == pytest.approx(140.0)
    assert p["pivot_s3"] == pytest.approx(80.0)


def test_compute_classical_symmetric_around_p():
    # When R1 - P == P - S1 the chain is symmetric (always true for classical).
    p = compute_classical(150.0, 130.0, 140.0)
    assert (p["pivot_r1"] - p["pivot_p"]) == pytest.approx(p["pivot_p"] - p["pivot_s1"])
    assert (p["pivot_r2"] - p["pivot_p"]) == pytest.approx(p["pivot_p"] - p["pivot_s2"])


# --- vectorised version ---

def _ohlc_frame() -> pd.DataFrame:
    idx = pd.date_range(end="2026-04-30", periods=4, freq="B")
    return pd.DataFrame(
        {
            "open":   [100.0, 110.0, 105.0, 112.0],
            "high":   [120.0, 115.0, 118.0, 119.0],
            "low":    [100.0, 102.0, 100.0, 105.0],
            "close":  [110.0, 108.0, 116.0, 117.0],
            "volume": [1_000_000.0, 1_100_000.0, 1_050_000.0, 1_200_000.0],
        },
        index=idx,
    )


def test_compute_pivot_columns_first_row_is_nan_and_second_uses_first_hlc():
    df = _ohlc_frame()
    pv = compute_pivot_columns(df)
    # Row 0 has no prior day -> NaN.
    assert math.isnan(pv["pivot_p"].iloc[0])
    # Row 1 uses row 0's H/L/C (120/100/110) so P should be 110.
    assert pv["pivot_p"].iloc[1] == pytest.approx(110.0)
    assert pv["pivot_r1"].iloc[1] == pytest.approx(120.0)
    assert pv["pivot_s1"].iloc[1] == pytest.approx(100.0)


def test_compute_pivot_columns_no_lookahead():
    # Row N's pivot must depend only on rows < N.
    df = _ohlc_frame()
    pv_full = compute_pivot_columns(df)
    pv_truncated = compute_pivot_columns(df.iloc[:3])
    # Both runs agree on the first three rows, even though `pv_full` saw row 3.
    pd.testing.assert_series_equal(
        pv_full["pivot_p"].iloc[:3], pv_truncated["pivot_p"], check_names=False,
    )


# --- helpers ---

def test_distance_pct_signed():
    assert distance_pct(110.0, 100.0) == pytest.approx(10.0)
    assert distance_pct(90.0, 100.0) == pytest.approx(-10.0)
    assert distance_pct(100.0, None) is None
    assert distance_pct(100.0, 0.0) is None


def test_nearest_level_picks_closest():
    levels = {"R1": 120.0, "P": 110.0, "S1": 100.0, "R2": None}
    assert nearest_level(112.0, levels) == "P"
    assert nearest_level(98.0, levels) == "S1"
    assert nearest_level(118.0, levels) == "R1"


# --- indicator integration ---

def test_indicators_compute_all_includes_pivot_columns():
    n = 60
    closes = np.linspace(100.0, 130.0, n)
    df = pd.DataFrame(
        {
            "open":   closes - 1.0,
            "high":   closes + 1.0,
            "low":    closes - 1.5,
            "close":  closes,
            "volume": np.full(n, 1_000_000.0),
        },
        index=pd.date_range(end="2026-04-30", periods=n, freq="B"),
    )
    out = compute_all(df)
    assert "pivot_p" in out.columns
    assert "pivot_distance_pct" in out.columns
    # Last row has a defined pivot (uses prior day's H/L/C).
    assert not math.isnan(out["pivot_p"].iloc[-1])

    snap = latest_indicator_dict(out)
    for k in (
        "pivot_p", "pivot_r1", "pivot_r2", "pivot_r3",
        "pivot_s1", "pivot_s2", "pivot_s3", "pivot_distance_pct",
    ):
        assert k in snap and snap[k] is not None
