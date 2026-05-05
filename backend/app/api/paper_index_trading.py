"""FastAPI endpoints for the paper-INDEX-trading layer."""
from __future__ import annotations

from datetime import date as date_type
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.index_schemas import (
    PaperIndexBotConfigOut,
    PaperIndexBotConfigUpdate,
    PaperIndexDailyPerformanceOut,
    PaperIndexJournalOut,
    PaperIndexLedgerOut,
    PaperIndexLiveTickOut,
    PaperIndexOrderOut,
    PaperIndexPerformanceOut,
    PaperIndexPositionOut,
    PaperIndexReplayOut,
    PaperIndexReplaySummary,
    PaperIndexResetOut,
    PaperIndexSelectionOut,
    PaperIndexSimulateDayOut,
    PaperIndexStatusOut,
    PaperIndexTradeSignalOut,
)
from ..paper_index import (
    config as cfg_mod,
    journal as journal_mod,
    ledger as ledger_mod,
    performance as perf_mod,
    service,
)

router = APIRouter(prefix="/v1/paper-index-trading", tags=["paper-index-trading"])


# ---------- Config ----------

@router.get("/config", response_model=PaperIndexBotConfigOut)
def get_config(db: Session = Depends(get_db)) -> PaperIndexBotConfigOut:
    cfg = cfg_mod.get_or_create(db)
    return PaperIndexBotConfigOut.model_validate(cfg)


