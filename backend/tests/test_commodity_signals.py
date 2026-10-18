"""Weekly-on-monthly MCX commodity signals — no network."""
from __future__ import annotations

from datetime import date

from app.analysis.commodity_signals import (
    HORIZON,
    HORIZON_MONTHLY,
    WEEKLY_HOLD_TRADING_DAYS,
    evaluate_commodity,
    evaluate_commodity_with_fallback,
    monthly_plan_dte,
    next_monthly_expiry,
    signal_to_dict,
    weekly_plan_dte,
)
from app.analysis.index_signals import _horizon_distances


def test_gold_monthly_picks_september_near_august_end():
    # 28 Aug 2026 — Aug GOLDM already rolled; Sep 4 is the front monthly.
    exp = next_monthly_expiry("GOLDM", date(2026, 8, 28), min_hold_days=0)
    assert exp == date(2026, 9, 4)


def test_silver_monthly_keeps_august_front_month():
    # 26 Aug 2026 — SILVERM Aug LTD is 31 Aug, still the active monthly.
    exp = next_monthly_expiry("SILVERM", date(2026, 8, 26), min_hold_days=0)
    assert exp == date(2026, 8, 31)


def test_silver_rolls_off_a_dying_august_with_hold_buffer():
    # 28 Aug 2026 + 8d buffer → skip Aug 31, pick September month-end.
    exp = next_monthly_expiry("SILVERM", date(2026, 8, 28), min_hold_days=8)
    assert exp == date(2026, 9, 30)


def test_next_monthly_default_keeps_near_expiry():
    # 1 Sep 2026 — Sep GOLDM (4 Sep) is the next monthly inside one month.
    exp = next_monthly_expiry("GOLDM", date(2026, 9, 1))
    assert exp == date(2026, 9, 4)


def test_weekly_plan_dte_is_capped_at_two_sessions():
    today = date(2026, 8, 25)
    far = date(2026, 9, 30)
    assert weekly_plan_dte(today, far) == WEEKLY_HOLD_TRADING_DAYS
    near = date(2026, 8, 31)
    assert 1 <= weekly_plan_dte(today, near) <= 2


def test_weekly_targets_are_tighter_than_full_monthly_atr_stretch():
    stop_5, t1_5, t2_5 = _horizon_distances(100.0, 5, stop_mult=1.0)
    _stop_30, _t1_30, t2_30 = _horizon_distances(100.0, 30, stop_mult=1.0)
    assert t2_5 < t2_30
    assert t1_5 <= t2_5


def test_uptrend_weekly_plan_has_invalidation_and_monthly_expiry(uptrend_df):
    expiry = date(2026, 9, 4)
    out = evaluate_commodity(
        "GOLD.MCX", uptrend_df, mcx_asset="GOLDM",
        monthly_expiry=expiry, today=date(2026, 8, 25),
    )
    assert out
    assert any(rec.direction == "LONG" for rec in out)
    assert not any(rec.direction == "SHORT" for rec in out)
    for rec in out:
        assert rec.plan is not None
        assert rec.plan.invalidation == rec.plan.stop_loss
        assert rec.plan.expiry == expiry
        assert rec.plan.horizon == HORIZON
        assert rec.plan.days_to_expiry == WEEKLY_HOLD_TRADING_DAYS
        assert rec.plan.entry > rec.plan.stop_loss
        payload = signal_to_dict(rec)
        assert payload["invalidation"] == rec.plan.invalidation
        assert payload["horizon"] == HORIZON


def test_monthly_plan_dte_within_thirty_day_window():
    today = date(2026, 8, 25)
    far = date(2026, 10, 5)
    dte = monthly_plan_dte(today, far)
    assert 5 < dte <= 22


def test_evaluate_with_fallback_emits_scalp_and_next_expiry(uptrend_df):
    expiry = date(2026, 9, 4)
    result = evaluate_commodity_with_fallback(
        "GOLD.MCX", uptrend_df, mcx_asset="GOLDM",
        monthly_expiry=expiry, today=date(2026, 8, 25),
    )
    assert result.effective_horizon == "both"
    assert result.signals
    assert not result.watch_notes
    directions = {r.direction for r in result.signals}
    assert directions == {"LONG"}
    horizons = {r.plan.horizon for r in result.signals if r.plan}
    assert HORIZON in horizons
    assert HORIZON_MONTHLY in horizons


def test_far_expiry_skips_monthly_window(uptrend_df):
    # 90 calendar days out — scalp only, no next-expiry row.
    result = evaluate_commodity_with_fallback(
        "GOLD.MCX", uptrend_df, mcx_asset="GOLDM",
        monthly_expiry=date(2026, 11, 30), today=date(2026, 9, 1),
    )
    assert result.effective_horizon == "scalp"
    assert all(
        r.plan and r.plan.horizon == HORIZON for r in result.signals
    )


