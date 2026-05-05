"""PaperTradingService.

Orchestrates the high-level operations:
  - run_selection(date)   : adapt screener output -> decision -> store signals + open PENDING positions
  - simulate_day(date)    : fill pending entries, walk open positions, mark-to-market, update daily perf
  - replay(start, end)    : day-by-day historical loop using CSVs (no look-ahead)
  - reset()               : wipe paper state
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data import csv_store, repository as repo
from ..models.paper_orm import (
    PaperOrder,
    PaperPosition,
    PaperTradeSignal,
)
from ..models.paper_schemas import ScreenerSignal
from . import (
    adapter,
    backtest as bt,
    config as cfg_mod,
    decision,
    journal,
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
    SimEvent,
    SimPosition,
    simulate_entry,
    simulate_position,
)
from .sizing import size

log = logging.getLogger(__name__)

# Module-level last-tick timestamp surfaced via /status. Updated on every
# successful process_live_tick() call (manual or scheduled). Optional - the
# status endpoint just reports `None` until the first tick lands.
_last_live_tick_at: Optional[datetime] = None


def last_live_tick_at() -> Optional[datetime]:
    return _last_live_tick_at


# ---------- Helpers ----------

def _persist_decisions(
    db: Session,
    *,
    on_date: date,
    selected: List[decision.Decision],
    skipped: List[decision.Decision],
    market_regime: str,
) -> Tuple[List[PaperTradeSignal], List[PaperTradeSignal]]:
    """Insert selected + skipped signal rows; return ORM objects in order."""
    sel_rows: List[PaperTradeSignal] = []
    skp_rows: List[PaperTradeSignal] = []

    def _common_fields(d: decision.Decision) -> dict:
        s = d.signal
        return {
            "signal_date": on_date,
            "symbol": s.symbol,
            "setup_type": s.setup_type,
            "trend": s.trend,
            "market_regime": market_regime,
            "screener_score": s.score,
            "automation_score": d.automation_score,
            "confidence": s.confidence,
            "risk_level": s.risk_level,
            "risk_reward": s.risk_reward,
            "entry": s.entry,
            "entry_zone_low": s.entry_zone_low,
            "entry_zone_high": s.entry_zone_high,
            "stop_loss": s.stop_loss,
            "target_1": s.target_1,
            "target_2": s.target_2,
            "rsi": s.rsi,
            "volume_ratio": s.volume_ratio,
            "atr_percent": s.atr_percent,
            "ai_reason": d.ai_reason,
            "extras_json": d.components,
        }

    for d in selected:
        row = ledger.insert_signal(
            db,
            decision="selected",
            skip_reason=None,
            **_common_fields(d),
        )
        sel_rows.append(row)
    for d in skipped:
        row = ledger.insert_signal(
            db,
            decision="skipped",
            skip_reason=d.skip_reason,
            **_common_fields(d),
        )
        skp_rows.append(row)
    db.flush()
    return sel_rows, skp_rows


def _open_pending_for_selected(
    db: Session,
    selected_decisions: List[decision.Decision],
    selected_rows: List[PaperTradeSignal],
    cfg_snap,
) -> int:
    """For each selected decision that passes sizing, create a PENDING_ENTRY position."""
    opened = 0
    for d, row in zip(selected_decisions, selected_rows):
        sig = d.signal
        sizing = size(sig, cfg_snap)
        if sizing.rejected:
            row.decision = "skipped"
            row.skip_reason = f"sizing rejected: {sizing.reject_reason}"
            db.flush()
            continue
        is_intraday = sig.setup_type == "Momentum Continuation" and (sig.atr_percent or 0) >= 1.5
        # Use intraday flag only when explicitly an intraday-style screener category;
        # for now keep all paper trades as swing (no intraday data resolution).
        is_intraday = False
        pos_mod.open_pending_position(
            db,
            signal=row,
            quantity=sizing.quantity,
            is_intraday=is_intraday,
        )
        opened += 1
    db.commit()
    return opened


# ---------- Public operations ----------

@dataclass
class RunSelectionResult:
    on_date: date
    market_regime: str
    candidates_evaluated: int
    selected: List[PaperTradeSignal]
    skipped: List[PaperTradeSignal]


def _gather_today_candidates(db: Session, on_date: date) -> List[ScreenerSignal]:
    """Build ScreenerSignals from the latest screener Signal+Snapshot rows."""
    from ..models.orm import Signal, Snapshot
    latest_run = db.scalar(select(__import__("sqlalchemy").func.max(Signal.run_at)))
    if latest_run is None:
        return []

    signals = list(db.scalars(
        select(Signal).where(Signal.run_at == latest_run)
        .order_by(Signal.score.desc())
    ))
    if not signals:
        return []

    snapshots: Dict[str, Snapshot] = {}
    for sym in {s.symbol for s in signals}:
        snap = db.scalar(
            select(Snapshot).where(Snapshot.symbol == sym).order_by(Snapshot.as_of_date.desc()).limit(1)
        )
        if snap is not None:
            snapshots[sym] = snap

    market_regime = regime.market_regime(db)
    chosen: Dict[str, ScreenerSignal] = {}
    for sig in signals:
        snap = snapshots.get(sig.symbol)
        ss = adapter.from_signal(sig, snap, market_regime=market_regime)
        if not adapter.is_actionable_setup(ss.setup_type):
            continue
        # Keep best per symbol
        existing = chosen.get(sig.symbol)
        if existing is None or ss.score > existing.score:
            chosen[sig.symbol] = ss
    return sorted(chosen.values(), key=lambda s: s.score, reverse=True)


def run_selection(db: Session, on_date: Optional[date] = None) -> RunSelectionResult:
    """Read latest screener signals -> decision engine -> persist -> open pendings."""
    cfg_snap = cfg_mod.snapshot(db)
    today = on_date or date.today()
    market_regime = regime.market_regime(db, as_of=today)

    candidates = _gather_today_candidates(db, today)
    open_syms = ledger.open_symbols(db)
    taken_today = ledger.signals_taken_on(db, today)

    selected_dec, skipped_dec = decision.evaluate(
        candidates,
        cfg_snap,
        market_regime=market_regime,
        open_symbols=open_syms,
        trades_taken_today=taken_today,
    )

    sel_rows, skp_rows = _persist_decisions(
        db,
        on_date=today,
        selected=selected_dec,
        skipped=skipped_dec,
        market_regime=market_regime,
    )

    _open_pending_for_selected(db, selected_dec, sel_rows, cfg_snap)

    return RunSelectionResult(
        on_date=today,
        market_regime=market_regime,
        candidates_evaluated=len(candidates),
        selected=sel_rows,
        skipped=skp_rows,
    )


@dataclass
class SimulateDayResult:
    on_date: date
    entries_filled: int
    exits_triggered: int
    realized_pnl: float
    unrealized_pnl: float
    bot_status: str


def _candles_for(symbol: str, *, after: date, n: int = 30) -> pd.DataFrame:
    df = csv_store.load(symbol)
    if df.empty:
        return df
    cutoff = pd.Timestamp(after)
    return df.loc[df.index > cutoff].head(n)


def _last_close_for(symbol: str, *, on_or_before: date) -> Optional[float]:
    df = csv_store.load(symbol)
    if df.empty:
        return None
    sliced = df.loc[df.index <= pd.Timestamp(on_or_before)]
    if sliced.empty:
        return None
    return float(sliced.iloc[-1]["close"])


def simulate_day(db: Session, on_date: Optional[date] = None) -> SimulateDayResult:
    """Process pending entries and run open positions through `on_date` candle.

    For paper-mode forward simulation we fill entries using the candle *after* the
    signal date. For convenience, when `on_date` is None we use `date.today()`.
    """
    cfg_snap = cfg_mod.snapshot(db)
    target_date = on_date or date.today()

    entries_filled = 0
    exits = 0

    # 1) Fill pending entries -----------------------------------------------------
    pending_positions = list(db.scalars(
        select(PaperPosition).where(PaperPosition.status == "PENDING_ENTRY")
    ))
    for pos in pending_positions:
        # Use candles AFTER the signal date - never the signal date itself.
        signal = db.get(PaperTradeSignal, pos.signal_id)
        if signal is None:
            continue
        candles = _candles_for(pos.symbol, after=signal.signal_date, n=5)
        if candles.empty:
            continue
        # Restrict to candles up to target_date
        candles = candles.loc[candles.index <= pd.Timestamp(target_date)]
        if candles.empty:
            continue

        sim_pos = SimPosition(
            symbol=pos.symbol,
            entry_price=signal.entry,
            quantity=pos.quantity,
            stop_loss=pos.stop_loss,
            target_1=pos.target_1,
            target_2=pos.target_2,
            entry_zone_low=signal.entry_zone_low,
            entry_zone_high=signal.entry_zone_high,
            is_intraday=pos.is_intraday,
        )
        ev, _idx = simulate_entry(sim_pos, candles, expiry_days=5)
        if ev is None:
            continue
        pos_mod.apply_event(db, position=pos, event=ev)
        if ev.event_type == EV_ENTRY_FILL:
            entries_filled += 1

    db.commit()

    # 2) Walk open positions for stops/targets up to target_date ------------------
    open_positions = list(db.scalars(
        select(PaperPosition).where(PaperPosition.status.in_(["OPEN", "PARTIAL_EXIT"]))
    ))
    for pos in open_positions:
        if pos.entry_date is None or pos.entry_price is None:
            continue
        # Run from the candle AFTER entry_date through target_date.
        df = csv_store.load(pos.symbol)
        if df.empty:
            continue
        candles = df.loc[(df.index > pd.Timestamp(pos.entry_date)) & (df.index <= pd.Timestamp(target_date))]
        if candles.empty:
            continue
        sim_pos = SimPosition(
            symbol=pos.symbol,
            entry_price=pos.entry_price,
            quantity=pos.quantity,
            stop_loss=pos.stop_loss,
            target_1=pos.target_1,
            target_2=pos.target_2,
            is_intraday=pos.is_intraday,
            breakeven_moved=pos.breakeven_moved,
            remaining_quantity=pos.remaining_quantity,
            status=pos.status,
        )
        events = simulate_position(
            sim_pos,
            candles,
            policy=cfg_snap.same_candle_policy,
            partial_exit_pct=cfg_snap.partial_exit_percent,
            trailing_stop_enabled=cfg_snap.trailing_stop_enabled,
        )
        for ev in events:
            pos_mod.apply_event(db, position=pos, event=ev)
            if ev.event_type in EXIT_EVENTS:
                exits += 1
            db.flush()
    db.commit()

    # 3) Mark-to-market remaining open positions to last close ---------------------
    still_open = ledger.open_positions(db)
    prices: Dict[str, float] = {}
    for p in still_open:
        if p.status not in ("OPEN", "PARTIAL_EXIT"):
            continue
        px = _last_close_for(p.symbol, on_or_before=target_date)
        if px is not None:
            prices[p.symbol] = px
    pos_mod.mark_open_positions(db, prices)
    db.commit()

    # 4) Daily perf + bot status -------------------------------------------------
    market_regime = regime.market_regime(db, as_of=target_date)
    state = kill_switch.evaluate(db, cfg_snap, on_date=target_date, market_regime=market_regime)
    performance.upsert_for_day(db, cfg_snap, on_date=target_date, bot_status=state.status)

    realized_today = ledger.realized_pnl_between(db, from_date=target_date, to_date=target_date)
    return SimulateDayResult(
        on_date=target_date,
        entries_filled=entries_filled,
        exits_triggered=exits,
        realized_pnl=round(realized_today, 2),
        unrealized_pnl=round(ledger.total_unrealized_pnl(db), 2),
        bot_status=state.status,
    )


# ---------- Live tick (intraday) ----------

# NSE regular session: 09:15 to 15:30 IST, Monday to Friday.
_IST_OFFSET_MINUTES = 5 * 60 + 30
_MARKET_OPEN_HHMM = (9, 15)
_MARKET_CLOSE_HHMM = (15, 30)


def _now_ist() -> datetime:
    """Naive IST datetime, regardless of host timezone.

    The scheduler runs APScheduler with `timezone="Asia/Kolkata"`; this helper
    matches that frame so manual /process-live-tick calls and the scheduler
    job agree on whether the market is open.
    """
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
class LiveTickResult:
    processed_at: datetime
    symbols_priced: int
    entries_filled: int
    exits_triggered: int
    realized_pnl_today: float
    unrealized_pnl: float
    bot_status: str
    prices: Dict[str, float]


def _eligible_symbols(db: Session) -> List[str]:
    """Symbols of every PENDING_ENTRY / OPEN / PARTIAL_EXIT position - the
    only ones the live engine needs prices for."""
    syms = set()
    for p in db.scalars(
        select(PaperPosition).where(PaperPosition.status.in_(["PENDING_ENTRY", "OPEN", "PARTIAL_EXIT"]))
    ):
        syms.add(p.symbol)
    return sorted(syms)


def process_live_tick(
    db: Session,
    *,
    prices: Optional[Dict[str, float]] = None,
    at: Optional[datetime] = None,
) -> LiveTickResult:
    """Apply one live-price tick to all PENDING / OPEN paper positions.

    If `prices` is None the function fetches them itself via the shared
    `data.live_quotes` helper (cached 30 s) for only the symbols that have
    active positions. Pass `prices` directly in tests to keep them offline.

    Same-day kill-switch behaviour: if the bot has already hit its daily
    loss limit or max-open-positions cap, new ENTRY_FILL events are skipped
    but exits still process so risk keeps unwinding.
    """
    global _last_live_tick_at

    cfg_snap = cfg_mod.snapshot(db)
    when = at or _now_ist()
    today = when.date()

    needed = _eligible_symbols(db)
    if prices is None:
        from ..data import live_quotes as _live_quotes
        prices = _live_quotes.fetch_live_prices(needed) if needed else {}

    market_regime = regime.market_regime(db, as_of=today)
    pre_state = kill_switch.evaluate(db, cfg_snap, on_date=today, market_regime=market_regime)
    can_open_new = pre_state.status == "ACTIVE"

    entries = 0
    exits = 0

    # 1) Pending entries.
    pending = list(db.scalars(
        select(PaperPosition).where(PaperPosition.status == "PENDING_ENTRY")
    ))
    for pos in pending:
        px = prices.get(pos.symbol)
        if px is None:
            continue
        signal = db.get(PaperTradeSignal, pos.signal_id)
        if signal is None:
            continue
        sim_pos = SimPosition(
            symbol=pos.symbol,
            entry_price=signal.entry,
            quantity=pos.quantity,
            stop_loss=pos.stop_loss,
            target_1=pos.target_1,
            target_2=pos.target_2,
            entry_zone_low=signal.entry_zone_low,
            entry_zone_high=signal.entry_zone_high,
            is_intraday=pos.is_intraday,
        )
        ev = live_engine.evaluate_pending_entry(sim_pos, px, at=today)
        if ev is None:
            continue
        if not can_open_new:
            log.info(
                "live tick: skipping ENTRY_FILL for %s (kill switch: %s)",
                pos.symbol, pre_state.status,
            )
            continue
        pos_mod.apply_event(db, position=pos, event=ev)
        entries += 1
    db.flush()

    # 2) Open / partial-exit positions.
    open_positions = list(db.scalars(
        select(PaperPosition).where(PaperPosition.status.in_(["OPEN", "PARTIAL_EXIT"]))
    ))
    for pos in open_positions:
        px = prices.get(pos.symbol)
        if px is None or pos.entry_price is None:
            continue
        sim_pos = SimPosition(
            symbol=pos.symbol,
            entry_price=pos.entry_price,
            quantity=pos.quantity,
            stop_loss=pos.stop_loss,
            target_1=pos.target_1,
            target_2=pos.target_2,
            is_intraday=pos.is_intraday,
            breakeven_moved=pos.breakeven_moved,
            remaining_quantity=pos.remaining_quantity,
            status=pos.status,
        )
        events = live_engine.evaluate_open_position(
            sim_pos, px, at=today,
            partial_exit_pct=cfg_snap.partial_exit_percent,
            trailing_stop_enabled=cfg_snap.trailing_stop_enabled,
        )
        for ev in events:
            pos_mod.apply_event(db, position=pos, event=ev)
            if ev.event_type in EXIT_EVENTS:
                exits += 1
            db.flush()
    db.commit()

    # 3) Mark-to-market remaining open positions to the latest tick.
    pos_mod.mark_open_positions(db, prices)
    db.commit()

    # 4) Daily perf + post-tick kill-switch refresh.
    post_state = kill_switch.evaluate(db, cfg_snap, on_date=today, market_regime=market_regime)
    performance.upsert_for_day(db, cfg_snap, on_date=today, bot_status=post_state.status)
    db.commit()

    _last_live_tick_at = when

    realized_today = ledger.realized_pnl_between(db, from_date=today, to_date=today)
    return LiveTickResult(
        processed_at=when,
        symbols_priced=len(prices),
        entries_filled=entries,
        exits_triggered=exits,
        realized_pnl_today=round(realized_today, 2),
        unrealized_pnl=round(ledger.total_unrealized_pnl(db), 2),
        bot_status=post_state.status,
        prices=dict(prices),
    )


# ---------- Replay ----------

@dataclass
class ReplayDaySummary:
    on_date: date
    bot_status: str
    selected: int
    skipped: int
    entries_filled: int
    exits_triggered: int
    realized_pnl: float
    ending_equity: float


def _historical_run_selection(
    db: Session,
    on_date: date,
    cfg_snap,
) -> Tuple[str, List[PaperTradeSignal], List[PaperTradeSignal], int]:
    """Replay-mode equivalent of run_selection() that reads from CSVs (no DB signals)."""
    snap = bt.build_day_snapshot(on_date)
    open_syms = ledger.open_symbols(db)
    taken = ledger.signals_taken_on(db, on_date)
    selected_dec, skipped_dec = decision.evaluate(
        snap.candidates,
        cfg_snap,
        market_regime=snap.market_regime,
        open_symbols=open_syms,
        trades_taken_today=taken,
    )
    sel_rows, skp_rows = _persist_decisions(
        db,
        on_date=on_date,
        selected=selected_dec,
        skipped=skipped_dec,
        market_regime=snap.market_regime,
    )
    _open_pending_for_selected(db, selected_dec, sel_rows, cfg_snap)
    return snap.market_regime, sel_rows, skp_rows, len(snap.candidates)


def replay(
    db: Session,
    *,
    start: date,
    end: date,
) -> Dict[str, Any]:
    """Run day-by-day from `start` to `end` using cached CSVs (no look-ahead)."""
    cfg_snap = cfg_mod.snapshot(db)
    summary: List[ReplayDaySummary] = []
    total_realized = 0.0

    for d in bt.replay_dates(start, end):
        try:
            market_regime, sel_rows, skp_rows, n_cand = _historical_run_selection(db, d, cfg_snap)
        except Exception:  # noqa: BLE001
            log.exception("run_selection failed for %s", d)
            sel_rows, skp_rows, n_cand, market_regime = [], [], 0, "Sideways"

        sd = simulate_day(db, on_date=d)
        total_realized += sd.realized_pnl

        cum = ledger.realized_pnl_between(db, to_date=d)
        ending_equity = float(cfg_snap.virtual_capital) + cum + ledger.total_unrealized_pnl(db)

        summary.append(ReplayDaySummary(
            on_date=d,
            bot_status=sd.bot_status,
            selected=len(sel_rows),
            skipped=len(skp_rows),
            entries_filled=sd.entries_filled,
            exits_triggered=sd.exits_triggered,
            realized_pnl=sd.realized_pnl,
            ending_equity=round(ending_equity, 2),
        ))

    final_equity = summary[-1].ending_equity if summary else float(cfg_snap.virtual_capital)
    return {
        "start": start,
        "end": end,
        "days_processed": len(summary),
        "final_equity": final_equity,
        "total_realized_pnl": round(total_realized, 2),
        "summary": summary,
    }


# ---------- Reset ----------

def reset(db: Session) -> Dict[str, int]:
    return ledger.reset_all(db)


# ---------- Live diagnostics ----------

def _distance_pct(target: Optional[float], current: Optional[float]) -> Optional[float]:
    if target is None or current is None or current == 0:
        return None
    return round(((float(target) - float(current)) / float(current)) * 100.0, 3)


def live_debug(db: Session) -> Dict[str, Any]:
    """One-call diagnostic that explains why the bot is (or is not) trading.

    Returns every gate the live tick loop has to clear, plus a per-position
    breakdown of how far each PENDING/OPEN position is from its entry / stop /
    targets. The frontend renders this so the operator can see exactly which
    gate is blocking trades without having to grep logs.
    """
    from ..models.orm import Signal as _ScreenerSignal

    cfg_snap = cfg_mod.snapshot(db)
    now = _now_ist()
    today = now.date()
    market_open = is_market_open(now)

    if now.weekday() >= 5:
        market_reason = f"weekend (today is {now.strftime('%A')})"
    elif not market_open:
        market_reason = (
            f"outside 09:15-15:30 IST (now {now.strftime('%H:%M IST')})"
        )
    else:
        market_reason = "market is open"

    latest_screener_run = db.scalar(
        select(__import__("sqlalchemy").func.max(_ScreenerSignal.run_at))
    )
    screener_signal_count = 0
    if latest_screener_run is not None:
        screener_signal_count = int(db.scalar(
            select(__import__("sqlalchemy").func.count(_ScreenerSignal.id))
            .where(_ScreenerSignal.run_at == latest_screener_run)
        ) or 0)
    screener_age_hours = (
        round((datetime.utcnow() - latest_screener_run).total_seconds() / 3600.0, 1)
        if latest_screener_run else None
    )

    # Latest Run Selection summary
    last_sig_date = db.scalar(
        select(__import__("sqlalchemy").func.max(PaperTradeSignal.signal_date))
    )
    selected_today = 0
    skipped_today = 0
    top_skip_reasons: List[Dict[str, Any]] = []
    if last_sig_date is not None:
        selected_today = int(db.scalar(
            select(__import__("sqlalchemy").func.count(PaperTradeSignal.id)).where(
                PaperTradeSignal.signal_date == last_sig_date,
                PaperTradeSignal.decision == "selected",
            )
        ) or 0)
        skipped_today = int(db.scalar(
            select(__import__("sqlalchemy").func.count(PaperTradeSignal.id)).where(
                PaperTradeSignal.signal_date == last_sig_date,
                PaperTradeSignal.decision == "skipped",
            )
        ) or 0)
        skip_rows = list(db.scalars(
            select(PaperTradeSignal).where(
                PaperTradeSignal.signal_date == last_sig_date,
                PaperTradeSignal.decision == "skipped",
            ).limit(50)
        ))
        from collections import Counter
        c = Counter((r.skip_reason or "unknown") for r in skip_rows)
        top_skip_reasons = [
            {"reason": reason, "count": n} for reason, n in c.most_common(5)
        ]

    # Per-position state ----------------------------------------------------
    pending = list(db.scalars(
        select(PaperPosition).where(PaperPosition.status == "PENDING_ENTRY")
    ))
    open_pos = list(db.scalars(
        select(PaperPosition).where(PaperPosition.status.in_(["OPEN", "PARTIAL_EXIT"]))
    ))

    needed = sorted({p.symbol for p in (pending + open_pos)})
    prices: Dict[str, float] = {}
    price_fetch_error: Optional[str] = None
    if needed and market_open and cfg_snap.live_trading_enabled:
        try:
            from ..data import live_quotes as _lq
            prices = _lq.fetch_live_prices(needed)
        except Exception as exc:  # noqa: BLE001
            price_fetch_error = f"{type(exc).__name__}: {exc}"
    elif needed:
        from ..data import live_quotes as _lq
        prices = _lq.cached_prices()

    pending_detail: List[Dict[str, Any]] = []
    for p in pending:
        sig = db.get(PaperTradeSignal, p.signal_id)
        entry = sig.entry if sig else None
        last_px = prices.get(p.symbol)
        would_fill = (
            last_px is not None and entry is not None and last_px <= float(entry)
        )
        pending_detail.append({
            "symbol": p.symbol,
            "entry_price": entry,
            "last_price": last_px,
            "distance_to_entry_pct": _distance_pct(entry, last_px),
            "would_fill_now": would_fill,
        })

    open_detail: List[Dict[str, Any]] = []
    for p in open_pos:
        last_px = prices.get(p.symbol)
        open_detail.append({
            "symbol": p.symbol,
            "entry_price": p.entry_price,
            "last_price": last_px,
            "stop_loss": p.stop_loss,
            "target_1": p.target_1,
            "target_2": p.target_2,
            "remaining_quantity": p.remaining_quantity,
            "breakeven_moved": p.breakeven_moved,
            "distance_to_stop_pct": _distance_pct(p.stop_loss, last_px),
            "distance_to_t1_pct": _distance_pct(p.target_1, last_px),
            "distance_to_t2_pct": _distance_pct(p.target_2, last_px),
        })

    # Best-effort scheduler liveness: during market hours with live mode on,
    # the tick should be no older than ~3 minutes (cron fires every minute).
    scheduler_relevant = market_open and cfg_snap.live_trading_enabled
    if scheduler_relevant and _last_live_tick_at is not None:
        last_tick_naive = _last_live_tick_at.replace(tzinfo=None) if _last_live_tick_at.tzinfo else _last_live_tick_at
        scheduler_age_sec = (now - last_tick_naive).total_seconds()
        scheduler_ok = scheduler_age_sec < 180
    elif scheduler_relevant:
        scheduler_age_sec = None
        scheduler_ok = False
    else:
        scheduler_age_sec = None
        scheduler_ok = True  # not applicable; don't fail this gate

    gates = {
        "live_trading_enabled": {
            "ok": bool(cfg_snap.live_trading_enabled),
            "value": bool(cfg_snap.live_trading_enabled),
            "fix": "Open Paper Trading > Config and set 'Live trading (auto fills/exits)' = Enabled.",
        },
        "scheduler_running": {
            "ok": scheduler_ok,
            "value": {
                "last_tick_at": _last_live_tick_at.isoformat() if _last_live_tick_at else None,
                "age_seconds": scheduler_age_sec,
            },
            "fix": "Restart the backend (uvicorn). Verify ENABLE_SCHEDULER=True in backend/.env. The startup log should mention 'paper live-tick */1'.",
        },
        "is_market_open": {
            "ok": market_open,
            "value": market_open,
            "reason": market_reason,
            "fix": "NSE only trades 09:15-15:30 IST Mon-Fri. Live ticks are skipped outside this window.",
        },
        "screener_has_recent_data": {
            "ok": screener_age_hours is not None and screener_age_hours <= 36.0,
            "value": {
                "latest_run_at": latest_screener_run.isoformat() if latest_screener_run else None,
                "age_hours": screener_age_hours,
                "signals_in_run": screener_signal_count,
            },
            "fix": "POST /admin/refresh (or use the Refresh button) to pull today's OHLCV before pressing Run Selection.",
        },
        "has_actionable_positions": {
            "ok": (len(pending) + len(open_pos)) > 0,
            "value": {"pending": len(pending), "open": len(open_pos)},
            "fix": (
                "Press 'Run Selection' to seed PENDING_ENTRY positions. "
                "If you already pressed it and got 0 selected, look at "
                "'last_run_selection.top_skip_reasons' below to see why every "
                "candidate was rejected."
            ),
        },
    }
    blockers = [name for name, g in gates.items() if not g["ok"]]

    return {
        "now_ist": now.isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "blockers": blockers,
        "summary": (
            "All gates green - waiting for prices to touch entries/stops/targets."
            if not blockers
            else f"Blocked by: {', '.join(blockers)}"
        ),
        "gates": gates,
        "last_live_tick_at": _last_live_tick_at.isoformat() if _last_live_tick_at else None,
        "last_run_selection": {
            "signal_date": last_sig_date.isoformat() if last_sig_date else None,
            "selected": selected_today,
            "skipped": skipped_today,
            "top_skip_reasons": top_skip_reasons,
        },
        "prices_fetched": len(prices),
        "price_fetch_error": price_fetch_error,
        "pending_positions": pending_detail,
        "open_positions": open_detail,
        "config": {
            "live_trading_enabled": cfg_snap.live_trading_enabled,
            "live_poll_interval_seconds": cfg_snap.live_poll_interval_seconds,
            "min_score": cfg_snap.min_score,
            "min_risk_reward": cfg_snap.min_risk_reward,
            "max_open_positions": cfg_snap.max_open_positions,
            "max_trades_per_day": cfg_snap.max_trades_per_day,
        },
    }


# ---------- Status ----------

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
        "unrealized_pnl_today": round(unreal, 2),  # unrealized is always live
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
