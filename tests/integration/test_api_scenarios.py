"""Scenario validation, idempotency, revisions and AT05/AT06/AT07/AT12 over the TEST FIXTURE."""

import copy
import json

import pytest
from fastapi.testclient import TestClient

from aabflow.main import create_app
from tests.fixtures import synthetic as fx
from tests.fixtures import synthetic_science as sx
from tests.fixtures.api_app import settings_for
from tests.integration.test_api_solve import REQ, metric, solve


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("scen")
    fx.build_all(tmp)
    sx.build_library(tmp)
    with TestClient(create_app(settings_for(tmp, dispatcher=True))) as c:
        yield c


def req(**kw):
    r = copy.deepcopy(REQ)
    r.update(kw)
    return r


def create(client, **kw):
    r = client.post("/api/v2/scenarios", json={"request": req(**kw)})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize(
    "changes,field,status",
    [
        ({"planning_mode": "historical_replay"}, "planning_mode", 422),
        ({"weather_scenario_ids": ["monsoon"]}, "weather_scenario_ids", 422),
        ({"supply_profile_id": "nope"}, "supply_profile_id", 422),
        ({"optimization_mode": "worst_case", "uncertainty_set_id": None}, "request", 422),
        ({"objective": "irrigation_contribution_pkr"}, "objective", 422),
        ({"forced_instance_ids": ["fixture-a:f4:pond-late"]}, "forced_instance_ids", 422),
        (
            {"allowed_intervention_instance_ids": ["fixture-a:f2:level-nocost"]},
            "allowed_intervention_instance_ids",
            422,
        ),
        ({"blocked_edge_ids": ["e-nope"]}, "blocked_edge_ids", 422),
        ({"decision_at": "2026-10-10T08:00:00"}, "request", 422),
        ({"uniform_reduction_fraction": 22}, "request.uniform_reduction_fraction", 422),
        ({"minimum_service_ratio": 0.5}, "request", 422),
        ({"season_id": "nope-season"}, "season_id", 404),
        ({"pilot_id": "nope"}, "pilot_id", 404),
    ],
)
def test_typed_validation_errors(client, changes, field, status):
    r = client.post("/api/v2/scenarios", json={"request": req(**changes)})
    assert r.status_code == status, r.text
    body = r.json()
    assert body["code"] == ("INVALID_INPUT" if status == 422 else "NOT_FOUND")
    assert any(k.startswith(field) for k in body["fields"]), body


def test_unknown_request_fields_rejected(client):
    r = client.post("/api/v2/scenarios", json={"request": {**REQ, "shortage_percent": 22}})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT"


def test_idempotency_same_and_conflict(client):
    body = {"request": REQ, "label": "idem"}
    a = client.post("/api/v2/scenarios", json=body, headers={"Idempotency-Key": "k-1"})
    b = client.post("/api/v2/scenarios", json=body, headers={"Idempotency-Key": "k-1"})
    assert a.status_code == b.status_code == 201
    assert a.json()["scenario_id"] == b.json()["scenario_id"]
    c = client.post(
        "/api/v2/scenarios", json={**body, "label": "other"}, headers={"Idempotency-Key": "k-1"}
    )
    assert c.status_code == 409 and c.json()["code"] == "IDEMPOTENCY_CONFLICT"
    rid = a.json()["revision"]["revision"]["scenario_revision_id"]
    j1 = client.post(
        f"/api/v2/scenario-revisions/{rid}/solve",
        json={"plan_kind": "B1"},
        headers={"Idempotency-Key": "s"},
    )
    j2 = client.post(
        f"/api/v2/scenario-revisions/{rid}/solve",
        json={"plan_kind": "B1"},
        headers={"Idempotency-Key": "s"},
    )
    assert j1.json()["job_id"] == j2.json()["job_id"]
    j3 = client.post(
        f"/api/v2/scenario-revisions/{rid}/solve",
        json={"plan_kind": "P"},
        headers={"Idempotency-Key": "s"},
    )
    assert j3.status_code == 409


