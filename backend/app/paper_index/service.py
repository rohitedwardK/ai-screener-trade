"""PaperIndexTradingService — orchestrates run_selection / simulate_day /
replay / reset / status for the paper-INDEX bot."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis import option_chain_metrics as ocm
from ..core.index_universe import all_index_symbols, get_index
from ..data import (
    index_csv_store,
    index_repository as idx_repo,
    live_quotes as _live_quotes,
    option_chain as oc_data,
)
from ..models.index_orm import IndexSignal, IndexSnapshot
from ..models.index_schemas import IndexScreenerSignal
from ..models.paper_index_orm import (
    PaperIndexOrder,
    PaperIndexPosition,
    PaperIndexTradeSignal,
)
from . import (
    adapter,
    config as cfg_mod,
    decision,
    journal as journal_mod,
    kill_switch,
    ledger,
    live_engine,
    performance,
    positions as pos_mod,
    regime,
)
from .simulator import (
    EV_ENTRY_FILL,
    EXIT_EVENTS,
    IndexSimEvent,
    IndexSimPosition,
    simulate_entry,
    simulate_position,
)
from .sizing import size as size_position

log = logging.getLogger(__name__)


# Module-level last-tick timestamp surfaced via /status. Updated on every
# successful process_live_tick() call (manual or scheduled).
_last_live_tick_at: Optional[datetime] = None


def last_live_tick_at() -> Optional[datetime]:
    return _last_live_tick_at


# ---------- Persistence helpers ----------

def _persist_decisions(
    db: Session,
    *,
    on_date: date,
    selected: List[decision.IndexDecision],
    skipped: List[decision.IndexDecision],
    market_regime: str,
) -> Tuple[List[PaperIndexTradeSignal], List[PaperIndexTradeSignal]]:
    sel_rows: List[PaperIndexTradeSignal] = []
    skp_rows: List[PaperIndexTradeSignal] = []

    def _common(d: decision.IndexDecision) -> dict:
        s = d.signal
        return {
            "signal_date": on_date,
            "symbol": s.symbol,
            "code": s.code,
            "setup_type": s.setup_type,
            "direction": s.direction,
            "option_type": s.option_type,
            "trend": s.market_regime,
            "market_regime": market_regime,
            "option_chain_bias": s.option_chain_bias,
            "screener_score": s.score,
            "automation_score": d.automation_score,
            "confidence": s.confidence,
            "risk_level": s.risk_level,
            "risk_reward": s.risk_reward,
            "spot": s.spot,
            "spot_stop_loss": s.spot_stop_loss,
            "spot_target_1": s.spot_target_1,
            "spot_target_2": s.spot_target_2,
            "spot_invalidation": s.spot_invalidation,
            "rsi": s.rsi,
            "atr_percent": s.atr_percent,
            "pcr": s.pcr,
            "max_pain": s.max_pain,
            "ai_reason": d.ai_reason,
            "extras_json": d.components,
        }

    for d in selected:
        row = ledger.insert_signal(db, decision="selected", skip_reason=None, **_common(d))
        sel_rows.append(row)
    for d in skipped:
        row = ledger.insert_signal(db, decision="skipped", skip_reason=d.skip_reason, **_common(d))
        skp_rows.append(row)
    db.flush()
    return sel_rows, skp_rows


def _next_weekly_expiry(meta, *, after: date) -> date:
    """Pick the next weekly expiry for an index. We approximate using the
    index's weekly_expiry_day; if not configured, default to the next Friday."""
    weekday_name = (meta.weekly_expiry_day or "Thursday").lower() if meta else "thursday"
    weekday_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    target = weekday_map.get(weekday_name, 3)
    delta = (target - after.weekday()) % 7
    if delta == 0:
        delta = 7
    return after + timedelta(days=delta)


def _option_chain_for(code: str, symbol: str) -> Optional[oc_data.OptionChainPayload]:
    try:
        return oc_data.fetch_option_chain(code, symbol)
    except Exception:  # noqa: BLE001
        log.exception("option chain fetch failed in service for %s", code)
        return None


