"""LLMContextBuilder — strict typed boundary between L1-L3 outputs and L4 LLM.

This module enforces the project rule:

    The HeadAgent (LLM) NEVER receives raw inputs. Only compact, structured,
    typed JSON: processed signals, summaries, reasons[]. No raw OHLCV
    candles, no raw indicators, no raw news article bodies, no full Pydantic
    models — only `HeadAgentContext`.

What this guard protects against
--------------------------------
1. **Token explosion.** A FeatureVector dict alone is ~50 numbers; the full
   enriched DataFrame for one stock is 5y × 30 cols = ~36,500 numbers.
   Multiply by 50 picks × 4 methods → catastrophic prompt size.
2. **Hallucination surface.** Raw indicators have meaningless values out of
   context (RSI 67 — bullish or bearish? Depends on regime + level). The
   builder pre-derives `reasons[]` from the engines, so the LLM repeats
   classifications, not invents them.
3. **PII / private data leakage.** As we add news bodies, broker emails,
   etc. they'd risk hitting the LLM. Routing through a typed builder makes
   this an explicit, reviewable shape.
4. **Cost control.** Token-budget cap (`MAX_LLM_TOKENS`) hard-truncates
   payloads — better degraded summary than a $50/cycle bill.

The orchestrator compacting path (`compact_briefing_payload`) is the only
shape enqueued for BRIEFING tasks and the only JSON the head-agent prompt
may contain.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# Approximate token cap. We err on the side of compactness — Llama 3.2
# context window is 128K but we budget ~4K so the prompt + system prompt
# + completion all fit comfortably with room for retries.
MAX_LLM_TOKENS = 4000

# Approximation: 1 token ≈ 4 characters for typical english + JSON. Cheap
# heuristic; PR3 will swap in a real tokenizer if we observe drift.
TOKENS_PER_CHAR = 0.25


# Forbidden field names — if any of these surface anywhere in the payload
# graph, the builder raises rather than send to the LLM. The list captures
# the kinds of raw data we explicitly never want in the prompt.
FORBIDDEN_FIELDS = frozenset({
    "candles",                  # raw OHLCV bars
    "ohlcv",                    # raw OHLCV bars
    "df",                       # accidentally-passed pandas DataFrames
    "raw_news",                 # full news article bodies
    "news_body",                # full news article bodies
    "feature_vector",           # the L1.5 FeatureVector dict
    "feature_vectors",          # batches of L1.5 FeatureVectors
    "ml_input_matrix",          # the X matrix sent to RF/GBM
    "lstm_window",              # the (N, window, features) tensor for LSTM
    "indicator_series",         # full pandas Series of indicators
    "csv_path",                 # filesystem hints
})


@dataclass(frozen=True)
class TopPickContext:
    """Single pick the LLM gets to mention in the briefing.

    `reasons` is a 2-5 item list of short human-readable rationales already
    derived by the inference engines (RuleEngineAgent, MLPredictionAgent,
    SequenceForecastAgent). The LLM's job is to *summarise* these, not to
    reason about them — that work was done in L2.
    """
    symbol: str
    name: Optional[str]
    direction: str                       # "BUY" | "SELL" | "NEUTRAL"
    confidence: float                    # 0..1
    score: float                         # 0..100 (consensus score)
    vote_count: int
    methods: List[str]                   # ["rule_based", "rf"]
    regime: Optional[str] = None
    category: Optional[str] = None
    close: Optional[float] = None
    reasons: List[str] = field(default_factory=list)
    upcoming_event_title: Optional[str] = None
    upcoming_event_days_until: Optional[int] = None


@dataclass(frozen=True)
class HeadAgentContext:
    """The complete typed payload the LLM sees. No other shape is allowed."""

    regime: str
    market_trend: Optional[str]
    vix_value: Optional[float]
    vix_band: Optional[str]
    top_picks: List[TopPickContext] = field(default_factory=list)
    sector_rotation: List[Dict[str, Any]] = field(default_factory=list)
    headlines: List[Dict[str, Any]] = field(default_factory=list)
    upcoming_events: List[Dict[str, Any]] = field(default_factory=list)
    counters: Dict[str, Any] = field(default_factory=dict)
    disclaimer: str = "Research and decision-support only. Not financial advice."

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ContextBuildError(ValueError):
    """Raised when builder inputs violate the typed boundary."""


@dataclass(frozen=True)
class ContextCaps:
    """Per-list truncation caps. Bundled so the builder signature stays
    short and the defaults are documented in one place."""
    max_picks: int = 8
    max_headlines: int = 5
    max_sectors: int = 5
    max_events: int = 6
    max_reasons_per_pick: int = 5


DEFAULT_CAPS = ContextCaps()


def build_head_agent_context(
    *,
    regime: str,
    market_trend: Optional[str],
    vix_value: Optional[float],
    vix_band: Optional[str],
    top_picks: List[Dict[str, Any]],
    sector_rotation: Optional[List[Dict[str, Any]]] = None,
    headlines: Optional[List[Dict[str, Any]]] = None,
    upcoming_events: Optional[List[Dict[str, Any]]] = None,
    counters: Optional[Dict[str, Any]] = None,
    caps: ContextCaps = DEFAULT_CAPS,
) -> HeadAgentContext:
    """Build a HeadAgentContext from L2/L3 outputs. The function applies:

    * Schema enforcement — only the documented fields go in.
    * Forbidden-field guard — raises ContextBuildError if any input dict
      mentions a banned key (defence in depth against accidental leakage).
    * Top-N truncation — caps each list so the payload size is bounded.
    * Reason truncation — each pick's reasons[] is capped at 5 items
      (keeps the prompt tight; the rest live in the structured DB row).
    """
    _reject_forbidden(top_picks, "top_picks")
    _reject_forbidden(sector_rotation or [], "sector_rotation")
    _reject_forbidden(headlines or [], "headlines")
    _reject_forbidden(upcoming_events or [], "upcoming_events")

    picks = [
        _coerce_pick(p, caps.max_reasons_per_pick) for p in top_picks[:caps.max_picks]
    ]
    sectors = list((sector_rotation or [])[:caps.max_sectors])
    heads = list((headlines or [])[:caps.max_headlines])
    events = list((upcoming_events or [])[:caps.max_events])

    return HeadAgentContext(
        regime=str(regime or "UNKNOWN"),
        market_trend=market_trend,
        vix_value=vix_value,
        vix_band=vix_band,
        top_picks=picks,
        sector_rotation=sectors,
        headlines=heads,
        upcoming_events=events,
        counters=dict(counters or {}),
    )


def serialize_context(
    ctx: HeadAgentContext,
    *,
    max_tokens: int = MAX_LLM_TOKENS,
) -> str:
    """JSON-serialise the context, enforcing the token budget. If the
    payload would exceed `max_tokens`, drop tail items until it fits.

    Returns the trimmed JSON string. Logs a warning if trimming was needed
    so we can spot drift toward bloated payloads in monitoring."""
    payload = ctx.to_dict()
    s = json.dumps(payload, separators=(",", ":"), default=str)
    if _approx_tokens(s) <= max_tokens:
        return s

    log.warning(
        "LLMContextBuilder: payload over budget (%.0f tok > %d), trimming",
        _approx_tokens(s), max_tokens,
    )

    # Trim in priority order — keep regime/vix/picks; drop tail items
    # from the auxiliary lists first, then headlines, then events,
    # then sectors, then picks themselves.
    trim_order: List[str] = ["headlines", "upcoming_events", "sector_rotation"]
    for key in trim_order:
        while payload.get(key) and _approx_tokens(s) > max_tokens:
            payload[key].pop()
            s = json.dumps(payload, separators=(",", ":"), default=str)

    while len(payload.get("top_picks", [])) > 1 and _approx_tokens(s) > max_tokens:
        payload["top_picks"].pop()
        s = json.dumps(payload, separators=(",", ":"), default=str)

    if _approx_tokens(s) > max_tokens:
        # Last-resort: clip reasons on every remaining pick to 1 item.
        for pick in payload.get("top_picks", []):
            pick["reasons"] = pick.get("reasons", [])[:1]
        s = json.dumps(payload, separators=(",", ":"), default=str)

    return s


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _approx_tokens(s: str) -> float:
    return len(s) * TOKENS_PER_CHAR


def _coerce_pick(raw: Dict[str, Any], max_reasons: int) -> TopPickContext:
    """Normalise an arbitrary pick dict (from consensus_picks_impl + the
    per-engine reasons[] additions) into a strict TopPickContext."""
    reasons = raw.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    reasons = [str(r) for r in reasons if r][:max_reasons]

    upcoming = raw.get("upcoming_event") or {}

    return TopPickContext(
        symbol=str(raw.get("symbol", "")),
        name=raw.get("name"),
        direction=str(raw.get("direction") or "NEUTRAL"),
        confidence=float(raw.get("mean_confidence") or raw.get("confidence") or 0.0),
        score=float(raw.get("score") or 0.0),
        vote_count=int(raw.get("vote_count") or 0),
        methods=list(raw.get("votes") or raw.get("methods") or []),
        regime=raw.get("regime"),
        category=raw.get("category") or (
            (raw.get("categories") or [None])[0] if raw.get("categories") else None
        ),
        close=_safe_float(raw.get("close")),
        reasons=reasons,
        upcoming_event_title=upcoming.get("title") if isinstance(upcoming, dict) else None,
        upcoming_event_days_until=upcoming.get("days_until") if isinstance(upcoming, dict) else None,
    )


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _reject_forbidden(items: List[Dict[str, Any]], where: str) -> None:
    """Raise ContextBuildError if any item dict contains a banned key.
    Catches accidental leakage of raw inputs at the type-boundary.
    Recursive across one level of nested dicts (good enough for the
    flat shapes we accept in PR1)."""
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        bad = FORBIDDEN_FIELDS & set(item.keys())
        if bad:
            raise ContextBuildError(
                f"{where}[{i}] contains forbidden raw-data field(s): {sorted(bad)}"
            )
        for v in item.values():
            if isinstance(v, dict):
                bad_nested = FORBIDDEN_FIELDS & set(v.keys())
                if bad_nested:
                    raise ContextBuildError(
                        f"{where}[{i}] has nested raw-data field(s): {sorted(bad_nested)}"
                    )


__all__ = [
    "HeadAgentContext",
    "TopPickContext",
    "ContextCaps",
    "DEFAULT_CAPS",
    "ContextBuildError",
    "build_head_agent_context",
    "serialize_context",
    "MAX_LLM_TOKENS",
    "FORBIDDEN_FIELDS",
]
