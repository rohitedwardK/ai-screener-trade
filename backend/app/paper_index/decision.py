"""PaperIndexTradeDecisionEngine.

Filters index candidates against rules, ranks survivors via automation_score
(option-chain bias contributes), and returns the top-N selections plus every
skipped candidate annotated with `skip_reason`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from ..models.index_schemas import IndexScreenerSignal
from .adapter import ALLOWED_SETUPS
from .config import PaperIndexConfigSnapshot

CONFIDENCE_RANK = {"Low": 0, "Medium": 1, "High": 2}
RISK_RANK = {"Low": 0, "Medium": 1, "High": 2}

SETUP_QUALITY = {
    "Trend Continuation": 0.95,
    "Breakout Retest": 1.00,
    "Pullback to EMA": 0.90,
    "Trend Breakdown": 0.90,
    "Breakdown Retest": 0.95,
    "Rally to Resistance": 0.80,
}

REGIME_QUALITY = {
    "Bullish": 1.00,
    "Sideways": 0.55,
    "Bearish": 1.00,  # bearish regime is fine for SHORT setups; per-direction filter elsewhere
}

CHAIN_BIAS_BONUS = {
    "Bullish": 0.30,
    "Bearish": 0.30,
    "Neutral": 0.0,
}


@dataclass
class IndexDecision:
    signal: IndexScreenerSignal
    decision: str
    automation_score: float
    skip_reason: Optional[str] = None
    ai_reason: Optional[str] = None
    components: dict = field(default_factory=dict)


def _setup_quality(setup_type: str) -> float:
    return SETUP_QUALITY.get(setup_type, 0.5)


def _rr_score(rr: Optional[float]) -> float:
    if rr is None or rr <= 1.0:
        return 0.0
    if rr >= 4.0:
        return 1.0
    return (rr - 1.0) / 3.0


def _regime_aligned(direction: str, regime: Optional[str]) -> float:
    if regime is None:
        return 0.55
    if direction == "LONG":
        if regime == "Bullish":
            return 1.0
        if regime == "Bearish":
            return 0.0
        return 0.55
    if regime == "Bearish":
        return 1.0
    if regime == "Bullish":
        return 0.0
    return 0.55


def _chain_alignment(direction: str, bias: Optional[str]) -> float:
    if not bias or bias == "Neutral":
        return 0.5
    if direction == "LONG":
        return 1.0 if bias == "Bullish" else 0.0
    return 1.0 if bias == "Bearish" else 0.0


def automation_score(
    sig: IndexScreenerSignal,
    market_regime: Optional[str] = None,
    *,
    use_chain_bias: bool = True,
) -> Tuple[float, dict]:
    score_part = max(0.0, min(1.0, (sig.score or 0.0) / 100.0))
    setup_part = _setup_quality(sig.setup_type)
    rr_part = _rr_score(sig.risk_reward)
    regime_part = _regime_aligned(sig.direction, market_regime or sig.market_regime)
    chain_part = _chain_alignment(sig.direction, sig.option_chain_bias) if use_chain_bias else 0.5
    total = (
        0.30 * score_part
        + 0.20 * setup_part
        + 0.20 * rr_part
        + 0.15 * regime_part
        + 0.15 * chain_part
    )
    return round(total * 100.0, 2), {
        "score_part": round(score_part, 4),
        "setup_part": round(setup_part, 4),
        "rr_part": round(rr_part, 4),
        "regime_part": round(regime_part, 4),
        "chain_part": round(chain_part, 4),
    }


def _disqualify(
    sig: IndexScreenerSignal,
    cfg: PaperIndexConfigSnapshot,
    *,
    market_regime: Optional[str],
    open_symbols: Set[str],
) -> Optional[str]:
    key = f"{sig.symbol}:{sig.direction}"
    if key in open_symbols:
        return f"duplicate: {sig.direction} position already open in {sig.code}"
    if (sig.score or 0.0) < cfg.min_score:
        return f"score {sig.score:.0f} below threshold {cfg.min_score:.0f}"
    if sig.risk_reward is None or sig.risk_reward < cfg.min_risk_reward:
        rr = "n/a" if sig.risk_reward is None else f"{sig.risk_reward:.2f}"
        return f"risk-reward {rr} below {cfg.min_risk_reward:.2f}"
    if CONFIDENCE_RANK.get(sig.confidence, 0) < CONFIDENCE_RANK["Medium"]:
        return f"confidence {sig.confidence} below Medium"
    if RISK_RANK.get(sig.risk_level, 0) >= RISK_RANK["High"]:
        return "risk_level High (volatility too elevated)"
    if sig.setup_type not in ALLOWED_SETUPS:
        return f"setup {sig.setup_type!r} not in allowed list"
    if sig.spot_entry is None or sig.spot_stop_loss is None or sig.spot_target_1 is None:
        return "missing entry / stop_loss / target_1"
    if sig.direction == "LONG" and not (sig.spot_stop_loss < sig.spot_entry < sig.spot_target_1):
        return "invalid LONG plan: stop must be below entry, target above entry"
    if sig.direction == "SHORT" and not (sig.spot_stop_loss > sig.spot_entry > sig.spot_target_1):
        return "invalid SHORT plan: stop must be above entry, target below entry"
    # Direction must align with regime for new entries (no fighting the trend).
    regime = market_regime or sig.market_regime
    if regime == "Bearish" and sig.direction == "LONG":
        return "market regime Bearish: skip LONG entries"
    if regime == "Bullish" and sig.direction == "SHORT":
        return "market regime Bullish: skip SHORT entries"
    # Option-chain hard veto: chain strongly opposes direction
    if sig.option_chain_bias == "Bearish" and sig.direction == "LONG":
        return "option chain bias Bearish: skip LONG entry"
    if sig.option_chain_bias == "Bullish" and sig.direction == "SHORT":
        return "option chain bias Bullish: skip SHORT entry"
    return None


def evaluate(
    candidates: List[IndexScreenerSignal],
    cfg: PaperIndexConfigSnapshot,
    *,
    market_regime: str,
    open_symbols: Optional[Set[str]] = None,
    trades_taken_today: int = 0,
) -> Tuple[List[IndexDecision], List[IndexDecision]]:
    open_set = set(open_symbols or [])
    daily_room = max(0, cfg.max_trades_per_day - trades_taken_today)

    skipped: List[IndexDecision] = []
    passed: List[IndexDecision] = []

    for sig in candidates:
        skip_reason = _disqualify(sig, cfg, market_regime=market_regime, open_symbols=open_set)
        if skip_reason is not None:
            score, comps = automation_score(sig, market_regime, use_chain_bias=cfg.use_option_chain_bias)
            skipped.append(IndexDecision(
                signal=sig, decision="skipped", automation_score=score,
                skip_reason=skip_reason,
                ai_reason=_short_reason(sig, market_regime, skip_reason=skip_reason),
                components=comps,
            ))
            continue
        score, comps = automation_score(sig, market_regime, use_chain_bias=cfg.use_option_chain_bias)
        passed.append(IndexDecision(
            signal=sig, decision="selected", automation_score=score,
            ai_reason=_short_reason(sig, market_regime),
            components=comps,
        ))

    passed.sort(key=lambda d: (d.automation_score, d.signal.risk_reward or 0.0), reverse=True)
    selected = passed[:daily_room]
    overflow = passed[daily_room:]
    for d in overflow:
        d.decision = "skipped"
        d.skip_reason = "daily paper-index trade limit reached"
        skipped.append(d)
    return selected, skipped


def _short_reason(
    sig: IndexScreenerSignal,
    market_regime: str,
    *,
    skip_reason: Optional[str] = None,
) -> str:
    if skip_reason is not None:
        return f"Skipped: {skip_reason}."
    rr = f"{sig.risk_reward:.2f}" if sig.risk_reward is not None else "n/a"
    parts = [
        f"{sig.setup_type} on {sig.code}",
        f"{sig.direction} via {sig.option_type}",
        f"score {sig.score:.0f}",
        f"R:R {rr}",
        f"market {market_regime}",
    ]
    if sig.option_chain_bias and sig.option_chain_bias != "Neutral":
        parts.append(f"chain {sig.option_chain_bias}")
    return "Selected: " + ", ".join(parts) + "."
