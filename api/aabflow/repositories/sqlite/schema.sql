-- AabFlow SQLite schema (T1.2, T9.4). Bump schema_version on any change.
-- v2: job leases/stages/payloads, idempotency, scenarios, runs, analyses,
--     comparisons, reports, surrogate previews, onboarding, evidence FTS5.
-- v3: copilot sessions, turns (with language and timings), events and tool calls.
-- v4: copilot_turns.mode (chat | plan, the "Plan my season" planner mode).
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '4');

CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    operation       TEXT NOT NULL,
    request_hash    TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    state           TEXT NOT NULL CHECK (state IN (
        'queued','running','waiting_for_review','succeeded','failed',
        'cancel_requested','cancelled','interrupted')),
    payload         TEXT NOT NULL DEFAULT '{}',
    stage           TEXT,
    progress        REAL,
    owner           TEXT,
    lease_until     TEXT,
    result_ref      TEXT,
    error_ref       TEXT,
    subject_id      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, created_at);

CREATE TABLE IF NOT EXISTS job_events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL REFERENCES jobs(job_id),
    created_at TEXT NOT NULL,
    type       TEXT NOT NULL,
    payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS job_events_job ON job_events(job_id, event_id);

CREATE TABLE IF NOT EXISTS idempotency (
    scope         TEXT NOT NULL,
    key           TEXT NOT NULL,
    request_hash  TEXT NOT NULL,
    status_code   INTEGER NOT NULL,
    response      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id      TEXT PRIMARY KEY,
    pilot_id         TEXT NOT NULL,
    label            TEXT,
    head_revision_id TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_revisions (
    scenario_revision_id  TEXT PRIMARY KEY,
    scenario_id           TEXT NOT NULL REFERENCES scenarios(scenario_id),
    parent_revision_id    TEXT,
    request               TEXT NOT NULL,
    semantic_hash         TEXT NOT NULL,
    candidate_library_hash TEXT,
    dependencies          TEXT NOT NULL,
    readiness             TEXT NOT NULL,
    origin                TEXT NOT NULL DEFAULT 'user',
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS revisions_scenario ON scenario_revisions(scenario_id, created_at);

CREATE TABLE IF NOT EXISTS runs (
    run_id               TEXT PRIMARY KEY,
    scenario_revision_id TEXT NOT NULL,
    plan_kind            TEXT NOT NULL,
    outcome              TEXT NOT NULL,
    solver_status        TEXT NOT NULL,
    scenario_hash        TEXT NOT NULL,
    candidate_library_hash TEXT NOT NULL,
    run_dir              TEXT NOT NULL,
    manifest_sha256      TEXT NOT NULL,
    job_id               TEXT,
    analysis_id          TEXT,
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_revision ON runs(scenario_revision_id, created_at);

CREATE TABLE IF NOT EXISTS analyses (
    analysis_id      TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,
    base_revision_id TEXT,
    base_run_id      TEXT,
    job_id           TEXT,
    request          TEXT NOT NULL,
    result           TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comparisons (
    comparison_id TEXT PRIMARY KEY,
    run_ids       TEXT NOT NULL,
    result        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    report_id   TEXT PRIMARY KEY,
    report_hash TEXT,
    report_type TEXT NOT NULL,
    request     TEXT NOT NULL,
    job_id      TEXT,
    report_dir  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS surrogate_previews (
    preview_id    TEXT PRIMARY KEY,
    request       TEXT NOT NULL,
    result        TEXT NOT NULL,
    verify_job_id TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS onboarding (
    onboarding_id TEXT PRIMARY KEY,
    state         TEXT NOT NULL,
    request       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT '{}',
    review_version INTEGER NOT NULL DEFAULT 0,
    job_id        TEXT,
    pilot_id      TEXT,
    pilot_version TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Copilot (F19, T11): transcripts hold no secrets; API keys never reach these tables.
CREATE TABLE IF NOT EXISTS copilot_sessions (
    session_id  TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    role        TEXT NOT NULL,
    ui_context  TEXT NOT NULL,
    preferences TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS copilot_turns (
    turn_id             TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES copilot_sessions(session_id),
    seq                 INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL,
    user_message        TEXT NOT NULL,
    context             TEXT NOT NULL,
    answer              TEXT,
    view_intents        TEXT NOT NULL DEFAULT '[]',
    created_refs        TEXT NOT NULL DEFAULT '[]',
    job_ids             TEXT NOT NULL DEFAULT '[]',
    error               TEXT,
    model               TEXT,
    prompt_version      TEXT,
    tool_schema_version TEXT,
    request_ids         TEXT NOT NULL DEFAULT '[]',
    rounds              INTEGER NOT NULL DEFAULT 0,
    latency_ms          INTEGER,
    idem_namespace      TEXT,
    language            TEXT,
    timings             TEXT,
    mode                TEXT NOT NULL DEFAULT 'chat'
);
CREATE INDEX IF NOT EXISTS copilot_turns_session ON copilot_turns(session_id, seq);
CREATE TABLE IF NOT EXISTS copilot_events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    type       TEXT NOT NULL,
    payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS copilot_events_turn ON copilot_events(turn_id, event_id);
CREATE TABLE IF NOT EXISTS copilot_tool_calls (
    pk              INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id         TEXT NOT NULL,
    call_id         TEXT NOT NULL,
    round           INTEGER NOT NULL,
    tool            TEXT NOT NULL,
    arguments       TEXT NOT NULL,
    idempotency_key TEXT,
    status          TEXT NOT NULL,
    result          TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS copilot_tool_calls_turn ON copilot_tool_calls(turn_id);

CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
    doc_id UNINDEXED, kind UNINDEXED, pilot_id UNINDEXED, title, body, source_url UNINDEXED,
    tokenize = 'porter unicode61'
);
