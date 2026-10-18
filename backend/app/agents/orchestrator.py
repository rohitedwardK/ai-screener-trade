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
    6. Deterministic markdown is persisted immediately. Optional Ollama
       context and briefing work is queued by evidence snapshot.

Two rows land in the DB on every cycle:

    - one `agent_runs` row capturing per-worker status and duration
    - one `daily_briefings` row holding the structured payload + markdown
"""
from __future__ import annotations

import logging
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..config import get_settings
from ..db import session_scope
from ..data import ai_task_repository as ai_queue
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
from . import monitoring_agent as monitor_mod
from .llm_context_builder import build_head_agent_context, serialize_context
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
# Deterministic stitch path used for every worker cycle.
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
    trend_info = context_out.get("trend") or {}
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
        "market_trend_basis": trend_info.get("basis", []),
        "market_trend_daily_state": trend_info.get("daily_state"),
        "market_trend_weekly_state": trend_info.get("weekly_state"),
    }
    market_trend = trend_info.get("label") or _market_trend_label(regime, vix_band)
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


_REGIME_LABELS = {
    "RISK_ON": "Risk-on",
    "NEUTRAL": "Neutral",
    "RISK_OFF": "Risk-off",
    "UNKNOWN": "Unknown",
}
_VIX_BAND_LABELS = {
    "NORMAL": "normal",
    "ELEVATED": "elevated",
    "PANIC": "panic",
    "UNKNOWN": "unknown",
}
# Small-model replies that describe the evidence JSON instead of writing a briefing.
_BRIEFING_JUNK_MARKERS = (
    "json object",
    "this is a json",
    "appears to be a stock market",
    "main object",
    "the following properties",
    "properties:",
    "breakdown of the report",
    "each stock analysis object",
    "the array is empty",
    "the report's structure",
    "stock analysis objects",
)


def _human_regime(regime: Optional[str]) -> str:
    key = (regime or "UNKNOWN").upper()
    return _REGIME_LABELS.get(key, (regime or "Unknown").replace("_", " ").title())


def _human_vix_band(band: Optional[str]) -> str:
    key = (band or "UNKNOWN").upper()
    return _VIX_BAND_LABELS.get(key, (band or "unknown").lower())


def _display_symbol(symbol: Optional[str]) -> str:
    return (symbol or "").replace(".NS", "")


def compact_briefing_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Typed, token-capped evidence the LLM is allowed to see.

    Accepts either the stitch dict or an already-compact HeadAgentContext
    dict so enqueue and the AI worker share one path.
    """
    ctx = build_head_agent_context(
        regime=str(payload.get("regime") or "UNKNOWN"),
        market_trend=payload.get("market_trend"),
        vix_value=payload.get("vix_value"),
        vix_band=payload.get("vix_band"),
        top_picks=list(payload.get("top_picks") or []),
        sector_rotation=payload.get("sector_rotation"),
        headlines=payload.get("news_headlines") or payload.get("headlines"),
        upcoming_events=payload.get("upcoming_events"),
        counters=payload.get("counters"),
    )
    return json.loads(serialize_context(ctx))


def _pick_event_note(pick: Dict[str, Any]) -> str:
    ev = pick.get("upcoming_event") if isinstance(pick.get("upcoming_event"), dict) else None
    title = None
    days = None
    if ev:
        title = ev.get("title")
        days = ev.get("days_until")
    else:
        title = pick.get("upcoming_event_title")
        days = pick.get("upcoming_event_days_until")
    if not title:
        return ""
    when = "today" if days == 0 else (f"in {days}d" if days is not None else "")
    return f"{title}" + (f" {when}" if when else "")


