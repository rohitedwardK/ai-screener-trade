"""Unit tests for the setup verifier (resolve ACTIVE -> TARGET_HIT/STOPPED/EXPIRED)."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import verifier
from app.models.orm import Base, ScalpSetup, SwingSetup


@pytest.fixture
def db():
    """Fresh in-memory SQLite for this module."""
    url = "sqlite:///:memory:"
    engine = create_engine(url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, future=True)
    sess = Session()
    yield sess
    sess.close()
    engine.dispose()


def _make_scalp(direction: str, *, t2: float, invalidation: float, expires_in_min: int = 20) -> ScalpSetup:
    now = datetime.utcnow()
    return ScalpSetup(
        symbol="^NSEI", category="RANGE_BOUNCE_TEST", direction=direction,
        status="ACTIVE", score=80.0, reasons=["test"],
        spot_entry=100.0, spot_stop=invalidation if direction == "LONG" else 102.0,
        spot_t1=(t2 + 100.0) / 2.0, spot_t2=t2,
        spot_invalidation=invalidation,
        created_at=now, expires_at=now + timedelta(minutes=expires_in_min),
    )


def test_long_target_hit(db):
    row = _make_scalp("LONG", t2=101.0, invalidation=99.7)
    db.add(row); db.commit()
    sc, _ = verifier.verify(db, {"^NSEI": 101.5}, now=datetime.utcnow())
    db.commit()
    assert sc == 1
    assert row.status == "TARGET_HIT"
    assert row.resolved_price == 101.5


def test_long_stopped(db):
    row = _make_scalp("LONG", t2=101.0, invalidation=99.7)
    db.add(row); db.commit()
    sc, _ = verifier.verify(db, {"^NSEI": 99.5}, now=datetime.utcnow())
    db.commit()
    assert sc == 1
    assert row.status == "STOPPED"


def test_short_target_hit(db):
    row = _make_scalp("SHORT", t2=99.0, invalidation=100.5)
    db.add(row); db.commit()
    sc, _ = verifier.verify(db, {"^NSEI": 98.8}, now=datetime.utcnow())
    db.commit()
    assert sc == 1
    assert row.status == "TARGET_HIT"


def test_expired_when_past_expires_at(db):
    row = _make_scalp("LONG", t2=200.0, invalidation=50.0, expires_in_min=-1)
    db.add(row); db.commit()
    sc, _ = verifier.verify(db, {"^NSEI": 100.0}, now=datetime.utcnow())
    db.commit()
    assert sc == 1
    assert row.status == "EXPIRED"


def test_active_remains_when_in_band(db):
    row = _make_scalp("LONG", t2=101.0, invalidation=99.7)
    db.add(row); db.commit()
    sc, _ = verifier.verify(db, {"^NSEI": 100.4}, now=datetime.utcnow())
    db.commit()
    assert sc == 0
    assert row.status == "ACTIVE"
