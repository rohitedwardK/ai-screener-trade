"""SQLAlchemy engine + session factory for the Live Market service.

Standalone DB at `live-market/backend/data/live_market.db`; never shared
with the parent app's `screener.db`. Same forward-only schema philosophy
as the parent: `init_db()` creates tables and adds new columns via
`ALTER TABLE ADD COLUMN` for additive evolution. No Alembic.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_settings = get_settings()

_connect_args = {"check_same_thread": False} if _settings.DB_URL.startswith("sqlite") else {}

engine = create_engine(
    _settings.DB_URL,
    echo=False,
    future=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent) and additively sync columns."""
    from .models.orm import Base  # noqa: WPS433 - circular avoidance

    Base.metadata.create_all(bind=engine)
    _sync_sqlite_columns(Base)


def _sync_sqlite_columns(Base) -> None:
    """SQLite-only additive column sync.

    Mirrors the parent app's pattern so adding a new field to an ORM model
    doesn't require a manual migration in development.
    """
    if not _settings.DB_URL.startswith("sqlite"):
        return
    from sqlalchemy import inspect

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                col_type = col.type.compile(dialect=engine.dialect)
                nullable = "" if col.nullable else " NOT NULL"
                default_clause = ""
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    default_value = col.default.arg
                    if isinstance(default_value, bool):
                        default_clause = f" DEFAULT {1 if default_value else 0}"
                    elif isinstance(default_value, (int, float)):
                        default_clause = f" DEFAULT {default_value}"
                    elif isinstance(default_value, str):
                        escaped = default_value.replace("'", "''")
                        default_clause = f" DEFAULT '{escaped}'"
                conn.exec_driver_sql(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" '
                    f"{col_type}{nullable}{default_clause}"
                )
