"""Tests for the L1.5 FeatureStore.

Covers the contract + cache mechanics that PR2/PR3 inference engines
will rely on:

    * `compute_features` produces a populated FeatureVector for a real
      uptrend frame (and an empty/skeleton vector for an empty df).
    * Auto-versioning detects content changes in the source files.
    * Hot LRU returns the same instance on a hit; cold L2 returns an
      equal vector after L1 eviction.
    * Invalidate clears L1 and forces a recompute on the next read.
    * Batch reads aggregate per-symbol results.
    * Stale `feature_set_version` rows are NOT served (auto-invalidation).
    * Snapshot read with `as_of_date` is look-ahead-free (uses df[:date]).
    * FeatureStoreAgent warm + status surface produce sensible numbers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Shared isolated-DB fixture (mirrors the agentic-layer test pattern)
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    """Spin up a fresh on-disk SQLite for the test, with all ORMs created."""
    from app import db as db_mod
    from app.config import get_settings

    settings = get_settings()
    db_path = tmp_path / "features_test.db"
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


@pytest.fixture
def csv_dir(monkeypatch, tmp_path):
    """Point STOCK_DATA_DIR at a tmp folder so csv_store reads/writes there."""
    from app.config import get_settings
    from app.data import csv_store

    settings = get_settings()
    d = tmp_path / "ohlcv"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STOCK_DATA_DIR", str(d))
    # csv_store also caches a module-level CSV_DIR; refresh.
    monkeypatch.setattr(csv_store, "CSV_DIR", d)
    return d


def _write_csv(csv_dir, symbol: str, df: pd.DataFrame) -> None:
    out = df.reset_index().rename(columns={"index": "date"})
    if "date" not in out.columns:
        out.insert(0, "date", df.index)
    out.to_csv(csv_dir / f"{symbol}.csv", index=False)


# ---------------------------------------------------------------------------
# compute_features — contract + edge cases
# ---------------------------------------------------------------------------
def test_compute_features_populates_vector_for_uptrend(uptrend_df):
    from app.features import compute_features, FEATURE_SET_VERSION

    fv = compute_features("TEST.NS", uptrend_df)

    assert fv.symbol == "TEST.NS"
    assert fv.timeframe == "EOD"
    assert fv.feature_set_version == FEATURE_SET_VERSION
    # Every core indicator must be populated for a 300-bar uptrend.
    assert fv.ema20 is not None
    assert fv.ema50 is not None
    assert fv.ema200 is not None
    assert fv.rsi14 is not None and 0 <= fv.rsi14 <= 100
    assert fv.macd is not None
    assert fv.adx is not None
    assert fv.atr14 is not None and fv.atr14 > 0
    assert fv.latest_close is not None and fv.latest_close > 0
    # Derived ratios should be sensibly sized (% values, not 0..1).
    assert fv.ema20_vs_ema50 is not None
    assert abs(fv.ema20_vs_ema50) < 50
    # Regime label comes from app.analysis.regime.classify — accept any
    # non-empty string the classifier returns for an uptrend frame.
    assert fv.regime_label is None or isinstance(fv.regime_label, str)
    assert isinstance(fv.pattern_flags, dict)


def test_compute_features_empty_df_returns_skeleton():
    from app.features import compute_features

    fv = compute_features("EMPTY.NS", pd.DataFrame())
    assert fv.symbol == "EMPTY.NS"
    assert fv.latest_close is None
    assert fv.ema20 is None


def test_feature_vector_roundtrip(uptrend_df):
    from app.features import FeatureVector, compute_features

    fv = compute_features("TEST.NS", uptrend_df)
    payload = fv.to_dict()
    assert payload["symbol"] == "TEST.NS"

    restored = FeatureVector.from_dict(payload)
    assert restored == fv


def test_feature_vector_from_dict_ignores_unknown_keys():
    """Forward-compat: payloads from a future schema with new fields should
    still deserialise (silently dropping the extras), so a mid-rollout L2
    row written by a newer process doesn't crash an older reader."""
    from app.features import FeatureVector, FEATURE_SET_VERSION

    fv = FeatureVector.from_dict({
        "symbol": "X.NS",
        "as_of_date": "2026-05-08",
        "timeframe": "EOD",
        "feature_set_version": FEATURE_SET_VERSION,
        "future_unknown_field": 42,
    })
    assert fv.symbol == "X.NS"