def test_semantic_hash_ignores_set_order_and_revisions_are_immutable(client):
    a = create(client)["revision"]["revision"]
    b = create(client, weather_scenario_ids=["wet", "typical", "dry"])["revision"]["revision"]
    assert a["semantic_hash"] == b["semantic_hash"]
    r = client.post(
        f"/api/v2/scenarios/{a['scenario_id']}/revisions",
        json={
            "parent_revision_id": a["scenario_revision_id"],
            "changes": {"capital_budget_pkr": 50000},
        },
    )
    assert r.status_code == 201, r.text
    child = r.json()
    assert child["revision"]["parent_revision_id"] == a["scenario_revision_id"]
    assert child["revision"]["semantic_hash"] != a["semantic_hash"] and child["is_head"]
    again = client.get(f"/api/v2/scenario-revisions/{a['scenario_revision_id']}").json()
    assert (
        again["revision"]["request"]["capital_budget_pkr"] == REQ["capital_budget_pkr"]
        and not again["is_head"]
    )
    wrong = client.post(
        f"/api/v2/scenarios/{b['scenario_id']}/revisions",
        json={"parent_revision_id": a["scenario_revision_id"], "changes": {}},
    )
    assert wrong.status_code == 409 and wrong.json()["code"] == "VERSION_CONFLICT"
    bad = client.post(
        f"/api/v2/scenarios/{a['scenario_id']}/revisions",
        json={
            "parent_revision_id": a["scenario_revision_id"],
            "changes": {"capital_budget_pkr": -1},
        },
    )
    assert bad.status_code == 422
    sc = client.get(f"/api/v2/scenarios/{a['scenario_id']}").json()
    assert len(sc["revisions"]) == 2


def _request_of(client, run):
    rid = run["run"]["scenario_revision_id"]
    body = client.get(f"/api/v2/scenario-revisions/{rid}")
    assert body.status_code == 200, body.text
    return body.json()["revision"]["request"]


