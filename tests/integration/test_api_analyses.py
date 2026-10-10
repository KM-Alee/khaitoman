"""M5 analyses over the TEST FIXTURE pilot + synthetic library: frontier (AT09), stress and robust
(AT09/AT10), why-not, sensitivity and synergy (F13). Every point/cell/arm must map to a run record."""

import pytest
from fastapi.testclient import TestClient

from aabflow.main import create_app
from tests.fixtures import synthetic as fx
from tests.fixtures import synthetic_science as sx
from tests.fixtures.api_app import settings_for
from tests.integration.test_api_solve import REQ, metric, solve, wait


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ana")
    fx.build_all(tmp)
    sx.build_library(tmp)
    with TestClient(create_app(settings_for(tmp, dispatcher=True))) as c:
        rid = c.post("/api/v2/scenarios", json={"request": REQ}).json()["revision"]["revision"][
            "scenario_revision_id"
        ]
        p = solve(c, rid, "P")
        r = solve(c, rid, "R")
        yield c, rid, p, r


def analyse(c, kind, body, key=None, timeout=180):
    h = {"Idempotency-Key": key} if key else {}
    r = c.post(f"/api/v2/analyses/{kind}", json=body, headers=h)
    assert r.status_code == 202, r.text
    acc = r.json()
    j = wait(c, acc["job_id"], timeout=timeout)
    assert j["state"] == "succeeded", j
    a = c.get(f"/api/v2/analyses/{acc['analysis_id']}").json()
    assert a["status"] == "completed", a
    return a


def run_exists(c, run_id):
    r = c.get(f"/api/v2/runs/{run_id}")
    assert r.status_code == 200, run_id
    return r.json()


FRONTIER = [
    {"capital_budget_pkr": 0},
    {"capital_budget_pkr": 60000},
    {"capital_budget_pkr": 120000},
    {"capital_budget_pkr": 200000},
    {"capital_budget_pkr": 300000},
    {"capital_budget_pkr": 300000, "minimum_service_ratio": 0.99, "service_group": "tail"},
]


def test_frontier_six_settings_map_to_runs(env):
    c, rid, _, _ = env
    a = analyse(
        c, "frontier", {"base_revision_id": rid, "settings": FRONTIER, "time_limit_per_point_s": 3}
    )
    res = a["result"]
    pts = res["points"]
    assert len(pts) == 6 and res["label"] == "Nondominated among evaluated plans"
    for p in pts:
        assert p["run_id"] in a["child_run_ids"]
        view = run_exists(c, p["run_id"])
        assert view["analysis_id"] == a["analysis_id"]
        if p["outcome"] == "plan":
            assert p["dominance"] in ("nondominated", "dominated", "dominance_unresolved")
            assert view["run"]["objective_value"] == p["objective_value"]
            assert p["capital_commitment_pkr"] <= p["setting"]["capital_budget_pkr"]
        else:
            assert p["dominance"] == "not_applicable" and p["objective_value"] is None
    zero = pts[0]
    assert (
        zero["outcome"] == "plan" and zero["capital_commitment_pkr"] == 0
    )  # AT05 inside the sweep
    prods = [p["objective_value"] for p in pts[:5]]
    assert prods == sorted(prods)  # more capital never hurts in the same finite model
    assert res["counts"]["nondominated"] >= 1
    # the impossible tail floor is reported as infeasible, never placed on the curve
    assert pts[5]["solver_status"] == "INFEASIBLE" and pts[5]["infeasibility_kind"]
    # identical portfolios are deduplicated while keeping the settings that produced them
    same = [p for p in pts if p["same_portfolio_as"]]
    assert all(p["portfolio_key"] for p in same)
    listed = c.get("/api/v2/analyses", params={"kind": "frontier", "base_revision_id": rid}).json()[
        "analyses"
    ]
    assert a["analysis_id"] in {x["analysis_id"] for x in listed}


def test_frontier_requires_six_distinct_settings(env):
    c, rid, _, _ = env
    r = c.post(
        "/api/v2/analyses/frontier", json={"base_revision_id": rid, "settings": FRONTIER[:5]}
    )
    assert r.status_code == 422
    r = c.post(
        "/api/v2/analyses/frontier", json={"base_revision_id": rid, "settings": [FRONTIER[0]] * 6}
    )
    assert r.status_code == 422


