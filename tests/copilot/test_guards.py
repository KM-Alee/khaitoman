"""Copilot safety and edge behavior: membership, clarification, eligibility, roles, cancel, SSE."""

from __future__ import annotations

import asyncio
import json
import time

from aabflow.copilot.provider import FunctionCall, ProviderResponse
from tests.copilot.conftest import ask, context
from tests.copilot.fakes import ScriptedProvider, final
from tests.fixtures import synthetic as fx

NULL_CHANGES = {
    "capital_budget": None,
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
}


def branch(**changes):
    return {
        "base_revision_id": None,
        "label": None,
        "solve": False,
        "plan_kind": None,
        "wait_s": None,
        "changes": {**NULL_CHANGES, **changes},
    }


def first(t, tool):
    return next(c for c in t["tool_calls"] if c["tool"] == tool)


def test_cross_pilot_ids_rejected_and_stale_selection_dropped(app_env):
    a_run = app_env["runs"]["P"]
    ctx = {
        "pilot_id": "fixture-b",
        "pilot_version": "test-v1",
        "selected_run_id": a_run,
        "selected_field_id": "fixture-a:f1",
        "language": "en",
    }
    prov = ScriptedProvider(
        [
            lambda o: [("inspect_run", {"run_id": a_run, "field_id": None}), ("get_context", {})],
            lambda o: final([{"type": "text", "text": "That run is not in this pilot."}]),
        ]
    )
    t = ask(app_env, prov, f"Show run {a_run}", ctx=ctx)
    res = first(t, "inspect_run")["result"]
    assert res["ok"] is False and res["error"]["code"] == "CROSS_PILOT_REFERENCE"
    gc = first(t, "get_context")["result"]
    assert gc["context"]["pilot_id"] == "fixture-b"
    assert (
        "selected_run_id" not in gc["context"]
    )  # run from the previously selected pilot is not used
    assert any(a_run in n for n in t["context"]["notes"])


def test_foreign_currency_needs_clarification(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [("branch_scenario", branch(capital_budget="$20,000"))],
            lambda o: final(
                [],
                clarify="Which PKR amount should the capital budget be? I do not convert dollars.",
            ),
        ]
    )
    t = ask(app_env, prov, "Set the budget to $20,000")
    res = first(t, "branch_scenario")["result"]
    assert res["error"]["code"] == "NEEDS_CLARIFICATION" and "USD" in res["error"]["detail"]
    assert t["status"] == "clarification"
    assert t["answer"]["clarification_question"]
    assert t["created_refs"] == []


def test_service_floor_without_group_needs_clarification(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [("branch_scenario", branch(minimum_service_ratio=0.7))],
            lambda o: final([], clarify="Which fields should get at least 70%?"),
        ]
    )
    t = ask(app_env, prov, "Keep service at 70%")
    assert first(t, "branch_scenario")["result"]["error"]["code"] == "NEEDS_CLARIFICATION"


def test_tail_preset_exposes_floor(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [
                (
                    "branch_scenario",
                    branch(service_preset="tail-protect-standard", capital_budget="2 million"),
                )
            ],
            lambda o: final([{"type": "text", "text": "Branch created with tail protection."}]),
        ]
    )
    t = ask(app_env, prov, "Reduce the budget to PKR 2 million and protect the tail fields")
    res = first(t, "branch_scenario")["result"]
    assert res["ok"], res
    shown = " ".join(res["applied_changes"])
    assert "PKR 2,000,000" in shown and "floor 0.60" in shown and "tail" in shown
    rv = app_env["client"].get(f"/api/v2/scenario-revisions/{res['scenario_revision_id']}").json()
    req = rv["revision"]["request"]
    assert req["minimum_service_ratio"] == 0.6 and req["service_group"] == "tail"


def test_ineligible_pond_runs_no_job(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [
                (
                    "evaluate_alternative",
                    {
                        "instance_id": "fixture-a:f4:pond-late",
                        "action": "force",
                        "base_revision_id": None,
                        "base_run_id": None,
                        "wait_s": None,
                    },
                )
            ],
            lambda o: final(
                [{"type": "text", "text": "The late pond cannot be commissioned in time."}]
            ),
        ]
    )
    t = ask(app_env, prov, "What if we build the late pond anyway?")
    res = first(t, "evaluate_alternative")["result"]
    assert (
        res["submitted"] is False
        and res["eligibility"]["eligible"] is False
        and res["eligibility"]["reasons"]
    )
    assert t["job_ids"] == []