def _fallback_summary_md(payload: Dict[str, Any]) -> str:
    """Markdown used when Ollama is down or the model dumps schema instead of
    a briefing. Same section order as the LLM prompt so the UI stays stable."""
    compact = compact_briefing_payload(payload)
    regime = _human_regime(compact.get("regime"))
    trend = compact.get("market_trend") or "Unclear"
    vix_val = compact.get("vix_value")
    vix_band = _human_vix_band(compact.get("vix_band"))
    vix_str = f"{vix_val:.2f} ({vix_band})" if isinstance(vix_val, (int, float)) else f"n/a ({vix_band})"

    lines: List[str] = []
    lines.append(f"## Market briefing — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(
        f"**Market take.** {regime} regime, India VIX {vix_str}, trend {trend}. "
        "Use the chips above as the source of truth for these labels."
    )
    lines.append("")

    top_picks = compact.get("top_picks") or []
    lines.append("**Consensus picks.**")
    if not top_picks:
        lines.append("No symbol crossed the 2-method threshold this cycle.")
    else:
        for p in top_picks:
            methods = p.get("methods") or p.get("votes") or []
            method_label = ", ".join(str(m) for m in methods) if methods else "—"
            vote_count = p.get("vote_count") or len(methods)
            conf = p.get("confidence") if p.get("confidence") is not None else p.get("mean_confidence") or 0
            score = p.get("score") or 0
            note = _pick_event_note(p)
            extra = f"; {note}" if note else ""
            lines.append(
                f"- **{_display_symbol(p.get('symbol'))}** — {vote_count} methods "
                f"({method_label}); score {float(score):.1f}; "
                f"mean conf {float(conf):.2f}{extra}"
            )
    lines.append("")

    upcoming = compact.get("upcoming_events") or []
    lines.append("**Upcoming events (next 5 days).**")
    if not upcoming:
        lines.append("No earnings, ex-dividends, F&O expiries or macro prints in the next 5 days.")
    else:
        for ev in upcoming[:6]:
            syms = ev.get("symbols") or []
            shown = [(_display_symbol(s) if s != "MARKET" else "Market-wide") for s in syms[:3]]
            extra = f" +{len(syms) - 3}" if len(syms) > 3 else ""
            sym_label = ", ".join(shown) + extra if shown else "—"
            days = ev.get("days_until")
            when = "today" if days == 0 else (f"in {days}d" if days is not None else "")
            lines.append(
                f"- [{ev.get('impact', '?')}] {ev.get('title')} — {when} ({sym_label})"
            )
    lines.append("")

    sectors = compact.get("sector_rotation") or []
    lines.append("**Sectors.**")
    if not sectors:
        lines.append("No sector rotation data this cycle.")
    else:
        bits = []
        for s in sectors[:5]:
            name = s.get("sector", "Unknown")
            total = s.get("total_score")
            total_s = f"{float(total):.1f}" if isinstance(total, (int, float)) else "—"
            bits.append(f"{name} (score {total_s})")
        lines.append(", ".join(bits) + ".")
    lines.append("")

    headlines = compact.get("headlines") or compact.get("news_headlines") or []
    lines.append("**Headlines.**")
    if not headlines:
        lines.append("No recent headlines fetched.")
    else:
        for h in headlines[:5]:
            src = h.get("source") or "news"
            lines.append(f"- [{src}] {h.get('title')}")
    lines.append("")
    lines.append(f"_{DISCLAIMER}_")
    return "\n".join(lines)


def briefing_text_is_usable(text: str, payload: Dict[str, Any]) -> bool:
    """Reject schema-tour replies from small local models; keep grounded copy."""
    if not isinstance(text, str) or not text.strip():
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in _BRIEFING_JUNK_MARKERS):
        return False
    compact = compact_briefing_payload(payload)
    picks = compact.get("top_picks") or []
    if picks:
        haystack = text.upper()
        mentioned = False
        for pick in picks:
            stem = _display_symbol(pick.get("symbol")).upper()
            if stem and stem in haystack:
                mentioned = True
                break
        if not mentioned:
            return False
    return True


# ---------------------------------------------------------------------------
# LLM path — Ollama via httpx (only the markdown summary uses the LLM)
# ---------------------------------------------------------------------------
_HEAD_SYSTEM_PROMPT = (
    "You are the Chief Market Strategist for an Indian equity research desk. "
    "You write a concise markdown briefing a human can read in 30 seconds. "
    "You ONLY use values from the evidence JSON. Never invent symbols, numbers, or headlines. "
    "Never describe JSON, keys, schemas, arrays, or object properties. "
    "If a list is empty, write one plain sentence saying so — do not tour the fields. "
    "Always end with this exact disclaimer: " + DISCLAIMER
)


_HEAD_FEW_SHOT = """Good briefing (follow this shape):
## Market briefing
**Market take.** Neutral regime, India VIX 11.61 (normal), trend Downtrend. Treat new longs as counter-trend until daily and weekly states agree.

**Consensus picks.**
- **RELIANCE** — 2 methods (rule_based, rf); score 72.0; mean conf 0.78; Earnings — Reliance in 2d
- **HDFCBANK** — 2 methods (rule_based, rf); score 61.0; mean conf 0.71

**Upcoming events (next 5 days).**
- [HIGH] Earnings — Reliance — in 2d (RELIANCE)

**Sectors.**
IT (score 18.0), Auto (score 14.2).

**Headlines.**
- [moneycontrol.com] Nifty slips as banks weigh

Research and decision-support only. Not financial advice.

Forbidden (never write this):
This is a JSON object that appears to be a stock market analysis report. The main object is an array of objects. Each stock analysis object contains symbol, name, confidence...
"""


