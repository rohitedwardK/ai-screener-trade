"""Bot status evaluator (kill switch).

Returns one of:
    ACTIVE
    PAUSED
    DAILY_LIMIT_REACHED
    DAILY_LOSS_LIMIT_HIT
    MAX_OPEN_POSITIONS_REACHED
    NO_QUALITY_SETUP
    ERROR

Checked before every new entry attempt and before/after each simulated day.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from . import ledger
from .config import PaperConfigSnapshot

CONSECUTIVE_LOSS_LIMIT = 3


@dataclass
class BotState:
    status: str
    reason: str
    trades_today: int
    open_positions: int
    realized_pnl_today: float
    consecutive_losses: int
    daily_loss_pct: float
    market_regime: str

    def can_take_new_trade(self) -> bool:
        return self.status == "ACTIVE"


def evaluate(
    db: Session,
    cfg: PaperConfigSnapshot,
    *,
    on_date: date,
    market_regime: str,
    quality_setups_available: Optional[int] = None,
) -> BotState:
    trades_today = ledger.signals_taken_on(db, on_date)
    open_count = len(ledger.open_positions(db))
    realized_today = ledger.realized_pnl_between(db, from_date=on_date, to_date=on_date)
    capital = max(1.0, cfg.virtual_capital)
    daily_loss_pct = (-realized_today / capital) * 100.0  # positive => losing
    consec = ledger.consecutive_recent_losses(db, on_date)

    # Order matters: most-restrictive first.
    if daily_loss_pct >= cfg.max_daily_loss_percent:
        return BotState(
            status="DAILY_LOSS_LIMIT_HIT",
            reason=f"daily loss {daily_loss_pct:.2f}% >= cap {cfg.max_daily_loss_percent:.2f}%",
            trades_today=trades_today, open_positions=open_count,
            realized_pnl_today=realized_today,
            consecutive_losses=consec, daily_loss_pct=daily_loss_pct,
            market_regime=market_regime,
        )

    if consec >= CONSECUTIVE_LOSS_LIMIT:
        return BotState(
            status="PAUSED",
            reason=f"{consec} consecutive losses",
            trades_today=trades_today, open_positions=open_count,
            realized_pnl_today=realized_today,
            consecutive_losses=consec, daily_loss_pct=daily_loss_pct,
            market_regime=market_regime,
        )

    if open_count >= cfg.max_open_positions:
        return BotState(
            status="MAX_OPEN_POSITIONS_REACHED",
            reason=f"{open_count} open positions >= cap {cfg.max_open_positions}",
            trades_today=trades_today, open_positions=open_count,
            realized_pnl_today=realized_today,
            consecutive_losses=consec, daily_loss_pct=daily_loss_pct,
            market_regime=market_regime,
        )

    if trades_today >= cfg.max_trades_per_day:
        return BotState(
            status="DAILY_LIMIT_REACHED",
            reason=f"{trades_today} trades taken >= cap {cfg.max_trades_per_day}",
            trades_today=trades_today, open_positions=open_count,
            realized_pnl_today=realized_today,
            consecutive_losses=consec, daily_loss_pct=daily_loss_pct,
            market_regime=market_regime,
        )

    if market_regime == "Bearish":
        return BotState(
            status="PAUSED",
            reason="market regime Bearish: pause new long entries",
            trades_today=trades_today, open_positions=open_count,
            realized_pnl_today=realized_today,
            consecutive_losses=consec, daily_loss_pct=daily_loss_pct,
            market_regime=market_regime,
        )

    if quality_setups_available is not None and quality_setups_available <= 0:
        return BotState(
            status="NO_QUALITY_SETUP",
            reason="no candidate cleared the rules today",
            trades_today=trades_today, open_positions=open_count,
            realized_pnl_today=realized_today,
            consecutive_losses=consec, daily_loss_pct=daily_loss_pct,
            market_regime=market_regime,
        )

    return BotState(
        status="ACTIVE",
        reason="all guards pass",
        trades_today=trades_today, open_positions=open_count,
        realized_pnl_today=realized_today,
        consecutive_losses=consec, daily_loss_pct=daily_loss_pct,
        market_regime=market_regime,
    )