@router.post("/config", response_model=PaperIndexBotConfigOut)
def update_config(
    patch: PaperIndexBotConfigUpdate,
    db: Session = Depends(get_db),
) -> PaperIndexBotConfigOut:
    try:
        updated = cfg_mod.update(db, **patch.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PaperIndexBotConfigOut.model_validate(updated)


# ---------- Status ----------

@router.get("/status", response_model=PaperIndexStatusOut)
def get_status(db: Session = Depends(get_db)) -> PaperIndexStatusOut:
    payload = service.status(db)
    return PaperIndexStatusOut(
        bot_status=payload["bot_status"],
        virtual_capital=payload["virtual_capital"],
        current_equity=payload["current_equity"],
        realized_pnl_today=payload["realized_pnl_today"],
        unrealized_pnl_today=payload["unrealized_pnl_today"],
        realized_pnl_total=payload["realized_pnl_total"],
        unrealized_pnl_total=payload["unrealized_pnl_total"],
        trades_taken_today=payload["trades_taken_today"],
        remaining_trades_today=payload["remaining_trades_today"],
        open_positions=payload["open_positions"],
        daily_loss_limit_percent=payload["daily_loss_limit_percent"],
        live_trading_enabled=payload.get("live_trading_enabled", False),
        is_market_open=payload.get("is_market_open", False),
        last_live_tick_at=payload.get("last_live_tick_at"),
        market_regime=payload["market_regime"],
        reason=payload.get("reason"),
    )


# ---------- Run selection ----------

@router.post("/run-selection", response_model=PaperIndexSelectionOut)
def post_run_selection(
    on_date: Optional[date_type] = Query(None, alias="date"),
    db: Session = Depends(get_db),
) -> PaperIndexSelectionOut:
    result = service.run_selection(db, on_date=on_date)
    return PaperIndexSelectionOut(
        date=result.on_date,
        market_regime=result.market_regime,
        candidates_evaluated=result.candidates_evaluated,
        selected=[PaperIndexTradeSignalOut.model_validate(r) for r in result.selected],
        skipped=[PaperIndexTradeSignalOut.model_validate(r) for r in result.skipped],
    )


# ---------- Simulate day ----------

@router.post("/simulate-day", response_model=PaperIndexSimulateDayOut)
def post_simulate_day(
    on_date: Optional[date_type] = Query(None, alias="date"),
    db: Session = Depends(get_db),
) -> PaperIndexSimulateDayOut:
    result = service.simulate_day(db, on_date=on_date)
    events = ledger_mod.list_ledger(db, from_date=result.on_date, to_date=result.on_date, limit=500)
    return PaperIndexSimulateDayOut(
        date=result.on_date,
        entries_filled=result.entries_filled,
        exits_triggered=result.exits_triggered,
        realized_pnl=result.realized_pnl,
        unrealized_pnl=result.unrealized_pnl,
        bot_status=result.bot_status,
        events=[PaperIndexLedgerOut.model_validate(e) for e in events],
    )


# ---------- Live tick (intraday trade-management agent) ----------

@router.post("/process-live-tick", response_model=PaperIndexLiveTickOut)
def post_process_live_tick(db: Session = Depends(get_db)) -> PaperIndexLiveTickOut:
    """Apply one yfinance live spot tick to all OPEN paper-index positions.

    Simulation only. Does not open new positions (PENDING entries continue
    to be filled by the daily simulate_day pass). Operator can call this
    manually from the UI; the scheduler also runs it every minute Mon-Fri
    09-15 IST when `live_trading_enabled` is on.
    """
    result = service.process_live_tick(db)
    return PaperIndexLiveTickOut(
        processed_at=result.processed_at,
        symbols_priced=result.symbols_priced,
        exits_triggered=result.exits_triggered,
        realized_pnl_today=result.realized_pnl_today,
        unrealized_pnl=result.unrealized_pnl,
        bot_status=result.bot_status,
        prices=result.prices,
    )


# ---------- Replay ----------

@router.post("/replay", response_model=PaperIndexReplayOut)
def post_replay(
    start: date_type = Query(...),
    end: date_type = Query(...),
    db: Session = Depends(get_db),
) -> PaperIndexReplayOut:
    if end < start:
        raise HTTPException(status_code=400, detail="end must be >= start")
    out = service.replay(db, start=start, end=end)
    summary = [
        PaperIndexReplaySummary(
            date=row.on_date,
            bot_status=row.bot_status,
            selected=row.selected,
            skipped=row.skipped,
            entries_filled=row.entries_filled,
            exits_triggered=row.exits_triggered,
            realized_pnl=row.realized_pnl,
            ending_equity=row.ending_equity,
        ) for row in out["summary"]
    ]
    return PaperIndexReplayOut(
        start=out["start"],
        end=out["end"],
        days_processed=out["days_processed"],
        final_equity=out["final_equity"],
        total_realized_pnl=out["total_realized_pnl"],
        summary=summary,
    )


# ---------- Listings ----------

@router.get("/signals", response_model=List[PaperIndexTradeSignalOut])
def get_signals(
    on_date: Optional[date_type] = Query(None, alias="date"),
    decision: Optional[str] = Query(None, pattern="^(selected|skipped)$"),
    symbol: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> List[PaperIndexTradeSignalOut]:
    rows = ledger_mod.list_signals(db, signal_date=on_date, decision=decision, symbol=symbol, limit=limit)
    return [PaperIndexTradeSignalOut.model_validate(r) for r in rows]


@router.get("/orders", response_model=List[PaperIndexOrderOut])
def get_orders(
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> List[PaperIndexOrderOut]:
    rows = ledger_mod.list_orders(db, status=status, symbol=symbol, limit=limit)
    return [PaperIndexOrderOut.model_validate(r) for r in rows]


@router.get("/positions", response_model=List[PaperIndexPositionOut])
def get_positions(
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> List[PaperIndexPositionOut]:
    rows = ledger_mod.list_positions(db, status=status, symbol=symbol, limit=limit)
    return [PaperIndexPositionOut.model_validate(r) for r in rows]


@router.get("/ledger", response_model=List[PaperIndexLedgerOut])
def get_ledger(
    from_date: Optional[date_type] = Query(None, alias="from"),
    to_date: Optional[date_type] = Query(None, alias="to"),
    symbol: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> List[PaperIndexLedgerOut]:
    rows = ledger_mod.list_ledger(db, from_date=from_date, to_date=to_date, symbol=symbol, limit=limit)
    return [PaperIndexLedgerOut.model_validate(r) for r in rows]


# ---------- Performance ----------

@router.get("/performance", response_model=PaperIndexPerformanceOut)
def get_performance(
    from_date: Optional[date_type] = Query(None, alias="from"),
    to_date: Optional[date_type] = Query(None, alias="to"),
    db: Session = Depends(get_db),
) -> PaperIndexPerformanceOut:
    cfg_snap = cfg_mod.snapshot(db)
    daily_rows = ledger_mod.daily_performance_between(
        db,
        from_date=from_date or date_type.min,
        to_date=to_date or date_type.max,
    )
    closed = ledger_mod.closed_positions(db, limit=10_000)
    if from_date:
        closed = [p for p in closed if p.exit_date and p.exit_date >= from_date]
    if to_date:
        closed = [p for p in closed if p.exit_date and p.exit_date <= to_date]
    curve = perf_mod.equity_curve(db, cfg_snap, from_date=from_date, to_date=to_date)
    metrics = perf_mod.aggregate(closed, equity_curve=[c["equity"] for c in curve])

    return PaperIndexPerformanceOut(
        from_date=from_date or (closed[0].exit_date if closed and closed[-1].exit_date else date_type.today()),
        to_date=to_date or (closed[0].exit_date if closed else date_type.today()),
        total_trades=metrics.total_trades,
        closed_trades=metrics.closed_trades,
        winning_trades=metrics.winning_trades,
        losing_trades=metrics.losing_trades,
        win_rate=metrics.win_rate,
        average_win=metrics.average_win,
        average_loss=metrics.average_loss,
        profit_factor=metrics.profit_factor,
        expectancy=metrics.expectancy,
        max_drawdown_percent=metrics.max_drawdown_percent,
        average_holding_days=metrics.average_holding_days,
        best_setup=metrics.best_setup,
        worst_setup=metrics.worst_setup,
        by_setup=metrics.by_setup,
        daily=[PaperIndexDailyPerformanceOut.model_validate(r) for r in daily_rows],
        equity_curve=curve,
    )


# ---------- Journal ----------

@router.get("/journal", response_model=PaperIndexJournalOut)
def get_journal(
    on_date: Optional[date_type] = Query(None, alias="date"),
    db: Session = Depends(get_db),
) -> PaperIndexJournalOut:
    target = on_date or date_type.today()
    out = journal_mod.generate(db, target)
    return PaperIndexJournalOut(date=target, summary=out["summary"], provider=out["provider"])


# ---------- Reset ----------

@router.post("/reset", response_model=PaperIndexResetOut)
def post_reset(
    confirm: str = Query(..., description="Must be 'YES' to confirm reset."),
    db: Session = Depends(get_db),
) -> PaperIndexResetOut:
    if confirm != "YES":
        raise HTTPException(status_code=400, detail="confirm must be 'YES'")
    counts = service.reset(db)
    return PaperIndexResetOut(
        deleted_signals=counts.get("deleted_signals", 0),
        deleted_orders=counts.get("deleted_orders", 0),
        deleted_positions=counts.get("deleted_positions", 0),
        deleted_ledger=counts.get("deleted_ledger", 0),
        deleted_daily=counts.get("deleted_daily", 0),
    )