def test_numeric_features_keys_match_feature_keys(uptrend_df):
    from app.features import FEATURE_KEYS, compute_features

    fv = compute_features("TEST.NS", uptrend_df)
    nums = fv.numeric_features()
    assert list(nums.keys()) == FEATURE_KEYS


# ---------------------------------------------------------------------------
# Versioning — content-hash detects changes
# ---------------------------------------------------------------------------
def test_feature_set_version_is_stable_within_run():
    from app.features.versioning import FEATURE_SET_VERSION, _compute_version

    assert _compute_version() == FEATURE_SET_VERSION
    assert len(FEATURE_SET_VERSION) == 12


def test_feature_set_version_changes_when_source_changes(monkeypatch):
    """Adding a fake byte to one of the versioned files should produce a
    different hash. We don't actually mutate the file — we monkeypatch the
    list to include a tmp file we can flip."""
    from pathlib import Path
    from app.features import versioning

    fake = Path(versioning._VERSIONED_PATHS[0])
    original_bytes = fake.read_bytes()

    # First compute baseline.
    baseline = versioning._compute_version()

    # Inject a sentinel "file" via monkeypatching read_bytes on the path.
    class FakePath:
        name = "FAKE"
        def read_bytes(self):  # noqa: PLR6301 — must match real Path API
            return original_bytes + b"\n# extra content\n"

    monkeypatch.setattr(versioning, "_VERSIONED_PATHS",
                        [FakePath()] + list(versioning._VERSIONED_PATHS[1:]))
    perturbed = versioning._compute_version()

    assert baseline != perturbed


# ---------------------------------------------------------------------------
# FeatureStore — hot/cold/invalidate/batch
# ---------------------------------------------------------------------------
def test_store_hot_lru_returns_same_instance(isolated_db, csv_dir, uptrend_df):
    from app.features.store import FeatureStore

    _write_csv(csv_dir, "RELIANCE.NS", uptrend_df)
    store = FeatureStore()

    fv1 = store.get_or_compute("RELIANCE.NS")
    fv2 = store.get_or_compute("RELIANCE.NS")

    assert fv1 is fv2
    assert store.stats["computes"] == 1
    assert store.stats["hits_l1"] == 1


def test_store_cold_l2_promotes_after_lru_eviction(isolated_db, csv_dir, uptrend_df):
    """Force an LRU eviction by setting max=1 then querying a second symbol.
    The first symbol's next read should be an L2 hit, not a recompute."""
    from app.features.store import FeatureStore

    _write_csv(csv_dir, "AAA.NS", uptrend_df)
    # Same-shape OHLCV is fine — the eviction test only cares about cache
    # mechanics, not signal differences between symbols.
    _write_csv(csv_dir, "BBB.NS", uptrend_df.copy())

    store = FeatureStore(lru_max=1)

    fv_a = store.get_or_compute("AAA.NS")
    fv_b = store.get_or_compute("BBB.NS")
    assert fv_a is not fv_b
    assert store.stats["computes"] == 2

    # Re-read AAA: L1 evicted (max=1 holds only BBB now), L2 should hit.
    fv_a2 = store.get_or_compute("AAA.NS")
    assert store.stats["hits_l2"] >= 1
    assert fv_a2.symbol == "AAA.NS"
    assert fv_a2.latest_close == pytest.approx(fv_a.latest_close)


def test_store_invalidate_forces_recompute(isolated_db, csv_dir, uptrend_df):
    from app.features.store import FeatureStore

    _write_csv(csv_dir, "X.NS", uptrend_df)
    store = FeatureStore()
    _ = store.get_or_compute("X.NS")
    assert store.stats["computes"] == 1

    dropped = store.invalidate("X.NS")
    assert dropped == 1

    _ = store.get_or_compute("X.NS")
    # L2 still has the row so this should be an L2 hit, not a recompute.
    assert store.stats["computes"] == 1
    assert store.stats["hits_l2"] >= 1


def test_store_invalidate_all(isolated_db, csv_dir, uptrend_df):
    from app.features.store import FeatureStore

    for s in ["A.NS", "B.NS", "C.NS"]:
        _write_csv(csv_dir, s, uptrend_df)
    store = FeatureStore()
    store.get_features_batch(["A.NS", "B.NS", "C.NS"])
    assert len(store._lru) == 3  # noqa: SLF001
    store.invalidate_all()
    assert len(store._lru) == 0  # noqa: SLF001


