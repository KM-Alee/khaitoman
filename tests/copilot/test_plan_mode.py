"""Plan mode ("Plan my season", WIN_PLAN P2/B1) through the real routes, tools, solver and validation.

The hosted model is replaced by the labelled scripted provider (TEST FIXTURE, tests/copilot/fakes.py).
"""

from __future__ import annotations

import time

from aabflow.copilot.answer_validation import (
    PLAN_STANDARD_CAVEATS,
    apply_plan_layout,
    plan_layout_gaps,
)
from aabflow.copilot.orchestrator import PLAN_LIMITS, TurnLimits, plan_phase, step_field_ids
from aabflow.copilot.prompts import PLANNER_INSTRUCTIONS, build_instructions
from tests.copilot.conftest import ask, context
from tests.copilot.fakes import ScriptedProvider, Stall, final, vis

GOAL = "We have 2 lakh. Don't hurt the tail farmers, and make sure it survives a dry year."

WHAT_IF_CHANGES = {
    k: None
    for k in (
        "operating_budget",
        "supply_profile_id",
        "uniform_reduction_percent",
        "weather_scenario_ids",
        "service_preset",
        "minimum_service_ratio",
        "service_group",
        "allowed_intervention_instance_ids",
        "forced_instance_ids",
        "excluded_instance_ids",
        "permit_groundwater",
        "blocked_edge_ids",
    )
} | {"capital_budget": "2 lakh"}


