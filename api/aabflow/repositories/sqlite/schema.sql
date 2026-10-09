-- AabFlow SQLite schema (T1.2, T9.4). Bump schema_version on any change.
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1');

CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    operation     TEXT NOT NULL,
    request_hash  TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    state         TEXT NOT NULL CHECK (state IN (
        'queued','running','waiting_for_review','succeeded','failed',
        'cancel_requested','cancelled','interrupted')),
    lease_until   TEXT,
    result_ref    TEXT,
    error_ref     TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL REFERENCES jobs(job_id),
    created_at TEXT NOT NULL,
    type       TEXT NOT NULL,
    payload    TEXT NOT NULL
);
