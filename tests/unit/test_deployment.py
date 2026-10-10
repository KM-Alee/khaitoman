"""Deployment boundaries; all temporary data below are labelled test fixtures."""

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from scripts.laptop_snapshot import snapshot

from aabflow.config import parse_cors_origins
from aabflow.main import create_app
from tests.fixtures.api_app import settings_for


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.vercel.app",
        "https://example.com/api",
        "null",
        "https://u:p@example.com",
        "https://example.com?x=1",
    ],
)
def test_cors_rejects_unsafe_origins(origin):
    with pytest.raises(ValueError):
        parse_cors_origins(origin)


def test_split_origin_preflight_and_errors(tmp_path):
    settings = settings_for(tmp_path).with_(cors_origins=("https://app.example.com",))
    with TestClient(create_app(settings)) as client:
        headers = {
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, X-Contract-Version, Idempotency-Key",
        }
        allowed = client.options("/api/v2/scenarios", headers=headers)
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == headers["Origin"]
        assert allowed.headers["access-control-allow-credentials"] == "true"
        missing = client.get("/api/v2/missing", headers={"Origin": headers["Origin"]})
        assert missing.status_code == 404
        assert missing.json()["code"] == "NOT_FOUND"
        assert missing.headers["access-control-allow-origin"] == headers["Origin"]
        denied = client.options(
            "/api/v2/scenarios", headers={**headers, "Origin": "https://evil.example"}
        )
        assert denied.status_code == 400
        assert "access-control-allow-origin" not in denied.headers


def test_default_has_no_cross_origin_access(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/api/v2/health", headers={"Origin": "https://app.example.com"})
        assert "access-control-allow-origin" not in response.headers


def fixture_store(source):
    source.mkdir()
    with sqlite3.connect(source / "app.sqlite") as db:
        db.executescript(
            "CREATE TABLE jobs(state TEXT); CREATE TABLE copilot_turns(status TEXT); CREATE TABLE fixture(value TEXT);"
        )
        db.execute("INSERT INTO fixture VALUES ('test fixture')")
    (source / "runs").mkdir()
    (source / "runs" / "fixture.txt").write_text("labelled test fixture")


def test_snapshot_independent_and_never_overwrites(tmp_path):
    source, dest = tmp_path / "source", tmp_path / "copy"
    fixture_store(source)
    assert snapshot(source, dest)["sqlite_integrity_check"] == "ok"
    assert (dest / "runs" / "fixture.txt").read_text() == "labelled test fixture"
    with sqlite3.connect(dest / "app.sqlite") as db:
        db.execute("UPDATE fixture SET value='independent'")
    with sqlite3.connect(source / "app.sqlite") as db:
        assert db.execute("SELECT value FROM fixture").fetchone()[0] == "test fixture"
    with pytest.raises(FileExistsError):
        snapshot(source, dest)
    with pytest.raises(ValueError):
        snapshot(source, source / "nested")


@pytest.mark.parametrize(
    "table, column, value",
    [
        ("jobs", "state", "running"),
        ("jobs", "state", "queued"),
        ("copilot_turns", "status", "running"),
    ],
)
def test_snapshot_rejects_active_work(tmp_path, table, column, value):
    source = tmp_path / "source"
    fixture_store(source)
    with sqlite3.connect(source / "app.sqlite") as db:
        db.execute(f"INSERT INTO {table} ({column}) VALUES (?)", (value,))
    with pytest.raises(ValueError, match="quiesce writers"):
        snapshot(source, tmp_path / "copy")


def test_failed_backup_restarts_service_and_reports_failure(tmp_path):
    """TEST FIXTURE: fail the Docker snapshot command, never invoke a real daemon."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "laptop.sh"
    shutil.copy2(Path(__file__).parents[2] / "scripts" / "laptop.sh", script)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_DOCKER_LOG"\nif [ "$1" = "run" ]; then exit 7; fi\n'
    )
    docker.chmod(0o755)
    (tmp_path / ".laptop" / "data").mkdir(parents=True)
    log = tmp_path / "docker.log"
    result = subprocess.run(
        ["bash", str(script), "backup"],
        env={**os.environ, "PATH": f"{binary}:{os.environ['PATH']}", "TEST_DOCKER_LOG": str(log)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "start backend" in log.read_text()
    assert "up -d" not in log.read_text()
    assert "Backup:" not in result.stdout
