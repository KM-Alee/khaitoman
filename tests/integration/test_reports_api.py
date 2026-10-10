"""HTTP contract for /api/v2/reports. TEST FIXTURE runs only.

The reports router is registered in main._routers immediately before copilot.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from aabflow.domain.hashes import file_sha256
from aabflow.domain.schemas import JobState
from aabflow.jobs import queue
from aabflow.main import _routers
from aabflow.repositories.sqlite import connect, utcnow
from tests.unit.test_reports_api import METRIC, seed_world

BODY = {
    "run_ids": ["run_fixture_a"],
    "analysis_ids": ["ana_fixture_a"],
    "report_type": "one_page_plan",
}


def app_with_reports(settings):
    """Mount reports immediately before the copilot router, as the parent must."""
    from aabflow import main
    from aabflow.api.reports import router as reports_router

    original = main._routers

    def patched():
        routers = original()
        if reports_router not in routers:
            routers.insert(-1, reports_router)
        return routers

    main._routers = patched
    try:
        return main.create_app(settings)
    finally:
        main._routers = original


def test_reports_router_is_registered_before_copilot():
    from aabflow.api.reports import router as reports_router
    from aabflow.copilot.router import router as copilot_router

    routers = _routers()
    assert routers.index(reports_router) == routers.index(copilot_router) - 1


@pytest.fixture(scope="module")
def quiet(tmp_path_factory):
    settings, conn = seed_world(tmp_path_factory.mktemp("reports-quiet"))
    conn.close()
    with TestClient(app_with_reports(settings)) as client:
        yield client, settings


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    settings, conn = seed_world(tmp_path_factory.mktemp("reports-live"))
    conn.close()
    live_settings = settings.with_(start_dispatcher=True, workers=1)
    with TestClient(app_with_reports(live_settings)) as client:
        yield client, live_settings


def post(client, body=None, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/api/v2/reports", json=BODY if body is None else body, headers=headers)


def wait(client, job_id, timeout=30):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.get(f"/api/v2/jobs/{job_id}").json()
        if last["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return last
        time.sleep(0.05)
    raise AssertionError(last)


def test_idempotency_same_body_replays_and_different_body_conflicts(quiet):
    client, _settings = quiet
    first = post(client, key="report-same")
    assert first.status_code == 202, first.text
    body = first.json()
    assert set(body) == {"report_id", "job_id", "job"}
    assert body["job"]["operation"] == "report"
    assert body["job"]["job_id"] == body["job_id"]
    assert body["job"]["state"] in {"queued", "running"}
    again = post(client, key="report-same")
    assert again.status_code == 202
    assert again.headers["Idempotent-Replay"] == "true"
    assert again.json()["report_id"] == body["report_id"]
    assert again.json()["job_id"] == body["job_id"]
    other = post(client, {**BODY, "report_type": "full_report"}, key="report-same")
    assert other.status_code == 409
    assert other.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_missing_idempotency_key_creates_distinct_reports(quiet):
    client, _settings = quiet
    first = post(client)
    second = post(client)
    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["report_id"] != second.json()["report_id"]
    assert first.json()["job_id"] != second.json()["job_id"]


def test_unknown_fields_nonfinite_and_bad_ids(quiet):
    client, _settings = quiet
    unknown = post(client, {**BODY, "surprise": 1}, key="bad-field")
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "INVALID_INPUT"
    nonfinite = client.post(
        "/api/v2/reports",
        content=b'{"run_ids": [NaN], "analysis_ids": [], "report_type": "one_page_plan"}',
        headers={"Content-Type": "application/json"},
    )
    assert nonfinite.status_code == 422
    assert nonfinite.json()["code"] == "INVALID_INPUT"
    infinite = client.post(
        "/api/v2/reports",
        content=(
            b'{"run_ids": ["run_fixture_a"], "analysis_ids": [], '
            b'"report_type": "one_page_plan", "weight": Infinity}'
        ),
        headers={"Content-Type": "application/json"},
    )
    assert infinite.status_code == 422
    assert infinite.json()["code"] == "INVALID_INPUT"
    empty = post(client, {**BODY, "run_ids": []})
    assert empty.status_code == 422
    duplicate = post(
        client, {**BODY, "run_ids": ["run_fixture_a", "run_fixture_a"], "analysis_ids": []}
    )
    assert duplicate.status_code == 422
    long_key = post(client, key="k" * 201)
    assert long_key.status_code == 422
    assert long_key.json()["code"] == "INVALID_INPUT"


def test_missing_run_unknown_analysis_and_foreign_context(quiet):
    client, settings = quiet
    conn = connect(settings.db_path)
    before = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    conn.close()
    missing = post(client, {**BODY, "run_ids": ["run_missing"], "analysis_ids": []})
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
    unknown = post(client, {**BODY, "analysis_ids": ["ana_missing"]})
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "NOT_FOUND"
    mixed = post(
        client, {**BODY, "run_ids": ["run_fixture_a", "run_fixture_b"], "analysis_ids": []}
    )
    assert mixed.status_code == 409
    assert mixed.json()["code"] == "VERSION_CONFLICT"
    assert "dependency_diff" in mixed.json()
    version = post(
        client, {**BODY, "run_ids": ["run_fixture_a", "run_fixture_a_v2"], "analysis_ids": []}
    )
    assert version.status_code == 409
    assert version.json()["code"] == "VERSION_CONFLICT"
    foreign = post(client, {**BODY, "analysis_ids": ["ana_fixture_b"]})
    assert foreign.status_code == 409
    assert foreign.json()["code"] == "VERSION_CONFLICT"
    absent = client.get("/api/v2/reports/rpt_missing")
    assert absent.status_code == 404
    assert absent.json()["code"] == "NOT_FOUND"
    conn = connect(settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == before
    conn.close()


def test_queued_failed_and_interrupted_stay_honest(quiet):
    client, settings = quiet
    accepted = post(
        client, {**BODY, "analysis_ids": [], "report_type": "full_report"}, key="queued-1"
    )
    assert accepted.status_code == 202
    report_id = accepted.json()["report_id"]
    job_id = accepted.json()["job_id"]
    queued = client.get(f"/api/v2/reports/{report_id}")
    assert queued.status_code == 200
    view = queued.json()
    assert view["status"] == "queued"
    assert view["report_type"] == "full_report"
    assert view["run_ids"] == ["run_fixture_a"]
    assert view["download_url"] is None
    assert view["final_self_contained_report"] is False
    refused = client.get(f"/api/v2/reports/{report_id}/files/../secret.txt")
    assert refused.status_code == 404
    assert b"OUTSIDE-SECRET" not in refused.content

    conn = connect(settings.db_path)
    directory = settings.reports_dir / report_id
    directory.mkdir(parents=True)
    partial = directory / "placeholder.json"
    partial.write_text("PARTIAL-SECRET\n")
    conn.execute(
        "UPDATE reports SET report_dir = ?, report_hash = ? WHERE report_id = ?",
        (str(directory), file_sha256(partial), report_id),
    )
    conn.execute(
        "UPDATE jobs SET state = 'running', owner = 'test', lease_until = ? WHERE job_id = ?",
        (utcnow(), job_id),
    )
    assert job_id in queue.mark_interrupted(
        conn, "API restarted while the job was running; no valid lease remained"
    )
    conn.close()
    interrupted = client.get(f"/api/v2/reports/{report_id}").json()
    assert interrupted["status"] == "interrupted"
    assert interrupted["job_state"] == "interrupted"
    assert interrupted["download_url"] is None
    assert interrupted["job_error"]["code"] == "INTERRUPTED"
    leaked = client.get(f"/api/v2/reports/{report_id}/files/placeholder.json")
    assert leaked.status_code == 404
    assert b"PARTIAL-SECRET" not in leaked.content

    failed_accept = post(
        client, {**BODY, "run_ids": ["run_fixture_a2"], "analysis_ids": []}, key="fail-1"
    )
    failed_id = failed_accept.json()["report_id"]
    failed_job = failed_accept.json()["job_id"]
    conn = connect(settings.db_path)
    queue.finish(
        conn,
        failed_job,
        JobState.failed,
        error={"code": "JOB_FAILED", "detail": "TEST FIXTURE failure"},
    )
    conn.close()
    failed = client.get(f"/api/v2/reports/{failed_id}").json()
    assert failed["status"] == "failed"
    assert failed["download_url"] is None
    assert failed["job_error"]["code"] == "JOB_FAILED"
    assert failed["final_self_contained_report"] is False


def test_dispatcher_copies_metrics_and_files_route_rejects_escapes(live):
    client, settings = live
    accepted = post(
        client,
        {
            "run_ids": ["run_fixture_a", "run_fixture_a2"],
            "analysis_ids": ["ana_fixture_a"],
            "report_type": "one_page_plan",
        },
        key="live-copy",
    )
    assert accepted.status_code == 202, accepted.text
    report_id = accepted.json()["report_id"]
    job = wait(client, accepted.json()["job_id"])
    assert job["state"] == "succeeded", job
    view = client.get(f"/api/v2/reports/{report_id}")
    assert view.status_code == 200
    body = view.json()
    assert body["status"] == "succeeded"
    assert body["download_url"] == f"/api/v2/reports/{report_id}/files/placeholder.json"
    assert body["final_self_contained_report"] is False
    assert body["artifact_kind"] == "p05-api-placeholder"
    assert (
        "manifest" not in (body["report_hash_scope"] or "")
        or "not a self-contained" in body["report_hash_scope"]
    )
    downloaded = client.get(body["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    document = downloaded.json()
    assert document["final_self_contained_report"] is False
    assert document["artifact_kind"] == "p05-api-placeholder"
    text = downloaded.text
    assert "http://" not in text and "https://" not in text
    stored = client.get(body["download_url"]).json()
    metrics = stored["runs"][0]["metrics"]
    assert metrics[0]["value"] == METRIC
    assert metrics[0]["definition_id"] == "production_kg@stored-fixture-do-not-replace"
    assert metrics[1]["value"] is None and metrics[1]["status"] == "blocked"
    assert stored["runs"][0]["scenario_revision_id"] == "rev_fixture_a"
    assert stored["runs"][0]["candidate_library_hash"] == "b" * 64
    assert stored["runs"][1]["metrics"][0]["value"] == 3456.0
    assert stored["analyses"][0]["stored_result"]["sentinel_metric"] == 42.0
    names = sorted(path.name for path in (settings.reports_dir / report_id).iterdir())
    assert names == ["placeholder.json"]

    secret = settings.reports_dir / "secret.txt"
    secret.write_text("OUTSIDE-SECRET")
    (settings.reports_dir / report_id / "leak.json").symlink_to(secret)
    for rel in (
        "../secret.txt",
        "..%2F..%2Fsecret.txt",
        "notes/../../../secret.txt",
        "/etc/passwd",
        "leak.json",
    ):
        escaped = client.get(f"/api/v2/reports/{report_id}/files/{rel}")
        assert escaped.status_code == 404, rel
        assert b"OUTSIDE-SECRET" not in escaped.content
    missing = client.get(f"/api/v2/reports/{report_id}/files/report.html")
    assert missing.status_code == 404

    path = settings.reports_dir / report_id / "placeholder.json"
    path.unlink()
    withdrawn = client.get(f"/api/v2/reports/{report_id}").json()
    assert withdrawn["job_state"] == "succeeded"
    assert withdrawn["status"] == "failed"
    assert withdrawn["download_url"] is None
    assert withdrawn["job_error"]["code"] == "ASSET_UNAVAILABLE"
    assert client.get(f"/api/v2/reports/{report_id}/files/placeholder.json").status_code == 404