def ask_plan(app_env, provider, message=GOAL, timeout=120):
    c = app_env["client"]
    app_env["app"].state.aab.extras["copilot_provider_factory"] = lambda: provider
    s = c.post("/api/v2/copilot/sessions", json={"context": context(app_env), "role": "planner"})
    assert s.status_code == 201, s.text
    sid = s.json()["session_id"]
    r = c.post(
        f"/api/v2/copilot/sessions/{sid}/messages",
        json={"message": message, "context": context(app_env), "mode": "plan"},
    )
    assert r.status_code == 202, r.text
    tid = r.json()["turn_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = c.get(f"/api/v2/copilot/turns/{tid}", params={"include_tools": True}).json()
        if t["status"] != "running":
            return t
        time.sleep(0.05)
    raise AssertionError("plan turn did not finish")


def _events(app_env, turn_id):
    return app_env["client"].get(f"/api/v2/copilot/turns/{turn_id}/event-log").json()


def _texts(t, kind="uncertainty"):
    return [b["text"] for b in t["answer"]["blocks"] if b["type"] == kind]


# ------------------------------------------------------------------ unit: limits, prompt, layout guard


def test_plan_limits_and_recipe_prompt_only_in_plan_mode():
    assert PLAN_LIMITS == TurnLimits(
        max_rounds=6, max_tool_calls=20, max_jobs=10, wall_s=240.0, provider_call_s=40.0
    )
    assert TurnLimits() == TurnLimits(
        max_rounds=8, max_tool_calls=12, max_jobs=3, wall_s=90.0
    )  # chat unchanged
    chat = build_instructions({"pilot_id": "x"}, [], [], None)
    plan = build_instructions({"pilot_id": "x"}, [], [], None, mode="plan")
    assert PLANNER_INSTRUCTIONS not in chat and "PLANNER MODE" not in chat
    assert plan.endswith(PLANNER_INSTRUCTIONS)
    for must in ("build_frontier", "run_stress_test", "equity", "create_report", "BY RULE"):
        assert must in PLANNER_INSTRUCTIONS


def test_layout_guard_adds_caveats_for_missing_parts_only():
    assert set(plan_layout_gaps([])) == {
        "kpi",
        "frontier",
        "stress",
        "equity",
        "steps",
        "caveats",
        "actions",
        "follow_ups",
    }
    out = apply_plan_layout([], "budget_exhausted")
    texts = [b["text"] for b in out]
    assert all(b["type"] == "uncertainty" for b in out)  # caveats only: nothing invented
    assert (
        "The stress test (weather x supply heatmap) was not completed within the time budget."
        in (texts)
    )
    assert set(PLAN_STANDARD_CAVEATS) <= set(texts)
    full = [
        {"type": "metric", "metric_id": "production_kg"},
        {"type": "visual", "chart": "frontier", "dataset_kind": "frontier"},
        {"type": "visual", "chart": "heatmap", "dataset_kind": "stress_matrix"},
        {"type": "visual", "chart": "table", "dataset_kind": "equity_fields"},
        {"type": "visual", "chart": "steps", "dataset_kind": "action_steps"},
        {"type": "uncertainty", "text": "Assumed rights."},
        {"type": "action", "action": "open_run"},
        {"type": "follow_ups", "questions": ["a", "b", "c"]},
    ]
    assert plan_layout_gaps(full) == [] and apply_plan_layout(full, "completed") == full
    # caveats go before the actions and follow-ups; existing blocks keep their order
    partial = [full[0], full[6], full[7]]
    out = apply_plan_layout(partial, "completed")
    assert out[0] == full[0] and out[-2:] == [full[6], full[7]]
    assert "The dated action steps is not part of this brief." in [b.get("text") for b in out]


def test_step_phases_and_field_ids():
    assert plan_phase("run_what_if") == "understand"
    assert plan_phase("run_stress_test") == "test" and plan_phase("equity") == "test"
    assert plan_phase("create_report") == "decide"
    res = {
        "fields_worse_off": ["f1", {"field_id": "f2"}],
        "lowest_service_fields": [{"field_id": "f2"}, {"field_id": "f3"}],
    }
    assert step_field_ids(res) == ["f1", "f2", "f3"]
    assert step_field_ids({"ok": False}) == []


# ------------------------------------------------------------------ through the routes


def test_plan_turn_runs_the_investigation_with_steps_and_brief(app_env):
    seen: dict = {}

    def round2(o):
        wi = o["run_what_if"][0]
        assert wi["ok"], wi
        seen["run"] = wi["new_run"]["run_id"]
        return [
            (
                "run_stress_test",
                {
                    "run_id": seen["run"],
                    "mode": "fixed_plan",
                    "uncertainty_set_id": None,
                    "state_ids": None,
                    "wait_s": 60,
                },
            ),
            ("equity", {"run_id": seen["run"], "baseline_run_id": app_env["runs"]["B0"]}),
        ]

    def answer(o):
        st = o["run_stress_test"][0]
        eq = o["equity"][0]
        hm = next(d for d in st["analysis"]["datasets"] if d["kind"] == "stress_matrix")
        tb = next(d for d in eq["datasets"] if d["kind"] == "equity_fields")
        seen["equity"] = eq
        return final(
            [
                {"type": "metric", "metric_id": "production_kg", "run_id": seen["run"]},
                {"type": "uncertainty", "text": "Water rights and costs are assumed."},
            ],
            headline="Use the 2 lakh plan.",
            visuals=[
                vis(hm["dataset_id"], "heatmap", title="Dry years"),
                vis(tb["dataset_id"], "table", title="Fields"),
            ],
            follow_ups=["What about 5 lakh?", "Which fields lose?", "Show the report"],
        )

    prov = ScriptedProvider(
        [
            lambda o: [
                ("get_plan_ladder", {"revision_id": None}),
                (
                    "run_what_if",
                    {
                        "changes": WHAT_IF_CHANGES,
                        "label": "Budget 2 lakh",
                        "plan_kind": "P",
                        "compare_with_run_id": None,
                    },
                ),
            ],
            round2,
            answer,
        ]
    )
    t = ask_plan(app_env, prov)
    assert t["status"] == "completed", t
    assert t["mode"] == "plan"
    assert "PLANNER MODE" in prov.requests[0]["instructions"]
    ev = _events(app_env, t["turn_id"])
    thinking = next(e["payload"] for e in ev if e["type"] == "thinking")
    assert thinking["remaining_s"] > 200  # plan wall budget (240 s), not the chat 90 s
    assert next(e for e in ev if e["type"] == "turn_started")["payload"]["mode"] == "plan"

    # one plan_step right after each tool_finished, numbered, with phase and the objects it made
    types = [e["type"] for e in ev]
    steps = [e["payload"] for e in ev if e["type"] == "plan_step"]
    assert len(steps) == types.count("tool_finished") == 4
    for i, ty in enumerate(types):
        if ty == "tool_finished":
            assert types[i + 1] == "plan_step"
    assert [s["step"] for s in steps] == [1, 2, 3, 4]
    by_tool = {s["tool"]: s for s in steps}
    assert by_tool["get_plan_ladder"]["phase"] == "understand"
    assert by_tool["run_what_if"]["phase"] == "understand"
    assert by_tool["run_what_if"]["run_id"] == seen["run"]
    assert by_tool["run_stress_test"]["phase"] == "test"
    stress_id = by_tool["run_stress_test"]["analysis_id"]
    assert stress_id and stress_id in {x["ref_id"] for x in t["created_refs"]}
    assert (
        by_tool["run_stress_test"]["run_id"] is None
    )  # the stress run is not attributed elsewhere
    low = [f["field_id"] for f in seen["equity"]["lowest_service_fields"]]
    assert set(low) <= set(by_tool["equity"]["field_ids"])
    assert all(s["ok"] for s in steps)
    assert app_env["client"].get(f"/api/v2/copilot/turns/{t['turn_id']}/plan-steps").json() == (
        steps
    )

    # brief: what the model gave, plus honest caveats for the parts it left out (frontier, steps)
    blocks = t["answer"]["blocks"]
    kinds = [b["type"] for b in blocks]
    assert "metric" in kinds and {b.get("chart") for b in blocks} >= {"heatmap", "table"}
    caveats = _texts(t)
    assert "The spending/service trade-off (frontier) is not part of this brief." in caveats
    assert "The dated action steps is not part of this brief." in caveats
    assert not any("stress test" in c.lower() and "not" in c for c in caveats)
    assert kinds.index("uncertainty") < kinds.index("action") < kinds.index("follow_ups")
    assert t["answer"]["validated"] is True


def test_chat_mode_is_unchanged(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [("inspect_run", {"run_id": None, "field_id": None})],
            lambda o: final([{"type": "text", "text": "Done."}]),
        ]
    )
    t = ask(app_env, prov, "status?")
    assert t["status"] == "completed" and t["mode"] == "chat"
    assert "PLANNER MODE" not in prov.requests[0]["instructions"]
    ev = _events(app_env, t["turn_id"])
    assert "plan_step" not in {e["type"] for e in ev}
    assert next(e["payload"] for e in ev if e["type"] == "thinking")["remaining_s"] <= 90
    assert not any("not part of this brief" in x for x in _texts(t))
    assert app_env["client"].get(f"/api/v2/copilot/turns/{t['turn_id']}/plan-steps").json() == []


