"""Visual answers, what-if, insight tools, events, language and persistence through the real routes.

The model is a labelled scripted TEST FIXTURE provider; tools, services, solver and validation are real.
"""

from __future__ import annotations

import json

from aabflow.copilot import store
from aabflow.copilot.provider import ProviderError
from tests.copilot.conftest import ask, context
from tests.copilot.fakes import ScriptedProvider, final, vis


def _blocks(t, kind):
    return [b for b in t["answer"]["blocks"] if b["type"] == kind]


def _ds(outputs, tool, kind, i=0):
    res = outputs[tool][i]
    for d in res.get("datasets") or (res.get("analysis") or {}).get("datasets") or []:
        if d["kind"] == kind:
            return d
    raise AssertionError((tool, kind, res.get("datasets")))


def test_visual_answer_is_built_from_tool_rows(app_env):
    p_run = app_env["runs"]["P"]
    c = app_env["client"]

    def answer(o):
        ds = _ds(o, "inspect_run", "field_outcomes")
        kpi = _ds(o, "inspect_run", "run_metrics")
        return final(
            [{"type": "text", "text": f"Run {p_run} is the selected plan.", "citations": [p_run]}],
            headline="Here is how each field does under the plan.",
            visuals=[
                vis(ds["dataset_id"], "bar", title="Production per field", sort="desc"),
                vis(kpi["dataset_id"], "kpi", title="Key numbers", limit=3),
            ],
            follow_ups=["Which fields lose out?", "What if the budget were lower?"],
        )

    prov = ScriptedProvider(
        [lambda o: [("inspect_run", {"run_id": None, "field_id": None})], answer]
    )
    t = ask(app_env, prov, "Show me the plan per field")
    assert t["status"] == "completed" and t["answer"]["validated"], t["answer"]
    types = [b["type"] for b in t["answer"]["blocks"]]
    assert types[:3] == ["run_badge", "headline", "text"] and types[-1] == "follow_ups", types
    bar, kpi = _blocks(t, "visual")
    run = c.get(f"/api/v2/runs/{p_run}").json()
    want = {
        m["field_id"]: m["value"]
        for m in run["metrics"]
        if m["metric_id"] == "field_production_kg" and m["field_id"]
    }
    got = {r["field_id"]: r["field_production_kg"] for r in bar["rows"]}
    assert set(got) == set(want)
    for fid, v in got.items():  # values copied from the service, not typed by the model
        assert abs(v - want[fid]) <= 1e-6 * max(1.0, abs(want[fid]))
    vals = [r["field_production_kg"] for r in bar["rows"]]
    assert vals == sorted(vals, reverse=True)
    assert bar["source"]["run_ids"] == [p_run] and bar["source"]["tool"] == "inspect_run"
    assert bar["source"]["call_id"] == t["tool_calls"][0]["call_id"]
    assert (
        next(col for col in bar["columns"] if col["key"] == "field_production_kg")["unit"] == "kg"
    )
    assert kpi["chart"] == "kpi" and len(kpi["rows"]) == 3 and kpi["rows"][0]["unit"]
    badge = _blocks(t, "run_badge")[0]
    assert badge["run_id"] == p_run and badge["role"] == "context" and badge["plan_kind"] == "P"
    # The stored transcript validates against the public contract.
    assert c.get(f"/api/v2/copilot/turns/{t['turn_id']}").status_code == 200


def test_unknown_dataset_and_invented_caption_are_regenerated_then_dropped(app_env):
    seen = {}

    def bad(o):
        if "inspect_run" in o:  # the regeneration round only carries the rejection
            seen["ds"] = _ds(o, "inspect_run", "field_outcomes")["dataset_id"]
        return final(
            [{"type": "text", "text": "The plan is shown below."}],
            visuals=[
                vis("ds99", "bar"),
                vis(seen["ds"], "bar", caption="Fields gain 777,777 kg in total."),
            ],
        )

    prov = ScriptedProvider(
        [lambda o: [("inspect_run", {"run_id": None, "field_id": None})], bad, bad]
    )
    t = ask(app_env, prov, "chart it")
    feedback = prov.requests[2]["input"][0]["output"]
    assert "ds99" in feedback and "777,777" in feedback
    vs = _blocks(t, "visual")
    assert len(vs) == 1 and vs[0]["caption"] is None
    assert t["answer"]["validated"] is False
    assert any("left out" in b["text"] for b in _blocks(t, "uncertainty"))


def test_datasets_do_not_cross_turns(app_env):
    """A dataset ID from an earlier turn is not this turn's tool result."""
    t1 = ask(
        app_env,
        ScriptedProvider(
            [
                lambda o: [("inspect_run", {"run_id": None, "field_id": None})],
                lambda o: final([{"type": "text", "text": "ok"}]),
            ]
        ),
        "first",
    )
    stale = final([{"type": "text", "text": "Chart."}], visuals=[vis("ds1", "bar")])
    t2 = ask(app_env, ScriptedProvider([stale, stale]), "again", session_id=t1["session_id"])
    assert not _blocks(t2, "visual")


