"""Copilot analysis tools against the real analysis and surrogate routes (fixture pilot, labelled)."""

from __future__ import annotations

import pytest

from tests.copilot.conftest import ask
from tests.copilot.fakes import ScriptedProvider, final
from tests.fixtures import synthetic as fx


def run_tool(app_env, name, args, message="analysis"):
    prov = ScriptedProvider(
        [
            lambda o: [(name, args)],
            lambda o: final([{"type": "text", "text": "Done."}]),
        ]
    )
    t = ask(app_env, prov, message, timeout=90)
    call = next(c for c in t["tool_calls"] if c["tool"] == name)
    return t, call["result"]


def assert_analysis(t, res, kind):
    assert res["ok"], res
    assert res["job"]["state"] == "succeeded", res
    a = res["analysis"]
    assert a["kind"] == kind and a["analysis_id"] == res["analysis_id"]
    assert not (a["result"] or {}).get("truncated"), a
    assert res["analysis_id"] in [c["ref_id"] for c in t["created_refs"]]
    assert len(t["job_ids"]) == 1
    return a["result"]


def test_stress_uses_run_uncertainty_set(app_env):
    t, res = run_tool(
        app_env,
        "run_stress_test",
        {
            "run_id": None,
            "mode": "fixed_plan",
            "uncertainty_set_id": None,
            "state_ids": None,
            "wait_s": 60,
        },
    )
    result = assert_analysis(t, res, "stress")
    assert result


def test_frontier_six_points(app_env):
    pts = [
        {
            "capital_budget": b,
            "service_preset": None,
            "minimum_service_ratio": r,
            "service_group": "tail",
        }
        for b in ("1 lakh", "3 lakh")
        for r in (0.5, 0.6, 0.7)
    ]
    t, res = run_tool(
        app_env, "build_frontier", {"base_revision_id": None, "settings": pts, "wait_s": 80}
    )
    assert_analysis(t, res, "frontier")


def test_frontier_rejects_duplicate_points(app_env):
    pt = {
        "capital_budget": "1 lakh",
        "service_preset": None,
        "minimum_service_ratio": 0.5,
        "service_group": "tail",
    }
    t, res = run_tool(
        app_env, "build_frontier", {"base_revision_id": None, "settings": [pt] * 6, "wait_s": 5}
    )
    assert res["error"]["code"] == "INVALID_INPUT" and t["job_ids"] == []


@pytest.mark.parametrize(
    ("parameter", "values"),
    [
        ("operating_budget_pkr", ["50,000", "1 lakh", "2 lakh", "400000"]),
        ("uniform_reduction_fraction", ["0", "10%", "20"]),
    ],
)
def test_sensitivity(app_env, parameter, values):
    t, res = run_tool(
        app_env,
        "analyze_sensitivity",
        {
            "analysis_id": None,
            "base_revision_id": None,
            "parameter": parameter,
            "values": values,
            "service_group": None,
            "wait_s": 80,
        },
    )
    assert_analysis(t, res, "sensitivity")


def test_synergy(app_env):
    t, res = run_tool(
        app_env,
        "analyze_synergy",
        {
            "instance_a": "fixture-a:f1:level",
            "instance_b": fx.POND_S,
            "other_actions": "fixed",
            "base_revision_id": None,
            "wait_s": 80,
        },
    )
    assert_analysis(t, res, "synergy")


def test_preview_reports_gate_or_estimate(app_env):
    _t, res = run_tool(
        app_env,
        "preview_policy",
        {
            "mode": "preview",
            "field_id": "fixture-a:f3",
            "schedule": [
                {"date": "2026-12-20", "gross_depth_mm": 60},
                {"date": "2027-02-10", "gross_depth_mm": 60},
            ],
            "weather_scenario_id": None,
            "preview_id": None,
        },
    )
    if res.get("ok"):
        assert res["preview"]["label"].startswith("Approximate")
    else:
        assert res.get("code") == "SURROGATE_NOT_VALIDATED" or res.get("error"), res