def _open_pending_for_selected(
    db: Session,
    selected_decisions: List[decision.IndexDecision],
    selected_rows: List[PaperIndexTradeSignal],
    cfg_snap: cfg_mod.PaperIndexConfigSnapshot,
) -> int:
    """Map each selected decision into an option contract + size, persist."""
    opened = 0
    for d, row in zip(selected_decisions, selected_rows):
        sig = d.signal
        meta = get_index(sig.symbol)
        if meta is None:
            row.decision = "skipped"
            row.skip_reason = "missing index metadata"
            db.flush()
            continue

        # Resolve a strike + entry premium from the option chain (best effort).
        strike: Optional[float] = None
        entry_premium: Optional[float] = None
        chain = _option_chain_for(meta.code, meta.symbol)
        if chain is not None and chain.rows:
            from ..analysis.option_chain_metrics import OCRow as _OCRow
            oc_rows = [
                _OCRow(
                    strike=r.strike,
                    ce_oi=r.ce_oi, ce_change_oi=r.ce_change_oi, ce_volume=r.ce_volume,
                    ce_iv=r.ce_iv, ce_ltp=r.ce_ltp,
                    pe_oi=r.pe_oi, pe_change_oi=r.pe_change_oi, pe_volume=r.pe_volume,
                    pe_iv=r.pe_iv, pe_ltp=r.pe_ltp,
                ) for r in chain.rows
            ]
            strike = ocm.pick_strike(
                oc_rows, spot=sig.spot, option_type=sig.option_type,
                moneyness=cfg_snap.option_moneyness, strike_step=meta.strike_step,
            )
            if strike is not None:
                entry_premium = ocm.premium_at_strike(oc_rows, strike, option_type=sig.option_type)
        if strike is None:
            from ..core.index_universe import round_to_step
            strike = round_to_step(sig.spot, meta.strike_step)

        sizing = size_position(
            sig, cfg_snap,
            lot_size=meta.lot_size, strike=strike, entry_premium=entry_premium,
            delta_estimate=cfg_snap.option_delta_estimate,
        )
        if sizing.rejected:
            row.decision = "skipped"
            row.skip_reason = f"sizing rejected: {sizing.reject_reason}"
            db.flush()
            continue

        expiry = chain.expiry if (chain is not None) else _next_weekly_expiry(meta, after=row.signal_date)

        # Persist option-contract details onto the signal row.
        row.strike = strike
        row.expiry = expiry
        row.lot_size = meta.lot_size
        row.lots = sizing.lots
        row.entry_premium = sizing.entry_premium
        row.stop_loss_premium = sizing.stop_premium
        row.target_1_premium = sizing.target_1_premium
        row.target_2_premium = sizing.target_2_premium
        row.delta_estimate = sizing.delta_estimate
        db.flush()

        pos_mod.open_pending_position(
            db,
            signal=row,
            lots=sizing.lots,
            quantity=sizing.quantity,
            entry_premium=sizing.entry_premium,
            stop_premium=sizing.stop_premium,
            target_1_premium=sizing.target_1_premium,
            target_2_premium=sizing.target_2_premium,
            delta_estimate=sizing.delta_estimate,
            is_intraday=True,
        )
        opened += 1
    db.commit()
    return opened


# ---------- Public operations ----------

@dataclass
class IndexRunSelectionResult:
    on_date: date
    market_regime: str
    candidates_evaluated: int
    selected: List[PaperIndexTradeSignal]
    skipped: List[PaperIndexTradeSignal]


def _gather_today_candidates(db: Session, on_date: date) -> List[IndexScreenerSignal]:
    latest_run = db.scalar(select(__import__("sqlalchemy").func.max(IndexSignal.run_at)))
    if latest_run is None:
        return []
    signals = list(db.scalars(
        select(IndexSignal)
        .where(IndexSignal.run_at == latest_run)
        .order_by(IndexSignal.score.desc())
    ))
    if not signals:
        return []
    snapshots: Dict[str, IndexSnapshot] = {}
    for sym in {s.symbol for s in signals}:
        snap = db.scalar(
            select(IndexSnapshot)
            .where(IndexSnapshot.symbol == sym)
            .order_by(IndexSnapshot.as_of_date.desc())
            .limit(1)
        )
        if snap is not None:
            snapshots[sym] = snap

    market_regime = regime.market_regime(db)
    chosen: Dict[str, IndexScreenerSignal] = {}
    for sig in signals:
        snap = snapshots.get(sig.symbol)
        meta = get_index(sig.symbol)
        if meta is None:
            continue
        ss = adapter.from_signal_row(sig, snap, code=meta.code, market_regime=market_regime)
        if not adapter.is_actionable_setup(ss.setup_type):
            continue
        key = f"{sig.symbol}:{sig.direction}"
        existing = chosen.get(key)
        if existing is None or ss.score > existing.score:
            chosen[key] = ss
    return sorted(chosen.values(), key=lambda s: s.score, reverse=True)


