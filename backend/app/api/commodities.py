"""Gold / Silver MCX dashboard — scalp and next-monthly on the front future."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..analysis import indicators as ind_mod
from ..analysis.commodity_signals import (
    WEEKLY_HOLD_TRADING_DAYS,
    evaluate_commodity_with_fallback,
    monthly_plan_dte,
    weekly_plan_dte,
)
from ..analysis.regime import classify
from ..core.commodity_universe import COMMODITIES, all_commodity_symbols
from ..data import csv_store, live_quotes, repository as repo
from ..data.mcx import (
    contract_expiry_date,
    contract_label,
    drop_synthetic_bars,
    is_mcx_session_open,
    overlay_live_session,
)
from ..db import get_db
from ..models.schemas import (
    CommodityDashboard,
    CommodityItem,
    ScreenerRow,
    SignalOut,
    SnapshotOut,
)

router = APIRouter(prefix="/commodities", tags=["commodities"])

_DISCLAIMER = "Research and decision-support only. Not financial advice."


def _row_from_eval(
    payload: dict,
    *,
    snap,
    stock,
    regime: str,
    close: float,
    ind: dict,
) -> ScreenerRow:
    return ScreenerRow(
        symbol=payload["symbol"],
        name=stock.name if stock else None,
        sector=stock.sector if stock else None,
        category=payload["category"],
        regime=regime,
        score=payload["score"],
        confidence=payload.get("confidence", 0.0),
        close=close,
        rsi=ind.get("rsi14"),
        adx=ind.get("adx"),
        atr_pct=ind.get("atr_pct"),
        entry=payload.get("entry"),
        stop_loss=payload.get("stop_loss"),
        target_1=payload.get("target_1"),
        target_2=payload.get("target_2"),
        invalidation=payload.get("invalidation"),
        reasons=payload.get("reasons_json") or [],
        live=None,
        direction=payload.get("direction"),
        expiry=payload.get("expiry"),
        days_to_expiry=payload.get("days_to_expiry"),
        horizon=payload.get("horizon"),
    )




def _live_commodity_context(
    symbol: str,
    mcx_asset: str,
    snap,
    stock,
) -> Tuple[List[ScreenerRow], List[str], Optional[str], dict, str, float, date]:
    """Recompute from CSV when DB signals/snapshot are missing or stale."""
    from ..analysis.commodity_signals import signal_to_dict

    # Include today's Upstox session so entry and targets are not sized off yesterday.
    df = overlay_live_session(drop_synthetic_bars(csv_store.load(symbol)), symbol)
    if df.empty or len(df) < 60:
        ind = (snap.indicators_json if snap else {}) or {}
        regime = snap.regime if snap else "RANGE"
        close = float(snap.close) if snap else 0.0
        as_of = snap.as_of_date if snap else date.today()
        return [], [], None, ind, regime, close, as_of

    enriched = ind_mod.compute_all(df)
    regime, _ = classify(enriched)
    ind = ind_mod.latest_indicator_dict(enriched)
    close = float(enriched.iloc[-1]["close"])
    as_of = enriched.index[-1].date() if hasattr(enriched.index[-1], "date") else date.today()
    expiry = contract_expiry_date(symbol)

    result = evaluate_commodity_with_fallback(
        symbol,
        df,
        mcx_asset=mcx_asset,
        monthly_expiry=expiry,
        df_enriched=enriched,
        today=date.today(),
    )
    rows = [
        _row_from_eval(
            signal_to_dict(rec),
            snap=snap,
            stock=stock,
            regime=regime,
            close=close,
            ind=ind,
        )
        for rec in result.signals
    ]
    return rows, result.watch_notes, result.effective_horizon, ind, regime, close, as_of


@dataclass
class CommodityDetailView:
    """Same quote and setups the commodity card shows, for the detail page."""

    snapshot: Optional[SnapshotOut]
    signals: Optional[List[SignalOut]]
    live_price: Optional[float]
    quote_source: str
    contract_label: Optional[str]
    watch_notes: List[str]


def build_commodity_detail(symbol: str, snap, stock) -> CommodityDetailView:
    """Score from the MCX CSV and overlay the Upstox LTP.

    `signals` is None when the CSV is too short to rescore, so the caller
    keeps the stored rows. The headline price is still the live quote.
    """
    from ..core.commodity_universe import COMMODITY_BY_SYMBOL

    meta = COMMODITY_BY_SYMBOL[symbol]
    live = live_quotes.fetch_live_prices([symbol])
    live_px = live.get(symbol)
    source = live_quotes.last_source() if live_px is not None else (
        "snapshot" if snap is not None else "none"
    )
    series = drop_synthetic_bars(csv_store.load(symbol))
    # Same bar-count gate as the card. A short cache must not replace stored signals.
    rescored = not series.empty and len(series) >= 60
    sig_rows, watch_notes, _horizon, ind, regime, csv_close, as_of = (
        _live_commodity_context(symbol, meta.mcx_asset, snap, stock)
    )

    daily_close = csv_close or (float(snap.close) if snap is not None else 0.0)
    snapshot: Optional[SnapshotOut] = None
    if rescored or snap is not None:
        snapshot = SnapshotOut(
            symbol=symbol,
            as_of_date=as_of if rescored else snap.as_of_date,
            close=daily_close if daily_close else (float(snap.close) if snap is not None else 0.0),
            regime=regime if rescored else (snap.regime if snap is not None else regime),
            atr=ind.get("atr14") if rescored else (snap.atr if snap is not None else None),
            atr_pct=ind.get("atr_pct") if rescored else (snap.atr_pct if snap is not None else None),
            indicators_json=ind if rescored else ((snap.indicators_json if snap is not None else {}) or {}),
        )

    signals: Optional[List[SignalOut]] = None
    if rescored:
        now = datetime.now(timezone.utc)
        signals = [
            SignalOut(
                id=i,
                symbol=symbol,
                run_at=now,
                as_of_date=as_of,
                category=row.category,
                score=row.score,
                confidence=row.confidence,
                entry=row.entry,
                stop_loss=row.stop_loss,
                target_1=row.target_1,
                target_2=row.target_2,
                invalidation=row.invalidation,
                reasons_json=list(row.reasons or []),
                direction=row.direction,
                expiry=row.expiry,
                days_to_expiry=row.days_to_expiry,
                horizon=row.horizon,
            )
            for i, row in enumerate(sig_rows, start=1)
        ]

    return CommodityDetailView(
        snapshot=snapshot,
        signals=signals,
        live_price=live_px,
        quote_source=source,
        contract_label=contract_label(symbol),
        watch_notes=watch_notes if rescored else [],
    )


@router.get("/dashboard", response_model=CommodityDashboard)
def dashboard(db: Session = Depends(get_db)) -> CommodityDashboard:
    symbols = all_commodity_symbols()
    live = live_quotes.fetch_live_prices(symbols)
    quote_source = live_quotes.last_source()

    items: List[CommodityItem] = []
    for meta in COMMODITIES:
        snap = repo.latest_snapshot(db, meta.symbol)
        stock = repo.get_stock(db, meta.symbol)
        live_px = live.get(meta.symbol)

        # Always re-score from CSV so stale DB rows cannot mix CE and PE.
        sig_rows, watch_notes, setup_horizon, ind, regime, csv_close, as_of = (
            _live_commodity_context(meta.symbol, meta.mcx_asset, snap, stock)
        )
        close = live_px or csv_close or (float(snap.close) if snap else 0.0)
        snap_regime = regime
        snap_as_of = as_of

        source = quote_source if live_px is not None else (
            "snapshot" if snap is not None else "none"
        )
        first = sig_rows[0] if sig_rows else None
        monthly = contract_expiry_date(meta.symbol)
        if first and first.expiry:
            monthly = first.expiry
        today = date.today()
        dte_contract = (monthly - today).days if monthly else None
        if first and first.days_to_expiry is not None:
            week_hold = first.days_to_expiry
        elif setup_horizon == "monthly" and monthly:
            week_hold = monthly_plan_dte(today, monthly)
        elif monthly:
            week_hold = weekly_plan_dte(today, monthly)
        else:
            week_hold = WEEKLY_HOLD_TRADING_DAYS

        if first and first.horizon == "MONTHLY_ON_MONTHLY":
            setup_horizon = setup_horizon or "monthly"
        elif first and first.horizon in ("SCALP_ON_MONTHLY", "WEEKLY_ON_MONTHLY"):
            setup_horizon = setup_horizon or "scalp"

        items.append(CommodityItem(
            symbol=meta.symbol,
            name=meta.name,
            venue=meta.venue,
            currency=meta.currency,
            unit=meta.unit,
            close=close,
            live_price=live_px,
            quote_source=source,
            regime=snap_regime,
            rsi=ind.get("rsi14"),
            adx=ind.get("adx"),
            atr_pct=ind.get("atr_pct"),
            as_of_date=snap_as_of,
            contract_label=contract_label(meta.symbol),
            monthly_expiry=monthly,
            days_to_expiry=dte_contract,
            week_hold_days=week_hold,
            setup_horizon=setup_horizon,
            watch_notes=watch_notes,
            signals=sig_rows,
        ))

    return CommodityDashboard(
        market_open=is_mcx_session_open(),
        quote_source=quote_source,
        items=items,
        disclaimer=_DISCLAIMER,
    )
