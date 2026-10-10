"""M3/M5 acceptance on the REAL published pilot-a libraries (AT05-AT10, AT12). Slow: real candidate
libraries with exact AquaCrop outcomes; skipped when the pilot or the 2027-28 library is absent."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aabflow.config import DATA_DIR, Settings
from aabflow.main import create_app
from tests.integration.test_api_solve import wait

pytestmark = pytest.mark.scientific
SEASON = "wheat-rabi-2027-28"
LIB = Path(DATA_DIR) / "libraries" / "pilot-a" / SEASON / "latest.json"
REQ = {
    "pilot_id": "pilot-a",
    "pilot_version": "reviewed-v1",
    "season_id": SEASON,
    "planning_mode": "capital_planning",
    "decision_at": "2026-10-10T08:00:00+05:00",
    "weather_scenario_ids": ["dry", "typical", "wet"],
    "supply_profile_id": "nominal-roster-v1",
    "capital_budget_pkr": 3000000,
    "operating_budget_pkr": 400000,
    "uncertainty_set_id": f"pilot-a:{SEASON}:release-9",
}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    if not LIB.exists():
        pytest.skip("pilot-a wheat-rabi-2027-28 library not published")
    tmp = tmp_path_factory.mktemp("real")
    data = tmp / "data"  # read-only links to the published data; this test's runs stay in tmp
    data.mkdir()
    for d in ("pilots", "libraries", "models", "experiments"):
        (data / d).symlink_to(Path(DATA_DIR) / d, target_is_directory=True)
    s = Settings(
        data_dir=data,
        db_path=tmp / "app.sqlite",
        web_dist=tmp / "nowd",
        workers=2,
        solver_workers=2,
    )
    with TestClient(create_app(s)) as c:
        r = c.post("/api/v2/scenarios", json={"request": REQ})
        assert r.status_code == 201, r.text
        rid = r.json()["revision"]["revision"]["scenario_revision_id"]
        runs = {k: solve(c, rid, k) for k in ("B0", "B1", "P", "R")}
        yield c, rid, runs


def solve(c, rid, kind):
    r = c.post(
        f"/api/v2/scenario-revisions/{rid}/solve", json={"plan_kind": kind, "time_limit_s": 30}
    )
    j = wait(c, r.json()["job_id"], timeout=600)
    assert j["state"] == "succeeded", j
    return c.get(f"/api/v2/runs/{j['result_ref']}").json()


def m(run, mid):
    return next(
        x["value"] for x in run["metrics"] if x["metric_id"] == mid and x["field_id"] is None
    )


def analyse(c, kind, body):
    a = c.post(f"/api/v2/analyses/{kind}", json=body)
    assert a.status_code == 202, a.text
    j = wait(c, a.json()["job_id"], timeout=900)
    assert j["state"] == "succeeded", j
    return c.get(f"/api/v2/analyses/{a.json()['analysis_id']}").json()


def test_ladder_on_real_pilot(env):
    c, _, runs = env
    for k, run in runs.items():
        assert run["run"]["outcome"] == "plan", (k, run["run"])
        assert run["run"]["physical_validation"]["status"] == "passed"
    b0, b1, p = (m(runs[k], "production_kg") for k in ("B0", "B1", "P"))
    assert b0 < b1 <= p  # B1 re-operates existing assets; P adds investments
    assert runs["B1"]["run"]["selected_intervention_instance_ids"] == []  # AT05
    assert m(runs["B1"], "capital_commitment_pkr") == 0
    assert m(runs["P"], "capital_commitment_pkr") <= REQ["capital_budget_pkr"]
    assert m(runs["P"], "operating_cost_pkr") <= REQ["operating_budget_pkr"]  # AT12 pumping on opex
    cmp = c.post(
        "/api/v2/comparisons",
        json={"run_ids": [runs[k]["run"]["run_id"] for k in ("B0", "B1", "P")]},
    )
    assert cmp.json()["compatible"] is True  # AT08


def test_live_budget_change_resolves(env):
    c, rid, runs = env  # AT06
    r = c.post(
        f"/api/v2/scenarios/{c.get(f'/api/v2/scenario-revisions/{rid}').json()['revision']['scenario_id']}"
        "/revisions",
        json={"parent_revision_id": rid, "changes": {"capital_budget_pkr": 400000}},
    )
    assert r.status_code == 201, r.text
    small = solve(c, r.json()["revision"]["scenario_revision_id"], "P")
    assert small["run"]["outcome"] == "plan"
    assert m(small, "capital_commitment_pkr") <= 400000
    assert set(small["run"]["selected_intervention_instance_ids"]) != set(
        runs["P"]["run"]["selected_intervention_instance_ids"]
    )


def test_frontier_and_stress_on_real_pilot(env):
    c, rid, runs = env
    fr = analyse(
        c,
        "frontier",
        {
            "base_revision_id": rid,
            "time_limit_per_point_s": 15,
            "settings": [{"capital_budget_pkr": v} for v in (0, 500000, 1500000, 3000000, 8000000)]
            + [
                {
                    "capital_budget_pkr": 3000000,
                    "minimum_service_ratio": 0.95,
                    "service_group": "tail",
                }
            ],
        },
    )
    pts = fr["result"]["points"]
    assert len(pts) == 6 and all(p.get("run_id") for p in pts)  # AT09
    assert pts[-1]["solver_status"] == "INFEASIBLE" and pts[-1]["dominance"] == "not_applicable"
    assert fr["result"]["counts"]["nondominated"] >= 2
    st = analyse(
        c,
        "stress",
        {"run_id": runs["R"]["run"]["run_id"], "reference_run_id": runs["P"]["run"]["run_id"]},
    )
    cells = st["result"]["cells"]
    assert len(cells) == 9 and all(cell["deliverable"] and cell["run_id"] for cell in cells)  # AT10
    assert st["result"]["foregone_typical_output"]["foregone_kg"] >= 0
    sp = analyse(c, "stress", {"run_id": runs["P"]["run"]["run_id"]})
    for cell in sp["result"]["cells"]:
        if not cell["deliverable"]:
            assert cell["production_kg"] is None and cell["violations"]
