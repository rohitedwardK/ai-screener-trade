"""Deterministic tests for the agentic layer.

These tests stub out network calls (Yahoo, NSE, Ollama, RSS feeds) and
exercise the pure-Python parts of the stack:

    - VIX classification + cache
    - News RSS parser (deduping + source label extraction)
    - Consensus stitching (vote count + score formula)
    - Orchestrator deterministic stitch path (when LLM is unavailable)

The orchestrator end-to-end test patches all worker tools so a single
in-memory fixture drives the entire deep cycle without touching disk
beyond the SQLite test DB.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# VIX helpers
# ---------------------------------------------------------------------------
def test_vix_classify_bands(monkeypatch):
    from app.config import get_settings
    from app.data import vix as vix_mod

    settings = get_settings()
    monkeypatch.setattr(settings, "INDIA_VIX_HIGH", 18.0)
    monkeypatch.setattr(settings, "INDIA_VIX_PANIC", 25.0)

    assert vix_mod._classify(None) == vix_mod.BAND_UNKNOWN
    assert vix_mod._classify(0) == vix_mod.BAND_UNKNOWN
    assert vix_mod._classify(12.5) == vix_mod.BAND_NORMAL
    assert vix_mod._classify(17.99) == vix_mod.BAND_NORMAL
    assert vix_mod._classify(18.0) == vix_mod.BAND_ELEVATED
    assert vix_mod._classify(20.0) == vix_mod.BAND_ELEVATED
    assert vix_mod._classify(25.0) == vix_mod.BAND_PANIC
    assert vix_mod._classify(40.0) == vix_mod.BAND_PANIC


def test_vix_fetch_uses_cache_then_force_refreshes(monkeypatch):
    from app.data import live_quotes, vix as vix_mod

    vix_mod.reset_cache()

    calls = {"count": 0}

    def fake_fetch(symbols):
        calls["count"] += 1
        return {vix_mod.VIX_SYMBOL: 14.2}

    monkeypatch.setattr(live_quotes, "fetch_live_prices", fake_fetch)
    monkeypatch.setattr(live_quotes, "last_source", lambda: "yfinance")

    snap1 = vix_mod.fetch_vix()
    snap2 = vix_mod.fetch_vix()
    snap3 = vix_mod.fetch_vix(force=True)

    assert snap1.value == pytest.approx(14.2)
    assert snap1.band == vix_mod.BAND_NORMAL
    # Second call hit the cache.
    assert calls["count"] == 2  # snap1 + snap3 only
    assert snap2.value == snap1.value
    assert snap3.value == pytest.approx(14.2)


# ---------------------------------------------------------------------------
# News RSS parser
# ---------------------------------------------------------------------------
def test_news_rss_parses_dedupes_and_labels(monkeypatch):
    from app.data import news_rss as news_mod
    from app.config import get_settings

    news_mod.reset_cache()

    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "NEWS_RSS_FEEDS",
        "https://www.moneycontrol.com/rss/marketreports.xml,"
        "https://economictimes.indiatimes.com/markets/rssfeeds/x.cms",
    )

    fake_feeds = {
        "https://www.moneycontrol.com/rss/marketreports.xml": _StubParsed([
            {"title": "Nifty closes flat", "link": "https://mc.com/a", "published": "Mon"},
            {"title": "Bank Nifty hits 52-week high", "link": "https://mc.com/b", "published": "Mon"},
        ]),
        "https://economictimes.indiatimes.com/markets/rssfeeds/x.cms": _StubParsed([
            # Duplicate title (different source) — should still dedupe across feeds
            # because we key on (title.lower(), source) — different source -> kept.
            {"title": "Nifty closes flat", "link": "https://et.com/a", "published": "Mon"},
            {"title": "RBI holds rates", "link": "https://et.com/c", "published": "Mon"},
        ]),
    }

    def fake_parse(url):
        return fake_feeds[url]

    monkeypatch.setattr(news_mod.feedparser, "parse", fake_parse)

    rows = news_mod.fetch_headlines(limit=10, force=True)
    titles = [r.title for r in rows]
    assert "Nifty closes flat" in titles
    assert "Bank Nifty hits 52-week high" in titles
    assert "RBI holds rates" in titles
    assert len(rows) == 4

    sources = {r.source for r in rows}
    assert sources == {"moneycontrol.com", "economictimes.indiatimes.com"}


class _StubParsed:
    """Minimal feedparser-like return shape."""

    def __init__(self, entries):
        self.entries = entries
        self.bozo = False


# ---------------------------------------------------------------------------
# Consensus stitcher
# ---------------------------------------------------------------------------
def test_consensus_picks_ranking_and_score():
    from app.agents import tools as tools_mod

    fake_methods = {
        "rule_based": [
            {"symbol": "RELIANCE.NS", "confidence": 0.8, "direction": "LONG", "category": "TREND_PULLBACK", "regime": "UPTREND", "close": 2900.0, "name": "Reliance"},
            {"symbol": "INFY.NS", "confidence": 0.7, "direction": "LONG", "category": "TREND_PULLBACK", "regime": "UPTREND", "close": 1800.0, "name": "Infy"},
            {"symbol": "ITC.NS", "confidence": 0.6, "direction": "LONG", "category": "MOMENTUM", "regime": "UPTREND", "close": 460.0, "name": "ITC"},
        ],
        "rf": [
            {"symbol": "RELIANCE.NS", "confidence": 0.75, "direction": "LONG", "regime": "UPTREND", "close": 2900.0, "name": "Reliance"},
            {"symbol": "INFY.NS", "confidence": 0.65, "direction": "LONG", "regime": "UPTREND", "close": 1800.0, "name": "Infy"},
        ],
        "gbm": [
            {"symbol": "RELIANCE.NS", "confidence": 0.7, "direction": "LONG", "regime": "UPTREND", "close": 2900.0, "name": "Reliance"},
        ],
        "lstm": {"error": "model not trained"},
    }

    with patch.object(
        tools_mod,
        "rank_methods_impl",
        return_value={"methods": fake_methods, "ran_at": "now"},
    ):
        consensus = tools_mod.consensus_picks_impl(top_k=10, min_votes=2)

    assert [c["symbol"] for c in consensus[:2]] == ["RELIANCE.NS", "INFY.NS"]
    rel = consensus[0]
    assert rel["vote_count"] == 3
    assert sorted(rel["votes"]) == ["gbm", "rf", "rule_based"]
    assert rel["mean_confidence"] == pytest.approx((0.8 + 0.75 + 0.7) / 3)
    assert rel["score"] == pytest.approx(rel["mean_confidence"] * (3 / 4) * 100, rel=1e-3)

    infy = consensus[1]
    assert infy["vote_count"] == 2
    assert "lstm" not in infy["votes"]
    assert infy["score"] < rel["score"]


# ---------------------------------------------------------------------------
# Orchestrator end-to-end (deterministic path; LLM stubbed unavailable)
# ---------------------------------------------------------------------------
def test_run_deep_cycle_persists_briefing_with_llm_unavailable(monkeypatch, tmp_path):
    from app import db as db_mod
    from app.config import get_settings

    settings = get_settings()
    db_path = tmp_path / "agentic_test.db"
    monkeypatch.setattr(settings, "DB_URL", f"sqlite:///{db_path}")

    # The engine + sessionmaker were built at import-time against the original
    # DB_URL; rebuild them so this test gets an isolated DB.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    new_engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
    new_session = sessionmaker(bind=new_engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(db_mod, "engine", new_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", new_session)

    db_mod.init_db()

    from app.agents import (
        analysis_agent,
        context_agent,
        data_agent,
        informant_agent,
        llm as llm_mod,
        orchestrator,
    )
    from app.agents.tools import DISCLAIMER

    # Stub each worker so the test is hermetic.
    monkeypatch.setattr(data_agent, "run_deterministic", lambda force_full=False: {
        "refresh_stocks": {"fetched_symbols": 50, "signals_generated": 12, "errors": []},
        "refresh_indices_intraday": {"result": "ok"},
        "cache_status": {"count": 50, "symbols": []},
    })
    monkeypatch.setattr(analysis_agent, "run_deterministic", lambda top_k=10, min_votes=2: {
        "methods": {"rule_based": [{"symbol": "RELIANCE.NS", "confidence": 0.8}]},
        "consensus_picks": [
            {
                "symbol": "RELIANCE.NS",
                "name": "Reliance",
                "votes": ["rule_based", "rf"],
                "vote_count": 2,
                "mean_confidence": 0.78,
                "score": 39.0,
                "confidences": {"rule_based": 0.8, "rf": 0.76},
                "directions": {"rule_based": "LONG", "rf": "LONG"},
                "regime": "UPTREND",
                "close": 2900.0,
                "categories": ["TREND_PULLBACK"],
            }
        ],
        "screener_signals_sample": [],
    })
    monkeypatch.setattr(context_agent, "run_deterministic", lambda news_limit=8: {
        "vix": {"value": 14.5, "band": "NORMAL", "source": "yfinance"},
        "regime": {"regime": "RISK_ON", "samples_used": 8},
        "sectors": [{"sector": "Energy", "count": 4, "total_score": 18.5,
                     "mean_score": 4.6, "top_symbols": []}],
        "headlines": [
            {"title": "Nifty climbs 0.6%", "link": "https://x", "source": "moneycontrol.com",
             "published": "Mon"},
        ],
    })
    # Informant agent: return one earnings event tied to RELIANCE so we can
    # assert the orchestrator stitched `upcoming_event` onto the top pick.
    monkeypatch.setattr(informant_agent, "run_deterministic", lambda days_ahead=None: {
        "events": [
            {
                "date": "2026-05-12",
                "days_until": 4,
                "category": "EARNINGS",
                "title": "Earnings — Reliance",
                "symbols": ["RELIANCE.NS"],
                "source": "yfinance",
                "impact": "HIGH",
            }
        ],
        "watch_symbols": ["RELIANCE.NS"],
        "days_ahead": 5,
        "fetched_at": "2026-05-08T12:00:00+00:00",
    })

    # Force the LLM path to be unavailable so we exercise the deterministic
    # markdown stitcher.
    monkeypatch.setattr(llm_mod, "is_available", lambda: False)

    result = orchestrator.run_deep_cycle(triggered_by="test", use_llm=True)

    assert result.status in ("OK", "PARTIAL")
    assert result.regime == "RISK_ON"
    assert result.vix_band == "NORMAL"
    assert result.market_trend == "Bullish"
    assert len(result.top_picks) == 1
    assert result.top_picks[0]["symbol"] == "RELIANCE.NS"
    assert "RELIANCE" in result.market_summary_md
    assert DISCLAIMER in result.market_summary_md
    assert result.worker_statuses["data_agent"] == "OK"
    assert result.worker_statuses["analysis_agent"] == "OK"
    assert result.worker_statuses["context_agent"] == "OK"
    assert result.worker_statuses["informant_agent"] == "OK"
    assert result.worker_statuses["head_agent"] == "PARTIAL"
    assert result.disclaimer == DISCLAIMER

    # Informant output was stitched into both the briefing payload and the
    # top pick that matches the affected symbol.
    assert len(result.upcoming_events) == 1
    assert result.upcoming_events[0]["category"] == "EARNINGS"
    assert result.top_picks[0]["upcoming_event"]["category"] == "EARNINGS"
    assert result.top_picks[0]["upcoming_event"]["days_until"] == 4
    # And the deterministic markdown surfaces the events section.
    assert "Upcoming events" in result.market_summary_md

    # And confirm the briefing was persisted.
    from sqlalchemy import select
    from app.models.agent_orm import AgentRun, DailyBriefing

    with db_mod.session_scope() as db:
        runs = list(db.scalars(select(AgentRun)))
        briefings = list(db.scalars(select(DailyBriefing)))
        assert len(runs) == 1
        assert len(briefings) == 1
        assert briefings[0].regime == "RISK_ON"
        assert briefings[0].vix_band == "NORMAL"
        assert briefings[0].top_picks_json[0]["symbol"] == "RELIANCE.NS"
        assert len(briefings[0].upcoming_events_json or []) == 1
        assert briefings[0].upcoming_events_json[0]["title"] == "Earnings — Reliance"


# ---------------------------------------------------------------------------
# Fast-monitor trigger logic
# ---------------------------------------------------------------------------
def test_fast_tick_triggers_when_overdue_and_no_invalidations(monkeypatch):
    from app.agents import monitoring_agent as monitor_mod

    # Reset deep-cycle clock so we look "overdue".
    monkeypatch.setattr(monitor_mod, "_last_deep_cycle_at", None)
    monkeypatch.setattr(monitor_mod, "_last_movers", [])

    monkeypatch.setattr(
        monitor_mod,
        "live_movers_impl",
        lambda k=15: {"movers": [{"symbol": "X.NS"}, {"symbol": "Y.NS"}]},
    )
    monkeypatch.setattr(
        monitor_mod, "_latest_briefing_top_picks", lambda: []
    )
    monkeypatch.setattr(
        monitor_mod, "check_invalidations_impl", lambda picks: []
    )
    monkeypatch.setattr(
        monitor_mod, "refresh_verification_impl", lambda: {"signals_evaluated": 0}
    )

    triggered = {"called": 0}

    def trigger():
        triggered["called"] += 1

    result = monitor_mod.run_fast_tick(trigger_deep_cycle_callback=trigger)
    assert result.movers_count == 2
    assert result.triggered_deep_cycle is True
    assert triggered["called"] == 1
    # On the next tick movers haven't changed and no invalidations -> still
    # triggers because we didn't mark deep cycle complete in this test.
    assert "deep-cycle overdue" in result.note or "new mover" in result.note


def test_fast_tick_skips_when_recent_and_quiet(monkeypatch):
    import time as time_mod

    from app.agents import monitoring_agent as monitor_mod

    monitor_mod.mark_deep_cycle_complete()
    monkeypatch.setattr(monitor_mod, "_last_movers", ["X.NS", "Y.NS"])

    monkeypatch.setattr(
        monitor_mod,
        "live_movers_impl",
        lambda k=15: {"movers": [{"symbol": "X.NS"}, {"symbol": "Y.NS"}]},
    )
    monkeypatch.setattr(
        monitor_mod, "_latest_briefing_top_picks", lambda: []
    )
    monkeypatch.setattr(
        monitor_mod, "check_invalidations_impl", lambda picks: []
    )
    monkeypatch.setattr(
        monitor_mod, "refresh_verification_impl", lambda: {"signals_evaluated": 0}
    )

    triggered = {"called": 0}

    def trigger():
        triggered["called"] += 1

    result = monitor_mod.run_fast_tick(trigger_deep_cycle_callback=trigger)
    assert result.triggered_deep_cycle is False
    assert triggered["called"] == 0
    assert result.note == "no triggers"
    # Suppress unused import warning — keeps the file self-contained.
    _ = time_mod
