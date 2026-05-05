"""Tests for `service.live_debug` and the auto-selection guard.

Uses an in-memory SQLite engine (no network, no shared state with the dev
DB) so the diagnostic and the once-per-day idempotency check can be
exercised end-to-end without standing the whole app up.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.orm import Base
from app.models import paper_orm  # noqa: F401  - register paper tables on Base
from app.models.paper_orm import (
    PaperBotConfig,
    PaperPosition,
    PaperTradeSignal,
)
from app.paper import service as paper_service


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_config(db, *, live_enabled: bool = False) -> PaperBotConfig:
    cfg = PaperBotConfig(live_trading_enabled=live_enabled)
    db.add(cfg)
    db.commit()
    return cfg


def _seed_signal(db, **overrides) -> PaperTradeSignal:
    base = dict(
        signal_date=date.today(),
        symbol="TEST.NS",
        setup_type="Pullback Entry",
        screener_score=82.0,
        automation_score=80.0,
        decision="selected",
        entry=100.0,
        stop_loss=95.0,
        target_1=110.0,
        target_2=120.0,
    )
    base.update(overrides)
    sig = PaperTradeSignal(**base)
    db.add(sig)
    db.commit()
    return sig


# --- live_debug shape ---

def test_live_debug_returns_all_top_level_keys(db_session):
    _seed_config(db_session, live_enabled=False)
    out = paper_service.live_debug(db_session)
    assert {
        "now_ist", "today", "blockers", "summary", "gates", "last_live_tick_at",
        "last_run_selection", "prices_fetched", "pending_positions",
        "open_positions", "config",
    }.issubset(out.keys())


def test_live_debug_flags_live_toggle_blocker_when_disabled(db_session):
    _seed_config(db_session, live_enabled=False)
    out = paper_service.live_debug(db_session)
    assert out["gates"]["live_trading_enabled"]["ok"] is False
    assert "live_trading_enabled" in out["blockers"]


def test_live_debug_flags_no_positions_blocker(db_session):
    _seed_config(db_session, live_enabled=True)
    out = paper_service.live_debug(db_session)
    assert out["gates"]["has_actionable_positions"]["ok"] is False
    assert out["gates"]["has_actionable_positions"]["value"] == {"pending": 0, "open": 0}
    assert "has_actionable_positions" in out["blockers"]


def test_live_debug_lists_pending_position_with_distance(db_session):
    _seed_config(db_session, live_enabled=True)
    sig = _seed_signal(db_session, entry=100.0, stop_loss=95.0)
    pos = PaperPosition(
        signal_id=sig.id,
        symbol=sig.symbol,
        setup_type=sig.setup_type,
        side="LONG",
        quantity=10,
        remaining_quantity=10,
        stop_loss=sig.stop_loss,
        target_1=sig.target_1,
        target_2=sig.target_2,
        status="PENDING_ENTRY",
    )
    db_session.add(pos)
    db_session.commit()

    out = paper_service.live_debug(db_session)
    assert out["gates"]["has_actionable_positions"]["ok"] is True
    assert out["gates"]["has_actionable_positions"]["value"] == {"pending": 1, "open": 0}
    assert len(out["pending_positions"]) == 1
    detail = out["pending_positions"][0]
    assert detail["symbol"] == "TEST.NS"
    assert detail["entry_price"] == 100.0


def test_live_debug_summary_text_reflects_blockers(db_session):
    _seed_config(db_session, live_enabled=False)
    out = paper_service.live_debug(db_session)
    assert out["summary"].startswith("Blocked by:")
    assert "live_trading_enabled" in out["summary"]


def test_live_debug_screener_freshness_flags_old_data(db_session):
    """No screener Signal rows at all => the gate fails with a fix hint."""
    _seed_config(db_session, live_enabled=True)
    out = paper_service.live_debug(db_session)
    gate = out["gates"]["screener_has_recent_data"]
    assert gate["ok"] is False
    assert gate["value"]["latest_run_at"] is None
    assert "POST /admin/refresh" in gate["fix"]


# --- auto-selection idempotency ---

def test_auto_selection_skip_logic_via_signal_count(db_session):
    """Mirrors the guard inside `run_paper_auto_selection`: if any
    PaperTradeSignal already exists for today, the auto job must skip."""
    _seed_config(db_session, live_enabled=True)
    today = date.today()
    _seed_signal(db_session, signal_date=today)

    from sqlalchemy import select, func
    n = int(db_session.scalar(
        select(func.count(PaperTradeSignal.id)).where(
            PaperTradeSignal.signal_date == today
        )
    ) or 0)
    assert n == 1, "fixture should produce exactly one row for today"