def run_selection(db: Session, on_date: Optional[date] = None) -> IndexRunSelectionResult:
    cfg_snap = cfg_mod.snapshot(db)
    today = on_date or date.today()
    market = regime.market_regime(db, as_of=today)

    candidates = _gather_today_candidates(db, today)
    open_keys = ledger.open_symbol_directions(db)
    taken_today = ledger.signals_taken_on(db, today)

    selected_dec, skipped_dec = decision.evaluate(
        candidates,
        cfg_snap,
        market_regime=market,
        open_symbols=open_keys,
        trades_taken_today=taken_today,
    )

    sel_rows, skp_rows = _persist_decisions(
        db,
        on_date=today,
        selected=selected_dec,
        skipped=skipped_dec,
        market_regime=market,
    )

    _open_pending_for_selected(db, selected_dec, sel_rows, cfg_snap)

    return IndexRunSelectionResult(
        on_date=today,
        market_regime=market,
        candidates_evaluated=len(candidates),
        selected=sel_rows,
        skipped=skp_rows,
    )


@dataclass
class IndexSimulateDayResult:
    on_date: date
    entries_filled: int
    exits_triggered: int
    realized_pnl: float
    unrealized_pnl: float
    bot_status: str


def _candles_for(symbol: str, *, after: date, n: int = 10) -> pd.DataFrame:
    df = index_csv_store.load(symbol)
    if df.empty:
        return df
    cutoff = pd.Timestamp(after)
    return df.loc[df.index > cutoff].head(n)


def _last_close_for(symbol: str, *, on_or_before: date) -> Optional[float]:
    df = index_csv_store.load(symbol)
    if df.empty:
        return None
    sliced = df.loc[df.index <= pd.Timestamp(on_or_before)]
    if sliced.empty:
        return None
    return float(sliced.iloc[-1]["close"])


