"""Tests for the cross-cutting EventEmitter (PR1 scaffold).

Severity-aware routing, dedup, and HALT escalation land in PR3 — these
tests assert the basic publish + persist + subscribe contract that PR3
will build on without breaking publishers wired in PR1.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    from app import db as db_mod
    from app.config import get_settings

    settings = get_settings()
    db_path = tmp_path / "events_test.db"
    monkeypatch.setattr(settings, "DB_URL", f"sqlite:///{db_path}")

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
    yield db_mod
    new_engine.dispose()


def test_emit_persists_event(isolated_db):
    from app.agents.event_emitter import EventEmitter
    from app.models.event_orm import AgentEvent, SEVERITY_INFO

    e = EventEmitter()
    rec = e.emit(
        source="test_src",
        event_type="unit_test",
        message="hello",
        symbol="X.NS",
        payload={"k": 1},
    )
    assert rec["severity"] == SEVERITY_INFO
    assert rec["emitted_at"]

    with isolated_db.session_scope() as db:
        rows = list(db.scalars(select(AgentEvent)))
        # Read attributes inside the session (post-commit objects are
        # expired; touching them after `__exit__` raises DetachedInstanceError).
        assert len(rows) == 1
        assert rows[0].source == "test_src"
        assert rows[0].symbol == "X.NS"
        assert rows[0].payload_json == {"k": 1}


def test_subscriber_receives_event(isolated_db):
    from app.agents.event_emitter import EventEmitter

    e = EventEmitter()
    received = []
    e.subscribe(lambda r: received.append(r))

    e.emit(source="s", event_type="t")
    assert len(received) == 1
    assert received[0]["source"] == "s"


def test_subscriber_failure_does_not_block_others(isolated_db):
    from app.agents.event_emitter import EventEmitter

    e = EventEmitter()
    others_called = {"n": 0}

    def bad(_):
        raise RuntimeError("boom")

    def good(_):
        others_called["n"] += 1

    e.subscribe(bad)
    e.subscribe(good)
    e.emit(source="s", event_type="t")

    assert e.counts["subscriber_errors"] == 1
    assert others_called["n"] == 1


def test_severity_helpers(isolated_db):
    from app.agents.event_emitter import EventEmitter
    from app.models.event_orm import (
        SEVERITY_CRITICAL,
        SEVERITY_HALT,
        SEVERITY_WARNING,
    )

    e = EventEmitter()
    assert e.warning("a", "b")["severity"] == SEVERITY_WARNING
    assert e.critical("a", "b")["severity"] == SEVERITY_CRITICAL
    assert e.halt("a", "b")["severity"] == SEVERITY_HALT


def test_unsubscribe_and_clear(isolated_db):
    from app.agents.event_emitter import EventEmitter

    e = EventEmitter()
    received = []
    fn = e.subscribe(lambda r: received.append(r))

    assert e.unsubscribe(fn) is True
    assert e.unsubscribe(fn) is False

    e.subscribe(lambda r: received.append(r))
    e.clear_subscribers()
    e.emit(source="x", event_type="y")
    assert received == []


def test_singleton_reset(isolated_db):
    from app.agents.event_emitter import get_emitter, reset_emitter

    e1 = get_emitter()
    e2 = get_emitter()
    assert e1 is e2

    reset_emitter()
    e3 = get_emitter()
    assert e3 is not e1