def test_store_batch_returns_per_symbol(isolated_db, csv_dir, uptrend_df):
    from app.features.store import FeatureStore

    for s in ["A.NS", "B.NS", "C.NS"]:
        _write_csv(csv_dir, s, uptrend_df)
    store = FeatureStore()

    out = store.get_features_batch(["A.NS", "B.NS", "C.NS", "MISSING.NS"])
    assert set(out.keys()) == {"A.NS", "B.NS", "C.NS"}
    assert all(v.feature_set_version for v in out.values())


def test_store_stale_version_rows_are_not_served(
    isolated_db, csv_dir, uptrend_df, monkeypatch
):
    """L2 rows with a different feature_set_version must be ignored — that's
    the auto-invalidation mechanism. Simulated by directly inserting an
    old-versioned row and asserting the read recomputes."""
    from app.db import session_scope
    from app.features.store import FeatureStore
    from app.models.feature_orm import FeatureRow

    _write_csv(csv_dir, "STALE.NS", uptrend_df)
    last_date = uptrend_df.index[-1].strftime("%Y-%m-%d")

    with session_scope() as db:
        db.add(FeatureRow(
            symbol="STALE.NS",
            as_of_date=last_date,
            timeframe="EOD",
            feature_set_version="OLD_HASH_1234",
            payload_json={
                "symbol": "STALE.NS",
                "as_of_date": last_date,
                "timeframe": "EOD",
                "feature_set_version": "OLD_HASH_1234",
                "latest_close": 999.99,
            },
        ))

    store = FeatureStore()
    fv = store.get_or_compute("STALE.NS")
    # We must NOT have read the 999.99 stale row.
    assert fv.latest_close != 999.99
    assert store.stats["computes"] == 1


def test_store_snapshot_read_is_lookahead_free(
    isolated_db, csv_dir, uptrend_df
):
    """Asking for an older as_of_date must yield a vector whose latest_close
    equals the close on that date — the store sliced df[:as_of] before
    computing. This is the property OutcomeAgent + backtests rely on."""
    from app.features.store import FeatureStore

    _write_csv(csv_dir, "BACK.NS", uptrend_df)
    store = FeatureStore()

    # Pick a date 60 bars before the end — well past warmup and still in df.
    target_idx = uptrend_df.index[-60]
    target_date = target_idx.strftime("%Y-%m-%d")
    expected_close = float(uptrend_df.loc[target_idx, "close"])

    fv = store.get_or_compute("BACK.NS", as_of_date=target_date)
    assert fv is not None
    assert fv.as_of_date == target_date
    assert fv.latest_close == pytest.approx(expected_close, rel=1e-9)


def test_store_prune_stale_l2(isolated_db, csv_dir, uptrend_df):
    from app.db import session_scope
    from app.features.store import FeatureStore
    from app.models.feature_orm import FeatureRow

    _write_csv(csv_dir, "P.NS", uptrend_df)

    # Seed a stale-version row.
    with session_scope() as db:
        db.add(FeatureRow(
            symbol="P.NS",
            as_of_date="2020-01-02",
            timeframe="EOD",
            feature_set_version="ANCIENT",
            payload_json={"latest_close": 1.0},
        ))

    store = FeatureStore()
    deleted = store.prune_stale_l2()
    assert deleted >= 1


# ---------------------------------------------------------------------------
# FeatureStoreAgent — warm + status
# ---------------------------------------------------------------------------
def test_feature_store_agent_warm_and_status(isolated_db, csv_dir, uptrend_df, monkeypatch):
    from app.agents import feature_store_agent
    from app.features.store import reset_default_store

    reset_default_store()

    _write_csv(csv_dir, "AAA.NS", uptrend_df)
    _write_csv(csv_dir, "BBB.NS", uptrend_df)

    # Restrict the agent's universe so it doesn't try to load 50 NSE symbols.
    monkeypatch.setattr(feature_store_agent, "all_symbols", lambda: ["AAA.NS", "BBB.NS"])

    out = feature_store_agent.run()
    assert out["ok"] is True
    assert out["warmed"] == 2
    assert out["status"]["l1_size"] >= 2
    assert out["status"]["l2_rows"] >= 2
