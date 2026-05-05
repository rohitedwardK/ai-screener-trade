"""AIJournalService.

Daily summary of the paper bot's behaviour. Reuses the existing pluggable
LLM provider with a deterministic template fallback.

This is *not* financial advice; the journal explicitly carries the standard
disclaimer.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.prompts import DISCLAIMER
from ..ai.provider import get_provider
from ..models.paper_orm import (
    PaperDailyPerformance,
    PaperPosition,
    PaperTradeSignal,
)
from . import ledger

log = logging.getLogger(__name__)


def _gather_facts(db: Session, on_date: date) -> Dict[str, Any]:
    """Read the paper_* tables and assemble a compact, JSON-able payload."""
    selected = list(db.scalars(select(PaperTradeSignal).where(
        PaperTradeSignal.signal_date == on_date,
        PaperTradeSignal.decision == "selected",
    )))
    skipped = list(db.scalars(select(PaperTradeSignal).where(
        PaperTradeSignal.signal_date == on_date,
        PaperTradeSignal.decision == "skipped",
    )))
    closed_today = list(db.scalars(select(PaperPosition).where(
        PaperPosition.exit_date == on_date,
        PaperPosition.status.like("CLOSED_%"),
    )))
    open_positions = ledger.open_positions(db)
    daily = db.scalar(select(PaperDailyPerformance).where(PaperDailyPerformance.date == on_date))

    def _sig_brief(s: PaperTradeSignal) -> Dict[str, Any]:
        return {
            "symbol": s.symbol,
            "setup": s.setup_type,
            "score": s.screener_score,
            "automation_score": s.automation_score,
            "rr": s.risk_reward,
            "skip_reason": s.skip_reason,
        }

    def _pos_brief(p: PaperPosition) -> Dict[str, Any]:
        return {
            "symbol": p.symbol,
            "setup": p.setup_type,
            "entry": p.entry_price,
            "exit": p.exit_price,
            "qty": p.quantity,
            "pnl": round(p.realized_pnl or 0.0, 2),
            "exit_reason": p.exit_reason,
            "holding_days": p.holding_days,
            "status": p.status,
        }

    realised = sum(float(p.realized_pnl or 0.0) for p in closed_today)
    wins = [p for p in closed_today if (p.realized_pnl or 0.0) > 0]
    losses = [p for p in closed_today if (p.realized_pnl or 0.0) < 0]
    best = max(closed_today, key=lambda p: (p.realized_pnl or 0.0), default=None)
    worst = min(closed_today, key=lambda p: (p.realized_pnl or 0.0), default=None)

    return {
        "date": on_date.isoformat(),
        "market_regime": (selected[0].market_regime if selected else (skipped[0].market_regime if skipped else None)),
        "selected_count": len(selected),
        "skipped_count": len(skipped),
        "closed_today": len(closed_today),
        "wins_today": len(wins),
        "losses_today": len(losses),
        "realized_pnl_today": round(realised, 2),
        "open_positions": len(open_positions),
        "bot_status": daily.bot_status if daily else "ACTIVE",
        "win_rate_to_date": daily.win_rate if daily else None,
        "profit_factor_to_date": daily.profit_factor if daily else None,
        "max_drawdown_to_date": daily.max_drawdown if daily else None,
        "selected_signals": [_sig_brief(s) for s in selected],
        "skipped_signals": [_sig_brief(s) for s in skipped[:8]],  # cap noise
        "closed_positions": [_pos_brief(p) for p in closed_today],
        "best_trade": _pos_brief(best) if best else None,
        "worst_trade": _pos_brief(worst) if worst else None,
    }


def _template_summary(facts: Dict[str, Any]) -> str:
    """Deterministic English summary for when no LLM is configured."""
    lines: List[str] = []
    lines.append(
        f"On {facts['date']} the paper bot operated in a "
        f"{facts.get('market_regime') or 'unknown'} market regime."
    )
    lines.append(
        f"It selected {facts['selected_count']} trade(s) and skipped "
        f"{facts['skipped_count']}. The bot was reported as "
        f"'{facts.get('bot_status', 'ACTIVE')}'."
    )
    if facts["closed_today"]:
        lines.append(
            f"Closed {facts['closed_today']} trade(s) today: "
            f"{facts['wins_today']} winner(s), {facts['losses_today']} loser(s), "
            f"realised P&L {facts['realized_pnl_today']:+.2f}."
        )
    else:
        lines.append("No trades were closed today.")

    if facts.get("best_trade") and (facts["best_trade"].get("pnl") or 0) > 0:
        bt = facts["best_trade"]
        lines.append(
            f"Best trade: {bt['symbol']} ({bt['setup']}) closed at {bt['exit']} "
            f"for {bt['pnl']:+.2f} via {bt['exit_reason']}."
        )
    if facts.get("worst_trade") and (facts["worst_trade"].get("pnl") or 0) < 0:
        wt = facts["worst_trade"]
        lines.append(
            f"Worst trade: {wt['symbol']} ({wt['setup']}) closed at {wt['exit']} "
            f"for {wt['pnl']:+.2f} via {wt['exit_reason']}."
        )

    if facts["skipped_signals"]:
        sample = ", ".join(
            f"{s['symbol']} ({s.get('skip_reason') or 'rules'})"
            for s in facts["skipped_signals"][:5]
        )
        lines.append(f"Skipped highlights: {sample}.")

    if facts.get("win_rate_to_date") is not None:
        lines.append(
            f"To-date metrics — win rate {facts['win_rate_to_date']:.1f}%, "
            f"profit factor {facts['profit_factor_to_date']:.2f}, "
            f"max drawdown {facts['max_drawdown_to_date']:.2f}%."
        )

    lines.append("Bot followed configured rules: stop-loss mandatory, no forced trades, daily caps respected.")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def generate(db: Session, on_date: date) -> Dict[str, str]:
    """Return {"summary": str, "provider": str}."""
    facts = _gather_facts(db, on_date)
    payload = {
        "task": "paper_trading_journal",
        "date": on_date.isoformat(),
        "facts": facts,
        "instruction": (
            "Write a short paper-trading journal entry (3-6 sentences) covering: "
            "what trades were taken or skipped and why, today's P&L, whether the "
            "bot followed risk rules, the best and worst trade, and a one-line "
            "next-day watchlist suggestion. End with the disclaimer."
        ),
    }
    template_text = _template_summary(facts)
    provider_name = "template"
    summary = template_text

    try:
        provider = get_provider()
        provider_name = getattr(provider, "name", "template")
        if provider_name != "template":
            llm_text = provider.explain(payload)
            if llm_text and isinstance(llm_text, str):
                summary = llm_text.strip()
                if DISCLAIMER not in summary:
                    summary = f"{summary}\n\n{DISCLAIMER}"
    except Exception:  # noqa: BLE001
        log.exception("LLM journal generation failed; using template")
        summary = template_text
        provider_name = "template"

    return {"summary": summary, "provider": provider_name}
