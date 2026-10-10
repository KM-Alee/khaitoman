"""End-to-end solve path over the TEST FIXTURE pilot + synthetic library (worker processes)."""

import time

import pytest
from fastapi.testclient import TestClient

from aabflow.main import create_app
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


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("solve")
    fx.build_all(tmp)
    sx.build_library(tmp)
    with TestClient(create_app(settings_for(tmp, dispatcher=True))) as c:
        yield c


def wait(client, job_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/v2/jobs/{job_id}").json()
        if j["state"] in ("succeeded", "failed", "cancelled", "interrupted"):
            return j
        time.sleep(0.1)
    raise AssertionError(j)


def solve(client, rev_id, kind="P", key=None):
    h = {"Idempotency-Key": key} if key else {}
    r = client.post(f"/api/v2/scenario-revisions/{rev_id}/solve", json={"plan_kind": kind, "time_limit_s": 5}, headers=h)
    assert r.status_code == 202, r.text
    j = wait(client, r.json()["job_id"])
    assert j["state"] == "succeeded", j
    run = client.get(f"/api/v2/runs/{j['result_ref']}").json()
    return run


def metric(run, mid, field=None):
    return next(m for m in run["metrics"] if m["metric_id"] == mid and m["field_id"] == field)


def test_ladder_b0_b1_p_r(client):
    r = client.post("/api/v2/scenarios", json={"label": "fixture", "request": REQ})
    assert r.status_code == 201, r.text
    rev = r.json()["revision"]
    assert rev["readiness"]["ready"] is True
    assert rev["readiness"]["max_attainable_service"]["tail"] is not None
    rid = rev["revision"]["scenario_revision_id"]
    b0 = solve(client, rid, "B0")
    b1 = solve(client, rid, "B1")
    p = solve(client, rid, "P")
    rr = solve(client, rid, "R")
    for run in (b0, b1, p, rr):
        assert run["run"]["outcome"] == "plan", run["run"]
        assert run["run"]["physical_validation"]["status"] == "passed"
        assert run["bundle_verified"]
    assert {f["family"] for f in b0["selection"]["fields"].values()} == {"baseline_B0"}
    assert b0["run"]["solver_status"] == "FEASIBLE"
    assert b1["run"]["selected_intervention_instance_ids"] == []  # AT05: no new assets at zero capital
    assert metric(b1, "capital_commitment_pkr")["value"] == 0
    pb0, pb1, pp = (metric(x, "production_kg")["value"] for x in (b0, b1, p))
    assert pb1 > pb0 and pp >= pb1
    assert p["run"]["solver_status"] == "OPTIMAL"
    assert rr["run"]["primary_objective"].startswith("worst_case")
    # robust plan's chosen policies are deliverable in all nine states
    for f in rr["selection"]["fields"].values():
        assert len(f["outcomes"]) == 9 and all(o["deliverable"] for o in f["outcomes"].values())
    cmp = client.post("/api/v2/comparisons", json={"run_ids": [b0["run"]["run_id"], b1["run"]["run_id"],
                                                               p["run"]["run_id"]]}).json()
    assert cmp["compatible"] is True and cmp["incremental"][0]["step"] == "B0->B1"
    tl = client.get(f"/api/v2/runs/{p['run']['run_id']}/timeline", params={"field_id": "fixture-a:f3"}).json()
    assert tl["dates"] and any(s["series_id"] == "canal_receipt_m3" for s in tl["series"])
    assert tl["edges"], "network-wide edge flows drive the replay animation"
    acc = client.get(f"/api/v2/runs/{p['run']['run_id']}/accounting").json()
    b = acc["boundaries"]
    assert abs(b["canal_source_withdrawal_m3"] - b["conveyance_loss_m3"] - b["outlet_receipt_m3"]) < 1e-6
    eq = client.get(f"/api/v2/runs/{p['run']['run_id']}/equity", params={"baseline_run_id": b0["run"]["run_id"]}).json()
    assert eq["comparison"]["compatible"] and eq["measure_label"] == "receipt / reference allowance"
    ap = client.get(f"/api/v2/runs/{p['run']['run_id']}/action-plan").json()
    assert ap["available"]
    imp = client.get(f"/api/v2/runs/{rr['run']['run_id']}/impact").json()
    assert all(c["official_indicator"] is False for c in imp["cards"])
    listed = client.get("/api/v2/runs", params={"pilot_id": fx.PILOT_ID}).json()["runs"]
    assert {x["plan_kind"] for x in listed} >= {"B0", "B1", "P", "R"}