def test_what_if_branches_solves_and_compares_in_one_call(app_env):
    c = app_env["client"]
    p_run = app_env["runs"]["P"]

    def answer(o):
        r = o["run_what_if"][0]
        assert r["ok"] and r["new_run"]["run_id"] and r["compared_with_run_id"] == p_run, r
        cmp_id = r["comparison"]["comparison_id"]
        side = next(d for d in r["datasets"] if d["kind"] == "plans_side_by_side")
        return final(
            [
                {"type": "text", "text": "The smaller budget was solved as a new scenario."},
                {"type": "comparison", "comparison_id": cmp_id},
            ],
            headline="Here is what a 1 lakh budget changes.",
            visuals=[vis(side["dataset_id"], "bar", title="Current plan vs what-if")],
        )

    changes = {
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
    }
    changes["capital_budget"] = "1 lakh"
    prov = ScriptedProvider(
        [
            lambda o: [
                (
                    "run_what_if",
                    {
                        "changes": changes,
                        "label": "Budget 1 lakh",
                        "plan_kind": None,
                        "compare_with_run_id": None,
                    },
                )
            ],
            answer,
        ]
    )
    t = ask(app_env, prov, "What if the budget is 1 lakh?", timeout=90)
    assert t["status"] == "completed", t
    kinds = {x["kind"] for x in t["created_refs"]}
    assert {"branch", "run", "comparison"} <= kinds
    new_run = next(x["ref_id"] for x in t["created_refs"] if x["kind"] == "run")
    badges = _blocks(t, "run_badge")
    assert [b["role"] for b in badges] == ["context", "created"] and badges[1]["run_id"] == new_run
    side = _blocks(t, "visual")[0]
    assert {r["run_id"] for r in side["rows"]} == {p_run, new_run}
    assert _blocks(t, "comparison")[0]["run_ids"] == [p_run, new_run]
    rev = c.get(f"/api/v2/scenario-revisions/{app_env['revision_id']}").json()
    assert rev["revision"]["request"]["capital_budget_pkr"] == 300000  # parent unchanged
    assert {b["action"] for b in _blocks(t, "action")} >= {"open_branch", "open_run"}


def test_lay_read_tools_in_one_parallel_round(app_env):
    """All plain-language read tools run together and each returns its datasets with provenance."""
    calls = [
        ("get_plan_ladder", {"revision_id": None}),
        ("equity", {"run_id": None, "baseline_run_id": None}),
        ("water_accounting", {"run_id": None}),
        ("economics", {"run_id": None}),
        ("action_plan", {"run_id": None, "field_id": "fixture-a:f3"}),
        ("explain_decisions", {"run_id": None}),
        ("impact_sdg", {"run_id": None, "baseline_run_id": None}),
        ("field_timeline", {"field_id": None, "run_id": None, "resolution": "weekly"}),
        ("methodology", {"topic": "service ratio"}),
    ]
    seen = {}

    def answer(o):
        seen.update(o)
        return final([{"type": "text", "text": "Read everything."}])

    prov = ScriptedProvider([lambda o: calls, answer])
    t = ask(app_env, prov, "Tell me everything", timeout=90)
    assert t["status"] == "completed", t
    by_tool = {c["tool"]: c for c in t["tool_calls"]}
    assert set(by_tool) == {n for n, _ in calls}
    for name, call in by_tool.items():
        assert call["status"] == "succeeded", (name, call["result"])
    ladder = seen["get_plan_ladder"][0]
    assert set(ladder["plans"]) >= {"B0", "B1", "P"} and ladder["comparison"]["compatible"]
    side = next(d for d in ladder["datasets"] if d["kind"] == "plans_side_by_side")
    assert side["rows"] == 3
    eq = seen["equity"][0]
    assert eq["baseline_run_id"] == app_env["runs"]["B0"]
    assert {d["kind"] for d in eq["datasets"]} >= {"equity_fields", "equity_groups"}
    assert any(d["kind"] == "water_flows" for d in seen["water_accounting"][0]["datasets"])
    assert any(d["kind"] == "money_cards" for d in seen["economics"][0]["datasets"])
    assert any(d["kind"] == "action_steps" for d in seen["action_plan"][0]["datasets"])
    assert seen["methodology"][0]["data_limitations"]["water_rights"].startswith("assumed")
    # dataset provenance points at the call that produced it (parallel calls, per-task context)
    ev = app_env["client"].get(f"/api/v2/copilot/turns/{t['turn_id']}/event-log").json()
    ready = [e["payload"] for e in ev if e["type"] == "dataset_ready"]
    assert ready and all(by_tool[p["tool"]]["call_id"] == p["call_id"] for p in ready)