def simulate_day(db: Session, on_date: Optional[date] = None) -> IndexSimulateDayResult:
    cfg_snap = cfg_mod.snapshot(db)
    target_date = on_date or date.today()
    entries_filled = 0
    exits = 0

    # 1) Fill pending entries
    pending = list(db.scalars(
        select(PaperIndexPosition).where(PaperIndexPosition.status == "PENDING_ENTRY")
    ))
    for pos in pending:
        signal = db.get(PaperIndexTradeSignal, pos.signal_id)
        if signal is None:
            continue
        candles = _candles_for(pos.symbol, after=signal.signal_date, n=5)
        if candles.empty:
            continue
        candles = candles.loc[candles.index <= pd.Timestamp(target_date)]
        if candles.empty:
            continue
        sim_pos = IndexSimPosition(
            symbol=pos.symbol, code=pos.code,
            direction=pos.direction, option_type=pos.option_type,
            strike=pos.strike, expiry=pos.expiry,
            lot_size=pos.lot_size, lots=pos.lots,
            entry_spot=signal.spot or 0.0,
            entry_premium=signal.entry_premium or 0.0,
            quantity=pos.quantity,
            stop_loss=pos.stop_loss,
            target_1=pos.target_1, target_2=pos.target_2,
            delta=pos.delta_estimate or cfg_snap.option_delta_estimate,
            is_intraday=pos.is_intraday,
        )
        ev, _idx = simulate_entry(
            sim_pos, candles,
            entry_spot_target=signal.spot or 0.0,
            expiry_days=cfg_snap.entry_order_expiry_days,
        )
        if ev is None:
            continue
        pos_mod.apply_event(db, position=pos, event=ev)
        if ev.event_type == EV_ENTRY_FILL:
            entries_filled += 1
    db.commit()

    # 2) Walk open positions for stops/targets up to target_date
    open_positions = list(db.scalars(
        select(PaperIndexPosition).where(PaperIndexPosition.status.in_(["OPEN", "PARTIAL_EXIT"]))
    ))
    for pos in open_positions:
        if pos.entry_date is None or pos.entry_premium is None:
            continue
        df = index_csv_store.load(pos.symbol)
        if df.empty:
            continue
        candles = df.loc[(df.index > pd.Timestamp(pos.entry_date)) & (df.index <= pd.Timestamp(target_date))]
        if candles.empty:
            continue
        sim_pos = IndexSimPosition(
            symbol=pos.symbol, code=pos.code,
            direction=pos.direction, option_type=pos.option_type,
            strike=pos.strike, expiry=pos.expiry,
            lot_size=pos.lot_size, lots=pos.lots,
            entry_spot=pos.entry_spot or 0.0,
            entry_premium=pos.entry_premium,
            quantity=pos.quantity,
            stop_loss=pos.stop_loss,
            target_1=pos.target_1, target_2=pos.target_2,
            delta=pos.delta_estimate or cfg_snap.option_delta_estimate,
            entry_date=pos.entry_date,
            is_intraday=pos.is_intraday,
            breakeven_moved=pos.breakeven_moved,
            remaining_quantity=pos.remaining_quantity,
            status=pos.status,
        )
        events = simulate_position(
            sim_pos, candles,
            policy=cfg_snap.same_candle_policy,
            partial_exit_pct=cfg_snap.partial_exit_percent,
            trailing_stop_enabled=cfg_snap.trailing_stop_enabled,
            intraday_horizon_days=cfg_snap.intraday_horizon_days,
            swing_horizon_days=cfg_snap.max_holding_days,
        )
        for ev in events:
            pos_mod.apply_event(db, position=pos, event=ev)
            if ev.event_type in EXIT_EVENTS:
                exits += 1
            db.flush()
    db.commit()

    # 3) Mark-to-market open positions using delta-implied premium
    still_open = ledger.open_positions(db)
    premiums: Dict[int, float] = {}
    for p in still_open:
        if p.status not in ("OPEN", "PARTIAL_EXIT"):
            continue
        spot = _last_close_for(p.symbol, on_or_before=target_date)
        if spot is None or p.entry_premium is None or p.entry_spot is None:
            continue
        sign = 1 if p.direction == "LONG" else -1
        prem = p.entry_premium + (p.delta_estimate or cfg_snap.option_delta_estimate) * sign * (spot - p.entry_spot)
        premiums[p.id] = max(0.0, prem)
    pos_mod.mark_open_positions(db, premiums)
    db.commit()

    market = regime.market_regime(db, as_of=target_date)
    state = kill_switch.evaluate(db, cfg_snap, on_date=target_date, market_regime=market)
    performance.upsert_for_day(db, cfg_snap, on_date=target_date, bot_status=state.status)

    realized_today = ledger.realized_pnl_between(db, from_date=target_date, to_date=target_date)
    return IndexSimulateDayResult(
        on_date=target_date,
        entries_filled=entries_filled,
        exits_triggered=exits,
        realized_pnl=round(realized_today, 2),
        unrealized_pnl=round(ledger.total_unrealized_pnl(db), 2),
        bot_status=state.status,
    )


# ---------- Live tick (intraday trade-management agent) ----------

# NSE regular session: 09:15 to 15:30 IST, Monday to Friday. Mirrors
# `app.paper.service` so manual /process-live-tick calls and the scheduler
# job agree on whether the market is open.
_IST_OFFSET_MINUTES = 5 * 60 + 30
_MARKET_OPEN_HHMM = (9, 15)
_MARKET_CLOSE_HHMM = (15, 30)


def _now_ist() -> datetime:
    """Naive IST datetime regardless of host timezone."""
    from datetime import timezone as _tz
    return (datetime.now(_tz.utc) + timedelta(minutes=_IST_OFFSET_MINUTES)).replace(tzinfo=None)


def is_market_open(at: Optional[datetime] = None) -> bool:
    now = at or _now_ist()
    if now.weekday() >= 5:
        return False
    open_t = now.replace(hour=_MARKET_OPEN_HHMM[0], minute=_MARKET_OPEN_HHMM[1], second=0, microsecond=0)
    close_t = now.replace(hour=_MARKET_CLOSE_HHMM[0], minute=_MARKET_CLOSE_HHMM[1], second=0, microsecond=0)
    return open_t <= now <= close_t


