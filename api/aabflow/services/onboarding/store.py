"""SQLite intake rows for onboarding (schema_version 2, no migration)."""

from __future__ import annotations

import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any

from aabflow.api.errors import invalid, not_found
from aabflow.config import Settings
from aabflow.repositories.sqlite import dumps, loads, tx, utcnow

_ID = "onboarding_id"


def workdir_for(settings: Settings, row: sqlite3.Row) -> Path:
    status = loads(row["status"]) or {}
    rel = status.get("workdir")
    if (
        not isinstance(rel, str)
        or not rel
        or any(part in ("", ".", "..") for part in PurePosixPath(rel).parts)
    ):
        raise invalid("intake workdir is missing", {"workdir": "missing"})
    path = (settings.data_dir / rel).resolve()
    root = settings.onboarding_dir.resolve()
    if path != root and root not in path.parents:
        raise invalid("intake workdir escapes onboarding storage", {"workdir": "path traversal"})
    return path


def require(conn: sqlite3.Connection, onboarding_id: str) -> sqlite3.Row:
    if not onboarding_id or "/" in onboarding_id or "\\" in onboarding_id or ".." in onboarding_id:
        raise invalid("invalid onboarding id", {_ID: "path traversal"})
    row = conn.execute(
        "SELECT * FROM onboarding WHERE onboarding_id = ?", (onboarding_id,)
    ).fetchone()
    if row is None:
        raise not_found(_ID, onboarding_id)
    return row


def insert(
    conn: sqlite3.Connection,
    *,
    onboarding_id: str,
    pilot_id: str | None,
    request: dict[str, Any],
    status: dict[str, Any],
    state: str,
) -> None:
    now = utcnow()
    with tx(conn):
        conn.execute(
            "INSERT INTO onboarding (onboarding_id, state, request, status, review_version, "
            "job_id, pilot_id, pilot_version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                onboarding_id,
                state,
                dumps(request),
                dumps(status),
                0,
                None,
                pilot_id,
                None,
                now,
                now,
            ),
        )


def patch(
    conn: sqlite3.Connection,
    onboarding_id: str,
    *,
    state: str | None = None,
    status: dict[str, Any] | None = None,
    job_id: str | None = None,
    review_version: int | None = None,
    pilot_id: str | None = None,
    pilot_version: str | None = None,
    clear_job: bool = False,
) -> sqlite3.Row:
    row = require(conn, onboarding_id)
    current = loads(row["status"]) or {}
    if status:
        current.update(status)
    with tx(conn):
        conn.execute(
            "UPDATE onboarding SET state = ?, status = ?, job_id = ?, review_version = ?, "
            "pilot_id = ?, pilot_version = ?, updated_at = ? WHERE onboarding_id = ?",
            (
                state if state is not None else row["state"],
                dumps(current),
                None if clear_job else (job_id if job_id is not None else row["job_id"]),
                review_version if review_version is not None else row["review_version"],
                pilot_id if pilot_id is not None else row["pilot_id"],
                pilot_version if pilot_version is not None else row["pilot_version"],
                utcnow(),
                onboarding_id,
            ),
        )
    return require(conn, onboarding_id)