def test_at05_zero_capital_no_new_assets(client):
    """AT05: zero capital produces no new assets, and a competent no-capital plan is available."""
    rid = create(client, capital_budget_pkr=0)["revision"]["revision"]["scenario_revision_id"]
    p = solve(client, rid, "P")
    b0 = solve(client, rid, "B0")
    b1 = solve(client, rid, "B1")
    assert p["run"]["selected_intervention_instance_ids"] == []
    assert metric(p, "capital_commitment_pkr")["value"] == 0
    assert metric(p, "new_instances_count")["value"] == 0
    assert b1["run"]["outcome"] == "plan"
    assert b1["run"]["physical_validation"]["status"] == "passed"
    assert b1["run"]["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert b1["run"]["selected_intervention_instance_ids"] == []
    assert metric(b1, "capital_commitment_pkr")["value"] == 0
    assert metric(b1, "production_kg")["value"] > metric(b0, "production_kg")["value"]
    compared = client.post(
        "/api/v2/comparisons",
        json={"run_ids": [b1["run"]["run_id"], p["run"]["run_id"]]},
    )
    assert compared.status_code == 201, compared.text
    body = compared.json()
    assert body["compatible"] is True
    assert {row["run_id"] for row in body["plans"]} == {
        b1["run"]["run_id"],
        p["run"]["run_id"],
    }


def test_at06_binding_change_changes_plan_and_nonbinding_does_not(client):
    s = create(client)
    rid = s["revision"]["revision"]["scenario_revision_id"]
    base = solve(client, rid, "P")
    low = client.post(
        f"/api/v2/scenarios/{s['scenario_id']}/revisions",
        json={"parent_revision_id": rid, "changes": {"capital_budget_pkr": 100000}},
    ).json()
    low_run = solve(client, low["revision"]["scenario_revision_id"], "P")
    assert low_run["run"]["run_id"] != base["run"]["run_id"]
    assert low_run["run"]["outcome"] == "plan"
    assert low_run["run"]["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert (
        low_run["run"]["selected_candidate_policy_ids"]
        != base["run"]["selected_candidate_policy_ids"]
    )
    assert metric(low_run, "capital_commitment_pkr")["value"] <= 100000
    same = client.post(
        f"/api/v2/scenarios/{s['scenario_id']}/revisions",
        json={"parent_revision_id": rid, "changes": {"operating_budget_pkr": 25000}},
    ).json()
    same_run = solve(client, same["revision"]["scenario_revision_id"], "P")
    assert (
        same_run["run"]["selected_candidate_policy_ids"]
        == base["run"]["selected_candidate_policy_ids"]
    )
    # the earlier run keeps its ledger and verified bundle
    again = client.get(f"/api/v2/runs/{base['run']['run_id']}").json()
    assert again["bundle_verified"] and again["run"] == base["run"]
    deficit = client.post(
        f"/api/v2/scenarios/{s['scenario_id']}/revisions",
        json={"parent_revision_id": rid, "changes": {"uniform_reduction_fraction": 0.3}},
    ).json()
    d_run = solve(client, deficit["revision"]["scenario_revision_id"], "P")
    assert d_run["run"]["run_id"] != base["run"]["run_id"]
    assert d_run["run"]["outcome"] == "plan"
    assert d_run["run"]["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert metric(d_run, "production_kg")["value"] < metric(base, "production_kg")["value"]
    for f in d_run["selection"]["fields"].values():
        assert f["receipt_volume_m3"] <= 3 * sx.WINDOW_M3 * 0.7 + 1e-6


def test_at07_coverage_and_finite_infeasibility(client):
    s = create(client, minimum_service_ratio=0.95, service_group="tail")
    rev = s["revision"]
    codes = [w["code"] for w in rev["readiness"]["warnings"]]
    assert "SERVICE_FLOOR_ABOVE_ATTAINABLE" in codes
    run = solve(client, rev["revision"]["scenario_revision_id"], "P")
    r = run["run"]
    assert r["outcome"] == "no_plan" and r["solver_status"] == "INFEASIBLE"
    assert r["infeasibility_kind"] == "finite_candidate_incompatibility"
    assert r["proof_scope"] == "finite_candidate_library"
    assert run["metrics"] == []
    assert "service floor" in json.dumps(r["diagnostics"])
    cov = client.get(f"/api/v2/runs/{r['run_id']}/coverage").json()
    assert cov["proof_scope"] == "finite_candidate_library" and len(cov["fields"]) == 4
    assert all(c["library_candidates"] > 0 for c in cov["fields"])
    assert "not evidence" in cov["note"] and "physical impossibility" in cov["note"]
    explained = client.get(f"/api/v2/runs/{r['run_id']}/explanations").json()
    statement = explained["why_no_solution"]["statement"]
    assert explained["proof_scope"] == "finite_candidate_library"
    assert "finite candidate library" in statement
    assert "not" in statement and "proof of physical impossibility" in statement
    assert r["infeasibility_kind"] != "bound_contradiction"
    ok = solve(
        client,
        create(client, minimum_service_ratio=0.8, service_group="tail")["revision"]["revision"][
            "scenario_revision_id"
        ],
        "P",
    )
    assert ok["run"]["solver_status"] == "OPTIMAL"
    assert ok["run"]["proof_scope"] == "finite_candidate_library"
    ok_cov = client.get(f"/api/v2/runs/{ok['run']['run_id']}/coverage").json()
    assert ok_cov["proof_scope"] == "finite_candidate_library"
    assert metric(ok, "tail_min_service_ratio")["value"] >= 0.8 - 1e-9
    assert (
        ok["run"]["shared_configuration_id"] == sx.CFG_REP
    )  # only the repair reaches the tail floor


def test_at08_matched_share_conditions_nonmatched_labelled(client):
    """AT08: matched comparisons share weather, crop/input state, and budget semantics."""
    created = create(client)
    rid = created["revision"]["revision"]["scenario_revision_id"]
    b1 = solve(client, rid, "B1")
    integrated = solve(client, rid, "P")
    matched = client.post(
        "/api/v2/comparisons",
        json={"run_ids": [b1["run"]["run_id"], integrated["run"]["run_id"]]},
    )
    assert matched.status_code == 201, matched.text
    body = matched.json()
    assert body["compatible"] is True
    assert body["labels"]["comparison"] == "matched comparison"
    shared = {row["condition"]: row["value"] for row in body["certificate"]["shared"]}
    assert shared["season_id"] == REQ["season_id"]
    assert shared["initial_state"] == "library-declared initial soil and pond state"
    assert any("typical" in state for state in shared["states"])
    assert not any(row["kind"] == "non_causal" for row in body["certificate"]["differences"])
    left, right = _request_of(client, b1), _request_of(client, integrated)
    for key in (
        "weather_scenario_ids",
        "season_id",
        "supply_profile_id",
        "capital_budget_pkr",
        "operating_budget_pkr",
    ):
        assert left[key] == right[key]
    dry = create(client, weather_scenario_ids=["dry"])
    dry_run = solve(client, dry["revision"]["revision"]["scenario_revision_id"], "P")
    labelled = client.post(
        "/api/v2/comparisons",
        json={"run_ids": [integrated["run"]["run_id"], dry_run["run"]["run_id"]]},
    )
    assert labelled.status_code == 201, labelled.text
    other = labelled.json()
    assert other["compatible"] is False
    assert other["labels"]["comparison"] == "non-matched comparison: differences are not causal"
    assert any(
        row["condition"] == "states" and row["kind"] == "non_causal"
        for row in other["certificate"]["differences"]
    )
    assert other["deltas"]
    assert all(row["causal"] is False for row in other["deltas"])


def test_at12_shared_cost_once_pond_land_pumping_budget(client):
    """AT12: shared cost is charged once, pond land is removed once, pumping is on the operating budget."""
    p = solve(client, create(client)["revision"]["revision"]["scenario_revision_id"], "P")
    insts = p["run"]["selected_intervention_instance_ids"]
    assert fx.REPAIR in insts
    expected = 200000 + sum(60000 for i in insts if i == fx.LEVEL)
    assert metric(p, "capital_commitment_pkr")["value"] == expected
    forced = solve(
        client,
        create(client, forced_instance_ids=[fx.POND_S])["revision"]["revision"][
            "scenario_revision_id"
        ],
        "P",
    )
    assert fx.POND_S in forced["run"]["selected_intervention_instance_ids"]
    footprint_ha = 500 / 10000
    gross_ha = fx.AREAS_HA["fixture-a:f3"]
    cropped = metric(forced, "field_cropped_area_ha", "fixture-a:f3")["value"]
    assert cropped == pytest.approx(gross_ha - footprint_ha)
    assert cropped == pytest.approx(0.85)
    assert abs(cropped - (gross_ha - 2 * footprint_ha)) > 1e-4
    nopump = solve(
        client,
        create(client, operating_budget_pkr=0)["revision"]["revision"]["scenario_revision_id"],
        "B1",
    )
    assert all(f["pump_volume_m3"] == 0 for f in nopump["selection"]["fields"].values())
    assert metric(nopump, "operating_cost_pkr")["value"] == 0
    pumped = solve(client, create(client)["revision"]["revision"]["scenario_revision_id"], "B1")
    pumping = metric(pumped, "pumping_cost_pkr")["value"]
    operating = metric(pumped, "operating_cost_pkr")["value"]
    assert operating == pumping > 0
    assert operating <= REQ["operating_budget_pkr"]


def test_groundwater_permission_and_blocked_edge(client):
    nogw = solve(
        client,
        create(client, permit_groundwater=False)["revision"]["revision"]["scenario_revision_id"],
        "B1",
    )
    assert all(f["pump_volume_m3"] == 0 for f in nogw["selection"]["fields"].values())
    blocked = solve(
        client,
        create(client, blocked_edge_ids=["e-tail"])["revision"]["revision"]["scenario_revision_id"],
        "P",
    )
    for fid in ("fixture-a:f3", "fixture-a:f4"):
        assert blocked["selection"]["fields"][fid]["receipt_volume_m3"] == 0


def test_robust_requires_uncertainty_set(client):
    rid = create(client, uncertainty_set_id=None)["revision"]["revision"]["scenario_revision_id"]
    r = client.post(f"/api/v2/scenario-revisions/{rid}/solve", json={"plan_kind": "R"})
    assert r.status_code == 422


def test_unknown_ids_404(client):
    assert client.get("/api/v2/runs/run_nope").status_code == 404
    assert client.get("/api/v2/scenario-revisions/rev_nope").status_code == 404
    assert client.post("/api/v2/scenario-revisions/rev_nope/solve", json={}).status_code == 404


def test_invalid_plan_and_missing_library(tmp_path):
    fx.build_all(tmp_path)
    sx.build_library(tmp_path, invalid_family="leveled")
    with TestClient(create_app(settings_for(tmp_path, dispatcher=True))) as c:
        rid = create(c)["revision"]["revision"]["scenario_revision_id"]
        run = solve(c, rid, "P")
        assert run["run"]["outcome"] == "invalid_plan"
        assert run["run"]["physical_validation"]["status"] == "failed"
        assert run["metrics"] == []
        ap = c.get(f"/api/v2/runs/{run['run']['run_id']}/action-plan").json()
        assert ap["available"] is False
        late = c.post(
            "/api/v2/scenarios",
            json={
                "request": req(
                    season_id=fx.SEASON_LATE,
                    planning_mode="capital_planning",
                    uncertainty_set_id=None,
                )
            },
        )
        assert late.status_code == 201
        lrev = late.json()["revision"]
        assert lrev["readiness"]["ready"] is False
        r = c.post(
            f"/api/v2/scenario-revisions/{lrev['revision']['scenario_revision_id']}/solve", json={}
        )
        assert r.status_code == 503 and r.json()["code"] == "ASSET_UNAVAILABLE"


def test_stale_library_version_conflict(tmp_path):
    fx.build_all(tmp_path)
    h = sx.build_library(tmp_path)
    p = tmp_path / "libraries" / fx.PILOT_ID / fx.SEASON_ID / h / "library.json"
    doc = json.loads(p.read_text())
    doc["pilot_version"] = "older-v0"
    p.write_text(json.dumps(doc))
    with TestClient(create_app(settings_for(tmp_path))) as c:
        r = c.post("/api/v2/scenarios", json={"request": REQ})
        assert r.status_code == 409 and r.json()["code"] == "VERSION_CONFLICT"
        assert r.json()["dependency_diff"]["library_pilot_version"] == "older-v0"
