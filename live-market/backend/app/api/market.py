"""Market dashboard + per-index regime + option-chain endpoints."""
from __future__ import annotations

from datetime import date as _date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..analysis import (
    market_regime as regime_mod,
    option_chain_signals as chain_mod,
    range_detector as range_mod,
    strike_picker as strike_mod,
    vwap as vwap_mod,
)
from ..core import daily_loader, intraday_store
from ..core.expiry import next_weekly_expiry, now_ist
from ..core.universe import IndexMeta, INDICES, get_meta
from ..data import upstox_options
from ..data.option_types import OptionChainPayload
from ..db import get_db
from ..models.orm import OptionChainSnapshot, RegimeSnapshot, ScalpSetup, SwingSetup
from ..models.schemas import (
    CreditSpreadDTO,
    DashboardDTO,
    DISCLAIMER,
    IndexCardDTO,
    OIWallDTO,
    OptionBiasDTO,
    OptionChainDTO,
    OptionRowDTO,
    RegimeSnapshotDTO,
    StrikeCandidateDTO,
    StrikeRecommendationsDTO,
)

router = APIRouter(prefix="/v1/market", tags=["market"])


# Implied directional bias drives a synthetic spot plan when no scalp/swing
# setup is live (typical during CHOPPY regime). Conservative: ~0.5% target.
_SYNTHETIC_TARGET_PCT = 0.005
_SYNTHETIC_STOP_PCT = 0.003


def _build_index_card(db: Session, meta) -> IndexCardDTO:
    bars = intraday_store.recent_bars(db, meta.symbol)
    df = intraday_store.to_dataframe(bars)
    spot = float(df["close"].iloc[-1]) if not df.empty else None
    last_bar_ts = bars[-1].ts if bars else None
    last_age = intraday_store.latest_bar_age_seconds(db, meta.symbol)

    daily_atr, daily_adx = daily_loader.latest_daily_atr_adx(meta.symbol)
    vwap_value = vwap_mod.latest_vwap(df) if not df.empty else None

    regime_label = regime_mod.REGIME_CHOPPY
    regime_reasons: List[str] = []
    support = None
    resistance = None
    if not df.empty:
        result = regime_mod.classify(
            df, daily_atr=daily_atr, daily_adx=daily_adx, vwap=vwap_value,
        )
        regime_label = result.regime
        regime_reasons = list(result.reasons)
        if regime_label == regime_mod.REGIME_RANGE_BOUND:
            levels = range_mod.detect_range(df)
            if levels is not None:
                support = levels.support
                resistance = levels.resistance

    active_scalps = db.scalar(
        select(func.count(ScalpSetup.id)).where(
            ScalpSetup.symbol == meta.symbol,
            ScalpSetup.status == "ACTIVE",
        )
    ) or 0
    active_swings = db.scalar(
        select(func.count(SwingSetup.id)).where(
            SwingSetup.symbol == meta.symbol,
            SwingSetup.status == "ACTIVE",
        )
    ) or 0

    return IndexCardDTO(
        symbol=meta.symbol,
        code=meta.code,
        name=meta.name,
        spot=spot,
        last_bar_ts=last_bar_ts,
        last_bar_age_seconds=last_age,
        regime=regime_label,
        regime_reasons=regime_reasons,
        daily_adx=daily_adx,
        vwap=vwap_value,
        range_support=support,
        range_resistance=resistance,
        active_scalps=int(active_scalps),
        active_swings=int(active_swings),
        has_option_chain=meta.has_option_chain,
    )


@router.get("/dashboard", response_model=DashboardDTO)
def dashboard(db: Session = Depends(get_db)) -> DashboardDTO:
    cards = [_build_index_card(db, meta) for meta in INDICES]
    return DashboardDTO(indices=cards, fetched_at=datetime.utcnow())


