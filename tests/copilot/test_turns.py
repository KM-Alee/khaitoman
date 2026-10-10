"""Copilot turns through the real routes, tools, solver workers and validation (scripted model)."""

from __future__ import annotations

from aabflow.copilot.provider import ProviderError
from tests.copilot.conftest import ask
from tests.copilot.fakes import ScriptedProvider, final


def _out(outputs, name, i=0):
    return outputs[name][i]


def test_read_turn_with_metric_card(app_env):
    p_run = app_env["runs"]["P"]

    def answer(o):
        run = _out(o, "inspect_run")
        prod = next(m for m in run["metrics"] if m["metric_id"] == "production_kg")
        return final(
            [
                {
                    "type": "text",
                    "text": f"Run {p_run} is {run['solver_status']} and produces {prod['value']:,.0f} kg.",
                    "citations": [p_run],
                },
                {"type": "metric", "metric_id": "production_kg", "run_id": p_run},
            ]
        )

    prov = ScriptedProvider(
        [lambda o: [("inspect_run", {"run_id": None, "field_id": None})], answer]
    )
    t = ask(app_env, prov, "How much does the selected plan produce?")
    assert t["status"] == "completed", t
    blocks = t["answer"]["blocks"]
    assert t["answer"]["validated"] is True, t["answer"]
    card = next(b for b in blocks if b["type"] == "metric")
    assert (
        card["run_id"] == p_run
        and card["value"] > 0
        and card["unit"] == "kg"
        and card["basis"] == "model_output"
    )
    assert prov.requests[1]["previous_response_id"]  # loop continues the same response chain
    assert t["tool_calls"][0]["tool"] == "inspect_run"
    assert t["prompt_version"] and t["tool_schema_version"].startswith("tools-")


def test_invented_number_is_regenerated_then_withheld(app_env):
    p_run = app_env["runs"]["P"]
    bad = final(
        [{"type": "text", "text": f"Run {p_run} produces 987,654 kg.", "citations": [p_run]}]
    )
    prov = ScriptedProvider(
        [lambda o: [("inspect_run", {"run_id": None, "field_id": None})], bad, bad]
    )
    t = ask(app_env, prov, "How much?")
    assert t["status"] == "completed"
    assert len(prov.requests) == 3  # one regeneration request
    regen_feedback = prov.requests[2]["input"][0]["output"]
    assert "987,654" in regen_feedback
    text = next(b for b in t["answer"]["blocks"] if b["type"] == "text")
    assert "987,654" not in text["text"] and text.get("withheld") is True
    assert t["answer"]["validated"] is False


def test_unreturned_ids_and_cross_context_cards_rejected(app_env):
    other = "run_doesnotexist"
    ans = final(
        [
            {"type": "metric", "metric_id": "production_kg", "run_id": other},
            {"type": "text", "text": "See the plan.", "citations": [other]},
        ]
    )
    prov = ScriptedProvider([ans, ans])
    t = ask(app_env, prov, "show")
    assert all(b.get("run_id") != other for b in t["answer"]["blocks"])
    assert any("could not be verified" in (b.get("text") or "") for b in t["answer"]["blocks"])


def test_provider_disconnect_has_no_invented_result(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [("inspect_run", {"run_id": None, "field_id": None})],
            ProviderError("PROVIDER_UNAVAILABLE", "cannot reach the hosted model", retryable=True),
        ]
    )
    t = ask(app_env, prov, "What is the production?")
    assert t["status"] == "provider_unavailable"
    assert t["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert t["answer"]["deterministic"] is True
    assert not any(b["type"] == "metric" for b in t["answer"]["blocks"])


def test_branch_lakh_budget_solve_and_compare(app_env):
    rev, p_run = app_env["revision_id"], app_env["runs"]["P"]
    seen = {}

    def compare(o):
        br = _out(o, "branch_scenario")
        assert br["ok"], br
        seen["branch"] = br
        new_run = br["solve"]["run"]["run_id"]
        return [("compare_runs", {"run_ids": [p_run, new_run]})]

    def answer(o):
        cmp = _out(o, "compare_runs")
        seen["cmp"] = cmp
        return final(
            [
                {
                    "type": "text",
                    "text": "Lower budget compared with the current plan.",
                    "citations": [cmp["comparison_id"]],
                },
                {"type": "comparison", "comparison_id": cmp["comparison_id"]},
            ]
        )

    prov = ScriptedProvider(
        [
            lambda o: [
                (
                    "branch_scenario",
                    {
                        "base_revision_id": None,
                        "label": "1 lakh budget",
                        "solve": True,
                        "plan_kind": None,
                        "wait_s": 40,
                        "changes": {
                            "capital_budget": "1 lakh",
                            "operating_budget": None,
                            "supply_profile_id": None,
                            "uniform_reduction_percent": None,
                            "weather_scenario_ids": None,
                            "service_preset": None,
                            "minimum_service_ratio": None,
                            "service_group": None,
                            "allowed_intervention_instance_ids": None,
                            "forced_instance_ids": None,
                            "excluded_instance_ids": None,
                            "permit_groundwater": None,
                            "blocked_edge_ids": None,
                        },
                    },
                )
            ],
            compare,
            answer,
        ]
    )
    t = ask(app_env, prov, "What if the capital budget is 1 lakh?")
    assert t["status"] == "completed", t
    br = seen["branch"]
    assert any("PKR 100,000" in c for c in br["applied_changes"])
    rv = app_env["client"].get(f"/api/v2/scenario-revisions/{br['scenario_revision_id']}").json()
    assert rv["revision"]["request"]["capital_budget_pkr"] == 100000
    assert rv["revision"]["parent_revision_id"] == rev
    parent = app_env["client"].get(f"/api/v2/scenario-revisions/{rev}").json()
    assert parent["revision"]["request"]["capital_budget_pkr"] == 300000  # parent unchanged
    assert seen["cmp"]["compatible"] in (True, False)
    kinds = [b["type"] for b in t["answer"]["blocks"]]
    assert "comparison" in kinds and "action" in kinds  # created branch/run offered as action cards
    assert len(t["job_ids"]) == 1


def test_retry_does_not_duplicate_branch(app_env):
    args = {
        "base_revision_id": None,
        "label": None,
        "solve": False,
        "plan_kind": None,
        "wait_s": None,
        "changes": {
            "capital_budget": "2 lakh",
            "operating_budget": None,
            "supply_profile_id": None,
            "uniform_reduction_percent": None,
            "weather_scenario_ids": None,
            "service_preset": None,
            "minimum_service_ratio": None,
            "service_group": None,
            "allowed_intervention_instance_ids": None,
            "forced_instance_ids": None,
            "excluded_instance_ids": None,
            "permit_groundwater": None,
            "blocked_edge_ids": None,
        },
    }
    prov = ScriptedProvider(
        [
            lambda o: [("branch_scenario", args)],
            lambda o: [("branch_scenario", args)],
            lambda o: final([{"type": "text", "text": "Branch created."}]),
        ]
    )
    before = app_env["client"].get(f"/api/v2/scenarios/{_scenario(app_env)}").json()["revisions"]
    t = ask(app_env, prov, "Make a 2 lakh branch")
    after = app_env["client"].get(f"/api/v2/scenarios/{_scenario(app_env)}").json()["revisions"]
    assert len(after) == len(before) + 1
    assert [c["tool"] for c in t["tool_calls"]] == [
        "branch_scenario"
    ]  # identical retry reused, not re-run


def _scenario(app_env):
    rv = app_env["client"].get(f"/api/v2/scenario-revisions/{app_env['revision_id']}").json()
    return rv["revision"]["scenario_id"]
