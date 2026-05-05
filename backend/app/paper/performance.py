"""PerformanceService.

Computes win rate, profit factor, expectancy, max drawdown, holding days,
best/worst setup, and per-setup breakdowns from the paper_* tables. Also
upserts a daily summary row into paper_daily_performance.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.paper_orm import PaperLedger, PaperPosition
from . import ledger
from .config import PaperConfigSnapshot


# ---------- aggregate metrics ----------

@dataclass
class AggregateMetrics:
    total_trades: int
    closed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float
    expectancy: float
    max_drawdown_percent: float
    average_holding_days: float
    best_setup: Optional[str]
    worst_setup: Optional[str]
    by_setup: Dict[str, Dict[str, Any]]


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    if den == 0:
        return default
    return num / den


def aggregate(
    closed_positions: List[PaperPosition],
    *,
    equity_curve: Optional[List[float]] = None,
) -> AggregateMetrics:
    n = len(closed_positions)
    wins = [p for p in closed_positions if (p.realized_pnl or 0.0) > 0]
    losses = [p for p in closed_positions if (p.realized_pnl or 0.0) < 0]
    win_pnl = sum((p.realized_pnl or 0.0) for p in wins)
    loss_pnl = sum((p.realized_pnl or 0.0) for p in losses)  # negative
    avg_win = _safe_div(win_pnl, len(wins))
    avg_loss = _safe_div(loss_pnl, len(losses))  # negative
    win_rate = _safe_div(len(wins), n)
    gross_profit = win_pnl
    gross_loss = abs(loss_pnl)
    profit_factor = _safe_div(gross_profit, gross_loss, default=0.0)
    expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * abs(avg_loss))

    holding = [p.holding_days for p in closed_positions if p.holding_days is not None]
    avg_holding = _safe_div(float(sum(holding)), float(len(holding))) if holding else 0.0

    # Per-setup breakdown
    grouped: Dict[str, List[PaperPosition]] = defaultdict(list)
    for p in closed_positions:
        grouped[p.setup_type or "Unknown"].append(p)
    by_setup: Dict[str, Dict[str, Any]] = {}
    for setup, items in grouped.items():
        s_wins = [x for x in items if (x.realized_pnl or 0.0) > 0]
        s_losses = [x for x in items if (x.realized_pnl or 0.0) < 0]
        s_total = sum((x.realized_pnl or 0.0) for x in items)
        s_win_rate = _safe_div(len(s_wins), len(items))
        by_setup[setup] = {
            "trades": len(items),
            "wins": len(s_wins),
            "losses": len(s_losses),
            "win_rate": round(s_win_rate * 100.0, 2),
            "total_pnl": round(s_total, 2),
            "average_pnl": round(_safe_div(s_total, len(items)), 2),
        }

    best_setup = None
    worst_setup = None
    if by_setup:
        ordered = sorted(by_setup.items(), key=lambda kv: kv[1]["total_pnl"], reverse=True)
        best_setup = ordered[0][0]
        worst_setup = ordered[-1][0]

    max_dd_pct = 0.0
    if equity_curve and len(equity_curve) >= 2:
        peak = equity_curve[0]
        max_dd = 0.0
        for v in equity_curve:
            if v > peak:
                peak = v
            if peak > 0:
                dd = (peak - v) / peak
                if dd > max_dd:
                    max_dd = dd
        max_dd_pct = round(max_dd * 100.0, 2)

    return AggregateMetrics(
        total_trades=n,
        closed_trades=n,
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate=round(win_rate * 100.0, 2),
        average_win=round(avg_win, 2),
        average_loss=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        expectancy=round(expectancy, 2),
        max_drawdown_percent=max_dd_pct,
        average_holding_days=round(avg_holding, 2),
        best_setup=best_setup,
        worst_setup=worst_setup,
        by_setup=by_setup,
    )


# ---------- equity curve ----------

def equity_curve(
    db: Session,
    cfg: PaperConfigSnapshot,
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Daily ending equity = starting capital + cumulative realized P&L per date."""
    stmt = select(PaperLedger.date, PaperLedger.pnl).order_by(PaperLedger.date.asc(), PaperLedger.id.asc())
    if from_date:
        stmt = stmt.where(PaperLedger.date >= from_date)
    if to_date:
        stmt = stmt.where(PaperLedger.date <= to_date)
    rows = db.execute(stmt).all()

    if not rows:
        return []

    by_day: Dict[date, float] = defaultdict(float)
    for d, pnl in rows:
        by_day[d] += float(pnl or 0.0)

    curve: List[Dict[str, Any]] = []
    cumulative = float(cfg.virtual_capital)
    for d in sorted(by_day):
        cumulative += by_day[d]
        curve.append({"date": d.isoformat(), "equity": round(cumulative, 2), "daily_pnl": round(by_day[d], 2)})
    return curve


# ---------- daily upsert ----------

def upsert_for_day(
    db: Session,
    cfg: PaperConfigSnapshot,
    *,
    on_date: date,
    bot_status: str,
) -> None:
    """Recompute and persist the paper_daily_performance row for `on_date`."""
    realized_today = ledger.realized_pnl_between(db, from_date=on_date, to_date=on_date)

    closed_today = list(db.scalars(
        select(PaperPosition).where(
            PaperPosition.exit_date == on_date,
            PaperPosition.status.like("CLOSED_%"),
        )
    ))
    closed_to_date = list(db.scalars(
        select(PaperPosition).where(
            PaperPosition.exit_date <= on_date,
            PaperPosition.status.like("CLOSED_%"),
        )
    ))
    open_count = len(ledger.open_positions(db))

    metrics = aggregate(closed_to_date)
    starting_cap = float(cfg.virtual_capital)
    cumulative_realized = ledger.realized_pnl_between(db, to_date=on_date)
    ending_cap = starting_cap + cumulative_realized + ledger.total_unrealized_pnl(db)
    daily_return_pct = (realized_today / starting_cap) * 100.0 if starting_cap > 0 else 0.0

    # Drawdown over the whole equity curve up to today.
    curve_vals = [row["equity"] for row in equity_curve(db, cfg, to_date=on_date)]
    dd_metrics = aggregate(closed_to_date, equity_curve=curve_vals)

    ledger.upsert_daily_performance(
        db,
        on_date=on_date,
        starting_capital=starting_cap,
        ending_capital=round(ending_cap, 2),
        total_trades=len(closed_today) + open_count,
        open_trades=open_count,
        closed_trades=len(closed_today),
        winning_trades=sum(1 for p in closed_today if (p.realized_pnl or 0.0) > 0),
        losing_trades=sum(1 for p in closed_today if (p.realized_pnl or 0.0) < 0),
        realized_pnl=round(realized_today, 2),
        unrealized_pnl=round(ledger.total_unrealized_pnl(db), 2),
        daily_return_percent=round(daily_return_pct, 4),
        win_rate=metrics.win_rate,
        average_win=metrics.average_win,
        average_loss=metrics.average_loss,
        profit_factor=metrics.profit_factor,
        max_drawdown=dd_metrics.max_drawdown_percent,
        bot_status=bot_status,
    )
    db.commit()
