"""Thin stdlib sqlite3 access: one schema.sql, WAL mode, short transactions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "4"


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """v1 had only a placeholder jobs table (no real rows); replace it."""
    row = None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return
    if row and row[0] == "1":
        conn.executescript(
            "DROP TABLE IF EXISTS job_events; DROP TABLE IF EXISTS jobs;"
            "UPDATE meta SET value = '2' WHERE key = 'schema_version';"
        )


def _upgrade(conn: sqlite3.Connection) -> None:
    """v2/v3 -> v4 in place. v3 moved the copilot tables into schema.sql (a v2 database may hold copilot
    tables created before that, without the language/timings columns); v4 adds ``copilot_turns.mode``.
    Missing columns are added, existing rows keep their data, then the new version is recorded."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row and row[0] in ("2", "3"):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(copilot_turns)")}
        for name in ("language", "timings"):
            if name not in cols:
                conn.execute(f"ALTER TABLE copilot_turns ADD COLUMN {name} TEXT")
        if "mode" not in cols:
            conn.execute("ALTER TABLE copilot_turns ADD COLUMN mode TEXT NOT NULL DEFAULT 'chat'")
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (SCHEMA_VERSION,))


def init_db(db_path: Path) -> str:
    """Apply schema.sql and return the stored schema version."""
    conn = connect(db_path)
    try:
        _migrate(conn)
        conn.executescript(SCHEMA_PATH.read_text())
        _upgrade(conn)
        return conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    finally:
        conn.close()


@contextmanager
def tx(conn: sqlite3.Connection, immediate: bool = True) -> Iterator[sqlite3.Connection]:
    """Short explicit write transaction."""
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def loads(text: str | None) -> Any:
    return None if text is None else json.loads(text)
