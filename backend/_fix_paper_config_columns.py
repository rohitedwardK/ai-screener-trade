"""One-shot schema patch: add missing columns to paper_bot_config.

Why this exists
---------------
The ORM (``backend/app/models/paper_orm.py``) was extended with
``live_trading_enabled`` and ``live_poll_interval_seconds`` after the SQLite
DB at ``backend/data/stock.db`` was already created. SQLAlchemy's
``Base.metadata.create_all`` only creates missing tables; it never ALTERs
existing ones. This script patches the schema in place without losing any
paper-trading state.

Run once (from ``backend/``):

    .\.venv\Scripts\python.exe _fix_paper_config_columns.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "screener.db"

REQUIRED = [
    ("live_trading_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("live_poll_interval_seconds", "INTEGER NOT NULL DEFAULT 60"),
]


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    existing = {row[1] for row in cur.execute("PRAGMA table_info('paper_bot_config')")}
    added: list[str] = []
    for name, decl in REQUIRED:
        if name not in existing:
            cur.execute(f"ALTER TABLE paper_bot_config ADD COLUMN {name} {decl}")
            added.append(name)
    con.commit()
    final = sorted({row[1] for row in cur.execute("PRAGMA table_info('paper_bot_config')")})
    con.close()
    print("Added columns:", added or "none (already up to date)")
    print("Final columns:", final)


if __name__ == "__main__":
    main()
