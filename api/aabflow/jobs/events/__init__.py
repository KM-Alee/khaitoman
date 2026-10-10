"""Job event log (SSE source, T9.4): monotonic integer ids for resumable streams."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from aabflow.domain.schemas import JobEvent
from aabflow.repositories.sqlite import dumps, loads, utcnow

EVENT_TYPES = {"stage", "progress", "heartbeat", "result", "error", "cancelled"}


def append_event(conn: sqlite3.Connection, job_id: str, type_: str, payload: dict[str, Any]) -> int:
    """Insert an event; callers own the surrounding transaction (or autocommit)."""
    if type_ not in EVENT_TYPES:
        raise ValueError(f"unknown job event type {type_!r}")
    cur = conn.execute(
        "INSERT INTO job_events (job_id, created_at, type, payload) VALUES (?,?,?,?)",
        (job_id, utcnow(), type_, dumps(payload)),
    )
    return int(cur.lastrowid)


def events_after(
    conn: sqlite3.Connection, job_id: str, after: int = 0, limit: int = 500
) -> list[JobEvent]:
    rows = conn.execute(
        "SELECT * FROM job_events WHERE job_id = ? AND event_id > ? ORDER BY event_id LIMIT ?",
        (job_id, after, limit),
    ).fetchall()
    return [
        JobEvent(
            event_id=r["event_id"],
            job_id=r["job_id"],
            created_at=datetime.fromisoformat(r["created_at"]),
            type=r["type"],
            payload=loads(r["payload"]),
        )
        for r in rows
    ]