@router.get("/regime/{symbol:path}", response_model=List[RegimeSnapshotDTO])
def regime_history(
    symbol: str,
    limit: int = 60,
    db: Session = Depends(get_db),
) -> List[RegimeSnapshotDTO]:
    """Most recent N regime snapshots, ordered NEWEST FIRST."""
    if get_meta(symbol) is None:
        raise HTTPException(status_code=404, detail=f"unknown index: {symbol}")
    rows = list(db.scalars(
        select(RegimeSnapshot)
        .where(RegimeSnapshot.symbol == symbol)
        .order_by(desc(RegimeSnapshot.ts))
        .limit(max(1, min(limit, 500)))
    ))
    return [RegimeSnapshotDTO.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Option-chain endpoints
# ---------------------------------------------------------------------------
def _current_expiry(meta: IndexMeta) -> _date:
    return next_weekly_expiry(
        meta.weekly_expiry_day, now_ist().date(), now_time=now_ist().time(),
    )


def _live_spot(db: Session, symbol: str) -> Optional[float]:
    bars = intraday_store.recent_bars(db, symbol)
    df = intraday_store.to_dataframe(bars)
    if df.empty:
        return None
    return float(df["close"].iloc[-1])


def _fetch_chain(meta: IndexMeta) -> Optional[OptionChainPayload]:
    if not meta.has_option_chain:
        return None
    expiry = _current_expiry(meta)
    return upstox_options.fetch_option_chain(meta.code, expiry)


def _latest_snapshot(db: Session, symbol: str) -> Optional[OptionChainSnapshot]:
    return db.scalar(
        select(OptionChainSnapshot)
        .where(OptionChainSnapshot.symbol == symbol)
        .order_by(desc(OptionChainSnapshot.ts))
        .limit(1)
    )


def _snapshot_to_bias_dto(symbol: str, snap: OptionChainSnapshot) -> OptionBiasDTO:
    walls = snap.oi_walls or {}
    resistance = [OIWallDTO(**w) for w in walls.get("resistance", [])]
    support = [OIWallDTO(**w) for w in walls.get("support", [])]
    return OptionBiasDTO(
        symbol=symbol,
        spot=snap.spot,
        expiry=snap.expiry,
        fetched_at=snap.ts,
        pcr_oi=snap.pcr_oi,
        pcr_volume=snap.pcr_volume,
        total_ce_oi=snap.total_ce_oi,
        total_pe_oi=snap.total_pe_oi,
        max_pain=snap.max_pain,
        atm_iv=snap.atm_iv,
        iv_skew=snap.iv_skew,
        ce_oi_added=snap.ce_oi_added,
        pe_oi_added=snap.pe_oi_added,
        flow_direction=snap.flow_direction,
        resistance_walls=resistance,
        support_walls=support,
        bias_label=snap.bias_label,
        bias_score=snap.bias_score,
        bias_reasons=list(snap.bias_reasons or []),
    )


@router.get("/option-chain/{symbol:path}", response_model=OptionChainDTO)
def option_chain(
    symbol: str,
    near_strikes: int = Query(20, ge=2, le=60, description="Strikes either side of ATM to return"),
    db: Session = Depends(get_db),
) -> OptionChainDTO:
    """Live option chain near ATM. Sensex (no chain coverage) returns empty rows."""
    meta = get_meta(symbol)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"unknown index: {symbol}")
    if not meta.has_option_chain:
        return OptionChainDTO(
            symbol=meta.symbol, code=meta.code, spot=_live_spot(db, meta.symbol),
            rows=[], disclaimer=DISCLAIMER,
        )

    chain = _fetch_chain(meta)
    if chain is None:
        return OptionChainDTO(
            symbol=meta.symbol, code=meta.code, spot=_live_spot(db, meta.symbol),
            rows=[], disclaimer=DISCLAIMER,
        )

    spot = float(chain.spot) if chain.spot else (_live_spot(db, meta.symbol) or 0.0)
    sorted_rows = sorted(chain.rows, key=lambda r: r.strike)
    # Trim to +/- N strikes around ATM so the payload stays small.
    if spot > 0 and near_strikes < len(sorted_rows):
        atm_idx = min(
            range(len(sorted_rows)),
            key=lambda i: abs(sorted_rows[i].strike - spot),
        )
        lo = max(0, atm_idx - near_strikes)
        hi = min(len(sorted_rows), atm_idx + near_strikes + 1)
        sorted_rows = sorted_rows[lo:hi]

    dto_rows = [
        OptionRowDTO(
            strike=r.strike, ce_oi=r.ce_oi, ce_change_oi=r.ce_change_oi,
            ce_volume=r.ce_volume, ce_iv=r.ce_iv, ce_ltp=r.ce_ltp,
            pe_oi=r.pe_oi, pe_change_oi=r.pe_change_oi,
            pe_volume=r.pe_volume, pe_iv=r.pe_iv, pe_ltp=r.pe_ltp,
        )
        for r in sorted_rows
    ]
    return OptionChainDTO(
        symbol=meta.symbol, code=meta.code, spot=spot,
        expiry=datetime.combine(chain.expiry, datetime.min.time()),
        fetched_at=chain.fetched_at, source=chain.source,
        rows=dto_rows,
    )


