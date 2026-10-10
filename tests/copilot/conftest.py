"""Copilot test app: TEST FIXTURE pilot + synthetic library, real routes, solver and workers."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import aabflow.main as main_mod
from aabflow.copilot.router import router as copilot_router
from tests.fixtures import synthetic as fx
from tests.fixtures import synthetic_science as sx
from tests.fixtures.api_app import settings_for

REQ = {
    "pilot_id": fx.PILOT_ID,
    "pilot_version": fx.VERSION,
    "season_id": fx.SEASON_ID,
    "planning_mode": "season_response",
    "decision_at": "2026-10-10T08:00:00+05:00",
    "weather_scenario_ids": ["dry", "typical", "wet"],
    "supply_profile_id": "nominal-roster-v1",
    "capital_budget_pkr": 300000,
    "operating_budget_pkr": 20000,
    "uncertainty_set_id": f"{fx.SEASON_ID}:release-9",
}


def _routers_with_copilot(orig):
    def inner():
        return [*orig(), copilot_router]

    return inner


def wait_job(client, job_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/v2/jobs/{job_id}").json()
        if j["state"] in ("succeeded", "failed", "cancelled", "interrupted"):
            return j
        time.sleep(0.1)
    raise AssertionError(j)


@pytest.fixture(scope="session")
def app_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("copilot")
    fx.build_all(tmp)
    sx.build_library(tmp)
    fx.build_pilot(tmp, "fixture-b", "test-v1")  # a second permitted pilot for cross-pilot checks
    orig = main_mod._routers
    main_mod._routers = _routers_with_copilot(orig)
    try:
        app = main_mod.create_app(settings_for(tmp, dispatcher=True))
    finally:
        main_mod._routers = orig
    with TestClient(app) as c:
        r = c.post("/api/v2/scenarios", json={"label": "copilot fixture", "request": REQ})
        assert r.status_code == 201, r.text
        rid = r.json()["revision"]["revision"]["scenario_revision_id"]
        runs = {}
        for kind in ("B0", "B1", "P"):
            j = c.post(
                f"/api/v2/scenario-revisions/{rid}/solve",
                json={"plan_kind": kind, "time_limit_s": 5},
            )
            job = wait_job(c, j.json()["job_id"])
            assert job["state"] == "succeeded", job
            runs[kind] = job["result_ref"]
        yield {"client": c, "app": app, "revision_id": rid, "runs": runs, "tmp": tmp}


@pytest.fixture
def client(app_env):
    return app_env["client"]


def context(app_env, **kw):
    ctx = {
        "pilot_id": fx.PILOT_ID,
        "pilot_version": fx.VERSION,
        "season_id": fx.SEASON_ID,
        "scenario_revision_id": app_env["revision_id"],
        "selected_run_id": app_env["runs"]["P"],
        "selected_field_id": "fixture-a:f3",
        "language": "en",
    }
    ctx.update(kw)
    return ctx


def ask(app_env, provider, message, ctx=None, session_id=None, role="planner", timeout=60):
    c = app_env["client"]
    app_env["app"].state.aab.extras["copilot_provider_factory"] = lambda: provider
    if session_id is None:
        s = c.post(
            "/api/v2/copilot/sessions", json={"context": ctx or context(app_env), "role": role}
        )
        assert s.status_code == 201, s.text
        session_id = s.json()["session_id"]
    r = c.post(
        f"/api/v2/copilot/sessions/{session_id}/messages",
        json={"message": message, "context": ctx or context(app_env)},
    )
    assert r.status_code == 202, r.text
    tid = r.json()["turn_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = c.get(f"/api/v2/copilot/turns/{tid}", params={"include_tools": True}).json()
        if t["status"] != "running":
            t["session_id"] = session_id
            return t
        time.sleep(0.05)
    raise AssertionError("turn did not finish")
