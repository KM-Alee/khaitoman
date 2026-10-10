"""TEST FIXTURE helpers and service checks for reports (PRD §8.6, T7.5, T9.1, T9.4).

The labelled runs below are not a real pilot and not a finished report.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aabflow.api.errors import DomainError
from aabflow.domain.hashes import file_sha256
from aabflow.domain.schemas import ErrorCode, JobState
from aabflow.jobs import queue
from aabflow.jobs.cancellation import JobCancelled
from aabflow.jobs.worker import HANDLERS, JobContext
from aabflow.repositories.sqlite import connect, dumps, init_db, utcnow
from aabflow.services import reports as svc
from aabflow.services.reports import ReportCreate
from tests.fixtures.api_app import settings_for

METRIC = 424242.0
STORED_DEFINITION = "production_kg@stored-fixture-do-not-replace"
STORED_VERSION = "stored-metrics-version"


def _metric(
    run_id: str, metric_id: str, value: float | None, status: str, definition_id: str, unit: str
):
    return {
        "metric_id": metric_id,
        "definition_id": definition_id,
        "run_id": run_id,
        "value": value,
        "unit": unit,
        "status": status,
        "reason": "stored-fixture",
        "evidence_ids": ["ev-fixture"],
        "crop": "wheat",
        "field_id": None,
    }


def _metrics(run_id: str, value: float, *, blocked: bool) -> list[dict]:
    rows = [
        _metric(run_id, "production_kg", value, "available", STORED_DEFINITION, "kg"),
    ]
    if blocked:
        rows.append(
            _metric(
                run_id,
                "withdrawal_productivity_kg_m3",
                None,
                "blocked",
                "withdrawal_productivity_kg_m3@stored-fixture",
                "kg/m3",
            )
        )
    return rows


def _bundle(
    run_dir: Path,
    run_id: str,
    revision_id: str,
    pilot: str,
    version: str,
    metrics,
    scenario_hash: str,
    library_hash: str,
) -> str:
    run_dir.mkdir(parents=True, exist_ok=True)
    document = {
        "result": {
            "contract_version": "2.0.0",
            "run_id": run_id,
            "scenario_revision_id": revision_id,
            "scenario_hash": scenario_hash,
            "candidate_library_hash": library_hash,
            "plan_kind": "P",
            "proof_scope": "finite_candidate_library",
            "primary_objective": "production_kg",
            "solve_wall_ms": 1,
            "outcome": "no_plan",
            "solver_status": "INFEASIBLE",
            "diagnostics": {"label": "TEST FIXTURE"},
            "created_at": "2026-10-10T00:00:00Z",
        },
        "meta": {
            "pilot_id": pilot,
            "pilot_version": version,
            "metrics_version": STORED_VERSION,
            "season_id": "season-fixture",
        },
    }
    (run_dir / "run.json").write_text(
        json.dumps(document, indent=1, sort_keys=True), encoding="utf-8"
    )
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=1, sort_keys=True), encoding="utf-8"
    )
    files = []
    for name in ("run.json", "metrics.json"):
        path = run_dir / name
        files.append({"path": name, "size_bytes": path.stat().st_size, "sha256": file_sha256(path)})
    manifest = run_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"run_id": run_id, "files": files, "created_at": utcnow()}, indent=1, sort_keys=True
        ),
        encoding="utf-8",
    )
    return file_sha256(manifest)


def _revision(
    conn,
    *,
    scenario_id: str,
    revision_id: str,
    pilot_id: str,
    pilot_version: str,
    library_hash: str,
) -> None:
    now = utcnow()
    if (
        conn.execute("SELECT 1 FROM scenarios WHERE scenario_id = ?", (scenario_id,)).fetchone()
        is None
    ):
        conn.execute(
            "INSERT INTO scenarios (scenario_id, pilot_id, label, head_revision_id, created_at) "
            "VALUES (?,?,?,?,?)",
            (scenario_id, pilot_id, "TEST FIXTURE", revision_id, now),
        )
    request = {
        "contract_version": "2.0.0",
        "pilot_id": pilot_id,
        "pilot_version": pilot_version,
        "season_id": "season-fixture",
    }
    conn.execute(
        "INSERT INTO scenario_revisions (scenario_revision_id, scenario_id, parent_revision_id, "
        "request, semantic_hash, candidate_library_hash, dependencies, readiness, origin, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            revision_id,
            scenario_id,
            None,
            dumps(request),
            "fixture-semantic",
            library_hash,
            dumps({}),
            dumps({}),
            "user",
            now,
        ),
    )


def _run(conn, settings, **spec) -> None:
    _revision(
        conn,
        scenario_id=spec["scenario_id"],
        revision_id=spec["revision_id"],
        pilot_id=spec["pilot_id"],
        pilot_version=spec["pilot_version"],
        library_hash=spec["library_hash"],
    )
    run_dir = settings.runs_dir / spec["run_id"]
    digest = _bundle(
        run_dir,
        spec["run_id"],
        spec["revision_id"],
        spec["pilot_id"],
        spec["pilot_version"],
        spec["metrics"],
        spec["scenario_hash"],
        spec["library_hash"],
    )
    conn.execute(
        "INSERT INTO runs (run_id, scenario_revision_id, plan_kind, outcome, solver_status, "
        "scenario_hash, candidate_library_hash, run_dir, manifest_sha256, job_id, analysis_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            spec["run_id"],
            spec["revision_id"],
            "P",
            "no_plan",
            "INFEASIBLE",
            spec["scenario_hash"],
            spec["library_hash"],
            str(run_dir),
            digest,
            None,
            None,
            utcnow(),
        ),
    )


def _analysis(conn, analysis_id: str, revision_id: str, run_id: str, stored: dict) -> None:
    now = utcnow()
    conn.execute(
        "INSERT INTO analyses (analysis_id, kind, base_revision_id, base_run_id, job_id, request, "
        "result, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            analysis_id,
            "stress",
            revision_id,
            run_id,
            None,
            dumps({"run_id": run_id}),
            dumps(stored),
            now,
            now,
        ),
    )


def seed_world(tmp: Path):
    """Four labelled runs and two analyses used by the report HTTP tests."""
    settings = settings_for(tmp, dispatcher=False, workers=1)
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    specs = [
        {
            "run_id": "run_fixture_a",
            "pilot_id": "pilot-a",
            "pilot_version": "reviewed-v1",
            "scenario_id": "scn_fixture_a",
            "revision_id": "rev_fixture_a",
            "scenario_hash": "a" * 64,
            "library_hash": "b" * 64,
            "metrics": _metrics("run_fixture_a", METRIC, blocked=True),
        },
        {
            "run_id": "run_fixture_a2",
            "pilot_id": "pilot-a",
            "pilot_version": "reviewed-v1",
            "scenario_id": "scn_fixture_a",
            "revision_id": "rev_fixture_a2",
            "scenario_hash": "c" * 64,
            "library_hash": "d" * 64,
            "metrics": _metrics("run_fixture_a2", 3456.0, blocked=False),
        },
        {
            "run_id": "run_fixture_b",
            "pilot_id": "pilot-b",
            "pilot_version": "reviewed-v1",
            "scenario_id": "scn_fixture_b",
            "revision_id": "rev_fixture_b",
            "scenario_hash": "e" * 64,
            "library_hash": "f" * 64,
            "metrics": _metrics("run_fixture_b", 1.0, blocked=False),
        },
        {
            "run_id": "run_fixture_a_v2",
            "pilot_id": "pilot-a",
            "pilot_version": "reviewed-v2",
            "scenario_id": "scn_fixture_a_v2",
            "revision_id": "rev_fixture_a_v2",
            "scenario_hash": "9" * 64,
            "library_hash": "8" * 64,
            "metrics": _metrics("run_fixture_a_v2", 2.0, blocked=False),
        },
    ]
    for spec in specs:
        _run(conn, settings, **spec)
    _analysis(
        conn,
        "ana_fixture_a",
        "rev_fixture_a",
        "run_fixture_a",
        {"status": "completed", "child_run_ids": ["run_fixture_a"], "sentinel_metric": 42.0},
    )
    _analysis(
        conn,
        "ana_fixture_b",
        "rev_fixture_b",
        "run_fixture_b",
        {"status": "completed", "child_run_ids": ["run_fixture_b"], "sentinel_metric": 7.0},
    )
    return settings, conn


def test_request_rejects_nonfinite_numbers():
    with pytest.raises(ValidationError) as caught:
        ReportCreate.model_validate(
            {"run_ids": [float("inf")], "analysis_ids": [], "report_type": "one_page_plan"}
        )
    assert "nonfinite" in str(caught.value)
    assert ReportCreate.model_config.get("allow_inf_nan") is False


def test_service_does_not_recompute_metrics():
    source = inspect.getsource(svc)
    assert "compute_plan_metrics" not in source
    assert "ledger_totals" not in source


def test_job_copies_stored_metrics_and_ids(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("metrics were recomputed")

    monkeypatch.setattr("aabflow.services.metrics.compute_plan_metrics", boom)
    monkeypatch.setattr("aabflow.services.runs.compute_plan_metrics", boom, raising=False)
    settings, conn = seed_world(tmp_path)
    try:
        body = ReportCreate(
            run_ids=["run_fixture_a", "run_fixture_a2"],
            analysis_ids=["ana_fixture_a"],
            report_type="full_report",
        )
        report_id, job_id = svc.create(conn, body)
        queued = svc.get_report(conn, settings, report_id)
        assert queued["status"] == "queued"
        assert queued["download_url"] is None
        assert queued["final_self_contained_report"] is False
        ctx = JobContext(settings, job_id, "unit-test", conn)
        result = svc.report_job(ctx, {"report_id": report_id})
        assert result["final_self_contained_report"] is False
        assert result["artifact"] == "placeholder.json"
        queue.finish(conn, job_id, JobState.succeeded, result_ref=dumps(result))
        view = svc.get_report(conn, settings, report_id)
        assert view["status"] == "succeeded"
        assert view["download_url"].endswith("/files/placeholder.json")
        document = json.loads((settings.reports_dir / report_id / "placeholder.json").read_text())
        assert document["artifact_kind"] == "p05-api-placeholder"
        assert document["final_self_contained_report"] is False
        assert "http://" not in json.dumps(document) and "https://" not in json.dumps(document)
        assert document["runs"][0]["metrics"][0]["value"] == METRIC
        assert document["runs"][0]["metrics"][0]["definition_id"] == STORED_DEFINITION
        assert document["runs"][0]["metrics"][1]["value"] is None
        assert document["runs"][0]["metrics"][1]["status"] == "blocked"
        assert document["runs"][0]["metrics_version"] == STORED_VERSION
        assert document["runs"][0]["scenario_revision_id"] == "rev_fixture_a"
        assert document["runs"][0]["candidate_library_hash"] == "b" * 64
        assert document["runs"][0]["pilot_id"] == "pilot-a"
        assert document["runs"][0]["pilot_version"] == "reviewed-v1"
        assert document["runs"][1]["metrics"][0]["value"] == 3456.0
        assert document["analyses"][0]["stored_result"]["sentinel_metric"] == 42.0
        names = sorted(path.name for path in (settings.reports_dir / report_id).iterdir())
        assert names == ["placeholder.json"]
    finally:
        conn.close()


def test_nonfinite_stored_metrics_are_not_rewritten(tmp_path):
    settings, conn = seed_world(tmp_path)
    try:
        metrics = settings.runs_dir / "run_fixture_a" / "metrics.json"
        payload = json.loads(metrics.read_text())
        payload[0]["value"] = float("nan")
        metrics.write_text(json.dumps(payload, allow_nan=True), encoding="utf-8")
        manifest = metrics.parent / "manifest.json"
        files = json.loads(manifest.read_text())
        for item in files["files"]:
            if item["path"] == "metrics.json":
                item["sha256"] = file_sha256(metrics)
                item["size_bytes"] = metrics.stat().st_size
        manifest.write_text(json.dumps(files), encoding="utf-8")
        conn.execute(
            "UPDATE runs SET manifest_sha256 = ? WHERE run_id = ?",
            (file_sha256(manifest), "run_fixture_a"),
        )
        from aabflow.services.runs import _VERIFIED

        _VERIFIED.pop(str(metrics.parent), None)
        body = ReportCreate(run_ids=["run_fixture_a"], analysis_ids=[], report_type="one_page_plan")
        with pytest.raises(DomainError) as caught:
            svc.create(conn, body)
        assert caught.value.code == ErrorCode.ASSET_UNAVAILABLE
        assert "not recomputed" in caught.value.detail
        assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0
    finally:
        conn.close()


def test_cancellation_publishes_nothing(tmp_path):
    settings, conn = seed_world(tmp_path)
    try:
        report_id, job_id = svc.create(
            conn,
            ReportCreate(run_ids=["run_fixture_a"], analysis_ids=[], report_type="one_page_plan"),
        )
        ctx = JobContext(settings, job_id, "unit-test", conn)
        ctx.token.cancel()
        with pytest.raises(JobCancelled):
            svc.report_job(ctx, {"report_id": report_id})
        row = conn.execute(
            "SELECT report_dir FROM reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        assert row["report_dir"] is None
        assert not (settings.reports_dir / report_id).exists()
    finally:
        conn.close()


def test_path_traversal_and_symlinks_are_rejected(tmp_path):
    report_dir = tmp_path / "reports" / "rpt_fixture"
    report_dir.mkdir(parents=True)
    (report_dir / "placeholder.json").write_text("{}\n", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET-OUTSIDE", encoding="utf-8")
    (report_dir / "leak.json").symlink_to(secret)
    for rel in (
        "../secret.txt",
        "/etc/passwd",
        "leak.json",
        "notes/../../secret.txt",
        "..%2fsecret.txt",
    ):
        with pytest.raises(DomainError) as caught:
            svc.resolve_report_file(report_dir, rel)
        assert caught.value.code == ErrorCode.NOT_FOUND
    assert svc.resolve_report_file(report_dir, "placeholder.json").is_file()


def test_handler_registration():
    assert HANDLERS["report"] == "aabflow.services.reports:report_job"
    assert callable(svc.report_job)