def test_fixed_plan_stress_typical_plan(env):
    c, _, p, _ = env
    a = analyse(
        c,
        "stress",
        {"run_id": p["run"]["run_id"], "mode": "fixed_plan", "time_limit_per_cell_s": 2},
    )
    res = a["result"]
    cells = res["cells"]
    assert (
        len(cells) == 9 and len(res["matrix"]["rows"]) == 3 and len(res["matrix"]["columns"]) == 3
    )
    for cell in cells:
        assert cell["run_id"] in a["child_run_ids"]
        run_exists(c, cell["run_id"])
        if cell["deliverable"]:
            assert cell["production_kg"] is not None and cell["violations"] == []
        else:  # AT10: no fabricated achievable yield for impossible cells
            assert cell["production_kg"] is None and cell["violations"]
            v = run_exists(c, cell["run_id"])["run"]
            assert v["outcome"] == "no_plan"
    typical = next(x for x in cells if x["state_id"] == "typical__nominal-roster-v1")
    assert typical["deliverable"]
    assert typical["production_kg"] == pytest.approx(metric(p, "production_kg")["value"])
    und = res["summary"]["undeliverable_state_ids"]
    assert und, "the full-window typical plan cannot be delivered under the 22% shortage"
    w = res["metrics_by_id"]["worst_tested_production_kg"]
    assert w["status"] == "blocked" and w["value"] is None
    assert res["summary"]["conditional_label"]


def test_robust_plan_shares_decisions_across_all_cells(env):
    c, _, p, r = env
    a = analyse(
        c,
        "stress",
        {
            "run_id": r["run"]["run_id"],
            "mode": "fixed_plan",
            "reference_run_id": p["run"]["run_id"],
            "time_limit_per_cell_s": 2,
        },
    )
    res = a["result"]
    assert all(cell["deliverable"] for cell in res["cells"])
    # AT10: one x/z across states -> the fixed-plan cell production equals R's own per-state outcome
    per_state = {}
    for f in r["selection"]["fields"].values():
        for sid, o in f["outcomes"].items():
            per_state[sid] = per_state.get(sid, 0.0) + o["production_kg"]
    for cell in res["cells"]:
        assert cell["production_kg"] == pytest.approx(per_state[cell["state_id"]], rel=1e-9)
        sel = run_exists(c, cell["run_id"])["run"]["selected_candidate_policy_ids"]
        assert sel == r["run"]["selected_candidate_policy_ids"]
    worst = res["metrics_by_id"]["worst_tested_production_kg"]["value"]
    assert worst == pytest.approx(min(per_state.values()))
    assert worst == pytest.approx(r["run"]["objective_value"], abs=1.0)
    fg = res["foregone_typical_output"]
    assert fg["foregone_kg"] is not None and fg["foregone_kg"] >= -1e-6
    imp = c.get(
        f"/api/v2/runs/{r['run']['run_id']}/impact", params={"stress_analysis_id": a["analysis_id"]}
    ).json()
    card = next(
        x
        for x in imp["cards"]
        if any(v["metric_id"] == "sdg_13_1_worst_tested_production_kg" for v in x["values"])
    )
    assert card["official_indicator"] is False


def test_recovery_mode_is_labelled_conditional(env):
    c, _, p, _ = env
    a = analyse(
        c,
        "stress",
        {
            "run_id": p["run"]["run_id"],
            "mode": "recovery_plan",
            "state_ids": ["dry__shortage-22pct-v1", "typical__shortage-22pct-v1"],
            "time_limit_per_cell_s": 2,
        },
    )
    res = a["result"]
    assert "Conditional recovery" in res["label"] and res["metrics_by_id"] == {}
    for cell in res["cells"]:
        assert cell["deliverable"]  # zero-receipt policies always exist, so recovery is feasible
        inst = set(cell["selected_intervention_instance_ids"])
        assert inst <= set(p["run"]["selected_intervention_instance_ids"])