def test_build_watch_guidance_returns_levels_to_watch(range_df):
    from app.analysis.commodity_signals import build_watch_guidance
    from app.analysis.indicators import compute_all
    from app.analysis.regime import classify

    enriched = compute_all(range_df)
    regime, _ = classify(enriched)
    last = enriched.iloc[-1]
    notes = build_watch_guidance(
        enriched,
        close=float(last["close"]),
        regime=regime,
        atr_v=float(last["atr14"]) if last.get("atr14") is not None else None,
        rsi_v=float(last["rsi14"]) if last.get("rsi14") is not None else None,
        expiry=date(2026, 9, 4),
        mcx_asset="GOLDM",
    )
    assert len(notes) >= 2
    assert len(notes) <= 3


def test_monthly_signals_use_monthly_horizon(uptrend_df):
    weekly = evaluate_commodity(
        "GOLD.MCX", uptrend_df, mcx_asset="GOLDM",
        monthly_expiry=date(2026, 9, 4), today=date(2026, 8, 25),
        horizon_mode="weekly",
    )
    monthly = evaluate_commodity(
        "GOLD.MCX", uptrend_df, mcx_asset="GOLDM",
        monthly_expiry=date(2026, 9, 4), today=date(2026, 8, 25),
        horizon_mode="monthly",
    )
    assert weekly and monthly
    assert weekly[0].plan.horizon == HORIZON
    assert monthly[0].plan.horizon == HORIZON_MONTHLY
    assert monthly[0].plan.days_to_expiry >= weekly[0].plan.days_to_expiry


def test_commodity_detail_uses_live_quote_and_fresh_plan(monkeypatch):
    import pandas as pd

    from app.api.commodities import build_commodity_detail
    from app.models.schemas import ScreenerRow

    idx = pd.bdate_range("2026-01-01", periods=80)
    frame = pd.DataFrame(
        {
            "open": 147000.0,
            "high": 148000.0,
            "low": 146000.0,
            "close": 147176.0,
            "volume": 1000.0,
        },
        index=idx,
    )
    row = ScreenerRow(
        symbol="GOLD.MCX",
        category="TREND_BREAKDOWN",
        regime="DOWNTREND",
        score=100.0,
        confidence=1.0,
        close=147176.0,
        entry=147176.0,
        stop_loss=149322.0,
        target_1=145029.0,
        invalidation=149322.0,
        reasons=["Trend is down. Buy PE; stop above is invalidation."],
        direction="SHORT",
        horizon="SCALP_ON_MONTHLY",
        days_to_expiry=2,
    )

    def fake_ctx(symbol, mcx_asset, snap, stock):
        return (
            [row],
            [],
            "scalp",
            {"rsi14": 38.0, "atr14": 2100.0, "atr_pct": 1.5},
            "DOWNTREND",
            147176.0,
            date(2026, 10, 13),
        )

    monkeypatch.setattr("app.api.commodities.csv_store.load", lambda symbol: frame)
    monkeypatch.setattr(
        "app.api.commodities.live_quotes.fetch_live_prices",
        lambda symbols: {"GOLD.MCX": 144640.0},
    )
    monkeypatch.setattr("app.api.commodities.live_quotes.last_source", lambda: "upstox")
    monkeypatch.setattr(
        "app.api.commodities.contract_label",
        lambda symbol: "GOLDM FUT 05 NOV 26",
    )
    monkeypatch.setattr("app.api.commodities._live_commodity_context", fake_ctx)

    view = build_commodity_detail("GOLD.MCX", snap=None, stock=None)

    assert view.live_price == 144640.0
    assert view.quote_source == "upstox"
    assert view.contract_label == "GOLDM FUT 05 NOV 26"
    assert view.snapshot is not None
    assert view.snapshot.close == 147176.0
    assert view.signals is not None
    assert view.signals[0].entry == 147176.0
    assert view.signals[0].invalidation == 149322.0


def test_downtrend_emits_shorts_with_invalidation(downtrend_df):
    out = evaluate_commodity(
        "SILVER.MCX", downtrend_df, mcx_asset="SILVERM",
        monthly_expiry=date(2026, 8, 31), today=date(2026, 8, 25),
    )
    shorts = [r for r in out if r.direction == "SHORT"]
    assert shorts
    for rec in shorts:
        assert rec.plan is not None
        assert rec.plan.invalidation == rec.plan.stop_loss
        assert rec.plan.entry < rec.plan.stop_loss
