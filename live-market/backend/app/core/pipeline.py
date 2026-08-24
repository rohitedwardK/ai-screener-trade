"""Per-tick orchestrator for the Live Market service.

`run_tick(db, now)` does, in order:

  1. Fetch spot quotes for the 3 indices via Upstox.
  2. Append each quote to the rolling 1-min OHLCV buffer.
  3. For each index:
       a. Pull recent bars + load daily ATR/ADX from the parent CSV cache.
       b. Compute VWAP, classify regime, persist `RegimeSnapshot`.
       c. If RANGE_BOUND -> evaluate scalp catalog.
          If TRENDING_*  -> evaluate swing catalog.
       d. For each new candidate that isn't already covered by an
          ACTIVE row of the same (symbol, category, direction):
            attach an option plan (when chain available),
            persist a new ScalpSetup / SwingSetup row.
  4. Verify ACTIVE setups against the freshest spots.
  5. Prune old bars beyond the rolling window.
  6. Commit.

Idempotent: re-running with the same `now` and the same DB state has no
material effect (bars merge, regime row is just another tick, and we
de-dupe candidates against ACTIVE rows of the same shape).

Exception-safe at the top level: the scheduler wrapper catches anything
that escapes here and logs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis import (
    market_regime as regime_mod,
    option_chain_signals as chain_mod,
    range_detector as range_mod,
    scalp_signals as scalp_mod,
    strike_picker as strike_mod,
    swing_signals as swing_mod,
    vwap as vwap_mod,
)
from ..config import get_settings
from ..data import upstox_client, upstox_options
from ..data.option_types import OptionChainPayload
from ..models.orm import (
    OptionChainSnapshot,
    RegimeSnapshot,
    ScalpSetup,
    SwingSetup,
)
from . import daily_loader, intraday_store, verifier
from .expiry import next_weekly_expiry, now_ist
from .universe import IndexMeta, INDICES, get_meta

log = logging.getLogger(__name__)


@dataclass
class TickResult:
    processed_at: datetime
    symbols_priced: int
    regimes: Dict[str, str]
    scalps_emitted: int
    swings_emitted: int
    setups_resolved: int
    note: str = ""


def _utc_now() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fetch_spots(symbols: List[str]) -> Dict[str, upstox_client.UpstoxQuote]:
    if not upstox_client.is_configured():
        return {}
    return upstox_client.fetch_quotes_batch(symbols)


def _load_chain_for(meta: IndexMeta) -> Optional[OptionChainPayload]:
    if not meta.has_option_chain:
        return None
    today = now_ist().date()
    expiry = next_weekly_expiry(meta.weekly_expiry_day, today, now_time=now_ist().time())
    return upstox_options.fetch_option_chain(meta.code, expiry)


def _has_active_match(
    db: Session, *, symbol: str, category: str, direction: str, kind: str,
) -> bool:
    """De-dupe: don't emit a fresh setup if an identical one is still ACTIVE."""
    table = ScalpSetup if kind == "scalp" else SwingSetup
    existing = db.scalar(
        select(table).where(
            table.symbol == symbol,
            table.category == category,
            table.direction == direction,
            table.status == verifier.STATUS_ACTIVE,
        ).limit(1)
    )
    return existing is not None


def _persist_scalp(
    db: Session,
    *,
    rec: scalp_mod.ScalpSetupRecord,
    meta: IndexMeta,
    chain: Optional[OptionChainPayload],
    when: datetime,
) -> None:
    cfg = get_settings()
    # Scalps are 5-15 min holds; theta drag is negligible at that horizon
    # even on expiry day, so leave hold_days at the default 0.
    option = strike_mod.pick_atm(
        spot_entry=rec.spot_entry, spot_stop=rec.spot_stop,
        spot_t1=rec.spot_t1, spot_t2=rec.spot_t2,
        direction=rec.direction, meta=meta, chain=chain,
        hold_days=0.0,
    )
    expires = when + timedelta(minutes=cfg.SCALP_EXPIRY_MIN)
    if rec.spot_invalidation is None:
        # Defensive: every plan must carry an invalidation level.
        log.warning("scalp %s %s missing invalidation, skipped", rec.symbol, rec.category)
        return
    db.add(ScalpSetup(
        symbol=rec.symbol,
        category=rec.category,
        direction=rec.direction,
        status=verifier.STATUS_ACTIVE,
        score=float(rec.score),
        reasons=list(rec.reasons),
        spot_entry=rec.spot_entry,
        spot_stop=rec.spot_stop,
        spot_t1=rec.spot_t1,
        spot_t2=rec.spot_t2,
        spot_invalidation=rec.spot_invalidation,
        option_strike=(option.strike if option else None),
        option_type=(option.type if option else None),
        option_expiry=(datetime.combine(option.expiry, datetime.min.time()) if option else None),
        option_instrument_key=(option.instrument_key if option else None),
        option_premium_entry=(option.premium_entry if option else None),
        option_premium_stop=(option.premium_stop if option else None),
        option_premium_t1=(option.premium_t1 if option else None),
        option_premium_t2=(option.premium_t2 if option else None),
        created_at=when,
        expires_at=expires,
        note=None if option else "no option chain - spot plan only",
    ))