def test_force_eligible_investment_why_not(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [
                (
                    "evaluate_alternative",
                    {
                        "instance_id": fx.POND_S,
                        "action": "force",
                        "base_revision_id": None,
                        "base_run_id": None,
                        "wait_s": 40,
                    },
                )
            ],
            lambda o: final([{"type": "text", "text": "Forced-pond alternative evaluated."}]),
        ]
    )
    t = ask(app_env, prov, "What if we build the small pond anyway?")
    res = first(t, "evaluate_alternative")["result"]
    assert res["ok"] and res["submitted"], res
    if "solve" in res:  # fallback when the why-not route is unavailable
        run = res["solve"]["run"]
        if run["outcome"] == "plan":
            assert fx.POND_S in run["selected_intervention_instance_ids"]
            assert res["objective_difference"] is not None
    else:
        assert res["job"]["state"] == "succeeded", res
        result = res["analysis"]["result"]
        assert result["instance_id"] == fx.POND_S
        assert result["difference"]["status"]
        alt = result["alternative"]
        if alt and alt.get("outcome") == "plan":
            assert fx.POND_S in alt["selected_intervention_instance_ids"]
    assert len(t["job_ids"]) == 1


def test_viewer_cannot_branch(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [("branch_scenario", branch(capital_budget="1 lakh"))],
            lambda o: final([{"type": "text", "text": "I can only read in this role."}]),
        ]
    )
    t = ask(app_env, prov, "Lower the budget", role="viewer")
    assert first(t, "branch_scenario")["result"]["error"]["code"] == "NOT_PERMITTED"
    assert "branch_scenario" not in prov.requests[0]["tools"]


def test_navigation_intents_validated(app_env):
    p = app_env["runs"]["P"]
    prov = ScriptedProvider(
        [
            lambda o: [
                (
                    "navigate_view",
                    {"target": "pilot", "ref_id": "pilot-zzz", "tab": None, "date": None},
                ),
                ("navigate_view", {"target": "run", "ref_id": p, "tab": "compare", "date": None}),
            ],
            lambda o: final([{"type": "text", "text": "Opening the run."}]),
        ]
    )
    t = ask(app_env, prov, "open it")
    calls = [c["result"] for c in t["tool_calls"]]
    assert calls[0]["error"]["code"] == "NOT_PERMITTED"
    assert t["view_intents"] == [{"target": "run", "run_id": p, "tab": "compare"}]


class SlowProvider:
    model = "slow-test-provider"

    def __init__(self):
        self.n = 0

    async def respond(self, **kw):
        self.n += 1
        if self.n == 1:
            return ProviderResponse(
                "r1",
                [
                    FunctionCall(
                        "c1",
                        "navigate_view",
                        json.dumps(
                            {"target": "tab", "ref_id": None, "tab": "impact", "date": None}
                        ),
                    )
                ],
                "",
                1,
            )
        await asyncio.sleep(30)
        raise AssertionError("should have been cancelled")


def test_cancel_discards_late_ui_changes(app_env):
    c = app_env["client"]
    app_env["app"].state.aab.extras["copilot_provider_factory"] = SlowProvider
    sid = c.post("/api/v2/copilot/sessions", json={"context": context(app_env)}).json()[
        "session_id"
    ]
    tid = c.post(
        f"/api/v2/copilot/sessions/{sid}/messages",
        json={"message": "go to impact", "context": context(app_env)},
    ).json()["turn_id"]
    time.sleep(0.6)
    r = c.post(f"/api/v2/copilot/turns/{tid}/cancel").json()
    assert r["cancel_requested"] is True
    for _ in range(100):
        t = c.get(f"/api/v2/copilot/turns/{tid}").json()
        if t["status"] != "running":
            break
        time.sleep(0.05)
    assert t["status"] == "cancelled"
    assert t["view_intents"] == [] and t["answer"] is None
    body = c.get(f"/api/v2/copilot/turns/{tid}/events").text
    assert "event: turn_finished" in body and "event: view_intents" not in body


def test_sse_stream_and_resume(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [("get_context", {})],
            lambda o: final([{"type": "text", "text": "You are looking at the fixture pilot."}]),
        ]
    )
    t = ask(app_env, prov, "where am I?")
    c = app_env["client"]
    body = c.get(f"/api/v2/copilot/turns/{t['turn_id']}/events").text
    for ev in ("turn_started", "tool_started", "tool_finished", "answer", "turn_finished"):
        assert f"event: {ev}" in body
    assert "Reading the current workspace" in body
    ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
    resumed = c.get(
        f"/api/v2/copilot/turns/{t['turn_id']}/events", headers={"Last-Event-ID": str(ids[2])}
    ).text
    assert f"id: {ids[2]}\n" not in resumed and f"id: {ids[3]}\n" in resumed


