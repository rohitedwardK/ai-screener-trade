"""MCX Gold / Silver signals — scalp or next-monthly on the front future.

The operator holds the *monthly* MCX lot (GOLDM / SILVERM FUT), not a weekly
mini. Two hold windows, never mixed directions on the same metal:

  - Scalp = 1–2 sessions, tighter ATR targets.
  - Next expiry = only when that monthly dies inside ~30 calendar days.
  - One primary setup per window, aligned with regime (CE in uptrend,
    PE in downtrend). Invalidation is always the stop.

Pure: no DB, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Literal, Optional

import pandas as pd

from . import patterns
from .indicators import compute_all, latest_indicator_dict
from .index_signals import (
    IndexTradePlan,
    _confidence,
    _long_plan,
    _score,
    _short_plan,
    _trading_days_between,
)
from .regime import classify


# MCX monthly mini futures last-trading-day rules (holidays not modelled):
#   GOLDM  — 5th of contract month, or previous weekday if the 5th is a weekend
#   SILVERM — last calendar day of contract month, rolled back over weekends
MONTHLY_EXPIRY_MONTHS = tuple(range(1, 13))

# Short-horizon paper trade (UI: "Scalp · 1–2 days"). Name kept for callers.
WEEKLY_HOLD_TRADING_DAYS = 2
SCALP_HOLD_TRADING_DAYS = WEEKLY_HOLD_TRADING_DAYS
# Optional buffer when synthesising a far expiry; next-month trades use 0.
MIN_HOLD_CALENDAR_DAYS = 8

CATEGORIES = (
    "TREND_CONTINUATION",
    "BREAKOUT_RETEST",
    "PULLBACK_TO_EMA",
    "TREND_BREAKDOWN",
    "BREAKDOWN_RETEST",
    "RALLY_TO_RESISTANCE",
)

HORIZON = "SCALP_ON_MONTHLY"
HORIZON_SCALP = HORIZON
HORIZON_WEEKLY = HORIZON  # older persisted rows / tests
HORIZON_MONTHLY = "MONTHLY_ON_MONTHLY"
MONTHLY_WINDOW_CALENDAR_DAYS = 30
MONTHLY_HOLD_TRADING_DAYS_MAX = 22

_SETUP_THESIS = {
    "TREND_CONTINUATION": "Trend is up. Buy CE; stop below is invalidation.",
    "BREAKOUT_RETEST": "Breakout hold. Buy CE; stop below the breakout is invalidation.",
    "PULLBACK_TO_EMA": "Dip in an uptrend. Buy CE on the pullback; stop below EMA is invalidation.",
    "TREND_BREAKDOWN": "Trend is down. Buy PE; stop above is invalidation.",
    "BREAKDOWN_RETEST": "Breakdown hold. Buy PE; stop above the breakdown is invalidation.",
    "RALLY_TO_RESISTANCE": "Bounce in a downtrend. Buy PE into resistance; stop above is invalidation.",
}


@dataclass
class CommoditySignalRecord:
    symbol: str
    as_of_date: date
    category: str
    direction: str
    score: float
    confidence: float
    reasons: List[str] = field(default_factory=list)
    plan: Optional[IndexTradePlan] = None
    indicators: Dict = field(default_factory=dict)
    regime: str = "RANGE"
    monthly_expiry: Optional[date] = None
    week_hold_days: int = WEEKLY_HOLD_TRADING_DAYS


@dataclass
class CommodityEvaluationResult:
    """Scalp and/or next-expiry rows; watch notes when neither fires."""
    signals: List[CommoditySignalRecord]
    watch_notes: List[str] = field(default_factory=list)
    effective_horizon: Optional[str] = None  # "scalp" | "monthly" | "both" | None


def _safe(val) -> Optional[float]:
    if val is None or pd.isna(val):
        return None
    return float(val)


def _last_weekday_on_or_before(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _last_trading_day(year: int, month: int, day: int = 5) -> date:
    return _last_weekday_on_or_before(date(year, month, day))


def _month_end_ltd(year: int, month: int) -> date:
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    return _last_weekday_on_or_before(d)


def _monthly_ltd(mcx_asset: str, year: int, month: int) -> date:
    if mcx_asset.upper().startswith("SILVER"):
        return _month_end_ltd(year, month)
    return _last_trading_day(year, month, day=5)


def expiry_months_for(mcx_asset: str) -> tuple[int, ...]:
    return MONTHLY_EXPIRY_MONTHS


def next_monthly_expiry(
    mcx_asset: str,
    today: date,
    *,
    min_hold_days: int = 0,
) -> date:
    """Next MCX monthly LTD on or after today + min_hold_days."""
    months = expiry_months_for(mcx_asset)
    cutoff = today + timedelta(days=min_hold_days)
    year = today.year
    for _ in range(24):
        for m in months:
            exp = _monthly_ltd(mcx_asset, year, m)
            if exp >= cutoff:
                return exp
        year += 1
    return cutoff


def is_within_one_month(today: date, expiry: date) -> bool:
    """True when the lot is the next monthly and dies inside ~30 calendar days."""
    delta = (expiry - today).days
    return 0 <= delta <= MONTHLY_WINDOW_CALENDAR_DAYS


def weekly_plan_dte(today: date, monthly_expiry: date) -> int:
    """Trading days used to size the 1–2 day scalp, capped at two sessions."""
    to_expiry = _trading_days_between(today, monthly_expiry)
    return max(1, min(SCALP_HOLD_TRADING_DAYS, to_expiry))


def monthly_plan_dte(today: date, monthly_expiry: date) -> int:
    """Trading days for the monthly swing, capped at ~30 calendar days."""
    window_end = today + timedelta(days=MONTHLY_WINDOW_CALENDAR_DAYS)
    effective_expiry = monthly_expiry if monthly_expiry <= window_end else window_end
    to_expiry = _trading_days_between(today, effective_expiry)
    return max(1, min(MONTHLY_HOLD_TRADING_DAYS_MAX, to_expiry))


def _plan_dte(
    today: date,
    monthly_expiry: date,
    *,
    horizon_mode: Literal["weekly", "scalp", "monthly"],
) -> int:
    if horizon_mode == "monthly":
        return monthly_plan_dte(today, monthly_expiry)
    return weekly_plan_dte(today, monthly_expiry)


def _horizon_label(horizon_mode: Literal["weekly", "scalp", "monthly"]) -> str:
    return HORIZON_MONTHLY if horizon_mode == "monthly" else HORIZON_SCALP


def _regime_side(regime: str) -> Optional[str]:
    u = (regime or "").upper()
    if "UPTREND" in u:
        return "LONG"
    if "DOWNTREND" in u:
        return "SHORT"
    return None


def select_primary(
    recs: List[CommoditySignalRecord],
    regime: str,
) -> List[CommoditySignalRecord]:
    """Keep a single regime-aligned setup so CE and PE never sit side by side."""
    if not recs:
        return []
    want = _regime_side(regime)
    pool = [r for r in recs if want is None or r.direction == want]
    if not pool:
        return []
    best = max(pool, key=lambda r: (r.score, r.confidence))
    return [best]


def build_watch_guidance(
    df: pd.DataFrame,
    *,
    close: float,
    regime: str,
    atr_v: Optional[float],
    rsi_v: Optional[float],
    expiry: date,
    mcx_asset: str,
) -> List[str]:
    """2–3 deterministic lines when no weekly/monthly setup qualifies."""
    if df is None or df.empty:
        return [
            "Insufficient MCX history to score a setup — refresh data and retry.",
            f"Front-month {mcx_asset} expires {expiry.isoformat()}.",
        ]

    last = df.iloc[-1]
    ema20 = _safe(last.get("ema20"))
    ema50 = _safe(last.get("ema50"))
    pivot_s1 = _safe(last.get("pivot_s1"))
    pivot_r1 = _safe(last.get("pivot_r1"))
    high20 = float(df["high"].iloc[-21:-1].max()) if len(df) >= 21 else None
    low20 = float(df["low"].iloc[-21:-1].min()) if len(df) >= 21 else None

    lines: List[str] = []
    rsi_note = f"RSI {rsi_v:.0f}" if rsi_v is not None else "RSI neutral"
    if regime in ("UPTREND", "STRONG_UPTREND"):
        sup = ema20 or ema50 or low20
        sup_txt = f"{sup:.0f}" if sup is not None else "recent swing low"
        lines.append(
            f"Uptrend ({rsi_note}) but no clean entry — watch pullback toward {sup_txt} "
            f"before adding; break above 20-day high {high20:.0f} would re-open momentum."
            if high20 is not None
            else f"Uptrend ({rsi_note}) but no clean entry — wait for pullback to EMA20/50."
        )
    elif regime in ("DOWNTREND", "STRONG_DOWNTREND"):
        res = ema20 or ema50 or high20
        res_txt = f"{res:.0f}" if res is not None else "recent swing high"
        lines.append(
            f"Downtrend ({rsi_note}) — rallies into {res_txt} are fade zones; "
            f"loss of {low20:.0f} would extend weakness." if low20 is not None
            else f"Downtrend ({rsi_note}) — fade rallies into EMA20/50 until structure improves."
        )
    else:
        s_txt = f"{low20:.0f}" if low20 is not None else (f"{pivot_s1:.0f}" if pivot_s1 else "range low")
        r_txt = f"{high20:.0f}" if high20 is not None else (f"{pivot_r1:.0f}" if pivot_r1 else "range high")
        lines.append(
            f"Range-bound ({rsi_note}) — no weekly/monthly setup; trade the edges only "
            f"near support {s_txt} / resistance {r_txt}."
        )

    if atr_v is not None and atr_v > 0:
        inv_long = close - 1.2 * atr_v
        inv_short = close + 1.2 * atr_v
        lines.append(
            f"Bias check: daily close below {inv_long:.0f} invalidates long watch; "
            f"above {inv_short:.0f} invalidates short watch (≈1.2× ATR from {close:.0f})."
        )
    else:
        lines.append(
            f"Contract {mcx_asset} exp {expiry.isoformat()} — wait for ADX ≥ 22 or a "
            f"volume-backed breakout before sizing a swing."
        )

    lines.append(
        "Re-scan after the next daily close; monthly window allows up to ~30 days on this lot."
    )
    return lines[:3]


def evaluate_commodity(
    symbol: str,
    df_raw: pd.DataFrame,
    *,
    mcx_asset: str = "GOLDM",
    monthly_expiry: Optional[date] = None,
    df_enriched: pd.DataFrame | None = None,
    today: Optional[date] = None,
    horizon_mode: Literal["weekly", "scalp", "monthly"] = "scalp",
) -> List[CommoditySignalRecord]:
    """Scalp (1–2 sessions) or next-expiry monthly setups on the MCX future."""
    if horizon_mode == "weekly":
        horizon_mode = "scalp"
    if df_raw is None or df_raw.empty or len(df_raw) < 60:
        return []

    df = df_enriched if df_enriched is not None else compute_all(df_raw)
    last = df.iloc[-1]
    as_of = pd.Timestamp(df.index[-1]).date()
    close = float(last["close"])
    atr_v = _safe(last.get("atr14"))
    rsi_v = _safe(last.get("rsi14"))
    adx_v = _safe(last.get("adx"))
    macd_h = _safe(last.get("macd_hist"))
    ret20 = _safe(last.get("return_20d"))
    pct_from_high = _safe(last.get("pct_from_52w_high"))

    ref = today or as_of
    expiry = monthly_expiry or next_monthly_expiry(mcx_asset, ref)
    plan_dte = _plan_dte(ref, expiry, horizon_mode=horizon_mode)
    dte_contract = _trading_days_between(ref, expiry)
    hold_label = "Scalp" if horizon_mode != "monthly" else "Next expiry"
    horizon_note = (
        f"{hold_label} on {mcx_asset} FUT exp {expiry.isoformat()} "
        f"({dte_contract}d to expiry; targets sized for {plan_dte} sessions)"
    )
    horizon_const = _horizon_label(horizon_mode)

    regime, _ = classify(df)
    pat = patterns.detect_all(df)
    indicators_dict = latest_indicator_dict(df)
    out: List[CommoditySignalRecord] = []

    def _emit(
        category: str,
        direction: str,
        reasons: List[str],
        *,
        stop_mult: float,
        cap: int,
    ) -> None:
        if atr_v is None:
            return
        if direction == "LONG":
            plan = _long_plan(
                close, atr_v, stop_mult=stop_mult,
                expiry=expiry, days_to_expiry=plan_dte,
            )
        else:
            plan = _short_plan(
                close, atr_v, stop_mult=stop_mult,
                expiry=expiry, days_to_expiry=plan_dte,
            )
        plan.horizon = horizon_const
        thesis = _SETUP_THESIS.get(category)
        reasons_out = ([thesis] if thesis else []) + reasons + [horizon_note]
        out.append(CommoditySignalRecord(
            symbol=symbol,
            as_of_date=as_of,
            category=category,
            direction=direction,
            score=round(_score(reasons, cap=cap), 2),
            confidence=_confidence(reasons),
            reasons=reasons_out,
            plan=plan,
            indicators=indicators_dict,
            regime=regime,
            monthly_expiry=expiry,
            week_hold_days=plan_dte,
        ))

    reasons: List[str] = []
    if regime in ("UPTREND", "STRONG_UPTREND"):
        reasons.append(f"Regime {regime}")
    if rsi_v is not None and 50 <= rsi_v <= 72:
        reasons.append(f"RSI {rsi_v:.0f} in momentum zone")
    if macd_h is not None and macd_h > 0:
        reasons.append("MACD histogram positive")
    if adx_v is not None and adx_v >= 22:
        reasons.append(f"ADX {adx_v:.0f} (trending)")
    if ret20 is not None and ret20 > 1.5:
        reasons.append(f"20-day return {ret20:.1f}%")
    if len(reasons) >= 3:
        _emit("TREND_CONTINUATION", "LONG", reasons, stop_mult=1.0, cap=5)

    reasons = []
    if pat.get("breakout_20d"):
        reasons.append("Closed above 20-day high")
    if pat.get("breakout_55d"):
        reasons.append("Closed above 55-day high")
    if regime in ("UPTREND", "STRONG_UPTREND"):
        reasons.append(f"Uptrend regime {regime}")
    if macd_h is not None and macd_h > 0:
        reasons.append("MACD bullish")
    if pct_from_high is not None and pct_from_high > -2.0:
        reasons.append("At/near 52-week high")
    if pat.get("breakout_20d") and len(reasons) >= 2:
        _emit("BREAKOUT_RETEST", "LONG", reasons, stop_mult=0.9, cap=5)

    reasons = []
    if pat.get("pullback"):
        reasons.append("Pullback to EMA20/EMA50 in uptrend")
    if rsi_v is not None and 42 <= rsi_v <= 58:
        reasons.append(f"RSI {rsi_v:.0f} cooled off")
    if pat.get("bullish_engulfing") or pat.get("hammer"):
        reasons.append("Bullish reversal candle")
    if regime in ("UPTREND", "STRONG_UPTREND"):
        reasons.append("Uptrend intact")
    if pat.get("pullback") and len(reasons) >= 2:
        _emit("PULLBACK_TO_EMA", "LONG", reasons, stop_mult=1.0, cap=4)

    reasons = []
    if regime in ("DOWNTREND", "STRONG_DOWNTREND"):
        reasons.append(f"Regime {regime}")
    if rsi_v is not None and 28 <= rsi_v <= 50:
        reasons.append(f"RSI {rsi_v:.0f} weak")
    if macd_h is not None and macd_h < 0:
        reasons.append("MACD histogram negative")
    if adx_v is not None and adx_v >= 22:
        reasons.append(f"ADX {adx_v:.0f} (trending)")
    if ret20 is not None and ret20 < -1.5:
        reasons.append(f"20-day return {ret20:.1f}%")
    if len(reasons) >= 3:
        _emit("TREND_BREAKDOWN", "SHORT", reasons, stop_mult=1.0, cap=5)

    reasons = []
    if pat.get("bearish_reversal"):
        reasons.append("Lower-highs + RSI rolling over")
    if pat.get("bearish_engulfing"):
        reasons.append("Bearish engulfing candle")
    if regime in ("DOWNTREND", "STRONG_DOWNTREND"):
        reasons.append(f"Downtrend regime {regime}")
    if macd_h is not None and macd_h < 0:
        reasons.append("MACD bearish")
    if (pat.get("bearish_reversal") or pat.get("bearish_engulfing")) and len(reasons) >= 2:
        _emit("BREAKDOWN_RETEST", "SHORT", reasons, stop_mult=0.9, cap=5)

    reasons = []
    if regime in ("DOWNTREND", "STRONG_DOWNTREND"):
        reasons.append(f"Regime {regime}")
    if rsi_v is not None and 55 <= rsi_v <= 68:
        reasons.append(f"RSI {rsi_v:.0f} bouncing into resistance")
    if pat.get("bearish_engulfing") or pat.get("bearish_reversal"):
        reasons.append("Bearish reversal at the level")
    if len(reasons) >= 2:
        _emit("RALLY_TO_RESISTANCE", "SHORT", reasons, stop_mult=1.0, cap=4)

    return out


def evaluate_commodity_with_fallback(
    symbol: str,
    df_raw: pd.DataFrame,
    *,
    mcx_asset: str = "GOLDM",
    monthly_expiry: Optional[date] = None,
    df_enriched: pd.DataFrame | None = None,
    today: Optional[date] = None,
) -> CommodityEvaluationResult:
    """Scalp first; add a next-expiry row only when the lot dies within ~30 days."""
    if df_raw is None or df_raw.empty or len(df_raw) < 60:
        return CommodityEvaluationResult(signals=[], watch_notes=[], effective_horizon=None)

    df = df_enriched if df_enriched is not None else compute_all(df_raw)
    last = df.iloc[-1]
    close = float(last["close"])
    atr_v = _safe(last.get("atr14"))
    rsi_v = _safe(last.get("rsi14"))
    ref = today or pd.Timestamp(df.index[-1]).date()
    expiry = monthly_expiry or next_monthly_expiry(mcx_asset, ref)
    regime, _ = classify(df)

    scalp = select_primary(
        evaluate_commodity(
            symbol, df_raw, mcx_asset=mcx_asset, monthly_expiry=expiry,
            df_enriched=df, today=ref, horizon_mode="scalp",
        ),
        regime,
    )
    monthly: List[CommoditySignalRecord] = []
    if is_within_one_month(ref, expiry):
        monthly = select_primary(
            evaluate_commodity(
                symbol, df_raw, mcx_asset=mcx_asset, monthly_expiry=expiry,
                df_enriched=df, today=ref, horizon_mode="monthly",
            ),
            regime,
        )

    signals: List[CommoditySignalRecord] = []
    if scalp:
        signals.extend(scalp)
    if monthly:
        # Same category twice is fine — targets differ by hold window.
        signals.extend(monthly)

    if signals:
        if scalp and monthly:
            horizon = "both"
        elif monthly:
            horizon = "monthly"
        else:
            horizon = "scalp"
        return CommodityEvaluationResult(
            signals=signals, watch_notes=[], effective_horizon=horizon,
        )

    notes = build_watch_guidance(
        df, close=close, regime=regime, atr_v=atr_v, rsi_v=rsi_v,
        expiry=expiry, mcx_asset=mcx_asset,
    )
    return CommodityEvaluationResult(signals=[], watch_notes=notes, effective_horizon=None)


def signal_to_dict(rec: CommoditySignalRecord) -> dict:
    plan = rec.plan
    return {
        "symbol": rec.symbol,
        "as_of_date": rec.as_of_date,
        "category": rec.category,
        "score": rec.score,
        "confidence": rec.confidence,
        "entry": plan.entry if plan else None,
        "stop_loss": plan.stop_loss if plan else None,
        "target_1": plan.target_1 if plan else None,
        "target_2": plan.target_2 if plan else None,
        "invalidation": plan.invalidation if plan else None,
        "reasons_json": rec.reasons,
        "direction": rec.direction,
        "expiry": plan.expiry if plan else rec.monthly_expiry,
        "days_to_expiry": plan.days_to_expiry if plan else None,
        "horizon": plan.horizon if plan else HORIZON,
    }
