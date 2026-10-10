"""Copilot persistence in the app SQLite database (own tables, created on first use).

Sessions, turns (pinned context, answer, audit fields), the resumable event log for
SSE and every tool call with its arguments, idempotency key and result. API keys
and provider credentials are never stored; request IDs are.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from aabflow.repositories.sqlite import dumps, loads, tx, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS copilot_sessions (
    session_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL,
    ui_context TEXT NOT NULL,
    preferences TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS copilot_turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES copilot_sessions(session_id),
    seq INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    user_message TEXT NOT NULL,
    context TEXT NOT NULL,
    answer TEXT,
    view_intents TEXT NOT NULL DEFAULT '[]',
    created_refs TEXT NOT NULL DEFAULT '[]',
    job_ids TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    model TEXT,
    prompt_version TEXT,
    tool_schema_version TEXT,
    request_ids TEXT NOT NULL DEFAULT '[]',
    rounds INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    idem_namespace TEXT
);
CREATE INDEX IF NOT EXISTS copilot_turns_session ON copilot_turns(session_id, seq);
CREATE TABLE IF NOT EXISTS copilot_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS copilot_events_turn ON copilot_events(turn_id, event_id);
CREATE TABLE IF NOT EXISTS copilot_tool_calls (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,
    idempotency_key TEXT,
    status TEXT NOT NULL,
    result TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS copilot_tool_calls_turn ON copilot_tool_calls(turn_id);
"""

TERMINAL_TURN = {
    "completed",
    "clarification",
    "failed",
    "cancelled",
    "provider_unavailable",
    "budget_exhausted",
}


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


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
                message,
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
) -> None:
    with tx(conn):
        conn.execute(
            "UPDATE copilot_turns SET status=?, finished_at=?, answer=?, view_intents=?, created_refs=?, job_ids=?, "
            "error=?, request_ids=?, rounds=?, latency_ms=? WHERE turn_id=?",
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
    ):
        d[k] = loads(d[k])
    return d


def session_turns(
    conn: sqlite3.Connection, session_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT turn_id FROM copilot_turns WHERE session_id = ? ORDER BY seq DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [t for r in reversed(rows) if (t := get_turn(conn, r[0]))]


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
