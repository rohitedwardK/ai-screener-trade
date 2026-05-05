"""Decision-engine tests: filtering rules + automation_score ranking."""
from __future__ import annotations

from datetime import date

import pytest

from app.models.paper_schemas import ScreenerSignal
from app.paper.config import PaperConfigSnapshot
from app.paper.decision import automation_score, evaluate


def _sig(symbol: str = "ABC.NS", **overrides) -> ScreenerSignal:
    base = dict(
        symbol=symbol,
        date=date(2026, 5, 5),
        close=2850.0,
        trend="Strong Uptrend",
        setup_type="Pullback to EMA20",
        score=84.0,
        confidence="High",
        risk_level="Medium",
        risk_reward=2.2,
        entry=2850.0,
        entry_zone_low=2810.0,
        entry_zone_high=2860.0,
        stop_loss=2760.0,
        target_1=2940.0,
        target_2=3020.0,
        rsi=61.0,
        volume_ratio=1.4,
        atr_percent=2.1,
        market_regime="Bullish",
    )
    base.update(overrides)
    return ScreenerSignal(**base)


def _cfg(**overrides) -> PaperConfigSnapshot:
    base = dict(
        max_trades_per_day=5,
        min_score=75.0,
        min_risk_reward=2.0,
    )
    base.update(overrides)
    return PaperConfigSnapshot(**base)


def test_clean_pass_is_selected():
    selected, skipped = evaluate(
        [_sig()], _cfg(), market_regime="Bullish", open_symbols=set(), trades_taken_today=0,
    )
    assert len(selected) == 1
    assert selected[0].decision == "selected"
    assert selected[0].automation_score > 0
    assert skipped == []


def test_low_score_skipped():
    selected, skipped = evaluate(
        [_sig(score=70.0)], _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert len(skipped) == 1
    assert "score" in skipped[0].skip_reason


def test_low_risk_reward_skipped():
    selected, skipped = evaluate(
        [_sig(risk_reward=1.5)], _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert "risk-reward" in skipped[0].skip_reason


def test_low_confidence_skipped():
    selected, skipped = evaluate(
        [_sig(confidence="Low")], _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert "confidence" in skipped[0].skip_reason


def test_high_risk_level_skipped():
    selected, skipped = evaluate(
        [_sig(risk_level="High")], _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert "risk_level" in skipped[0].skip_reason


def test_bearish_market_regime_skipped():
    selected, skipped = evaluate(
        [_sig()], _cfg(), market_regime="Bearish", open_symbols=set(),
    )
    assert selected == []
    assert "Bearish" in skipped[0].skip_reason


def test_disallowed_setup_skipped():
    selected, skipped = evaluate(
        [_sig(setup_type="Range Trade")], _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert "not in allowed" in skipped[0].skip_reason


def test_overheated_rsi_skipped():
    selected, skipped = evaluate(
        [_sig(rsi=78.0)], _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert "RSI" in skipped[0].skip_reason


def test_invalid_plan_stop_above_entry_skipped():
    selected, skipped = evaluate(
        [_sig(stop_loss=2900.0, entry=2850.0, target_1=2950.0)],
        _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert "invalid plan" in skipped[0].skip_reason


def test_duplicate_open_symbol_skipped():
    s = _sig(symbol="DUP.NS")
    selected, skipped = evaluate(
        [s], _cfg(), market_regime="Bullish", open_symbols={"DUP.NS"},
    )
    assert selected == []
    assert "duplicate" in skipped[0].skip_reason


def test_daily_limit_caps_selection_and_overflows_skipped():
    candidates = [_sig(symbol=f"S{i}.NS", score=80.0 + i, risk_reward=2.5) for i in range(7)]
    selected, skipped = evaluate(
        candidates, _cfg(max_trades_per_day=3), market_regime="Bullish", open_symbols=set(),
    )
    assert len(selected) == 3
    # 4 overflow into skipped with daily-limit reason; none filtered out by quality.
    overflow = [s for s in skipped if "daily paper trade limit" in (s.skip_reason or "")]
    assert len(overflow) == 4


def test_ranking_prefers_higher_automation_score():
    high = _sig(symbol="HIGH.NS", score=95.0, risk_reward=3.5, volume_ratio=1.5)
    mid = _sig(symbol="MID.NS", score=80.0, risk_reward=2.1, volume_ratio=1.0)
    selected, _ = evaluate(
        [mid, high], _cfg(max_trades_per_day=1), market_regime="Bullish", open_symbols=set(),
    )
    assert len(selected) == 1
    assert selected[0].signal.symbol == "HIGH.NS"


def test_no_quality_setups_returns_empty():
    selected, skipped = evaluate(
        [], _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert skipped == []


def test_automation_score_components():
    s = _sig()
    score, comps = automation_score(s, "Bullish")
    # All five buckets present, all in [0, 1].
    assert 0 < score <= 100
    for k in ("score_part", "setup_part", "rr_part", "liquidity_part", "regime_part"):
        assert 0.0 <= comps[k] <= 1.0


def test_oversold_recovery_is_allowed():
    s = _sig(setup_type="Oversold Recovery", score=80.0, risk_reward=2.5, confidence="High")
    selected, _ = evaluate([s], _cfg(), market_regime="Bullish", open_symbols=set())
    assert len(selected) == 1


def test_daily_limit_already_reached():
    selected, skipped = evaluate(
        [_sig()],
        _cfg(max_trades_per_day=5),
        market_regime="Bullish",
        open_symbols=set(),
        trades_taken_today=5,
    )
    assert selected == []
    # Candidate passes filters but no room left -> overflow into skipped.
    assert any("daily paper trade limit" in (s.skip_reason or "") for s in skipped)