def test_stress_rejects_non_plan_runs(env):
    c, _, _, _ = env
    assert c.post("/api/v2/analyses/stress", json={"run_id": "run_nope"}).status_code == 404


def test_why_not_force_and_exclude(env):
    c, rid, p, _ = env
    chosen = set(p["run"]["selected_intervention_instance_ids"])
    # exclude something the plan uses: a matched alternative with a supported objective interval
    j = min(chosen)
    a = analyse(
        c,
        "why-not",
        {
            "base_revision_id": rid,
            "instance_id": j,
            "action": "exclude",
            "base_run_id": p["run"]["run_id"],
            "time_limit_s": 3,
        },
    )
    res = a["result"]
    alt = res["alternative"]
    run_exists(c, alt["run_id"])
    d = res["difference"]
    if alt["outcome"] == "plan":
        assert d["status"] in ("exact", "interval") and d["upper"] <= 1e-6 + fx_quant(
            alt, res["base"]
        )
        assert res["certificate"]["compatible"] is True
        assert j not in alt["selected_intervention_instance_ids"]
    # forcing something already chosen changes nothing and runs no extra solve
    a2 = analyse(
        c,
        "why-not",
        {
            "base_revision_id": rid,
            "instance_id": j,
            "action": "force",
            "base_run_id": p["run"]["run_id"],
        },
    )
    assert a2["result"]["difference"]["status"] == "no_change"


def fx_quant(a, b):
    return (a.get("quantization_bound") or 0) + (b.get("quantization_bound") or 0)


def test_why_not_ineligible_instance_is_explained_not_priced(env):
    c, rid, p, _ = env
    a = analyse(
        c,
        "why-not",
        {
            "base_revision_id": rid,
            "instance_id": "fixture-a:f4:pond-late",
            "action": "force",
            "base_run_id": p["run"]["run_id"],
        },
    )
    res = a["result"]
    assert res["alternative"]["outcome"] == "rejected"
    assert res["difference"]["status"] == "not_comparable" and res["difference"]["point"] is None
    assert any(
        "commission" in e or "ineligible" in e or "excludes" in e for e in res["explanation"]
    )


def test_synergy_four_matched_arms(env):
    c, rid, _, _ = env
    a = analyse(
        c,
        "synergy",
        {
            "base_revision_id": rid,
            "instance_a": fx.REPAIR,
            "instance_b": fx.LEVEL,
            "other_actions": "reoptimize",
            "time_limit_per_arm_s": 3,
        },
    )
    res = a["result"]
    arms = res["arms"]
    assert set(arms) == {"none", "a", "b", "ab"}
    for k, arm in arms.items():
        view = run_exists(c, arm["run_id"])
        inst = set(view["run"].get("selected_intervention_instance_ids") or [])
        if arm["outcome"] == "plan":
            assert (fx.REPAIR in inst) == (k in ("a", "ab"))
            assert (fx.LEVEL in inst) == (k in ("b", "ab"))
    syn = res["synergy"]
    if all(arm["outcome"] == "plan" for arm in arms.values()):
        o = {k: arms[k]["objective_value"] for k in arms}
        assert syn["incumbent_value"] == pytest.approx(o["ab"] - o["a"] - o["b"] + o["none"])
        assert syn["lower"] <= syn["incumbent_value"] + 1e-6 <= syn["upper"] + 2e-6
        assert res["certificate"]["compatible"]
    else:
        assert syn["value"] is None and syn["status"] == "not_available"


def test_synergy_fixed_other_actions(env):
    c, rid, p, _ = env
    a = analyse(
        c,
        "synergy",
        {
            "base_revision_id": rid,
            "instance_a": fx.REPAIR,
            "instance_b": fx.LEVEL,
            "other_actions": "fixed",
            "base_run_id": p["run"]["run_id"],
            "time_limit_per_arm_s": 3,
        },
    )
    res = a["result"]
    held = set(res["held_fixed_instance_ids"])
    for arm in res["arms"].values():
        if arm["outcome"] == "plan":
            assert held <= set(arm["selected_intervention_instance_ids"])