def test_stress_heatmap_keeps_undeliverable_cells_empty(app_env):
    def answer(o):
        res = o["run_stress_test"][0]
        ds = next(d for d in res["analysis"]["datasets"] if d["kind"] == "stress_matrix")
        return final(
            [{"type": "text", "text": "The stress test is shown below."}],
            visuals=[vis(ds["dataset_id"], "heatmap", title="Weather x supply")],
        )

    prov = ScriptedProvider(
        [
            lambda o: [
                (
                    "run_stress_test",
                    {
                        "run_id": None,
                        "mode": "fixed_plan",
                        "uncertainty_set_id": None,
                        "state_ids": None,
                        "wait_s": 60,
                    },
                )
            ],
            answer,
        ]
    )
    t = ask(app_env, prov, "How robust is the plan?", timeout=90)
    hm = _blocks(t, "visual")[0]
    assert hm["chart"] == "heatmap" and hm["encoding"]["value"] == "production_kg"
    assert hm["rows"]
    for r in hm["rows"]:
        assert (r["status"] == "deliverable") == r["deliverable"]
        if not r["deliverable"]:
            assert r["production_kg"] is None

    again = ScriptedProvider(
        [
            lambda o: [("read_analysis", {"analysis_id": None, "kind": "stress", "mode": None})],
            lambda o: final([{"type": "text", "text": "Saved stress test."}]),
        ]
    )
    t2 = ask(app_env, again, "show the saved stress test")
    res = next(c for c in t2["tool_calls"] if c["tool"] == "read_analysis")["result"]
    assert res["analysis"]["kind"] == "stress" and not t2["job_ids"]  # read, no new job


def test_events_stream_progress_and_answer_blocks(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [("inspect_run", {"run_id": None, "field_id": None})],
            lambda o: final([{"type": "text", "text": "Done."}], headline="All good."),
        ]
    )
    t = ask(app_env, prov, "status?")
    c = app_env["client"]
    ev = c.get(f"/api/v2/copilot/turns/{t['turn_id']}/event-log").json()
    types = [e["type"] for e in ev]
    order = ["turn_started", "thinking", "tool_started", "dataset_ready", "tool_finished"]
    idx = [types.index(x) for x in order]
    assert idx == sorted(idx), types
    assert types.index("answer_block") < types.index("answer") < types.index("turn_finished")
    finished = next(e for e in ev if e["type"] == "tool_finished")["payload"]
    assert finished["duration_ms"] >= 0 and finished["datasets"]
    sse = c.get(f"/api/v2/copilot/turns/{t['turn_id']}/events").text
    assert "event: thinking" in sse and "event: answer_block" in sse
    turn = c.get(f"/api/v2/copilot/turns/{t['turn_id']}").json()
    assert (
        turn["timings"]["provider_calls"] and turn["timings"]["tools"][0]["tool"] == "inspect_run"
    )


def test_urdu_message_switches_language(app_env):
    prov = ScriptedProvider([lambda o: final([{"type": "text", "text": "جی ہاں۔"}], language="ur")])
    t = ask(app_env, prov, "کیا یہ منصوبہ بہتر ہے؟")
    assert t["language"] == "ur" and t["context"]["language"] == "ur"
    assert "answer in Urdu" in prov.requests[0]["instructions"]
    roman = ScriptedProvider([lambda o: final([{"type": "text", "text": "Ji haan."}])])
    t2 = ask(app_env, roman, "kya pani kam hoga agar nehar band ho?")
    assert t2["language"] == "roman_ur"


def test_provider_failure_after_tools_shows_only_tool_results(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [("get_plan_ladder", {"revision_id": None})],
            ProviderError("PROVIDER_UNAVAILABLE", "cannot reach the hosted model", retryable=True),
        ]
    )
    t = ask(app_env, prov, "what is the best plan?")
    assert t["status"] == "provider_unavailable"
    a = t["answer"]
    assert a["deterministic"] is True and not _blocks(t, "headline")
    assert not _blocks(t, "text")  # no prose was invented
    vs = _blocks(t, "visual")
    assert vs and all(v["auto"] for v in vs)
    assert any("unavailable" in b["text"] for b in _blocks(t, "uncertainty"))


def test_malformed_final_answers_stop_after_two_attempts(app_env):
    broken = {
        "language": "en",
        "blocks": [],
        "needs_clarification": False,
        "visuals": [{"chart": "bar"}],
    }
    prov = ScriptedProvider(
        [lambda o: [("inspect_run", {"run_id": None, "field_id": None})], broken, broken, broken]
    )
    t = ask(app_env, prov, "show")
    assert t["status"] == "failed" and t["error"]["code"] == "ANSWER_INVALID"
    assert len(prov.requests) == 3 and prov.requests[2]["tool_choice"]["name"] == "final_answer"
    assert t["answer"]["deterministic"] is True and not _blocks(t, "text")
    assert all(p.get("rejected") for p in t["timings"]["provider_calls"][1:])


