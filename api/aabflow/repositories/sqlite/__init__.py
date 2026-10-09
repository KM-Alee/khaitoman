"""Thin stdlib sqlite3 access: one schema.sql, WAL mode, short transactions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> str:
    """Apply schema.sql and return the stored schema version."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        return conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
