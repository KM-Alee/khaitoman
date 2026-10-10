"""Schema v2 -> v3: copilot tables move into schema.sql; an old database keeps its transcripts."""

from __future__ import annotations

from aabflow.copilot import store
from aabflow.repositories.sqlite import SCHEMA_VERSION, connect, init_db

V2_TURNS = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta VALUES ('schema_version', '2');
CREATE TABLE copilot_sessions (session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, role TEXT NOT NULL,
    ui_context TEXT NOT NULL, preferences TEXT NOT NULL DEFAULT '{}');
CREATE TABLE copilot_turns (turn_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, seq INTEGER NOT NULL,
    created_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, user_message TEXT NOT NULL,
    context TEXT NOT NULL, answer TEXT, view_intents TEXT NOT NULL DEFAULT '[]',
    created_refs TEXT NOT NULL DEFAULT '[]', job_ids TEXT NOT NULL DEFAULT '[]', error TEXT, model TEXT,
    prompt_version TEXT, tool_schema_version TEXT, request_ids TEXT NOT NULL DEFAULT '[]',
    rounds INTEGER NOT NULL DEFAULT 0, latency_ms INTEGER, idem_namespace TEXT);
INSERT INTO copilot_sessions VALUES ('cps_old', '2026-10-09T00:00:00Z', 'planner', '{}', '{}');
INSERT INTO copilot_turns (turn_id, session_id, seq, created_at, status, user_message, context)
    VALUES ('turn_old', 'cps_old', 1, '2026-10-09T00:00:00Z', 'completed', 'hello', '{}');
"""


def test_v2_database_upgrades_in_place(tmp_path):
    db = tmp_path / "app.sqlite"
    c = connect(db)
    c.executescript(V2_TURNS)
    c.close()
    assert init_db(db) == SCHEMA_VERSION == "3"
    c = connect(db)
    try:
        t = store.get_turn(c, "turn_old")
        assert t["user_message"] == "hello" and t["timings"] is None and t["language"] is None
        store.finish_turn(
            c,
            "turn_old",
            status="completed",
            answer=None,
            view_intents=[],
            created=[],
            job_ids=[],
            error=None,
            request_ids=[],
            rounds=1,
            latency_ms=5,
            timings={"total_ms": 5},
            language="ur",
        )
        t = store.get_turn(c, "turn_old")
        assert t["timings"] == {"total_ms": 5} and t["language"] == "ur"
    finally:
        c.close()
    assert init_db(db) == "3"  # idempotent


def test_fresh_database_has_copilot_tables(tmp_path):
    db = tmp_path / "fresh.sqlite"
    init_db(db)
    c = connect(db)
    try:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()
    assert {"copilot_sessions", "copilot_turns", "copilot_events", "copilot_tool_calls"} <= names
