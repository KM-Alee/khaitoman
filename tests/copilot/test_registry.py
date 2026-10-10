"""Tool registry contract: 16 spec tools, strict provider schemas, roles, no unsafe capabilities."""

from aabflow.copilot.answer_validation import FINAL_ANSWER_TOOL
from aabflow.copilot.registry import (
    REGISTRY,
    check_strict,
    openai_tools,
    tool_schema_version,
    tools_for_role,
)

SPEC_TOOLS = {
    "get_context",
    "inspect_field",
    "inspect_run",
    "compare_runs",
    "search_evidence",
    "branch_scenario",
    "solve_scenario",
    "get_job_result",
    "evaluate_alternative",
    "run_stress_test",
    "build_frontier",
    "analyze_sensitivity",
    "analyze_synergy",
    "preview_policy",
    "create_report",
    "navigate_view",
}
# Plain-language read tools and the one-step what-if added for lay questions (each wraps one service).
INSIGHT_TOOLS = {
    "get_plan_ladder",
    "read_analysis",
    "water_accounting",
    "economics",
    "equity",
    "impact_sdg",
    "action_plan",
    "field_timeline",
    "explain_decisions",
    "methodology",
    "run_what_if",
}


def test_registry_has_exactly_the_spec_tools():
    tools_for_role("planner")
    assert set(REGISTRY) == SPEC_TOOLS | INSIGHT_TOOLS
    assert {n for n, t in REGISTRY.items() if t.mutation} & INSIGHT_TOOLS == {"run_what_if"}


def test_every_schema_is_strict():
    for t in openai_tools("planner", [FINAL_ANSWER_TOOL]):
        assert t["strict"] is True
        assert check_strict(t["parameters"]) == [], (t["name"], check_strict(t["parameters"]))
        assert t["description"]


def test_tool_declarations():
    for spec in REGISTRY.values():
        assert spec.semantics in ("read", "create", "compute", "view")
        assert spec.timeout_s > 0 and spec.max_result_chars > 0
        assert spec.activity and "{" not in spec.activity_for({})
    assert REGISTRY["branch_scenario"].mutation and not REGISTRY["inspect_run"].mutation


def test_viewer_role_cannot_mutate():
    names = {t.name for t in tools_for_role("viewer")}
    assert (
        "branch_scenario" not in names
        and "solve_scenario" not in names
        and "create_report" not in names
    )
    assert {
        "get_context",
        "inspect_run",
        "compare_runs",
        "search_evidence",
        "navigate_view",
    } <= names


def test_no_unsafe_tool_names_or_arguments():
    banned = (
        "sql",
        "python",
        "shell",
        "exec",
        "path",
        "url",
        "fetch",
        "email",
        "send",
        "purchase",
        "pump_control",
        "gate",
        "rights",
        "provenance",
        "source_record",
    )
    for t in openai_tools("planner"):
        assert not set(t["name"].split("_")) & set(banned), t["name"]
        props = str(t["parameters"]["properties"].keys())
        assert not any(b in props for b in ("sql", "file_path", "shell", "url"))


def test_branch_changes_do_not_expose_rights_or_sources():
    params = REGISTRY["branch_scenario"].openai_tool()["parameters"]["properties"]["changes"][
        "properties"
    ]
    assert not any(
        k in params
        for k in (
            "roster",
            "rights",
            "evidence_ids",
            "decision_at",
            "pilot_id",
            "reference_receipt_m3",
            "provenance",
        )
    )


def test_schema_version_is_stable():
    assert tool_schema_version() == tool_schema_version()
    assert tool_schema_version().startswith("tools-")