def test_urdu_answer_with_urdu_digits_validates(app_env):
    p_run = app_env["runs"]["P"]

    def answer(o):
        run = o["inspect_run"][0]
        prod = next(m for m in run["metrics"] if m["metric_id"] == "production_kg")["value"]
        urdu = f"{prod:.0f}".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
        return final(
            [
                {
                    "type": "text",
                    "text": f"رن {p_run} میں پیداوار {urdu} کلوگرام ہے۔",
                    "citations": [p_run],
                },
                {"type": "metric", "metric_id": "production_kg", "run_id": p_run},
            ],
            language="ur",
        )

    prov = ScriptedProvider(
        [lambda o: [("inspect_run", {"run_id": None, "field_id": None})], answer]
    )
    t = ask(app_env, prov, "یہ پلان کتنی پیداوار دیتا ہے؟", ctx=context(app_env, language="ur"))
    assert t["answer"]["validated"] is True and t["answer"]["language"] == "ur"


def test_infeasible_run_has_no_metric_card(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [
                (
                    "branch_scenario",
                    {
                        **branch(
                            minimum_service_ratio=1.0,
                            service_group="all",
                            capital_budget="0",
                            operating_budget="0",
                        ),
                        "solve": True,
                        "wait_s": 40,
                    },
                )
            ],
            lambda o: final(
                [
                    {
                        "type": "metric",
                        "metric_id": "production_kg",
                        "run_id": o["branch_scenario"][0]["solve"]["run"]["run_id"],
                    }
                ]
            ),
            lambda o: final(
                [
                    {
                        "type": "uncertainty",
                        "text": "No plan meets a full-service floor with no budget.",
                    }
                ]
            ),
        ]
    )
    t = ask(app_env, prov, "Can every field get full service with no money?")
    run = first(t, "branch_scenario")["result"]["solve"]["run"]
    if run["outcome"] == "no_plan":
        assert run["metrics"] == [] and "no plan" in run["note"].lower()
        assert not any(b["type"] == "metric" for b in t["answer"]["blocks"])
        regen = prov.requests[2]["input"][0]["output"]
        assert "has no plan" in regen


def test_turn_retry_reuses_branch_and_job(app_env):
    args = {**branch(capital_budget="1.2 lakh"), "solve": True, "wait_s": 40}
    steps = lambda: [
        lambda o: [("branch_scenario", args)],
        lambda o: final([{"type": "text", "text": "Done."}]),
    ]
    prov = ScriptedProvider(steps() + steps())
    t1 = ask(app_env, prov, "Lower the budget to 1.2 lakh and solve")
    c = app_env["client"]
    r = c.post(f"/api/v2/copilot/turns/{t1['turn_id']}/retry")
    assert r.status_code == 202, r.text
    tid = r.json()["turn_id"]
    for _ in range(400):
        t2 = c.get(f"/api/v2/copilot/turns/{tid}", params={"include_tools": True}).json()
        if t2["status"] != "running":
            break
        time.sleep(0.05)
    b1 = first(t1, "branch_scenario")["result"]
    b2 = first(t2, "branch_scenario")["result"]
    assert b1["scenario_revision_id"] == b2["scenario_revision_id"]
    assert t1["job_ids"] == t2["job_ids"] and len(t1["job_ids"]) == 1
    assert t2["idem_namespace"] == t1["turn_id"]


def test_sensitivity_needs_two_distinct_values_and_submits_no_job(app_env):
    sens = {
        "analysis_id": None,
        "base_revision_id": None,
        "parameter": "operating_budget_pkr",
        "values": ["2 lakh", "200,000"],
        "service_group": None,
        "wait_s": None,
    }
    prov = ScriptedProvider(
        [
            lambda o: [("analyze_sensitivity", sens)],
            lambda o: final([], clarify="Which other operating budgets should I compare?"),
        ]
    )
    t = ask(app_env, prov, "How sensitive is the plan to operating budget around 2 lakh?")
    res = first(t, "analyze_sensitivity")["result"]
    assert res["error"]["code"] == "INVALID_INPUT" and "2 to 12" in res["error"]["detail"]
    assert t["job_ids"] == []
