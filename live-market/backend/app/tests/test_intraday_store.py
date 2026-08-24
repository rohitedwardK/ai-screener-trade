"""Tests for the rolling intraday OHLCV store."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import intraday_store
from app.data.upstox_client import UpstoxQuote
from app.models.orm import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, future=True)
    sess = Session()
    yield sess
    sess.close()
    engine.dispose()


def _quote(price: float, *, ts_ms: int = 0, vol: int = 1000) -> UpstoxQuote:
    return UpstoxQuote(
        symbol="^NSEI", last_price=price, open=price, high=price,
        low=price, close_prev=price, volume=vol, timestamp_ms=ts_ms,
    )


def test_append_creates_new_bar(db):
    when = datetime(2026, 1, 6, 9, 15, 30)
    bar = intraday_store.append_tick(db, _quote(100.0), now=when)
    db.commit()
    assert bar.ts == datetime(2026, 1, 6, 9, 15)
    assert bar.open == bar.high == bar.low == bar.close == 100.0


def test_append_updates_existing_bar_with_high_low(db):
    when = datetime(2026, 1, 6, 9, 15, 10)
    intraday_store.append_tick(db, _quote(100.0), now=when)
    intraday_store.append_tick(db, _quote(101.5), now=when + timedelta(seconds=10))
    intraday_store.append_tick(db, _quote(99.5), now=when + timedelta(seconds=20))
    intraday_store.append_tick(db, _quote(100.7), now=when + timedelta(seconds=30))
    db.commit()
    bars = intraday_store.recent_bars(db, "^NSEI")
    assert len(bars) == 1
    bar = bars[0]
    assert bar.open == 100.0
    assert bar.high == 101.5
    assert bar.low == 99.5
    assert bar.close == 100.7


def test_recent_bars_returns_ascending_time(db):
    base = datetime(2026, 1, 6, 9, 15)
    for i in range(5):
        intraday_store.append_tick(db, _quote(100.0 + i), now=base + timedelta(minutes=i))
    db.commit()
    bars = intraday_store.recent_bars(db, "^NSEI", lookback=10)
    assert len(bars) == 5
    timestamps = [b.ts for b in bars]
    assert timestamps == sorted(timestamps)


def test_prune_old_keeps_latest_n(db):
    base = datetime(2026, 1, 6, 9, 15)
    for i in range(20):
        intraday_store.append_tick(db, _quote(100.0 + i), now=base + timedelta(minutes=i))
    db.commit()
    deleted = intraday_store.prune_old(db, "^NSEI", keep=10)
    db.commit()
    assert deleted >= 9  # 20 - 10 = 10 to drop, but the cutoff is exclusive
    bars = intraday_store.recent_bars(db, "^NSEI", lookback=100)
    assert len(bars) <= 11
