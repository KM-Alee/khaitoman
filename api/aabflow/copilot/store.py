"""Copilot persistence in the app SQLite database (tables in ``schema.sql``, v3).

Sessions, turns (pinned context, answer, language, timings, audit fields), the
resumable event log for SSE and every tool call with its arguments, idempotency key
and result. API keys and provider credentials are never stored (anything that looks
like one is redacted before writing); provider request IDs are.
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any

from aabflow.repositories.sqlite import SCHEMA_PATH, loads, tx, utcnow
from aabflow.repositories.sqlite import dumps as _dumps

_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,})")


def _redact(obj: Any) -> Any:
    key = os.environ.get("OPENAI_API_KEY") or ""
    if isinstance(obj, str):
        out = _SECRET.sub("[redacted]", obj)
        return out.replace(key, "[redacted]") if len(key) >= 8 else out
    if isinstance(obj, dict):
        return {k: _redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def dumps(obj: Any) -> str:
    """JSON for storage with secrets redacted (transcripts never store keys)."""
    return _dumps(_redact(obj))


TERMINAL_TURN = {
    "completed",
    "clarification",
    "failed",
    "cancelled",
    "provider_unavailable",
    "budget_exhausted",
}


def ensure(conn: sqlite3.Connection) -> None:
    """Tables come from schema.sql (init_db at startup); apply it if this database predates that."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='copilot_turns'"
    ).fetchone()
    if row is None:
        conn.executescript(SCHEMA_PATH.read_text())


def create_session(conn: sqlite3.Connection, session_id: str, role: str, ui_context: dict) -> None:
    with tx(conn):
        conn.execute(
            "INSERT INTO copilot_sessions (session_id, created_at, role, ui_context) VALUES (?,?,?,?)",
            (session_id, utcnow(), role, dumps(ui_context)),
        )


def get_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM copilot_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()


def create_turn(
    conn: sqlite3.Connection,
    turn_id: str,
    session_id: str,
    message: str,
    context: dict,
    model: str,
    prompt_version: str,
    tool_schema_version: str,
    idem_namespace: str | None = None,
) -> int:
    with tx(conn):
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM copilot_turns WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO copilot_turns (turn_id, session_id, seq, created_at, status, user_message, context, model, "
            "prompt_version, tool_schema_version, idem_namespace) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                turn_id,
                session_id,
                seq,
                utcnow(),
                "running",
                _redact(message),
                dumps(context),
                model,
                prompt_version,
                tool_schema_version,
                idem_namespace,
            ),
        )
    return seq


def finish_turn(
    conn: sqlite3.Connection,
    turn_id: str,
    *,
    status: str,
    answer: Any,
    view_intents: list,
    created: list,
    job_ids: list,
    error: Any,
    request_ids: list,
    rounds: int,
    latency_ms: int,
    timings: dict | None = None,
    language: str | None = None,
) -> None:
    with tx(conn):
        conn.execute(
            "UPDATE copilot_turns SET status=?, finished_at=?, answer=?, view_intents=?, created_refs=?, job_ids=?, "
            "error=?, request_ids=?, rounds=?, latency_ms=?, timings=?, language=COALESCE(?, language) "
            "WHERE turn_id=?",
            (
                status,
                utcnow(),
                dumps(answer),
                dumps(view_intents),
                dumps(created),
                dumps(job_ids),
                dumps(error),
                dumps(request_ids),
                rounds,
                latency_ms,
                dumps(timings) if timings is not None else None,
                language,
                turn_id,
            ),
        )


def get_turn(conn: sqlite3.Connection, turn_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM copilot_turns WHERE turn_id = ?", (turn_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    for k in (
        "context",
        "answer",
        "view_intents",
        "created_refs",
        "job_ids",
        "error",
        "request_ids",
        "timings",
    ):
        d[k] = loads(d.get(k))
    return d


