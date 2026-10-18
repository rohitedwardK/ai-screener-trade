"""Tests for the LLMContextBuilder.

These tests are the type-boundary contract every PR going forward must
respect: only `HeadAgentContext` reaches the LLM, and only the documented
fields populate it.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Schema enforcement
# ---------------------------------------------------------------------------
def test_build_basic_context_round_trip():
    from app.agents.llm_context_builder import (
        HeadAgentContext,
        TopPickContext,
        build_head_agent_context,
    )

    ctx = build_head_agent_context(
        regime="RISK_ON",
        market_trend="Bullish",
        vix_value=14.2,
        vix_band="NORMAL",
        top_picks=[
            {
                "symbol": "RELIANCE.NS",
                "name": "Reliance",
                "vote_count": 3,
                "votes": ["rule_based", "rf", "lstm"],
                "mean_confidence": 0.81,
                "score": 60.75,
                "regime": "UPTREND",
                "close": 2900.0,
                "categories": ["TREND_PULLBACK"],
                "reasons": [
                    "RSI oversold bounce",
                    "EMA20 > EMA50",
                    "Pullback into 50EMA",
                ],
            }
        ],
        sector_rotation=[{"sector": "Energy", "mean_score": 4.6}],
        headlines=[{"title": "Nifty up", "source": "moneycontrol.com"}],
        upcoming_events=[{"category": "EARNINGS", "title": "X earnings"}],
        counters={"events_count": 1},
    )

    assert isinstance(ctx, HeadAgentContext)
    assert ctx.regime == "RISK_ON"
    assert ctx.vix_band == "NORMAL"
    assert len(ctx.top_picks) == 1
    pick = ctx.top_picks[0]
    assert isinstance(pick, TopPickContext)
    assert pick.symbol == "RELIANCE.NS"
    assert pick.confidence == pytest.approx(0.81)
    assert pick.score == pytest.approx(60.75)
    assert pick.vote_count == 3
    assert pick.methods == ["rule_based", "rf", "lstm"]
    assert pick.category == "TREND_PULLBACK"
    assert "RSI oversold bounce" in pick.reasons
    assert ctx.disclaimer.endswith("Not financial advice.")


def test_top_picks_truncated_to_max():
    from app.agents.llm_context_builder import ContextCaps, build_head_agent_context

    raw = [{"symbol": f"S{i}.NS", "vote_count": 1, "score": 10} for i in range(20)]
    ctx = build_head_agent_context(
        regime="UNKNOWN", market_trend=None, vix_value=None, vix_band=None,
        top_picks=raw, caps=ContextCaps(max_picks=5),
    )
    assert len(ctx.top_picks) == 5


def test_reasons_truncated_per_pick():
    from app.agents.llm_context_builder import ContextCaps, build_head_agent_context

    raw = [{
        "symbol": "X.NS", "vote_count": 1, "score": 10,
        "reasons": [f"reason_{i}" for i in range(10)],
    }]
    ctx = build_head_agent_context(
        regime="UNKNOWN", market_trend=None, vix_value=None, vix_band=None,
        top_picks=raw, caps=ContextCaps(max_reasons_per_pick=3),
    )
    assert len(ctx.top_picks[0].reasons) == 3


# ---------------------------------------------------------------------------
# Forbidden-field guard
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_field", [
    "candles", "ohlcv", "df", "raw_news", "news_body",
    "feature_vector", "feature_vectors", "ml_input_matrix",
    "lstm_window", "indicator_series", "csv_path",
])
def test_raw_fields_in_top_picks_raise(bad_field):
    from app.agents.llm_context_builder import (
        ContextBuildError,
        build_head_agent_context,
    )

    with pytest.raises(ContextBuildError) as exc:
        build_head_agent_context(
            regime="X", market_trend=None, vix_value=None, vix_band=None,
            top_picks=[{"symbol": "S", bad_field: "leaked"}],
        )
    assert bad_field in str(exc.value)


def test_nested_raw_fields_also_blocked():
    """Nested dict carrying a forbidden key should also raise."""
    from app.agents.llm_context_builder import (
        ContextBuildError,
        build_head_agent_context,
    )

    with pytest.raises(ContextBuildError):
        build_head_agent_context(
            regime="X", market_trend=None, vix_value=None, vix_band=None,
            top_picks=[{"symbol": "S", "extra": {"feature_vector": [1, 2]}}],
        )


def test_raw_fields_in_headlines_raise():
    from app.agents.llm_context_builder import (
        ContextBuildError,
        build_head_agent_context,
    )

    with pytest.raises(ContextBuildError):
        build_head_agent_context(
            regime="X", market_trend=None, vix_value=None, vix_band=None,
            top_picks=[],
            headlines=[{"title": "ok", "news_body": "very long article..."}],
        )


# ---------------------------------------------------------------------------
# Token budget
# ---------------------------------------------------------------------------
def test_serialize_under_budget_returns_full_payload():
    from app.agents.llm_context_builder import (
        build_head_agent_context,
        serialize_context,
    )

    ctx = build_head_agent_context(
        regime="RISK_ON", market_trend="Bullish",
        vix_value=14.2, vix_band="NORMAL",
        top_picks=[{"symbol": "X.NS", "vote_count": 1, "score": 10}],
    )
    s = serialize_context(ctx, max_tokens=10_000)
    assert "RISK_ON" in s
    assert "X.NS" in s
    assert "method_outputs" not in s
    assert "consensus_picks" not in s


def test_serialize_over_budget_trims_payload(monkeypatch):
    from app.agents.llm_context_builder import (
        build_head_agent_context,
        serialize_context,
    )

    big_picks = [
        {"symbol": f"S{i}.NS", "vote_count": 1, "score": 10,
         "reasons": [f"reason_{j} " * 20 for j in range(5)]}
        for i in range(8)
    ]
    big_headlines = [{"title": "x" * 500} for _ in range(20)]
    big_events = [{"title": "e" * 500, "category": "MACRO"} for _ in range(10)]

    from app.agents.llm_context_builder import ContextCaps

    ctx = build_head_agent_context(
        regime="RISK_ON", market_trend=None, vix_value=None, vix_band=None,
        top_picks=big_picks,
        headlines=big_headlines,
        upcoming_events=big_events,
        caps=ContextCaps(max_picks=8, max_headlines=20, max_events=10),
    )

    full = serialize_context(ctx, max_tokens=10_000_000)
    trimmed = serialize_context(ctx, max_tokens=200)

    assert len(trimmed) < len(full)
    # Critical fields survive even after aggressive trimming.
    assert "RISK_ON" in trimmed


def test_safe_float_handles_garbage_inputs():
    from app.agents.llm_context_builder import build_head_agent_context

    ctx = build_head_agent_context(
        regime="X", market_trend=None, vix_value=None, vix_band=None,
        top_picks=[{"symbol": "S.NS", "close": "not_a_number", "vote_count": 1, "score": 10}],
    )
    assert ctx.top_picks[0].close is None