def _llm_prompt_for_payload(payload: Dict[str, Any]) -> str:
    """User prompt for Ollama. Evidence is compact HeadAgentContext JSON only."""
    compact = compact_briefing_payload(payload)
    evidence = json.dumps(compact, separators=(",", ":"), default=str)
    return (
        "Write today's Indian-market briefing as markdown.\n"
        "Sections in this order:\n"
        "1. ## Market briefing — then **Market take.** one or two sentences on regime vs trend vs VIX.\n"
        "2. **Consensus picks.** One bullet per pick: display symbol (drop .NS), method count, "
        "score, mean confidence. If upcoming_event_title is set, add it with days_until. "
        "If top_picks is empty, write: No symbol crossed the 2-method threshold this cycle.\n"
        "3. **Upcoming events (next 5 days).** [impact] title — timing — symbols. "
        "If empty, one sentence that nothing is due.\n"
        "4. **Sectors.** Top 3-5 by aggregate score, as a short sentence or bullets.\n"
        "5. **Headlines.** 3-5 sourced titles from the list only.\n"
        "6. End with the disclaimer verbatim.\n\n"
        f"{_HEAD_FEW_SHOT}\n"
        "Use ONLY the evidence JSON below. Do not mention that it is JSON.\n\n"
        f"EVIDENCE:\n{evidence}\n"
    )


def _context_needs_review(context: Dict[str, Any]) -> bool:
    regime = (context.get("regime") or {}).get("regime")
    trend = (context.get("trend") or {}).get("trend")
    vix = (context.get("vix") or {}).get("band")
    return (
        (regime == "RISK_ON" and trend == "DOWN")
        or (regime == "RISK_OFF" and trend == "UP")
        or (vix == "PANIC" and regime == "RISK_ON")
    )


def _payload_key(payload: Dict[str, Any]) -> str:
    relevant = {key: payload.get(key) for key in (
        "regime", "market_trend", "vix_value", "vix_band", "top_picks",
        "sector_rotation", "news_headlines", "upcoming_events",
    )}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, default=str).encode()).hexdigest()


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
    json_statuses: Dict[str, str] = {}
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
        json_statuses["context_agent"] = "NOT_USED"
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

    head_status = "SKIPPED"
    summary_md = _fallback_summary_md(payload)

    worker_statuses["head_agent"] = head_status

    # Roll up status: any ERROR -> PARTIAL (we still have a briefing).
    overall_degraded = any(v in (RUN_STATUS_ERROR, RUN_STATUS_PARTIAL) for v in worker_statuses.values())
    overall_status = RUN_STATUS_PARTIAL if overall_degraded else RUN_STATUS_OK
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
            run_row.json_statuses_json = json_statuses
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
        db.flush()
        briefing_id = int(briefing_row.id)

    if use_llm and settings.AGENTIC_ENABLED:
        key = _payload_key(payload)
        try:
            compact = compact_briefing_payload(payload)
            task_id = ai_queue.enqueue(
                "BRIEFING", f"briefing:{datetime.utcnow().date()}:{key}", compact,
                briefing_id=briefing_id, expires_at=datetime.utcnow() + timedelta(days=1),
            )
            completed = ai_queue.completed_result(task_id)
            if completed and completed.get("summary_md"):
                summary_md = completed["summary_md"]
                head_status = RUN_STATUS_OK
                worker_statuses["head_agent"] = head_status
                with session_scope() as db:
                    current = db.get(DailyBriefing, briefing_id)
                    if current is not None:
                        current.market_summary_md = summary_md
                    run_row = db.get(AgentRun, run_id)
                    if run_row is not None:
                        run_row.head_agent_status = head_status
                        run_row.worker_statuses_json = worker_statuses
            if _context_needs_review(context_out):
                ai_queue.enqueue(
                    "MARKET_CONTEXT", f"context:{datetime.utcnow().date()}:{key}",
                    {"reason": "Conflicting deterministic market context", "context": context_out},
                    briefing_id=briefing_id,
                    expires_at=datetime.utcnow() + timedelta(minutes=45),
                )
        except Exception:  # noqa: BLE001
            log.exception("Could not queue optional AI analysis for briefing %s", briefing_id)

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


__all__ = [
    "BriefingResult",
    "run_deep_cycle",
    "run_boot_cycle",
    "compact_briefing_payload",
    "briefing_text_is_usable",
]