def _persist_swing(
    db: Session,
    *,
    rec: swing_mod.SwingSetupRecord,
    meta: IndexMeta,
    chain: Optional[OptionChainPayload],
    when: datetime,
) -> None:
    # Swings hold for `days_to_expiry` business days (default 3). Pass that
    # through so the persisted premium targets reflect theta erosion over
    # the realistic hold horizon instead of an instantaneous-fill fantasy.
    option = strike_mod.pick_atm(
        spot_entry=rec.spot_entry, spot_stop=rec.spot_stop,
        spot_t1=rec.spot_t1, spot_t2=rec.spot_t2,
        direction=rec.direction, meta=meta, chain=chain,
        hold_days=float(rec.days_to_expiry),
    )
    if rec.spot_invalidation is None:
        log.warning("swing %s %s missing invalidation, skipped", rec.symbol, rec.category)
        return
    expires = when + timedelta(days=rec.days_to_expiry)
    db.add(SwingSetup(
        symbol=rec.symbol,
        category=rec.category,
        direction=rec.direction,
        status=verifier.STATUS_ACTIVE,
        score=float(rec.score),
        reasons=list(rec.reasons),
        spot_entry=rec.spot_entry,
        spot_stop=rec.spot_stop,
        spot_t1=rec.spot_t1,
        spot_t2=rec.spot_t2,
        spot_invalidation=rec.spot_invalidation,
        option_strike=(option.strike if option else None),
        option_type=(option.type if option else None),
        option_expiry=(datetime.combine(option.expiry, datetime.min.time()) if option else None),
        option_instrument_key=(option.instrument_key if option else None),
        option_premium_entry=(option.premium_entry if option else None),
        option_premium_stop=(option.premium_stop if option else None),
        option_premium_t1=(option.premium_t1 if option else None),
        option_premium_t2=(option.premium_t2 if option else None),
        days_to_expiry=int(rec.days_to_expiry),
        created_at=when,
        expires_at=expires,
        note=None if option else "no option chain - spot plan only",
    ))


def _persist_regime(
    db: Session, symbol: str, *, when: datetime, result: regime_mod.RegimeResult,
) -> None:
    db.add(RegimeSnapshot(
        symbol=symbol,
        ts=when,
        regime=result.regime,
        spot=float(result.spot),
        daily_adx=result.daily_adx,
        bb_width_pct=result.bb_width_pct,
        ema_spread_pct=result.ema_spread_pct,
        realized_range_pct=result.realized_range_pct,
        atr_pct=result.atr_pct,
        vwap=result.vwap,
        reasons=list(result.reasons),
    ))


def _persist_chain_snapshot(
    db: Session,
    *,
    meta: IndexMeta,
    when: datetime,
    chain: OptionChainPayload,
    spot: float,
) -> None:
    """Compute the five chain signals + combined bias and store one row.

    Cheap: one row per index per tick, ~1KB each. Even a full 6.5h NSE
    session produces only ~1170 rows across the three indices, so we don't
    need aggressive pruning.
    """
    pcr = chain_mod.compute_pcr(chain)
    max_pain = chain_mod.compute_max_pain(chain)
    flow = chain_mod.compute_change_oi_bias(chain)
    iv_metrics = chain_mod.compute_iv_metrics(chain, spot)
    resistance, support = chain_mod.compute_oi_walls(chain, spot, k=3)
    bias = chain_mod.derive_bias(chain, spot, pcr=pcr, max_pain=max_pain, flow=flow, iv=iv_metrics)

    walls_json = {
        "resistance": [
            {"strike": w.strike, "oi": w.oi, "side": w.side} for w in resistance
        ],
        "support": [
            {"strike": w.strike, "oi": w.oi, "side": w.side} for w in support
        ],
    }
    db.add(OptionChainSnapshot(
        symbol=meta.symbol,
        ts=when,
        expiry=datetime.combine(chain.expiry, datetime.min.time()),
        spot=float(spot),
        pcr_oi=pcr.pcr_oi,
        pcr_volume=pcr.pcr_volume,
        total_ce_oi=pcr.total_ce_oi,
        total_pe_oi=pcr.total_pe_oi,
        max_pain=max_pain,
        atm_iv=iv_metrics.atm_iv,
        iv_skew=iv_metrics.skew,
        ce_oi_added=flow.ce_oi_added,
        pe_oi_added=flow.pe_oi_added,
        flow_direction=flow.direction,
        bias_label=bias.label,
        bias_score=bias.score,
        bias_reasons=list(bias.reasons),
        oi_walls=walls_json,
    ))


