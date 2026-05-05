"""Decision-engine tests for the paper-INDEX bot."""
from __future__ import annotations

from datetime import date

from app.models.index_schemas import IndexScreenerSignal
from app.paper_index.config import PaperIndexConfigSnapshot
from app.paper_index.decision import automation_score, evaluate


def _sig(symbol: str = "^NSEI", **overrides) -> IndexScreenerSignal:
    base = dict(
        symbol=symbol,
        code="NIFTY",
        date=date(2026, 5, 5),
        spot=20000.0,
        direction="LONG",
        option_type="CE",
        setup_type="Trend Continuation",
        score=85.0,
        confidence="High",
        risk_level="Medium",
        risk_reward=2.5,
        spot_entry=20000.0,
        spot_stop_loss=19850.0,
        spot_target_1=20300.0,
        spot_target_2=20500.0,
        spot_invalidation=19850.0,
        rsi=60.0,
        atr_percent=1.5,
        market_regime="Bullish",
        option_chain_bias="Bullish",
        pcr=1.4,
        max_pain=20100.0,
    )
    base.update(overrides)
    return IndexScreenerSignal(**base)


def _cfg(**overrides) -> PaperIndexConfigSnapshot:
    base = dict(max_trades_per_day=5, min_score=70.0, min_risk_reward=1.5)
    base.update(overrides)
    return PaperIndexConfigSnapshot(**base)


def test_clean_long_pass_is_selected():
    selected, skipped = evaluate(
        [_sig()], _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert len(selected) == 1
    assert selected[0].decision == "selected"
    assert selected[0].automation_score > 0
    assert skipped == []


def test_clean_short_pass_is_selected():
    s = _sig(
        direction="SHORT", option_type="PE",
        setup_type="Trend Breakdown",
        spot_entry=20000.0, spot_stop_loss=20150.0,
        spot_target_1=19700.0, spot_target_2=19500.0,
        spot_invalidation=20150.0, market_regime="Bearish",
        option_chain_bias="Bearish",
    )
    selected, skipped = evaluate([s], _cfg(), market_regime="Bearish", open_symbols=set())
    assert len(selected) == 1
    assert selected[0].signal.direction == "SHORT"


def test_low_score_skipped():
    selected, skipped = evaluate(
        [_sig(score=50.0)], _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert "score" in skipped[0].skip_reason


def test_low_rr_skipped():
    selected, skipped = evaluate(
        [_sig(risk_reward=1.0)], _cfg(), market_regime="Bullish", open_symbols=set(),
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


def test_disallowed_setup_skipped():
    selected, skipped = evaluate(
        [_sig(setup_type="Range Trade")], _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert "not in allowed" in skipped[0].skip_reason


def test_invalid_long_plan_skipped():
    selected, skipped = evaluate(
        [_sig(spot_entry=20000.0, spot_stop_loss=20100.0, spot_target_1=20300.0)],
        _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert "invalid LONG plan" in skipped[0].skip_reason


def test_long_against_bearish_regime_skipped():
    selected, skipped = evaluate(
        [_sig()], _cfg(), market_regime="Bearish", open_symbols=set(),
    )
    assert selected == []
    assert "Bearish" in skipped[0].skip_reason


def test_long_against_bearish_chain_skipped():
    selected, skipped = evaluate(
        [_sig(option_chain_bias="Bearish")],
        _cfg(), market_regime="Bullish", open_symbols=set(),
    )
    assert selected == []
    assert "option chain bias Bearish" in skipped[0].skip_reason


def test_duplicate_open_direction_skipped():
    s = _sig()
    selected, skipped = evaluate(
        [s], _cfg(), market_regime="Bullish", open_symbols={f"{s.symbol}:LONG"},
    )
    assert selected == []
    assert "duplicate" in skipped[0].skip_reason


def test_daily_limit_caps_selection():
    candidates = [
        _sig(symbol=f"^IDX{i}", code=f"I{i}", score=80.0 + i, risk_reward=2.5)
        for i in range(7)
    ]
    selected, skipped = evaluate(
        candidates, _cfg(max_trades_per_day=3), market_regime="Bullish", open_symbols=set(),
    )
    assert len(selected) == 3
    overflow = [s for s in skipped if "daily paper-index trade limit" in (s.skip_reason or "")]
    assert len(overflow) == 4


def test_daily_limit_already_reached():
    selected, skipped = evaluate(
        [_sig()], _cfg(max_trades_per_day=5),
        market_regime="Bullish", open_symbols=set(), trades_taken_today=5,
    )
    assert selected == []
    assert any("daily paper-index trade limit" in (s.skip_reason or "") for s in skipped)


def test_ranking_prefers_higher_automation_score():
    high = _sig(symbol="^NSEI", code="NIFTY", score=95.0, risk_reward=3.5)
    mid = _sig(symbol="^NSEBANK", code="BANKNIFTY", score=75.0, risk_reward=1.7)
    selected, _ = evaluate(
        [mid, high], _cfg(max_trades_per_day=1), market_regime="Bullish", open_symbols=set(),
    )
    assert len(selected) == 1
    assert selected[0].signal.symbol == "^NSEI"


def test_chain_bias_boosts_automation_score_for_long():
    bullish = _sig(option_chain_bias="Bullish")
    neutral = _sig(option_chain_bias="Neutral")
    cfg = _cfg()
    score_bull, _ = automation_score(bullish, "Bullish", use_chain_bias=True)
    score_neut, _ = automation_score(neutral, "Bullish", use_chain_bias=True)
    assert score_bull >= score_neut


def test_automation_score_components_in_range():
    s = _sig()
    score, comps = automation_score(s, "Bullish")
    assert 0 < score <= 100
    for key in ("score_part", "setup_part", "rr_part", "regime_part", "chain_part"):
        assert 0.0 <= comps[key] <= 1.0
