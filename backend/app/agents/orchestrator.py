"""Head orchestrator — runs the deep cycle, persists output.

Pipeline:

    1. DataAgent.run()       -> refreshes CSV + intraday indices
    2. AnalysisAgent.run()   -> rank_methods + consensus_picks + screener
    3. ContextAgent.run()    -> VIX + regime + sector rotation + news
    4. InformantAgent.run()  -> upcoming events (earnings, ex-div, RBI/Fed,
                                F&O expiry) + watch-symbol roll-up
    5. _stitch_payload()     -> deterministic synthesis (filter, rank, attach
                                invalidation, mark events on top picks). This
                                is the canonical structured output the
                                frontend renders.
    6. Head LLM (Ollama)     -> writes a 6-8 line markdown briefing grounded
                                in the structured payload. Falls back to
                                `_fallback_summary_md` if Ollama is unreachable.

Two rows land in the DB on every cycle:

    - one `agent_runs` row capturing per-worker status and duration
    - one `daily_briefings` row holding the structured payload + markdown
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import get_settings
from ..db import session_scope
from ..models.agent_orm import (
    CYCLE_BOOT,
    CYCLE_DEEP,
    AgentRun,
    DailyBriefing,
    RUN_STATUS_ERROR,
    RUN_STATUS_OK,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_RUNNING,
)
from . import analysis_agent as analysis_mod
from . import context_agent as context_mod
from . import data_agent as data_mod
from . import informant_agent as informant_mod
from . import llm as llm_mod
from . import monitoring_agent as monitor_mod
from .tools import DISCLAIMER, latest_snapshot_close_impl

log = logging.getLogger(__name__)


@dataclass
class BriefingResult:
    """Serializable payload returned by `run_deep_cycle`. Mirrors the
    `daily_briefings` row layout."""

    run_at: str
    cycle_type: str
    duration_s: float
    status: str
    head_agent_status: str
    worker_statuses: Dict[str, str] = field(default_factory=dict)
    regime: str = "UNKNOWN"
    market_trend: Optional[str] = None
    vix_value: Optional[float] = None
    vix_band: Optional[str] = None
    market_summary_md: str = ""
    top_picks: List[Dict[str, Any]] = field(default_factory=list)
    consensus_picks: List[Dict[str, Any]] = field(default_factory=list)
    sector_rotation: List[Dict[str, Any]] = field(default_factory=list)
    news_headlines: List[Dict[str, Any]] = field(default_factory=list)
    method_outputs: Dict[str, Any] = field(default_factory=dict)
    counters: Dict[str, Any] = field(default_factory=dict)
    upcoming_events: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    disclaimer: str = DISCLAIMER


# ---------------------------------------------------------------------------
# Deterministic stitch path (used always to produce structured payload, even
# when the LLM head agent is in play — the LLM only adds the markdown summary)
# ---------------------------------------------------------------------------
def _stitch_payload(
    *,
    data_out: Dict[str, Any],
    analysis_out: Dict[str, Any],
    context_out: Dict[str, Any],
    informant_out: Dict[str, Any],
) -> Dict[str, Any]:
    """Filter consensus picks by regime/VIX, compute top picks, attach
    invalidation, and tag picks that have an upcoming event. This is the
    deterministic backbone the head agent's markdown wraps around. Keeping
    it deterministic guarantees the structured columns in `daily_briefings`
    are always trustworthy."""
    consensus: List[Dict[str, Any]] = analysis_out.get("consensus_picks", []) or []
    regime = (context_out.get("regime") or {}).get("regime", "UNKNOWN")
    vix = context_out.get("vix") or {}
    vix_band = vix.get("band", "UNKNOWN")

    upcoming_events: List[Dict[str, Any]] = list(informant_out.get("events") or [])
    # Build a quick symbol -> nearest-event lookup so we can stamp top picks
    # in O(P+E) without nested scans on the frontend. We keep the EARLIEST
    # event for each symbol; ties broken by HIGH > MEDIUM > LOW impact.
    impact_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sym_to_event: Dict[str, Dict[str, Any]] = {}
    for ev in upcoming_events:
        for sym in (ev.get("symbols") or []):
            existing = sym_to_event.get(sym)
            if existing is None:
                sym_to_event[sym] = ev
                continue
            # Keep the closer / higher-impact one.
            if (ev.get("days_until", 999), impact_rank.get(ev.get("impact", "LOW"), 9)) < (
                existing.get("days_until", 999), impact_rank.get(existing.get("impact", "LOW"), 9)
            ):
                sym_to_event[sym] = ev

    # Defensive filter: in PANIC band, downgrade LONG-only picks.
    filtered: List[Dict[str, Any]] = []
    for pick in consensus:
        directions = list((pick.get("directions") or {}).values())
        if vix_band == "PANIC" and all(d.upper() == "LONG" for d in directions if d):
            # Keep them, but flag as "defensive review" — the markdown agent
            # picks this up.
            pick = {**pick, "note": "VIX in PANIC band — review with smaller size"}
        filtered.append(pick)

    # Top picks = first 8 consensus rows. Backfill close where missing and
    # attach the next upcoming event for that symbol if any.
    top_picks: List[Dict[str, Any]] = []
    for pick in filtered[:8]:
        if not pick.get("close"):
            pick = {**pick, "close": latest_snapshot_close_impl(pick["symbol"])}
        if "invalidation" not in pick:
            pick["invalidation"] = None  # explicit so the UI can render n/a
        ev = sym_to_event.get(pick["symbol"])
        if ev is not None:
            pick = {
                **pick,
                "upcoming_event": {
                    "category": ev.get("category"),
                    "title": ev.get("title"),
                    "date": ev.get("date"),
                    "days_until": ev.get("days_until"),
                    "impact": ev.get("impact"),
                },
            }
        top_picks.append(pick)

    # Sector rotation comes verbatim from the context agent; trim to top 6.
    sectors = (context_out.get("sectors") or [])[:6]
    headlines = (context_out.get("headlines") or [])[:8]

    methods = analysis_out.get("methods", {})
    counters = {
        "consensus_total": len(consensus),
        "top_picks": len(top_picks),
        "sectors": len(sectors),
        "news_count": len(headlines),
        "events_count": len(upcoming_events),
        "watch_symbols_count": len(informant_out.get("watch_symbols") or []),
        "data_refresh_errors": len((data_out.get("refresh_stocks") or {}).get("errors", []) or []),
    }
    market_trend = _market_trend_label(regime, vix_band)
    return {
        "regime": regime,
        "vix_value": vix.get("value"),
        "vix_band": vix_band,
        "market_trend": market_trend,
        "top_picks": top_picks,
        "consensus_picks": consensus,
        "sector_rotation": sectors,
        "news_headlines": headlines,
        "method_outputs": methods,
        "counters": counters,
        "upcoming_events": upcoming_events,
    }


def _market_trend_label(regime: str, vix_band: str) -> str:
    """Coarse human-readable label for the dashboard banner."""
    if vix_band == "PANIC":
        return "Defensive (VIX panic)"
    if regime == "RISK_ON" and vix_band in ("NORMAL", "ELEVATED"):
        return "Bullish"
    if regime == "RISK_OFF":
        return "Bearish"
    if regime == "NEUTRAL":
        return "Mixed"
    return "Unclear"


def _fallback_summary_md(payload: Dict[str, Any]) -> str:
    """Markdown summary used when the LLM is unavailable or fails. Mirrors
    the layout the LLM is prompted to produce so the frontend stays stable."""
    regime = payload.get("regime", "UNKNOWN")
    trend = payload.get("market_trend", "Unclear")
    vix_val = payload.get("vix_value")
    vix_band = payload.get("vix_band", "UNKNOWN")
    vix_str = f"{vix_val:.2f} ({vix_band})" if isinstance(vix_val, (int, float)) else f"n/a ({vix_band})"

    lines: List[str] = []
    lines.append(f"## Market briefing — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(f"**Trend:** {trend} · **Regime:** {regime} · **India VIX:** {vix_str}")
    lines.append("")

    sectors = payload.get("sector_rotation") or []
    if sectors:
        lines.append("**Sector rotation (by aggregate score):**")
        for s in sectors[:5]:
            lines.append(f"- {s.get('sector', 'Unknown')}: count {s.get('count', 0)}, total {s.get('total_score', 0):.1f}")
        lines.append("")

    top_picks = payload.get("top_picks") or []
    if top_picks:
        lines.append("**Top consensus picks (across rule-based + RF + GBM + LSTM):**")
        for p in top_picks:
            votes = ", ".join(p.get("votes") or [])
            lines.append(
                f"- **{p.get('symbol')}** — votes: {votes}; "
                f"score {p.get('score', 0):.1f}; "
                f"mean conf {p.get('mean_confidence', 0):.2f}"
            )
        lines.append("")

    upcoming = payload.get("upcoming_events") or []
    if upcoming:
        lines.append("**Upcoming events (next 5 days — expect higher volatility):**")
        for ev in upcoming[:6]:
            syms = ev.get("symbols") or []
            sym_label = ", ".join(syms) if len(syms) <= 3 else f"{', '.join(syms[:3])} +{len(syms) - 3}"
            when = "today" if ev.get("days_until") == 0 else f"in {ev.get('days_until')}d"
            lines.append(f"- [{ev.get('impact', '?')}] {ev.get('title')} — {when} ({sym_label})")
        lines.append("")

    headlines = payload.get("news_headlines") or []
    if headlines:
        lines.append("**Recent headlines:**")
        for h in headlines[:5]:
            lines.append(f"- [{h.get('source')}] {h.get('title')}")
        lines.append("")

    lines.append(f"_{DISCLAIMER}_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM path — Ollama via httpx (only the markdown summary uses the LLM)
# ---------------------------------------------------------------------------
_HEAD_SYSTEM_PROMPT = (
    "You are the Chief Market Strategist for an Indian equity research desk. "
    "You ONLY use the structured JSON payload supplied in the user message. "
    "You NEVER invent symbols, numbers, or headlines. "
    "You write a concise, professional markdown briefing (6-10 lines). "
    "You always end the briefing with the exact disclaimer: " + DISCLAIMER
)


def _llm_prompt_for_payload(payload: Dict[str, Any]) -> str:
    """Build the user prompt fed to Ollama. The system prompt is the constant
    above; the user message is the structured payload + section instructions."""
    return (
        "Write the day's market briefing as markdown. Sections (in order):\n"
        "1. **Header line** with Regime, Market Trend, India VIX (value + band).\n"
        "2. **Top consensus picks** — bullet list, one per pick: symbol, "
        "vote count (e.g. 3/4 methods), score, mean confidence. If a pick "
        "has an `upcoming_event`, append a short note with the event title "
        "and days_until (e.g. \"earnings in 2d\").\n"
        "3. **Upcoming events (next 5 days)** — if present, list each event "
        "as: [impact] title — date — affected symbols. Note that these "
        "stocks are expected to have higher volatility around the date.\n"
        "4. **Sector rotation** — top 3-5 sectors by aggregate score.\n"
        "5. **Recent headlines** — 3-5 lines from the news list.\n"
        "6. End with the disclaimer verbatim.\n\n"
        "Use ONLY the values in the payload below. Do not invent anything.\n\n"
        f"PAYLOAD:\n{payload}\n"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run_deep_cycle(
    *,
    cycle_type: str = CYCLE_DEEP,
    triggered_by: str = "scheduler",
    use_llm: bool = True,
) -> BriefingResult:
    """Execute one deep cycle: data → analysis → context → synthesis.

    Always produces a `BriefingResult` (never raises). Persists one row
    each in `agent_runs` and `daily_briefings`."""
    settings = get_settings()
    started_mono = time.monotonic()
    started_at = datetime.utcnow()

    # Insert RUNNING row up-front so the UI can show "Crew running…".
    with session_scope() as db:
        run_row = AgentRun(
            run_at=started_at,
            cycle_type=cycle_type,
            status=RUN_STATUS_RUNNING,
            triggered_by=triggered_by,
        )
        db.add(run_row)
        db.flush()
        run_id = int(run_row.id)

    worker_statuses: Dict[str, str] = {}
    error_text: Optional[str] = None

    # --- worker 1: data ----------------------------------------------------
    try:
        data_out = data_mod.run_deterministic(force_full=False)
        worker_statuses["data_agent"] = RUN_STATUS_OK
    except Exception as exc:  # noqa: BLE001
        log.exception("DataAgent failed")
        data_out = {"error": str(exc)}
        worker_statuses["data_agent"] = RUN_STATUS_ERROR

    # --- worker 2: analysis -----------------------------------------------
    try:
        analysis_out = analysis_mod.run_deterministic(top_k=10, min_votes=2)
        worker_statuses["analysis_agent"] = RUN_STATUS_OK
    except Exception as exc:  # noqa: BLE001
        log.exception("AnalysisAgent failed")
        analysis_out = {"consensus_picks": [], "methods": {}, "error": str(exc)}
        worker_statuses["analysis_agent"] = RUN_STATUS_ERROR

    # --- worker 3: context ------------------------------------------------
    try:
        context_out = context_mod.run_deterministic()
        worker_statuses["context_agent"] = RUN_STATUS_OK
    except Exception as exc:  # noqa: BLE001
        log.exception("ContextAgent failed")
        context_out = {"vix": {}, "regime": {}, "sectors": [], "headlines": [], "error": str(exc)}
        worker_statuses["context_agent"] = RUN_STATUS_ERROR

    # --- worker 4: informant (upcoming events for next 5 days) ------------
    # Failures here must not block the briefing — events are an enhancement,
    # not a prerequisite. We swallow into an empty list so _stitch_payload
    # works the same way it would on a totally empty calendar day.
    try:
        informant_out = informant_mod.run_deterministic()
        if "error" in informant_out:
            worker_statuses["informant_agent"] = RUN_STATUS_PARTIAL
        else:
            worker_statuses["informant_agent"] = RUN_STATUS_OK
    except Exception as exc:  # noqa: BLE001
        log.exception("InformantAgent failed")
        informant_out = {"events": [], "watch_symbols": [], "error": str(exc)}
        worker_statuses["informant_agent"] = RUN_STATUS_ERROR

    # --- head synthesis ---------------------------------------------------
    payload = _stitch_payload(
        data_out=data_out,
        analysis_out=analysis_out,
        context_out=context_out,
        informant_out=informant_out,
    )

    head_status = RUN_STATUS_OK
    summary_md = ""
    if use_llm and settings.AGENTIC_ENABLED and llm_mod.is_available():
        try:
            summary_md = llm_mod.chat(
                _llm_prompt_for_payload(payload),
                system=_HEAD_SYSTEM_PROMPT,
                temperature=0.2,
            )
            if DISCLAIMER not in summary_md:
                summary_md = f"{summary_md.rstrip()}\n\n_{DISCLAIMER}_"
        except Exception as exc:  # noqa: BLE001
            log.warning("Head LLM call failed; falling back to deterministic markdown: %s", exc)
            summary_md = _fallback_summary_md(payload)
            head_status = RUN_STATUS_PARTIAL
    else:
        summary_md = _fallback_summary_md(payload)
        if use_llm and settings.AGENTIC_ENABLED:
            # LLM was requested but Ollama is unreachable.
            head_status = RUN_STATUS_PARTIAL

    worker_statuses["head_agent"] = head_status

    # Roll up status: any ERROR -> PARTIAL (we still have a briefing).
    overall_error = any(v == RUN_STATUS_ERROR for v in worker_statuses.values())
    overall_status = RUN_STATUS_PARTIAL if overall_error else RUN_STATUS_OK
    if all(v == RUN_STATUS_ERROR for v in worker_statuses.values()):
        overall_status = RUN_STATUS_ERROR
        error_text = "all workers failed"

    duration = time.monotonic() - started_mono

    # Persist agent_run + daily_briefing.
    with session_scope() as db:
        run_row = db.get(AgentRun, run_id)
        if run_row is not None:
            run_row.status = overall_status
            run_row.head_agent_status = head_status
            run_row.worker_statuses_json = worker_statuses
            run_row.duration_s = duration
            run_row.error = error_text

        briefing_row = DailyBriefing(
            run_at=started_at,
            agent_run_id=run_id,
            regime=payload["regime"],
            market_trend=payload["market_trend"],
            vix_value=payload["vix_value"],
            vix_band=payload["vix_band"],
            market_summary_md=summary_md,
            top_picks_json=payload["top_picks"],
            consensus_picks_json=payload["consensus_picks"],
            sector_rotation_json=payload["sector_rotation"],
            news_headlines_json=payload["news_headlines"],
            method_outputs_json=payload["method_outputs"],
            counters_json=payload["counters"],
            upcoming_events_json=payload.get("upcoming_events", []),
        )
        db.add(briefing_row)

    monitor_mod.mark_deep_cycle_complete()

    log.info(
        "Deep cycle complete: status=%s duration=%.1fs picks=%d sectors=%d headlines=%d",
        overall_status, duration, len(payload["top_picks"]),
        len(payload["sector_rotation"]), len(payload["news_headlines"]),
    )

    return BriefingResult(
        run_at=started_at.isoformat(),
        cycle_type=cycle_type,
        duration_s=duration,
        status=overall_status,
        head_agent_status=head_status,
        worker_statuses=worker_statuses,
        regime=payload["regime"],
        market_trend=payload["market_trend"],
        vix_value=payload["vix_value"],
        vix_band=payload["vix_band"],
        market_summary_md=summary_md,
        top_picks=payload["top_picks"],
        consensus_picks=payload["consensus_picks"],
        sector_rotation=payload["sector_rotation"],
        news_headlines=payload["news_headlines"],
        method_outputs=payload["method_outputs"],
        counters=payload["counters"],
        upcoming_events=payload.get("upcoming_events", []),
        error=error_text,
    )


def run_boot_cycle() -> BriefingResult:
    """Convenience wrapper — same as `run_deep_cycle` but tagged BOOT."""
    return run_deep_cycle(cycle_type=CYCLE_BOOT, triggered_by="lifespan_startup")


__all__ = ["BriefingResult", "run_deep_cycle", "run_boot_cycle"]