def test_retry_keeps_plan_mode(app_env):
    prov = ScriptedProvider([lambda o: final([{"type": "text", "text": "Plan."}])])
    t = ask_plan(app_env, prov)
    assert t["mode"] == "plan"
    again = ScriptedProvider([lambda o: final([{"type": "text", "text": "Plan again."}])])
    app_env["app"].state.aab.extras["copilot_provider_factory"] = lambda: again
    r = app_env["client"].post(f"/api/v2/copilot/turns/{t['turn_id']}/retry")
    assert r.status_code == 202, r.text
    tid = r.json()["turn_id"]
    for _ in range(400):
        t2 = app_env["client"].get(f"/api/v2/copilot/turns/{tid}").json()
        if t2["status"] != "running":
            break
        time.sleep(0.05)
    assert t2["mode"] == "plan" and "PLANNER MODE" in again.requests[0]["instructions"]


def test_wall_budget_exhaustion_gives_an_honest_partial_brief(app_env):
    extras = app_env["app"].state.aab.extras
    extras["copilot_plan_limits"] = TurnLimits(
        max_rounds=6, max_tool_calls=20, max_jobs=10, wall_s=8.0, provider_call_s=40.0
    )
    try:
        prov = ScriptedProvider(
            [
                lambda o: [("equity", {"run_id": None, "baseline_run_id": None})],
                Stall(30),  # the model never writes the brief within the remaining budget
            ]
        )
        t = ask_plan(app_env, prov, timeout=60)
    finally:
        extras.pop("copilot_plan_limits", None)
    assert t["status"] == "budget_exhausted", t
    assert t["error"]["code"] == "TURN_TIMEOUT"
    ans = t["answer"]
    assert ans["deterministic"] is True
    blocks = ans["blocks"]
    assert not any(b["type"] in ("metric", "headline", "text") for b in blocks)  # nothing invented
    # the equity result the tools already returned is shown; every missing part is named honestly
    assert any(b["type"] == "visual" and b["dataset_kind"].startswith("equity") for b in blocks)
    caveats = _texts(t)
    assert (
        "The stress test (weather x supply heatmap) was not completed within the time budget."
        in caveats
    )
    assert (
        "The spending/service trade-off (frontier) was not completed within the time budget."
        in (caveats)
    )
    assert not any("fairness check" in c.lower() for c in caveats)  # equity did finish
    ev = _events(app_env, t["turn_id"])
    assert [e["payload"]["tool"] for e in ev if e["type"] == "plan_step"] == ["equity"]
    assert ev[-1]["type"] in ("turn_finished", "jobs_settled")
