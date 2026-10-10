"""Durable SQLite job queue (T9.4): atomic claims, leases, lifecycle transitions.

States: queued, running, waiting_for_review, succeeded, failed, cancel_requested,
cancelled, interrupted. Every write is a short transaction; long calculations
never hold a write lock.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from aabflow.domain.ids import new_id
from aabflow.domain.schemas import Job, JobState
from aabflow.jobs.events import append_event
from aabflow.repositories.sqlite import dumps, loads, tx, utcnow

TERMINAL = {JobState.succeeded, JobState.failed, JobState.cancelled, JobState.interrupted}
ACTIVE = {JobState.running, JobState.cancel_requested}


def _iso_in(seconds: float) -> str:
    return (
        (datetime.now(UTC) + timedelta(seconds=seconds))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        job_id=row["job_id"],
        operation=row["operation"],
        request_hash=row["request_hash"],
        state=JobState(row["state"]),
        progress=row["progress"],
        stage=row["stage"],
        result_ref=row["result_ref"],
        error=loads(row["error_ref"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def enqueue(
    conn: sqlite3.Connection,
    operation: str,
    payload: dict[str, Any],
    request_hash: str,
    *,
    subject_id: str | None = None,
    job_id: str | None = None,
) -> str:
    jid = job_id or new_id("job")
    now = utcnow()
    with tx(conn):
        conn.execute(
            "INSERT INTO jobs (job_id, operation, request_hash, state, payload, subject_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                jid,
                operation,
                request_hash,
                JobState.queued.value,
                dumps(payload),
                subject_id,
                now,
                now,
            ),
        )
        append_event(conn, jid, "stage", {"stage": "queued", "operation": operation})
    return jid


def get(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()


def claim_next(conn: sqlite3.Connection, owner: str, lease_s: float) -> str | None:
    """Atomically move the oldest queued job to running and return its id."""
    now = utcnow()
    with tx(conn):
        row = conn.execute(
            "UPDATE jobs SET state = 'running', owner = ?, lease_until = ?, started_at = ?, updated_at = ? "
            "WHERE job_id = (SELECT job_id FROM jobs WHERE state = 'queued' ORDER BY created_at, job_id LIMIT 1) "
            "AND state = 'queued' RETURNING job_id",
            (owner, _iso_in(lease_s), now, now),
        ).fetchone()
        if row is None:
            return None
        append_event(conn, row[0], "stage", {"stage": "running", "owner": owner})
        return row[0]


def heartbeat(conn: sqlite3.Connection, job_id: str, owner: str, lease_s: float) -> str | None:
    """Extend the lease; returns the current state (None if the job is no longer ours)."""
    with tx(conn):
        conn.execute(
            "UPDATE jobs SET lease_until = ? WHERE job_id = ? AND owner = ? AND state IN ('running','cancel_requested')",
            (_iso_in(lease_s), job_id, owner),
        )
        row = conn.execute("SELECT state, owner FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None or row["owner"] != owner:
        return None
    return row["state"]


def set_stage(
    conn: sqlite3.Connection, job_id: str, stage: str | None, progress: float | None, detail: Any
) -> None:
    with tx(conn):
        conn.execute(
            "UPDATE jobs SET stage = COALESCE(?, stage), progress = COALESCE(?, progress), updated_at = ? "
            "WHERE job_id = ?",
            (stage, progress, utcnow(), job_id),
        )
        payload: dict[str, Any] = {}
        if stage is not None:
            payload["stage"] = stage
        if progress is not None:
            payload["progress"] = progress
        if detail is not None:
            payload["detail"] = detail
        append_event(conn, job_id, "progress" if stage is None else "stage", payload)


def finish(
    conn: sqlite3.Connection,
    job_id: str,
    state: JobState,
    *,
    result_ref: str | None = None,
    error: dict[str, Any] | None = None,
    event_payload: dict[str, Any] | None = None,
) -> bool:
    now = utcnow()
    with tx(conn):
        cur = conn.execute(
            "UPDATE jobs SET state = ?, result_ref = COALESCE(?, result_ref), error_ref = ?, updated_at = ?, "
            "finished_at = ?, lease_until = NULL WHERE job_id = ? AND state IN ('running','cancel_requested','queued')",
            (state.value, result_ref, dumps(error) if error else None, now, now, job_id),
        )
        if cur.rowcount == 0:
            return False
        etype = {JobState.succeeded: "result", JobState.cancelled: "cancelled"}.get(state, "error")
        payload = {"state": state.value, **(event_payload or {})}
        if result_ref:
            payload["result_ref"] = result_ref
        if error:
            payload["error"] = error
        append_event(conn, job_id, etype, payload)
    return True


def request_cancel(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    """Idempotent cooperative cancellation."""
    now = utcnow()
    with tx(conn):
        row = conn.execute("SELECT state FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        st = JobState(row["state"])
        if st is JobState.queued:
            conn.execute(
                "UPDATE jobs SET state = 'cancelled', updated_at = ?, finished_at = ? WHERE job_id = ?",
                (now, now, job_id),
            )
            append_event(
                conn,
                job_id,
                "cancelled",
                {"state": "cancelled", "detail": "cancelled before start"},
            )
        elif st in (JobState.running, JobState.waiting_for_review):
            conn.execute(
                "UPDATE jobs SET state = 'cancel_requested', updated_at = ? WHERE job_id = ?",
                (now, job_id),
            )
            append_event(conn, job_id, "stage", {"stage": "cancel_requested"})
    return get(conn, job_id)


def mark_interrupted(
    conn: sqlite3.Connection, reason: str, *, owner_not: str | None = None
) -> list[str]:
    """Jobs left running without a valid lease become interrupted (restart recovery)."""
    now = utcnow()
    with tx(conn):
        if owner_not is None:
            rows = conn.execute(
                "SELECT job_id FROM jobs WHERE state IN ('running','cancel_requested')"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT job_id FROM jobs WHERE state IN ('running','cancel_requested') "
                "AND (owner IS NULL OR owner != ? OR lease_until IS NULL OR lease_until < ?)",
                (owner_not, now),
            ).fetchall()
        ids = [r[0] for r in rows]
        for jid in ids:
            conn.execute(
                "UPDATE jobs SET state = 'interrupted', updated_at = ?, finished_at = ?, lease_until = NULL, "
                "error_ref = ? WHERE job_id = ?",
                (now, now, dumps({"code": "INTERRUPTED", "detail": reason}), jid),
            )
            append_event(
                conn,
                jid,
                "error",
                {"state": "interrupted", "error": {"code": "INTERRUPTED", "detail": reason}},
            )
    return ids


def expired_leases(conn: sqlite3.Connection) -> list[str]:
    now = utcnow()
    rows = conn.execute(
        "SELECT job_id FROM jobs WHERE state IN ('running','cancel_requested') AND lease_until IS NOT NULL "
        "AND lease_until < ?",
        (now,),
    ).fetchall()
    return [r[0] for r in rows]


def payload(conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    row = get(conn, job_id)
    return loads(row["payload"]) if row else {}