def test_synergy_rejects_exclusive_pair(env):
    c, rid, _, _ = env
    r = c.post(
        "/api/v2/analyses/synergy",
        json={"base_revision_id": rid, "instance_a": fx.POND_S, "instance_b": fx.POND_L},
    )
    assert r.status_code == 422 and "mutually exclusive" in r.json()["detail"]
    r = c.post(
        "/api/v2/analyses/synergy",
        json={"base_revision_id": rid, "instance_a": fx.POND_S, "instance_b": fx.POND_S},
    )
    assert r.status_code == 422


def test_sensitivity_capital_and_water(env):
    c, rid, _, _ = env
    a = analyse(
        c,
        "sensitivity",
        {
            "base_revision_id": rid,
            "parameter": "capital_budget_pkr",
            "values": [0, 100000, 300000],
            "time_limit_per_point_s": 3,
        },
    )
    res = a["result"]
    assert len(res["points"]) == 3 and len(res["steps"]) == 2
    for pt in res["points"]:
        run_exists(c, pt["run_id"])
    assert res["decision_stable"] is False and res["resolving_measurement"]
    w = analyse(
        c,
        "sensitivity",
        {
            "base_revision_id": rid,
            "parameter": "uniform_reduction_fraction",
            "values": [0.0, 0.1],
            "time_limit_per_point_s": 3,
        },
    )
    step = w["result"]["steps"][0]
    assert step["delta_available_m3"] < 0
    if "marginal_value_per_m3" in step:
        mv = step["marginal_value_per_m3"]
        assert mv["lower"] <= mv["upper"] and "finite difference" in mv["label"]


def test_analysis_idempotency_and_404(env):
    c, rid, _, _ = env
    body = {
        "base_revision_id": rid,
        "parameter": "operating_budget_pkr",
        "values": [10000, 20000],
        "time_limit_per_point_s": 2,
    }
    r1 = c.post("/api/v2/analyses/sensitivity", json=body, headers={"Idempotency-Key": "sens-1"})
    r2 = c.post("/api/v2/analyses/sensitivity", json=body, headers={"Idempotency-Key": "sens-1"})
    assert (
        r1.status_code == r2.status_code == 202
        and r1.json()["analysis_id"] == r2.json()["analysis_id"]
    )
    r3 = c.post(
        "/api/v2/analyses/sensitivity",
        json={**body, "values": [1, 2]},
        headers={"Idempotency-Key": "sens-1"},
    )
    assert r3.status_code == 409
    wait(c, r1.json()["job_id"], timeout=120)
    assert c.get("/api/v2/analyses/ana_nope").status_code == 404
    assert (
        c.post(
            "/api/v2/analyses/why-not", json={"base_revision_id": rid, "instance_id": "nope"}
        ).status_code
        == 422
    )


def test_run_explanations_and_bottlenecks(env):
    c, _rid, p, _ = env
    e = c.get(f"/api/v2/runs/{p['run']['run_id']}/explanations").json()
    sel = {x["instance_id"] for x in e["selected"]}
    assert sel == set(p["run"]["selected_intervention_instance_ids"])
    rej = {x["instance_id"]: x for x in e["rejected"]}
    assert rej["fixture-a:f4:pond-late"]["kind"] == "ineligible"
    assert all(x["opportunity_cost"]["status"] == "needs_solve" for x in e["rejected"])
    b = e["bottlenecks"]
    assert {x["constraint"] for x in b["budgets"]} == {"capital_budget", "operating_budget"}
    assert "does not prove" in b["note"]
    # an infeasible run explains constraint groups and offers explicit (not silent) relaxations
    r = c.post(
        "/api/v2/scenarios",
        json={"request": {**REQ, "minimum_service_ratio": 0.99, "service_group": "tail"}},
    )
    rid2 = r.json()["revision"]["revision"]["scenario_revision_id"]
    run = solve(c, rid2, "P")
    assert run["run"]["outcome"] == "no_plan"
    e2 = c.get(f"/api/v2/runs/{run['run']['run_id']}/explanations").json()
    w = e2["why_no_solution"]
    assert w["relaxation_branches"] and "not proof of physical impossibility" in w["statement"]