def test_stalled_provider_call_is_retried_once_for_the_answer(app_env):
    from aabflow.copilot.orchestrator import TurnLimits
    from tests.copilot.fakes import Stall

    extras = app_env["app"].state.aab.extras
    extras["copilot_limits"] = TurnLimits(provider_call_s=0.5)
    try:
        prov = ScriptedProvider(
            [
                lambda o: [("inspect_run", {"run_id": None, "field_id": None})],
                Stall(5),
                lambda o: final([{"type": "text", "text": "Here is the plan."}]),
            ]
        )
        t = ask(app_env, prov, "show the plan")
    finally:
        extras.pop("copilot_limits", None)
    assert t["status"] == "completed", t
    assert prov.requests[2]["tool_choice"] == {"type": "function", "name": "final_answer"}
    assert prov.requests[2]["input"] == prov.requests[1]["input"]  # same tool outputs resent
    assert any(p.get("timed_out") for p in t["timings"]["provider_calls"])


def test_tool_failure_is_reported_not_hidden(app_env):
    prov = ScriptedProvider(
        [
            lambda o: [("equity", {"run_id": "run_doesnotexist", "baseline_run_id": None})],
            lambda o: final(
                [{"type": "uncertainty", "text": "I could not read that run."}],
                headline="That run does not exist.",
            ),
        ]
    )
    t = ask(app_env, prov, "fairness of run_doesnotexist?")
    call = t["tool_calls"][0]
    assert call["status"] == "failed" and call["result"]["error"]["code"] == "NOT_FOUND"
    ev = app_env["client"].get(f"/api/v2/copilot/turns/{t['turn_id']}/event-log").json()
    fin = next(e for e in ev if e["type"] == "tool_finished")["payload"]
    assert fin["ok"] is False and fin["error"]["code"] == "NOT_FOUND"


def test_what_if_cannot_target_another_pilot(app_env):
    """The what-if base is always the pinned revision; injected run IDs from another pilot are refused."""
    other = ScriptedProvider(
        [
            lambda o: [("compare_runs", {"run_ids": [app_env["runs"]["P"], "run_from_elsewhere"]})],
            lambda o: final([{"type": "text", "text": "Cannot."}]),
        ]
    )
    t = ask(app_env, other, "compare with the other pilot")
    assert t["tool_calls"][0]["result"]["ok"] is False
    assert "base_revision_id" not in json.dumps(
        next(x for x in t["tool_calls"] if x["tool"] == "compare_runs")["arguments"]
    )


def test_sessions_listed_and_restored_after_restart(app_env):
    c = app_env["client"]
    prov = ScriptedProvider([lambda o: final([{"type": "text", "text": "Hello."}])])
    t = ask(app_env, prov, "hello sk-abcdefghijklmnopqrstuvwxyz123456 there")
    lst = c.get("/api/v2/copilot/sessions").json()["sessions"]
    mine = next(s for s in lst if s["session_id"] == t["session_id"])
    assert mine["turns"] == 1 and "[redacted]" in mine["title"] and "sk-abc" not in mine["title"]
    # Simulate a turn left running by a previous process: it is reported as interrupted, not running.
    conn = app_env["app"].state.aab.connect()
    try:
        store.create_turn(conn, "turn_stale", t["session_id"], "x", {}, "m", "p", "t")
    finally:
        conn.close()
    s = c.get(f"/api/v2/copilot/sessions/{t['session_id']}").json()
    stale = next(x for x in s["turns"] if x["turn_id"] == "turn_stale")
    assert stale["status"] == "failed" and stale["error"]["code"] == "INTERRUPTED"
    restored = next(x for x in s["turns"] if x["turn_id"] == t["turn_id"])
    assert restored["answer"]["blocks"] and restored["language"] == "en"


def test_status_reports_unavailable_without_key(app_env, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    extras = app_env["app"].state.aab.extras
    saved = extras.pop("copilot_provider_factory", None)
    try:
        st = app_env["client"].get("/api/v2/copilot/status").json()
        assert st["configured"] is False and st["state"] == "unavailable" and st["reason"]
        s = (
            app_env["client"]
            .post("/api/v2/copilot/sessions", json={"context": context(app_env)})
            .json()
        )
        r = app_env["client"].post(
            f"/api/v2/copilot/sessions/{s['session_id']}/messages",
            json={"message": "hi", "context": context(app_env)},
        )
        assert r.status_code == 503 and r.json()["code"] == "PROVIDER_UNAVAILABLE"
    finally:
        if saved is not None:
            extras["copilot_provider_factory"] = saved
