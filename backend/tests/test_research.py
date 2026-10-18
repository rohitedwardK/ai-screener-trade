"""Research validation, point-in-time slicing, tool boundaries and persistence."""
import json
from datetime import datetime, timezone

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agents import research
from app.data import research_repository
from app.models.agent_orm import ResearchRun

NOW = datetime(2026, 4, 30, 11, tzinfo=timezone.utc)


@pytest.fixture
def candidates(monkeypatch, uptrend_df):
    monkeypatch.setattr(research, "all_symbols", lambda: ["TEST.NS"])
    monkeypatch.setattr(research.csv_store, "load", lambda symbol: uptrend_df)
    rows, warnings = research.collect_candidates(research.ResearchRequest(), NOW)
    assert len(rows) == 1
    assert warnings == []
    return rows


@pytest.mark.parametrize("field,value", [("invalidation", None), ("entry", float("nan")),
    ("target_1", float("inf")), ("stop_loss", 101), ("target_2", 103), ("score", 101), ("entry", True)])
def test_rejects_bad_levels(field, value):
    row = dict(entry=100, stop_loss=95, target_1=105, target_2=110, invalidation=95, score=80, direction="LONG")
    assert research.valid_plan(row)
    row[field] = value
    assert not research.valid_plan(row)


def test_short_level_validation():
    row = dict(entry=100, stop_loss=105, target_1=95, target_2=90, invalidation=106, score=80, direction="SHORT")
    assert research.valid_plan(row)
    row["invalidation"] = 94
    assert not research.valid_plan(row)


def test_daily_excludes_unfinished_and_future_bars(uptrend_df):
    before_close = datetime(2026, 4, 30, 9, tzinfo=timezone.utc)
    frame = research.prepare_frame(uptrend_df, before_close, False)
    assert frame.index[-1].date().isoformat() == "2026-04-29"
    altered = uptrend_df.copy()
    altered.iloc[-1] = 999999
    pd.testing.assert_frame_equal(frame, research.prepare_frame(altered, before_close, False))


def test_intraday_excludes_incomplete_and_missing_bars():
    df = pd.DataFrame({k: [100.] * 7 for k in ("open", "high", "low", "close", "volume")},
                      index=pd.date_range("2026-04-30 09:15", periods=7, freq="5min"))
    now = datetime(2026, 4, 30, 4, 16, tzinfo=timezone.utc)
    frame = research.prepare_frame(df, now, True)
    assert len(frame) == 2
    assert frame.iloc[-1]["volume"] == 300
    frame = research.prepare_frame(df.drop(df.index[1]), now, True)
    assert len(frame) == 1
    assert frame.index[0].minute == 30


