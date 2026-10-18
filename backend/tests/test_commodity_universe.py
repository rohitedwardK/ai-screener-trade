"""Commodity universe helpers — no network."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest

from app.core.commodity_universe import (
    all_commodity_symbols,
    commodity_stock_meta,
    get_commodity,
    is_commodity_symbol,
)
from app.core.universe import all_symbols
from app.data.mcx import (
    gold_inr_per_10g,
    overlay_live_session,
    pick_front_month,
    reset_cache,
    silver_inr_per_kg,
    cached_close_ltp,
)
from app.data.upstox_client import UpstoxQuote


def test_gold_and_silver_are_mcx_app_symbols():
    assert all_commodity_symbols() == ["GOLD.MCX", "SILVER.MCX"]
    gold = get_commodity("GOLD.MCX")
    silver = get_commodity("Silver")
    assert gold is not None and gold.currency == "INR" and gold.venue == "MCX"
    assert silver is not None and silver.symbol == "SILVER.MCX"


def test_commodity_tickers_are_not_in_nifty_universe():
    nifty = set(all_symbols())
    for sym in all_commodity_symbols():
        assert sym not in nifty
        assert is_commodity_symbol(sym)
    assert not is_commodity_symbol("RELIANCE.NS")
    assert not is_commodity_symbol("GC=F")


def test_stock_meta_shape_matches_upsert():
    rows = commodity_stock_meta()
    assert {r["symbol"] for r in rows} == {"GOLD.MCX", "SILVER.MCX"}
    for r in rows:
        assert r["sector"] == "Commodity"
        assert r["name"]


def test_pick_front_month_skips_expired_and_other_variants():
    rows = [
        {
            "asset_symbol": "GOLDM",
            "instrument_type": "FUT",
            "name": "GOLD",
            "expiry": 1_000,
            "instrument_key": "MCX_FO|OLD",
        },
        {
            "asset_symbol": "GOLDPETAL",
            "instrument_type": "FUT",
            "name": "GOLD",
            "expiry": 9_999_999_999_000,
            "instrument_key": "MCX_FO|PETAL",
        },
        {
            "asset_symbol": "GOLDM",
            "instrument_type": "CE",
            "name": "GOLD",
            "expiry": 9_999_999_999_000,
            "instrument_key": "MCX_FO|CE",
        },
        {
            "asset_symbol": "GOLDM",
            "instrument_type": "FUT",
            "name": "GOLD",
            "expiry": 2_000_000_000_000,
            "instrument_key": "MCX_FO|NEAR",
            "trading_symbol": "GOLDM FUT NEAR",
        },
        {
            "asset_symbol": "GOLDM",
            "instrument_type": "FUT",
            "name": "GOLD",
            "expiry": 3_000_000_000_000,
            "instrument_key": "MCX_FO|FAR",
        },
    ]
    picked = pick_front_month(rows, "GOLDM", now_ms=1_500_000_000_000)
    assert picked is not None
    assert picked["instrument_key"] == "MCX_FO|NEAR"


def test_pick_front_month_prefers_lot_inside_30_days():
    now_ms = 1_700_000_000_000
    day = 86_400_000
    rows = [
        {
            "asset_symbol": "SILVERM",
            "instrument_type": "FUT",
            "name": "SILVER",
            "expiry": now_ms + 20 * day,
            "instrument_key": "MCX_FO|NEAR",
        },
        {
            "asset_symbol": "SILVERM",
            "instrument_type": "FUT",
            "name": "SILVER",
            "expiry": now_ms + 90 * day,
            "instrument_key": "MCX_FO|NOV",
        },
    ]
    picked = pick_front_month(rows, "SILVERM", now_ms=now_ms)
    assert picked is not None
    assert picked["instrument_key"] == "MCX_FO|NEAR"


def test_comex_to_mcx_unit_conversion():
    # 2000 USD/oz * 80 INR * 10 / 31.1034768 ≈ 51441.37 INR / 10g
    gold = gold_inr_per_10g(2000.0, 80.0)
    assert gold == pytest.approx(2000.0 * 80.0 * 10.0 / 31.1034768)
    silver = silver_inr_per_kg(30.0, 80.0)
    assert silver == pytest.approx(30.0 * 80.0 * 1000.0 / 31.1034768)


def test_drop_synthetic_bars_keeps_mcx_prints():
    from app.data.mcx import drop_synthetic_bars

    idx = pd.to_datetime(["2026-08-19", "2026-08-20", "2026-08-23"])
    df = pd.DataFrame(
        {
            "open": [157157.0, 138370.8216, 160519.0],
            "high": [158599.0, 139083.1297, 163394.0],
            "low": [155727.0, 137732.2119, 159458.0],
            "close": [158025.0, 138662.4970, 161985.0],
            "volume": [53552.0, 478.0, 54059.0],
        },
        index=idx,
    )
    out = drop_synthetic_bars(df)
    assert list(out.index.strftime("%Y-%m-%d")) == ["2026-08-19", "2026-08-23"]
    assert list(out["close"]) == [158025.0, 161985.0]


def test_drop_synthetic_bars_rejects_near_integer_proxy():
    from app.data.mcx import drop_synthetic_bars

    idx = pd.to_datetime(["2026-08-19", "2026-08-26"])
    df = pd.DataFrame(
        {
            "open": [244498.0, 208311.98],
            "high": [245950.0, 208311.98],
            "low": [237200.0, 204485.14],
            "close": [244498.0, 208311.98351303156],
            "volume": [66125.0, 4.0],
        },
        index=idx,
    )
    out = drop_synthetic_bars(df)
    assert list(out["close"]) == [244498.0]


def test_load_remote_does_not_overlay_proxy_on_mcx_cache(tmp_path, monkeypatch):
    from app.data import mcx as mcx_data
    from app.data import csv_store

    monkeypatch.setattr(
        "app.data.csv_store._csv_dir", lambda: tmp_path,
    )
    idx = pd.to_datetime(["2026-08-23"])
    existing = pd.DataFrame(
        {"open": [160519.0], "high": [163394.0], "low": [159458.0],
         "close": [161985.0], "volume": [54059.0]},
        index=idx,
    )
    csv_store.save("GOLD.MCX", existing)
    monkeypatch.setattr(mcx_data, "instrument_key_for", lambda _s: "MCX_FO|1")
    monkeypatch.setattr(mcx_data, "_fetch_upstox_daily", lambda *_a, **_k: pd.DataFrame())
    monkeypatch.setattr(
        mcx_data, "synthetic_daily",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("proxy must not run")),
    )
    out = mcx_data._load_remote("GOLD.MCX", date(2026, 8, 20), date(2026, 8, 27))
    assert out.empty


def test_persist_merges_short_front_month_into_long_cache(tmp_path, monkeypatch):
    from app.data import mcx as mcx_data
    from app.data import csv_store

    monkeypatch.setattr("app.data.csv_store._csv_dir", lambda: tmp_path)
    idx = pd.to_datetime(["2026-08-20", "2026-08-21"])
    existing = pd.DataFrame(
        {"open": [160000.0, 161000.0], "high": [161000.0, 162000.0],
         "low": [159000.0, 160000.0], "close": [160500.0, 161500.0],
         "volume": [1000.0, 1100.0]},
        index=idx,
    )
    csv_store.save("GOLD.MCX", existing)
    short = pd.DataFrame(
        {"open": [162000.0], "high": [163000.0], "low": [161000.0],
         "close": [162882.0], "volume": [9000.0]},
        index=pd.to_datetime(["2026-08-24"]),
    )
    out = mcx_data._persist_mcx_frame("GOLD.MCX", short, existing)
    assert len(out) == 3
    assert float(out["close"].iloc[-1]) == 162882.0


def test_cached_close_skips_comex_proxy_float_dust(tmp_path, monkeypatch):
    from app.data import csv_store

    monkeypatch.setattr("app.data.csv_store._csv_dir", lambda: tmp_path)
    df = pd.DataFrame(
        {
            "open": [161_000.0, 142_821.88],
            "high": [161_500.0, 142_821.88],
            "low": [160_500.0, 142_821.88],
            "close": [161_985.0, 142_821.88801644373],
            "volume": [1000.0, 100.0],
        },
        index=pd.to_datetime(["2026-08-23", "2026-08-27"]),
    )
    csv_store.save("GOLD.MCX", df)
    assert cached_close_ltp(["GOLD.MCX"]) == {"GOLD.MCX": 161_985.0}


def test_front_month_cache_invalidates_after_expiry():
    import time

    reset_cache()
    now_ms = int(time.time() * 1000)
    day = 86_400_000
    rows = [
        {
            "asset_symbol": "GOLDM",
            "instrument_type": "FUT",
            "name": "GOLD",
            "expiry": now_ms - day,
            "instrument_key": "MCX_FO|OLD",
            "trading_symbol": "GOLDM OLD",
        },
        {
            "asset_symbol": "GOLDM",
            "instrument_type": "FUT",
            "name": "GOLD",
            "expiry": now_ms + 30 * day,
            "instrument_key": "MCX_FO|NEW",
            "trading_symbol": "GOLDM NEW",
        },
    ]
    from app.data import mcx as mcx_mod

    with patch.object(mcx_mod, "load_instruments", return_value=rows):
        mcx_mod._front_month["GOLD.MCX"] = rows[0]
        row = mcx_mod._contract_row("GOLD.MCX")
    assert row is not None
    assert row["instrument_key"] == "MCX_FO|NEW"
    reset_cache()


def _session_quote(last: float, *, when: datetime) -> UpstoxQuote:
    return UpstoxQuote(
        symbol="GOLD.MCX",
        last_price=last,
        open=147500.0,
        high=148000.0,
        low=144200.0,
        close_prev=147176.0,
        volume=12,
        timestamp_ms=int(when.timestamp() * 1000),
    )


def test_overlay_live_session_appends_current_day_for_scoring():
    reset_cache()
    idx = pd.to_datetime(["2026-10-13"])
    df = pd.DataFrame(
        {
            "open": [148410.0],
            "high": [148672.0],
            "low": [147050.0],
            "close": [147176.0],
            "volume": [100.0],
        },
        index=idx,
    )
    quote = _session_quote(144710.0, when=datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc))
    with patch("app.data.upstox_client.is_configured", return_value=True), \
         patch("app.data.upstox_client.fetch_quotes_batch", return_value={"GOLD.MCX": quote}):
        out = overlay_live_session(df, "GOLD.MCX")
    assert len(out) == 2
    assert pd.Timestamp(out.index[-1]).date() == date(2026, 10, 14)
    assert float(out.iloc[-1]["close"]) == 144710.0
    assert float(out.iloc[-1]["low"]) == 144200.0
    # Cache file itself is not rewritten.
    assert float(df.iloc[-1]["close"]) == 147176.0
    reset_cache()


def test_overlay_live_session_refreshes_same_day_bar():
    reset_cache()
    idx = pd.to_datetime(["2026-10-14"])
    df = pd.DataFrame(
        {
            "open": [147500.0],
            "high": [147800.0],
            "low": [146000.0],
            "close": [147176.0],
            "volume": [100.0],
        },
        index=idx,
    )
    quote = _session_quote(144710.0, when=datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc))
    with patch("app.data.upstox_client.is_configured", return_value=True), \
         patch("app.data.upstox_client.fetch_quotes_batch", return_value={"GOLD.MCX": quote}):
        out = overlay_live_session(df, "GOLD.MCX")
    assert len(out) == 1
    assert float(out.iloc[-1]["close"]) == 144710.0
    assert float(out.iloc[-1]["open"]) == 147500.0
    assert float(out.iloc[-1]["low"]) == 144200.0
    reset_cache()