@router.get("/option-bias/{symbol:path}", response_model=OptionBiasDTO)
def option_bias(symbol: str, db: Session = Depends(get_db)) -> OptionBiasDTO:
    """PCR / max-pain / OI walls / IV skew / combined bias from the latest tick."""
    meta = get_meta(symbol)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"unknown index: {symbol}")
    if not meta.has_option_chain:
        return OptionBiasDTO(
            symbol=meta.symbol,
            bias_label="NEUTRAL",
            bias_score=0.0,
            bias_reasons=["index has no option chain coverage"],
        )

    snap = _latest_snapshot(db, meta.symbol)
    if snap is not None:
        return _snapshot_to_bias_dto(meta.symbol, snap)

    # Fallback: compute on-the-fly when the scheduler hasn't ticked yet.
    chain = _fetch_chain(meta)
    if chain is None or not chain.rows:
        return OptionBiasDTO(
            symbol=meta.symbol,
            bias_label="NEUTRAL",
            bias_score=0.0,
            bias_reasons=["no option chain available yet"],
        )
    spot = float(chain.spot) if chain.spot else (_live_spot(db, meta.symbol) or 0.0)
    pcr = chain_mod.compute_pcr(chain)
    max_pain = chain_mod.compute_max_pain(chain)
    flow = chain_mod.compute_change_oi_bias(chain)
    iv_metrics = chain_mod.compute_iv_metrics(chain, spot)
    resistance, support = chain_mod.compute_oi_walls(chain, spot, k=3)
    bias = chain_mod.derive_bias(chain, spot, pcr=pcr, max_pain=max_pain, flow=flow, iv=iv_metrics)
    return OptionBiasDTO(
        symbol=meta.symbol, spot=spot,
        expiry=datetime.combine(chain.expiry, datetime.min.time()),
        fetched_at=chain.fetched_at,
        pcr_oi=pcr.pcr_oi, pcr_volume=pcr.pcr_volume,
        total_ce_oi=pcr.total_ce_oi, total_pe_oi=pcr.total_pe_oi,
        max_pain=max_pain, atm_iv=iv_metrics.atm_iv, iv_skew=iv_metrics.skew,
        ce_oi_added=flow.ce_oi_added, pe_oi_added=flow.pe_oi_added,
        flow_direction=flow.direction,
        resistance_walls=[OIWallDTO(strike=w.strike, oi=w.oi, side=w.side) for w in resistance],
        support_walls=[OIWallDTO(strike=w.strike, oi=w.oi, side=w.side) for w in support],
        bias_label=bias.label, bias_score=bias.score, bias_reasons=list(bias.reasons),
    )


def _build_synthetic_plan(
    spot: float, *, direction: str,
) -> tuple[float, float, float, float]:
    """Conservative (entry, stop, t1, t2) when no scalp/swing setup is live.

    LONG: 0.3% stop below, 0.25% T1, 0.5% T2.
    SHORT: mirror.
    """
    if direction == "LONG":
        entry = round(spot, 2)
        stop = round(spot * (1 - _SYNTHETIC_STOP_PCT), 2)
        t1 = round(spot * (1 + _SYNTHETIC_TARGET_PCT / 2), 2)
        t2 = round(spot * (1 + _SYNTHETIC_TARGET_PCT), 2)
    else:
        entry = round(spot, 2)
        stop = round(spot * (1 + _SYNTHETIC_STOP_PCT), 2)
        t1 = round(spot * (1 - _SYNTHETIC_TARGET_PCT / 2), 2)
        t2 = round(spot * (1 - _SYNTHETIC_TARGET_PCT), 2)
    return entry, stop, t1, t2


