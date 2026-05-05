"""AI journal for the paper-index bot. Reuses the pluggable LLM layer."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.prompts import DISCLAIMER
from ..ai.provider import get_provider
from ..models.paper_index_orm import (
    PaperIndexDailyPerformance,
    PaperIndexPosition,
    PaperIndexTradeSignal,
)
from . import ledger

log = logging.getLogger(__name__)


def _gather_facts(db: Session, on_date: date) -> Dict[str, Any]:
    selected = list(db.scalars(select(PaperIndexTradeSignal).where(
        PaperIndexTradeSignal.signal_date == on_date,
        PaperIndexTradeSignal.decision == "selected",
    )))
    skipped = list(db.scalars(select(PaperIndexTradeSignal).where(
        PaperIndexTradeSignal.signal_date == on_date,
        PaperIndexTradeSignal.decision == "skipped",
    )))
    closed_today = list(db.scalars(select(PaperIndexPosition).where(
        PaperIndexPosition.exit_date == on_date,
        PaperIndexPosition.status.like("CLOSED_%"),
    )))
    open_positions = ledger.open_positions(db)
    daily = db.scalar(select(PaperIndexDailyPerformance).where(PaperIndexDailyPerformance.date == on_date))

    def _sig_brief(s: PaperIndexTradeSignal) -> Dict[str, Any]:
        return {
            "code": s.code,
            "setup": s.setup_type,
            "direction": s.direction,
            "option_type": s.option_type,
            "score": s.screener_score,
            "automation_score": s.automation_score,
            "rr": s.risk_reward,
            "skip_reason": s.skip_reason,
            "option_chain_bias": s.option_chain_bias,
        }

    def _pos_brief(p: PaperIndexPosition) -> Dict[str, Any]:
        return {
            "code": p.code,
            "setup": p.setup_type,
            "direction": p.direction,
            "option_type": p.option_type,
            "strike": p.strike,
            "lots": p.lots,
            "entry": p.entry_premium,
            "exit": p.exit_price,
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
        "skipped_signals": [_sig_brief(s) for s in skipped[:8]],
        "closed_positions": [_pos_brief(p) for p in closed_today],
        "best_trade": _pos_brief(best) if best else None,
        "worst_trade": _pos_brief(worst) if worst else None,
    }


def _template_summary(facts: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(
        f"On {facts['date']} the index paper bot operated in a "
        f"{facts.get('market_regime') or 'unknown'} market regime."
    )
    lines.append(
        f"It selected {facts['selected_count']} index option trade(s) and skipped "
        f"{facts['skipped_count']}. Bot status: '{facts.get('bot_status', 'ACTIVE')}'."
    )
    if facts["closed_today"]:
        lines.append(
            f"Closed {facts['closed_today']} trade(s) today: "
            f"{facts['wins_today']} winner(s), {facts['losses_today']} loser(s), "
            f"realised P&L {facts['realized_pnl_today']:+.2f}."
        )
    else:
        lines.append("No index option trades were closed today.")

    if facts.get("best_trade") and (facts["best_trade"].get("pnl") or 0) > 0:
        bt = facts["best_trade"]
        lines.append(
            f"Best trade: {bt['code']} {bt['option_type']} {bt['strike']:.0f} "
            f"({bt['setup']}, {bt['lots']} lots) for {bt['pnl']:+.2f} via {bt['exit_reason']}."
        )
    if facts.get("worst_trade") and (facts["worst_trade"].get("pnl") or 0) < 0:
        wt = facts["worst_trade"]
        lines.append(
            f"Worst trade: {wt['code']} {wt['option_type']} {wt['strike']:.0f} "
            f"({wt['setup']}, {wt['lots']} lots) for {wt['pnl']:+.2f} via {wt['exit_reason']}."
        )

    if facts["skipped_signals"]:
        sample = ", ".join(
            f"{s['code']} {s['direction']} ({s.get('skip_reason') or 'rules'})"
            for s in facts["skipped_signals"][:5]
        )
        lines.append(f"Skipped highlights: {sample}.")

    if facts.get("win_rate_to_date") is not None:
        lines.append(
            f"To-date metrics — win rate {facts['win_rate_to_date']:.1f}%, "
            f"profit factor {facts['profit_factor_to_date']:.2f}, "
            f"max drawdown {facts['max_drawdown_to_date']:.2f}%."
        )

    lines.append(
        "Bot followed configured rules: stop-loss mandatory, no real broker, "
        "lot-aware option sizing with delta-based premium simulation."
    )
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def generate(db: Session, on_date: date) -> Dict[str, str]:
    facts = _gather_facts(db, on_date)
    payload = {
        "task": "paper_index_trading_journal",
        "date": on_date.isoformat(),
        "facts": facts,
        "instruction": (
            "Write a short index-options paper-trading journal entry "
            "(3-6 sentences) covering: which indices the bot traded today, "
            "whether option-chain bias supported the calls/puts, today's "
            "P&L, the best and worst trade, and a one-line next-day "
            "watchlist suggestion. End with the disclaimer."
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
        log.exception("LLM index journal generation failed; using template")
        summary = template_text
        provider_name = "template"
    return {"summary": summary, "provider": provider_name}