def _evaluate_index(
    db: Session,
    *,
    meta: IndexMeta,
    when: datetime,
) -> Tuple[str, int, int]:
    """Run the full classify -> evaluate -> persist pipeline for one index.

    Returns `(regime_label, scalps_emitted, swings_emitted)`.
    """
    bars = intraday_store.recent_bars(db, meta.symbol)
    df = intraday_store.to_dataframe(bars)
    if df.empty:
        return regime_mod.REGIME_CHOPPY, 0, 0

    daily_atr, daily_adx = daily_loader.latest_daily_atr_adx(meta.symbol)
    vwap_value = vwap_mod.latest_vwap(df)
    result = regime_mod.classify(
        df, daily_atr=daily_atr, daily_adx=daily_adx, vwap=vwap_value,
    )
    _persist_regime(db, meta.symbol, when=when, result=result)

    # Pre-fetch the chain so analytics + setup option plans use the SAME
    # snapshot. The 60s in-process cache inside `upstox_options` ensures a
    # second call from a setup persist path doesn't hit Upstox twice.
    chain: Optional[OptionChainPayload] = _load_chain_for(meta)
    if chain is not None and chain.rows and result.spot > 0:
        try:
            _persist_chain_snapshot(db, meta=meta, when=when, chain=chain, spot=result.spot)
        except Exception:  # noqa: BLE001 - chain analytics failure must not poison the tick
            log.exception("option-chain snapshot failed: %s", meta.symbol)

    scalps_emitted = 0
    swings_emitted = 0

    # ---- Scalp setups (RANGE_BOUND only) ----
    if result.regime == regime_mod.REGIME_RANGE_BOUND:
        levels = range_mod.detect_range(df)
        if levels is not None:
            scalp_recs = scalp_mod.evaluate(
                meta.symbol, df, levels=levels, vwap_value=vwap_value,
            )
            for rec in scalp_recs:
                if _has_active_match(
                    db, symbol=rec.symbol, category=rec.category,
                    direction=rec.direction, kind="scalp",
                ):
                    continue
                _persist_scalp(db, rec=rec, meta=meta, chain=chain, when=when)
                scalps_emitted += 1

    # ---- Swing setups (TRENDING only) ----
    if result.regime in (regime_mod.REGIME_TRENDING_UP, regime_mod.REGIME_TRENDING_DOWN):
        daily_df = daily_loader.load_daily(meta.symbol)
        if daily_df is not None and not daily_df.empty:
            swing_recs = swing_mod.evaluate(
                meta.symbol, daily_df,
                intraday_regime=result.regime,
                live_spot=result.spot,
            )
            for rec in swing_recs:
                if _has_active_match(
                    db, symbol=rec.symbol, category=rec.category,
                    direction=rec.direction, kind="swing",
                ):
                    continue
                _persist_swing(db, rec=rec, meta=meta, chain=chain, when=when)
                swings_emitted += 1

    return result.regime, scalps_emitted, swings_emitted


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run_tick(db: Session, *, now: Optional[datetime] = None) -> TickResult:
    """Execute one Live Market tick. Always returns a `TickResult`.

    Idempotent. Designed to be called from the scheduler every minute
    during NSE hours; safe to call manually via `/v1/admin/tick`.
    """
    when = now or _utc_now()

    symbols = [meta.symbol for meta in INDICES]
    quotes = _fetch_spots(symbols)
    spots_by_symbol: Dict[str, float] = {sym: q.last_price for sym, q in quotes.items()}

    # Append every received quote to its rolling buffer.
    for sym, q in quotes.items():
        intraday_store.append_tick(db, q, now=when)

    regimes: Dict[str, str] = {}
    total_scalps = 0
    total_swings = 0

    for meta in INDICES:
        try:
            regime, sc, sw = _evaluate_index(db, meta=meta, when=when)
            regimes[meta.symbol] = regime
            total_scalps += sc
            total_swings += sw
        except Exception:  # noqa: BLE001 - one index's failure must not poison the others
            log.exception("index evaluation failed: %s", meta.symbol)
            regimes[meta.symbol] = regime_mod.REGIME_CHOPPY

    scalps_resolved, swings_resolved = verifier.verify(db, spots_by_symbol, now=when)

    for meta in INDICES:
        intraday_store.prune_old(db, meta.symbol)

    db.commit()

    note = (
        ""
        if quotes
        else "no Upstox quotes (token missing/dead or out of session hours)"
    )
    return TickResult(
        processed_at=when,
        symbols_priced=len(quotes),
        regimes=regimes,
        scalps_emitted=total_scalps,
        swings_emitted=total_swings,
        setups_resolved=scalps_resolved + swings_resolved,
        note=note,
    )


__all__ = ["TickResult", "run_tick"]