def test_stale_data_abstains(monkeypatch, uptrend_df):
    monkeypatch.setattr(research, "all_symbols", lambda: ["TEST.NS"])
    monkeypatch.setattr(research.csv_store, "load", lambda _: uptrend_df)
    result = research.run_research(research.ResearchRequest(), {}, now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert result.ideas == []
    assert any("too old" in w for w in result.warnings)


def test_agent_inspects_before_selecting(monkeypatch, candidates):
    key = candidates[0]["id"]
    replies = iter([{"tool": "inspect_candidate", "candidate_id": key}, {"tool": "finish", "selected_ids": [key]}])
    monkeypatch.setattr(research.llm, "chat", lambda *a, **kw: json.dumps(next(replies)))
    result = research.run_research(research.ResearchRequest(), {}, now=NOW)
    assert result.mode == "agent"
    assert result.ideas[0].id == key
    assert [s["tool"] for s in result.trace] == ["get_candidates", "inspect_candidate", "finish"]
    assert result.ideas[0].invalidation < result.ideas[0].entry
    assert result.disclaimer == research.DISCLAIMER


@pytest.mark.parametrize("reply", ['not JSON', '{"tool":"place_order"}',
    '{"tool":"finish","selected_ids":["fabricated"]}'])
def test_invalid_agent_action_uses_labelled_fallback(monkeypatch, candidates, reply):
    monkeypatch.setattr(research.llm, "chat", lambda *a, **kw: reply)
    result = research.run_research(research.ResearchRequest(), {}, now=NOW)
    assert result.mode == "fallback"
    assert result.ideas[0].id == candidates[0]["id"]


def test_agent_can_abstain(monkeypatch, candidates):
    monkeypatch.setattr(research.llm, "chat", lambda *a, **kw: '{"tool":"finish","selected_ids":[]}')
    result = research.run_research(research.ResearchRequest(), {}, now=NOW)
    assert result.mode == "agent"
    assert result.ideas == []


def test_unavailable_llm_preserves_evidence(monkeypatch, candidates):
    def unavailable(*a, **kw):
        raise research.llm.AgenticUnavailable("offline")
    monkeypatch.setattr(research.llm, "chat", unavailable)
    result = research.run_research(research.ResearchRequest(), {}, now=NOW)
    assert result.mode == "fallback"
    assert result.ideas[0].evidence == candidates[0]["evidence"]


def test_stock_intraday_does_not_use_daily_data():
    result = research.run_research(research.ResearchRequest(horizon="intraday"), {}, now=NOW)
    assert result.ideas == []
    assert "intraday cache" in result.warnings[0]


def test_index_swing_recomputes_spot_plans(monkeypatch, uptrend_df):
    monkeypatch.setattr(research.index_csv_store, "load", lambda *a, **kw: uptrend_df)
    result = research.run_research(research.ResearchRequest(asset_class="index", use_llm=False), {}, now=NOW)
    assert len(result.ideas) == 3
    assert {i.symbol for i in result.ideas} == {i.symbol for i in research.INDICES}
    assert all(research.valid_plan(i.model_dump()) for i in result.ideas)
    assert all("Spot-index" in " ".join(i.counter_evidence) for i in result.ideas)


def test_stale_index_research_refreshes_once(monkeypatch, uptrend_df):
    from app.core import index_pipeline

    stale = uptrend_df.copy()
    stale.index = stale.index - pd.Timedelta(days=30)
    calls = {"refresh": 0, "load": 0}

    def load(*args, **kwargs):
        calls["load"] += 1
        return stale if calls["load"] <= len(research.INDICES) else uptrend_df

    def refresh(force_full=False):
        calls["refresh"] += 1
        return type("Result", (), {"fetched_symbols": 3, "errors": []})()

    monkeypatch.setattr(research.index_csv_store, "load", load)
    monkeypatch.setattr(index_pipeline, "run_full_refresh", refresh)
    result = research.run_research(research.ResearchRequest(asset_class="index", use_llm=False), {}, now=NOW)
    assert calls["refresh"] == 1
    assert len(result.ideas) == 3
    assert any("Index daily cache refresh attempted" in w for w in result.warnings)


def test_invalid_completed_bar_is_rejected(uptrend_df):
    damaged = uptrend_df.copy()
    damaged.iloc[-1, damaged.columns.get_loc("close")] = float("inf")
    with pytest.raises(ValueError, match="Non-finite"):
        research.prepare_frame(damaged, NOW, False)


def test_repeated_tool_call_stops_with_fallback(monkeypatch, candidates):
    calls = []
    def repeat(*a, **kw):
        calls.append(kw)
        return json.dumps({"tool": "inspect_candidate", "candidate_id": candidates[0]["id"]})
    monkeypatch.setattr(research.llm, "chat", repeat)
    result = research.run_research(research.ResearchRequest(), {}, now=NOW)
    assert result.mode == "fallback"
    assert len(calls) == 2
    assert all(0 < c["timeout_sec"] <= 8 for c in calls)


def test_history_roundtrip_and_api_validation(monkeypatch, candidates):
    from app.api import agents
    from app.db import get_db
    result = research.run_research(research.ResearchRequest(use_llm=False), {}, now=NOW)
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    ResearchRun.__table__.create(engine)
    with Session(engine) as db:
        app = FastAPI()
        app.include_router(agents.router)
        app.dependency_overrides[get_db] = lambda: db
        monkeypatch.setattr(agents, "run_research", lambda *args: result)
        monkeypatch.setattr(research_repository, "latest_context", lambda db: {})
        with TestClient(app) as client:
            saved = client.post("/v1/agents/research", json={"use_llm": False})
            assert saved.status_code == 200
            rows = client.get("/v1/agents/research/history").json()
            assert rows == [saved.json()]
            assert client.get("/v1/agents/research/history?asset_class=index").json() == []
            assert client.post("/v1/agents/research", json={"asset_class": "commodity"}).status_code == 422
            assert client.post("/v1/agents/research", json={"horizon": "unknown"}).status_code == 422
            assert client.post("/v1/agents/research", json={"symbol": "../../secret"}).status_code == 422
            assert "/v1/agents/research" in client.get("/openapi.json").json()["paths"]
    engine.dispose()