@router.get("/strike-recommendations/{symbol:path}", response_model=StrikeRecommendationsDTO)
def strike_recommendations(
    symbol: str,
    direction: Optional[str] = Query(
        None,
        pattern="^(LONG|SHORT)$",
        description="Override the bias-inferred direction. LONG=CE, SHORT=PE.",
    ),
    hold_days: Optional[float] = Query(
        None,
        ge=0.0,
        le=30.0,
        description="Assumed hold horizon in DAYS for theta drag. "
                    "Default = min(days_to_expiry, 3). Use 0 for intraday "
                    "(no theta), 1 for overnight, 3 for swing.",
    ),
    db: Session = Depends(get_db),
) -> StrikeRecommendationsDTO:
    """Ranked OTM/ATM/ITM strikes + an optional defined-risk credit spread.

    When `direction` is not supplied, we infer from the latest option-chain
    bias (BULLISH -> LONG / CE, BEARISH -> SHORT / PE, NEUTRAL -> no
    recommendations - silence is better than noise).
    """
    meta = get_meta(symbol)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"unknown index: {symbol}")
    if not meta.has_option_chain:
        return StrikeRecommendationsDTO(
            symbol=meta.symbol, code=meta.code,
            note=f"{meta.code} has no option chain via Upstox in this service",
        )

    chain = _fetch_chain(meta)
    if chain is None or not chain.rows:
        return StrikeRecommendationsDTO(
            symbol=meta.symbol, code=meta.code,
            note="option chain unavailable - check Upstox token",
        )
    spot = float(chain.spot) if chain.spot else (_live_spot(db, meta.symbol) or 0.0)
    if spot <= 0:
        return StrikeRecommendationsDTO(
            symbol=meta.symbol, code=meta.code,
            note="no live spot yet",
        )

    # Re-derive bias on the same chain so the rationale shown matches the
    # ladder. (Latest snapshot may be a tick old; close enough for the
    # bias label but the candidates need fresh LTPs anyway.)
    pcr = chain_mod.compute_pcr(chain)
    max_pain = chain_mod.compute_max_pain(chain)
    flow = chain_mod.compute_change_oi_bias(chain)
    iv_metrics = chain_mod.compute_iv_metrics(chain, spot)
    resistance, support = chain_mod.compute_oi_walls(chain, spot, k=3)
    bias = chain_mod.derive_bias(chain, spot, pcr=pcr, max_pain=max_pain, flow=flow, iv=iv_metrics)
    bias_dto = OptionBiasDTO(
        symbol=meta.symbol, spot=spot,
        expiry=datetime.combine(chain.expiry, datetime.min.time()),
        fetched_at=chain.fetched_at,
        pcr_oi=pcr.pcr_oi, pcr_volume=pcr.pcr_volume,
        total_ce_oi=pcr.total_ce_oi, total_pe_oi=pcr.total_pe_oi,
        max_pain=max_pain, atm_iv=iv_metrics.atm_iv, iv_skew=iv_metrics.skew,
        ce_oi_added=flow.ce_oi_added, pe_oi_added=flow.pe_oi_added,
        flow_direction=flow.direction,
        resistance_walls=[OIWallDTO(strike=w.strike, oi=w.oi, side=w.side) for w in resistance],
        support_walls=[OIWallDTO(strike=w.strike, oi=w.oi, side=w.side) for w in support],
        bias_label=bias.label, bias_score=bias.score, bias_reasons=list(bias.reasons),
    )

    # Resolve direction
    if direction is None:
        if bias.label == "BULLISH":
            chosen = "LONG"
        elif bias.label == "BEARISH":
            chosen = "SHORT"
        else:
            return StrikeRecommendationsDTO(
                symbol=meta.symbol, code=meta.code, spot=spot,
                expiry=datetime.combine(chain.expiry, datetime.min.time()),
                bias=bias_dto, candidates=[], credit_spread=None,
                note="option-chain bias is NEUTRAL - no directional ladder. "
                     "Pass ?direction=LONG or ?direction=SHORT to force one.",
            )
    else:
        chosen = direction

    entry, stop, t1, t2 = _build_synthetic_plan(spot, direction=chosen)

    # Pick a sensible hold_days default: don't assume the operator holds
    # longer than the option exists. Cap at 3 days for swing-like usage.
    dte_today = max(0.0, (chain.expiry - now_ist().date()).days + 0.0)
    if hold_days is None:
        effective_hold = min(dte_today, 3.0)
    else:
        effective_hold = float(hold_days)

    candidates = strike_mod.recommend_strikes(
        spot_entry=entry, spot_stop=stop, spot_t1=t1, spot_t2=t2,
        direction=chosen, meta=meta, chain=chain,
        hold_days=effective_hold,
    )
    candidate_dtos = [
        StrikeCandidateDTO(
            moneyness=c.moneyness, strike=c.strike, type=c.type,
            expiry=datetime.combine(c.expiry, datetime.min.time()),
            instrument_key=c.instrument_key, delta_assumed=c.delta_assumed,
            premium_entry=c.premium_entry, premium_stop=c.premium_stop,
            premium_t1=c.premium_t1, premium_t2=c.premium_t2,
            breakeven_spot=c.breakeven_spot,
            max_loss_per_unit=c.max_loss_per_lot,
            max_profit_per_unit=c.max_profit_per_lot,
            days_to_expiry=c.days_to_expiry,
            theta_per_day=c.theta_per_day,
            theta_drag_total=c.theta_drag_total,
            hold_days=c.hold_days,
            reasons=list(c.reasons),
        )
        for c in candidates
    ]

    # Optional credit spread aligned with the chosen direction. We anchor
    # the short leg at the strongest OI wall (resistance for bearish,
    # support for bullish) so the spread sits behind real positioning.
    spread_dto: Optional[CreditSpreadDTO] = None
    if chosen == "LONG" and support:
        spread = strike_mod.recommend_credit_spread(
            bias="BULLISH", spot=spot, meta=meta, chain=chain,
            support_strike=support[0].strike,
        )
        if spread is not None:
            spread_dto = CreditSpreadDTO(
                bias=spread.bias,
                short_strike=spread.short_strike, long_strike=spread.long_strike,
                short_type=spread.short_type,
                expiry=datetime.combine(spread.expiry, datetime.min.time()),
                short_instrument_key=spread.short_instrument_key,
                long_instrument_key=spread.long_instrument_key,
                short_premium=spread.short_premium, long_premium=spread.long_premium,
                net_credit=spread.net_credit, max_profit=spread.max_profit,
                max_loss=spread.max_loss, breakeven_spot=spread.breakeven_spot,
                days_to_expiry=spread.days_to_expiry,
                theta_per_day=spread.theta_per_day,
                projected_value_1d=spread.projected_value_1d,
                projected_value_3d=spread.projected_value_3d,
                projected_value_at_expiry=spread.projected_value_at_expiry,
                reasons=list(spread.reasons),
            )
    elif chosen == "SHORT" and resistance:
        spread = strike_mod.recommend_credit_spread(
            bias="BEARISH", spot=spot, meta=meta, chain=chain,
            resistance_strike=resistance[0].strike,
        )
        if spread is not None:
            spread_dto = CreditSpreadDTO(
                bias=spread.bias,
                short_strike=spread.short_strike, long_strike=spread.long_strike,
                short_type=spread.short_type,
                expiry=datetime.combine(spread.expiry, datetime.min.time()),
                short_instrument_key=spread.short_instrument_key,
                long_instrument_key=spread.long_instrument_key,
                short_premium=spread.short_premium, long_premium=spread.long_premium,
                net_credit=spread.net_credit, max_profit=spread.max_profit,
                max_loss=spread.max_loss, breakeven_spot=spread.breakeven_spot,
                days_to_expiry=spread.days_to_expiry,
                theta_per_day=spread.theta_per_day,
                projected_value_1d=spread.projected_value_1d,
                projected_value_3d=spread.projected_value_3d,
                projected_value_at_expiry=spread.projected_value_at_expiry,
                reasons=list(spread.reasons),
            )

    note = ""
    if direction is not None and direction != ("LONG" if bias.label == "BULLISH" else "SHORT" if bias.label == "BEARISH" else direction):
        note = f"direction={direction} forced by caller; chain bias was {bias.label}"
    return StrikeRecommendationsDTO(
        symbol=meta.symbol, code=meta.code, spot=spot,
        expiry=datetime.combine(chain.expiry, datetime.min.time()),
        bias=bias_dto, candidates=candidate_dtos, credit_spread=spread_dto,
        note=note,
    )
