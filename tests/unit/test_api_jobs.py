"""Job runtime (T9.4): process-pool execution, SSE resume, cancellation, restart recovery."""

import time

import pytest
from fastapi.testclient import TestClient

from aabflow.jobs import queue
from aabflow.main import create_app
from aabflow.repositories.sqlite import connect, init_db
from tests.fixtures.api_app import settings_for


def wait_state(client, job_id, states, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/v2/jobs/{job_id}").json()
        if j["state"] in states:
            return j
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} stuck in {j['state']}")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("jobs")
    settings = settings_for(tmp, dispatcher=True)
    with TestClient(create_app(settings)) as c:
        yield c, settings


def enqueue(settings, op, payload):
    conn = connect(settings.db_path)
    try:
        return queue.enqueue(conn, op, payload, "h-" + op)
    finally:
        conn.close()


def test_job_runs_in_worker_and_streams_resumable_events(env):
    client, settings = env
    jid = enqueue(settings, "test.sleep", {"steps": 3, "step_s": 0.05})
    j = wait_state(client, jid, {"succeeded"})
    assert j["progress"] == 1.0 and '"slept_steps": 3' in j["result_ref"].replace(":", ": ")
    with client.stream("GET", f"/api/v2/jobs/{jid}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    ids = [int(line[4:]) for line in text.splitlines() if line.startswith("id: ")]
    assert ids == sorted(ids) and len(ids) >= 5
    assert "event: result" in text
    with client.stream(
        "GET", f"/api/v2/jobs/{jid}/events", headers={"Last-Event-ID": str(ids[2])}
    ) as r:
        resumed = [
            int(line[4:]) for line in "".join(r.iter_text()).splitlines() if line.startswith("id: ")
        ]
    assert resumed == ids[3:]


def test_failed_job_records_error(env):
    client, settings = env
    jid = enqueue(settings, "test.fail", {"message": "boom"})
    j = wait_state(client, jid, {"failed"})
    assert j["error"]["code"] == "JOB_FAILED" and "boom" in j["error"]["detail"]


def test_cooperative_cancellation_is_idempotent(env):
    client, settings = env
    jid = enqueue(settings, "test.sleep", {"steps": 200, "step_s": 0.05})
    wait_state(client, jid, {"running"})
    a = client.post(f"/api/v2/jobs/{jid}/cancel").json()
    assert a["state"] in ("cancel_requested", "cancelled")
    j = wait_state(client, jid, {"cancelled"})
    assert j["state"] == "cancelled"
    assert client.post(f"/api/v2/jobs/{jid}/cancel").json()["state"] == "cancelled"
    assert client.get("/api/v2/jobs/nope").status_code == 404
    assert client.post("/api/v2/jobs/nope/cancel").status_code == 404


def test_queued_cancel_and_restart_marks_running_interrupted(tmp_path):
    settings = settings_for(tmp_path)
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    queued = queue.enqueue(conn, "test.sleep", {}, "h")
    assert queue.request_cancel(conn, queued)["state"] == "cancelled"
    stuck = queue.enqueue(conn, "test.sleep", {"steps": 1}, "h2")
    assert queue.claim_next(conn, "old-owner", 60) == stuck
    waiting = queue.enqueue(conn, "test.sleep", {"steps": 1, "step_s": 0.01}, "h3")
    conn.close()
    with TestClient(create_app(settings.with_(start_dispatcher=True))) as client:
        j = client.get(f"/api/v2/jobs/{stuck}").json()
        assert j["state"] == "interrupted" and j["error"]["code"] == "INTERRUPTED"
        # a job that never started is still executed after restart
        assert wait_state(client, waiting, {"succeeded"})["state"] == "succeeded"


def test_claim_is_atomic(tmp_path):
    settings = settings_for(tmp_path)
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    jid = queue.enqueue(conn, "test.sleep", {}, "h")
    other = connect(settings.db_path)
    assert queue.claim_next(conn, "a", 10) == jid
    assert queue.claim_next(other, "b", 10) is None
    assert queue.heartbeat(other, jid, "b", 10) is None
    assert queue.heartbeat(conn, jid, "a", 10) == "running"
