"""Cold-cache table for the FeatureStore (L1.5).

One row per (symbol, as_of_date, timeframe, feature_set_version). Primary
key is the composite of those four — this is what makes the store naturally
a snapshot store: backtests can query "the feature vector for RELIANCE.NS
on 2025-03-15" and get back exactly what the system would have seen that
day, without re-deriving it from CSV.

Why a JSON blob instead of one column per feature
-------------------------------------------------
* The feature schema evolves. Pinning each feature to a column would force
  an ALTER TABLE every time `vectors.py` grows a field. The auto-version
  hash (`feature_set_version`) handles schema drift cleanly: cached rows
  with stale versions are simply skipped on read.
* Compressed JSON in SQLite is ~80 bytes per row for the current schema —
  smaller than the per-column overhead would be.
* All numeric work happens in-memory in `FeatureVector`; the DB layer is
  pure cache, never the source of truth for math.

Index strategy: the composite PK already covers the common access pattern
(`get(symbol, as_of_date)`). A secondary index on `(symbol, computed_at)`
lets the AuditAgent (PR2+) prune stale rows efficiently.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Index, PrimaryKeyConstraint

from .orm import Base


class FeatureRow(Base):
    """One persisted FeatureVector. Use the FeatureStore — never write here directly."""

    __tablename__ = "features"

    symbol = Column(String, nullable=False)
    as_of_date = Column(String, nullable=False)
    timeframe = Column(String, nullable=False, default="EOD")
    feature_set_version = Column(String, nullable=False)

    payload_json = Column(JSON, nullable=False)
    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    bytes_size = Column(Integer, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint(
            "symbol",
            "as_of_date",
            "timeframe",
            "feature_set_version",
            name="pk_features",
        ),
        Index("ix_features_symbol_computedat", "symbol", "computed_at"),
        Index("ix_features_version", "feature_set_version"),
    )


__all__ = ["FeatureRow"]