@dataclass
class IndexLiveTickResult:
    processed_at: datetime
    symbols_priced: int
    exits_triggered: int
    realized_pnl_today: float
    unrealized_pnl: float
    bot_status: str
    prices: Dict[str, float]


def _eligible_live_symbols(db: Session) -> List[str]:
    """Underlying symbols of every OPEN / PARTIAL_EXIT paper-index position.

    PENDING_ENTRY positions are intentionally excluded - the live agent only
    manages already-open trades and never opens new ones intraday.
    """
    syms = set()
    for p in db.scalars(
        select(PaperIndexPosition).where(PaperIndexPosition.status.in_(["OPEN", "PARTIAL_EXIT"]))
    ):
        syms.add(p.symbol)
    return sorted(syms)


def process_live_tick(
    db: Session,
    *,
    prices: Optional[Dict[str, float]] = None,
    at: Optional[datetime] = None,
) -> IndexLiveTickResult:
    """Apply one live-spot tick to every OPEN / PARTIAL_EXIT paper-index position.

    The live agent is simulation-only:
        - Reads spot prices for the underlying indices (^NSEI / ^BSESN /
          ^NSEBANK) from the shared `data.live_quotes` cache (TTL 30s).
        - Maps each spot to an estimated option premium via the existing
          delta model and walks the position through `live_engine` for
          SL / T1-partial / T2 / breakeven-trail.
        - Re-marks remaining open positions and refreshes the daily-perf
          + kill-switch row.
        - Never opens new positions intraday. PENDING entries continue to
          be filled by the daily `simulate_day` pass.
    """
    global _last_live_tick_at

    cfg_snap = cfg_mod.snapshot(db)
    when = at or _now_ist()
    today = when.date()

    needed = _eligible_live_symbols(db)
    if prices is None:
        prices = _live_quotes.fetch_live_prices(needed) if needed else {}

    market = regime.market_regime(db, as_of=today)
    exits = 0

    open_positions = list(db.scalars(
        select(PaperIndexPosition).where(PaperIndexPosition.status.in_(["OPEN", "PARTIAL_EXIT"]))
    ))
    for pos in open_positions:
        spot_px = prices.get(pos.symbol)
        if spot_px is None or pos.entry_premium is None or pos.entry_spot is None:
            continue
        sim_pos = IndexSimPosition(
            symbol=pos.symbol, code=pos.code,
            direction=pos.direction, option_type=pos.option_type,
            strike=pos.strike, expiry=pos.expiry,
            lot_size=pos.lot_size, lots=pos.lots,
            entry_spot=pos.entry_spot,
            entry_premium=pos.entry_premium,
            quantity=pos.quantity,
            stop_loss=pos.stop_loss,
            target_1=pos.target_1, target_2=pos.target_2,
            delta=pos.delta_estimate or cfg_snap.option_delta_estimate,
            entry_date=pos.entry_date,
            is_intraday=pos.is_intraday,
            breakeven_moved=pos.breakeven_moved,
            remaining_quantity=pos.remaining_quantity,
            status=pos.status,
        )
        events = live_engine.evaluate_open_position(
            sim_pos, spot_px, at=today,
            partial_exit_pct=cfg_snap.partial_exit_percent,
            trailing_stop_enabled=cfg_snap.trailing_stop_enabled,
        )
        for ev in events:
            pos_mod.apply_event(db, position=pos, event=ev)
            if ev.event_type in EXIT_EVENTS:
                exits += 1
            db.flush()
    db.commit()

    # Mark remaining open positions to the latest delta-implied premium so
    # the dashboard's unrealized P&L tracks the live spot tick.
    still_open = ledger.open_positions(db)
    premiums: Dict[int, float] = {}
    for p in still_open:
        if p.status not in ("OPEN", "PARTIAL_EXIT"):
            continue
        spot_px = prices.get(p.symbol)
        if spot_px is None or p.entry_premium is None or p.entry_spot is None:
            continue
        prem = live_engine.spot_to_premium(
            spot=spot_px,
            entry_spot=p.entry_spot,
            entry_premium=p.entry_premium,
            delta=p.delta_estimate or cfg_snap.option_delta_estimate,
            direction=p.direction,
        )
        premiums[p.id] = prem
    pos_mod.mark_open_positions(db, premiums)
    db.commit()

    state = kill_switch.evaluate(db, cfg_snap, on_date=today, market_regime=market)
    performance.upsert_for_day(db, cfg_snap, on_date=today, bot_status=state.status)
    db.commit()

    _last_live_tick_at = when

    realized_today = ledger.realized_pnl_between(db, from_date=today, to_date=today)
    return IndexLiveTickResult(
        processed_at=when,
        symbols_priced=len(prices),
        exits_triggered=exits,
        realized_pnl_today=round(realized_today, 2),
        unrealized_pnl=round(ledger.total_unrealized_pnl(db), 2),
        bot_status=state.status,
        prices=dict(prices),
    )


