"""PaperTradeDecisionEngine.

Filters screener candidates against the spec rules, ranks the survivors with
the automation_score, then returns the top-N selections together with
*every* skipped candidate annotated with a human-readable skip_reason. Both
arms of the decision are persisted later in `paper_trade_signals` for audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from ..models.paper_schemas import ScreenerSignal
from .adapter import ALLOWED_SETUPS
from .config import PaperConfigSnapshot

CONFIDENCE_RANK = {"Low": 0, "Medium": 1, "High": 2}
RISK_RANK = {"Low": 0, "Medium": 1, "High": 2}

SETUP_QUALITY = {
    "Breakout Retest": 1.00,
    "Pullback to EMA20": 0.95,
    "Pullback to SMA20": 0.85,
    "Momentum Continuation": 0.80,
    "Oversold Recovery": 0.65,
}

REGIME_QUALITY = {
    "Bullish": 1.00,
    "Sideways": 0.55,
    "Bearish": 0.0,
}


@dataclass
class Decision:
    """A single decision row (selected or skipped)."""
    signal: ScreenerSignal
    decision: str                 # "selected" | "skipped"
    automation_score: float
    skip_reason: Optional[str] = None
    ai_reason: Optional[str] = None
    components: dict = field(default_factory=dict)


# --- helpers ---

def _liquidity_score(volume_ratio: Optional[float]) -> float:
    if volume_ratio is None:
        return 0.5
    # 0 -> 0, 1 -> ~0.67, 1.5+ -> 1.0
    return max(0.0, min(1.0, volume_ratio / 1.5))


def _rr_score(rr: Optional[float]) -> float:
    if rr is None:
        return 0.0
    if rr <= 1.0:
        return 0.0
    if rr >= 4.0:
        return 1.0
    return (rr - 1.0) / 3.0


def _setup_quality(setup_type: str) -> float:
    return SETUP_QUALITY.get(setup_type, 0.5)


def _regime_quality(regime: Optional[str]) -> float:
    if regime is None:
        return 0.55
    return REGIME_QUALITY.get(regime, 0.55)


def automation_score(
    sig: ScreenerSignal,
    market_regime: Optional[str] = None,
) -> Tuple[float, dict]:
    """Compute the spec automation_score on a 0..1 scale and return components."""
    score_part = max(0.0, min(1.0, (sig.score or 0.0) / 100.0))
    setup_part = _setup_quality(sig.setup_type)
    rr_part = _rr_score(sig.risk_reward)
    liq_part = _liquidity_score(sig.volume_ratio)
    regime_part = _regime_quality(market_regime or sig.market_regime)
    total = (
        0.35 * score_part
        + 0.25 * setup_part
        + 0.20 * rr_part
        + 0.10 * liq_part
        + 0.10 * regime_part
    )
    return round(total * 100.0, 2), {
        "score_part": round(score_part, 4),
        "setup_part": round(setup_part, 4),
        "rr_part": round(rr_part, 4),
        "liquidity_part": round(liq_part, 4),
        "regime_part": round(regime_part, 4),
    }


# --- filter ---

def _disqualify(
    sig: ScreenerSignal,
    cfg: PaperConfigSnapshot,
    *,
    market_regime: Optional[str],
    open_symbols: Set[str],
) -> Optional[str]:
    """Return a skip_reason if the candidate is disqualified, else None."""
    if sig.symbol in open_symbols:
        return "duplicate: position already open in same symbol"
    if (sig.score or 0.0) < cfg.min_score:
        return f"score {sig.score:.0f} below threshold {cfg.min_score:.0f}"
    if sig.risk_reward is None or sig.risk_reward < cfg.min_risk_reward:
        rr = "n/a" if sig.risk_reward is None else f"{sig.risk_reward:.2f}"
        return f"risk-reward {rr} below {cfg.min_risk_reward:.2f}"
    if CONFIDENCE_RANK.get(sig.confidence, 0) < CONFIDENCE_RANK["Medium"]:
        return f"confidence {sig.confidence} below Medium"
    if RISK_RANK.get(sig.risk_level, 0) >= RISK_RANK["High"]:
        return "risk_level High"
    if (market_regime or sig.market_regime) == "Bearish":
        return "market regime Bearish"
    if sig.setup_type not in ALLOWED_SETUPS:
        return f"setup {sig.setup_type!r} not in allowed list"
    if sig.entry is None or sig.stop_loss is None or sig.target_1 is None:
        return "missing entry / stop_loss / target_1"
    if not (sig.stop_loss < sig.entry < sig.target_1):
        return "invalid plan: stop must be below entry, target above entry"
    if sig.rsi is not None and sig.rsi > 75.0:
        return f"RSI {sig.rsi:.0f} overheated"
    return None


# --- engine ---

def evaluate(
    candidates: List[ScreenerSignal],
    cfg: PaperConfigSnapshot,
    *,
    market_regime: str,
    open_symbols: Optional[Set[str]] = None,
    trades_taken_today: int = 0,
) -> Tuple[List[Decision], List[Decision]]:
    """Return (selected, skipped) decision lists.

    Selected list is bounded by `cfg.max_trades_per_day - trades_taken_today`.
    No filler trades: returns fewer than the cap if quality is poor.
    """
    open_set = set(open_symbols or [])
    daily_room = max(0, cfg.max_trades_per_day - trades_taken_today)

    skipped: List[Decision] = []
    passed: List[Decision] = []

    for sig in candidates:
        skip_reason = _disqualify(sig, cfg, market_regime=market_regime, open_symbols=open_set)
        if skip_reason is not None:
            score, comps = automation_score(sig, market_regime)
            skipped.append(Decision(
                signal=sig,
                decision="skipped",
                automation_score=score,
                skip_reason=skip_reason,
                ai_reason=_short_reason(sig, market_regime, skip_reason=skip_reason),
                components=comps,
            ))
            continue
        score, comps = automation_score(sig, market_regime)
        passed.append(Decision(
            signal=sig,
            decision="selected",  # provisional; trimmed by daily cap below
            automation_score=score,
            ai_reason=_short_reason(sig, market_regime),
            components=comps,
        ))

    # Rank survivors by automation_score (descending), then RR as tie-breaker.
    passed.sort(key=lambda d: (d.automation_score, d.signal.risk_reward or 0.0), reverse=True)

    selected = passed[:daily_room]
    overflow = passed[daily_room:]
    for d in overflow:
        d.decision = "skipped"
        d.skip_reason = "daily paper trade limit reached"
        skipped.append(d)

    if daily_room == 0 and not overflow:
        # No survivors at all; nothing additional to record beyond what's already in skipped.
        pass

    return selected, skipped


def _short_reason(
    sig: ScreenerSignal,
    market_regime: str,
    *,
    skip_reason: Optional[str] = None,
) -> str:
    if skip_reason is not None:
        return f"Skipped: {skip_reason}."
    rr = f"{sig.risk_reward:.2f}" if sig.risk_reward is not None else "n/a"
    parts = [
        f"{sig.setup_type} on {sig.symbol}",
        f"score {sig.score:.0f}",
        f"R:R {rr}",
        f"trend {sig.trend}",
        f"market {market_regime}",
    ]
    if sig.rsi is not None:
        parts.append(f"RSI {sig.rsi:.0f}")
    return "Selected: " + ", ".join(parts) + "."