def session_turns(
    conn: sqlite3.Connection, session_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT turn_id FROM copilot_turns WHERE session_id = ? ORDER BY seq DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [t for r in reversed(rows) if (t := get_turn(conn, r[0]))]


def list_sessions(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    """Recent sessions with their turn count and first question (title), newest first."""
    rows = conn.execute(
        "SELECT s.session_id, s.created_at, s.role, COUNT(t.turn_id) AS turns, MAX(t.created_at) AS last_turn_at, "
        "(SELECT user_message FROM copilot_turns f WHERE f.session_id = s.session_id ORDER BY seq LIMIT 1) "
        "AS title FROM copilot_sessions s LEFT JOIN copilot_turns t ON t.session_id = s.session_id "
        "GROUP BY s.session_id ORDER BY COALESCE(MAX(t.created_at), s.created_at) DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "session_id": r["session_id"],
            "created_at": r["created_at"],
            "role": r["role"],
            "title": (r["title"] or "")[:120] or None,
            "turns": r["turns"],
            "last_turn_at": r["last_turn_at"],
        }
        for r in rows
    ]


def append_event(conn: sqlite3.Connection, turn_id: str, type_: str, payload: dict) -> int:
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO copilot_events (turn_id, created_at, type, payload) VALUES (?,?,?,?)",
            (turn_id, utcnow(), type_, dumps(payload)),
        )
        return int(cur.lastrowid)


def events_after(conn: sqlite3.Connection, turn_id: str, after: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM copilot_events WHERE turn_id = ? AND event_id > ? ORDER BY event_id",
        (turn_id, after),
    ).fetchall()
    return [
        {
            "event_id": r["event_id"],
            "turn_id": r["turn_id"],
            "created_at": r["created_at"],
            "type": r["type"],
            "payload": loads(r["payload"]),
        }
        for r in rows
    ]


def start_call(
    conn: sqlite3.Connection,
    turn_id: str,
    call_id: str,
    rnd: int,
    tool: str,
    args: Any,
    idem: str | None,
) -> int:
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO copilot_tool_calls (turn_id, call_id, round, tool, arguments, idempotency_key, status, "
            "started_at) VALUES (?,?,?,?,?,?,?,?)",
            (turn_id, call_id, rnd, tool, dumps(args), idem, "running", utcnow()),
        )
        return int(cur.lastrowid)


def finish_call(conn: sqlite3.Connection, pk: int, status: str, result: Any) -> None:
    with tx(conn):
        conn.execute(
            "UPDATE copilot_tool_calls SET status=?, result=?, finished_at=? WHERE pk=?",
            (status, dumps(result), utcnow(), pk),
        )


def tool_calls(conn: sqlite3.Connection, turn_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM copilot_tool_calls WHERE turn_id = ? ORDER BY pk", (turn_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["arguments"] = loads(d["arguments"])
        d["result"] = loads(d["result"])
        out.append(d)
    return out


def session_known_ids(conn: sqlite3.Connection, session_id: str) -> set[str]:
    ids: set[str] = set()
    for t in session_turns(conn, session_id):
        for c in t.get("created_refs") or []:
            ids.add(c["ref_id"])
        ids.update(t.get("job_ids") or [])
    return ids


def interrupt_turn(conn: sqlite3.Connection, turn_id: str) -> None:
    """A turn recorded as running that no live process owns (server restarted): mark it honestly."""
    with tx(conn):
        conn.execute(
            "UPDATE copilot_turns SET status='failed', finished_at=?, error=? "
            "WHERE turn_id=? AND status='running'",
            (
                utcnow(),
                dumps({"code": "INTERRUPTED", "detail": "the server restarted during this turn"}),
                turn_id,
            ),
        )


def interrupt_running(conn: sqlite3.Connection) -> int:
    """On startup: turns left running by a previous process are marked failed honestly."""
    ensure(conn)
    with tx(conn):
        cur = conn.execute(
            "UPDATE copilot_turns SET status='failed', finished_at=?, error=? WHERE status='running'",
            (
                utcnow(),
                dumps({"code": "INTERRUPTED", "detail": "the server restarted during this turn"}),
            ),
        )
    return cur.rowcount