# ---------- Replay ----------

@dataclass
class IndexReplayDaySummary:
    on_date: date
    bot_status: str
    selected: int
    skipped: int
    entries_filled: int
    exits_triggered: int
    realized_pnl: float
    ending_equity: float


def replay(db: Session, *, start: date, end: date) -> Dict[str, Any]:
    """Day-by-day replay using cached index CSVs (no look-ahead).

    NOTE: For full screener-style replay we would re-derive signals per as-of
    date. Index option chain history is not stored, so the replay re-uses the
    existing snapshot bias (which is appropriate for short windows). The
    simulator side is fully look-ahead-free."""
    cfg_snap = cfg_mod.snapshot(db)
    summary: List[IndexReplayDaySummary] = []
    total_realized = 0.0

    cur = start
    while cur <= end:
        try:
            res = run_selection(db, on_date=cur)
        except Exception:  # noqa: BLE001
            log.exception("run_selection failed for %s", cur)
            res = IndexRunSelectionResult(
                on_date=cur, market_regime="Sideways",
                candidates_evaluated=0, selected=[], skipped=[],
            )
        sd = simulate_day(db, on_date=cur)
        total_realized += sd.realized_pnl
        cum = ledger.realized_pnl_between(db, to_date=cur)
        ending_equity = float(cfg_snap.virtual_capital) + cum + ledger.total_unrealized_pnl(db)
        summary.append(IndexReplayDaySummary(
            on_date=cur,
            bot_status=sd.bot_status,
            selected=len(res.selected),
            skipped=len(res.skipped),
            entries_filled=sd.entries_filled,
            exits_triggered=sd.exits_triggered,
            realized_pnl=sd.realized_pnl,
            ending_equity=round(ending_equity, 2),
        ))
        cur += timedelta(days=1)

    final_equity = summary[-1].ending_equity if summary else float(cfg_snap.virtual_capital)
    return {
        "start": start,
        "end": end,
        "days_processed": len(summary),
        "final_equity": final_equity,
        "total_realized_pnl": round(total_realized, 2),
        "summary": summary,
    }


# ---------- Reset / status ----------

def reset(db: Session) -> Dict[str, int]:
    return ledger.reset_all(db)


def status(db: Session) -> Dict[str, Any]:
    cfg_snap = cfg_mod.snapshot(db)
    today = date.today()
    market = regime.market_regime(db, as_of=today)
    state = kill_switch.evaluate(db, cfg_snap, on_date=today, market_regime=market)

    realized_today = ledger.realized_pnl_between(db, from_date=today, to_date=today)
    realized_total = ledger.realized_pnl_between(db)
    unreal = ledger.total_unrealized_pnl(db)
    open_count = len(ledger.open_positions(db))
    trades_taken = ledger.signals_taken_on(db, today)

    return {
        "bot_status": state.status,
        "virtual_capital": cfg_snap.virtual_capital,
        "current_equity": round(cfg_snap.virtual_capital + realized_total + unreal, 2),
        "realized_pnl_today": round(realized_today, 2),
        "unrealized_pnl_today": round(unreal, 2),
        "realized_pnl_total": round(realized_total, 2),
        "unrealized_pnl_total": round(unreal, 2),
        "trades_taken_today": trades_taken,
        "remaining_trades_today": max(0, cfg_snap.max_trades_per_day - trades_taken),
        "open_positions": open_count,
        "daily_loss_limit_percent": cfg_snap.max_daily_loss_percent,
        "live_trading_enabled": cfg_snap.live_trading_enabled,
        "is_market_open": is_market_open(),
        "last_live_tick_at": _last_live_tick_at,
        "market_regime": market,
        "reason": state.reason,
    }
