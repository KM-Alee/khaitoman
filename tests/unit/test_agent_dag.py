"""Scheduling regression cases; these synthetic DAGs are test fixtures only."""

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "agent_dag", Path(__file__).resolve().parents[2] / "scripts/agent_dag.py"
)
assert _SPEC and _SPEC.loader
dag = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dag)


def node(node_id, chunk=None, needs=(), resources=(), **extra):
    return {
        "id": node_id,
        "chunk": chunk,
        "title": "Synthetic test task",
        "role": "fixture-engineer",
        "needs": list(needs),
        "resources": list(resources),
        "paths": ["tests/fixture-only/**"],
        "specs": ["Synthetic fixture spec"],
        "requirements": ["Fixture requirement"],
        "checks": ["Fixture check"],
        **extra,
    }


@pytest.fixture
def manifest():
    nodes = [
        node("P00", "P00", external=True),
        node("P01", "P01", ["P00"], external=True),
        node("P02", "P02", ["P01"], ["science"]),
        node("P03", "P03", ["P01"], ["science"]),
        node("P04", "P04", ["P01"], ["gpu"]),
        node("P05-api", "P05", ["P01"]),
        node("P05-files", "P05", ["P05-api"]),
        *[node(f"P{i:02d}", f"P{i:02d}", ["P01"]) for i in range(6, 9)],
        node("P09", "P09", ["P02", "P03", "P04", "P05-files", "P06", "P07", "P08"]),
        node("G-CORE", needs=["P09", "P11-ui"]),
        node("G-CONNECT", needs=["P01"], resources=["provider"]),
        node("P10", "P10", ["G-CORE", "G-CONNECT"], ["provider"]),
        node("P11-ui", "P11", ["P09"], ["demo"]),
        node("P11-final", "P11", ["P10", "P11-ui"], ["demo"]),
        node("P12", "P12", ["P11-final"], ["demo"]),
        node(
            "G-REVIEW",
            needs=[
                "P00",
                "P01",
                "P02",
                "P03",
                "P04",
                "P05-files",
                "P06",
                "P07",
                "P08",
                "P09",
                "P10",
                "P11-final",
                "P12",
            ],
            external=True,
            dependency_state="merged",
        ),
        node("P13", "P13", ["G-REVIEW"]),
        node("G-RELEASE", needs=["P13"], external=True, dependency_state="merged"),
    ]
    return {
        "version": 1,
        "model": dag.MODEL,
        "max_workers": 3,
        "resources": {"contracts": 1, "gpu": 1, "science": 1, "demo": 1, "provider": 1},
        "chunks": {
            f"P{i:02d}": [n["id"] for n in nodes if n["chunk"] == f"P{i:02d}"] for i in range(14)
        },
        "features": {f"F{i:02d}": ["P00"] for i in range(1, 21)},
        "acceptance": {f"AT{i:02d}": ["P00"] for i in range(1, 19)},
        "nodes": nodes,
    }


def completed(status="validated"):
    record = {"status": status, "commit": "a" * 40, "evidence": ["evidence/test-fixture.log"]}
    if status in {"review", "merged"}:
        record["pr"] = "https://github.com/fixture/fixture/pull/123"
    return record


def state(**records):
    return {
        "version": 1,
        "nodes": {"P00": completed("merged"), "P01": completed("review"), **records},
    }


def active(node_id):
    return {
        "status": "active",
        "agent_id": f"agent-{node_id}",
        "worktree": f"/fixture/{node_id}",
        "branch": f"feat/{node_id}",
    }


def find(manifest, node_id):
    return next(n for n in manifest["nodes"] if n["id"] == node_id)


def test_ready_tasks_are_bounded_and_do_not_overbook_science(manifest):
    result = dag.plan(manifest, state())
    assert result["ready"] == ["P02", "P04", "P05-api"]
    assert result["waiting"]["P03"].startswith("resource lease")
    assert result["waiting"]["P06"] == "worker capacity"
    assert "G-REVIEW" in result["waiting_external"]


def test_existing_active_lease_reserves_resource_and_worker_slot(manifest):
    result = dag.plan(manifest, state(P03=active("P03")))
    assert result["ready"] == ["P04", "P05-api"]
    assert result["active"] == ["P03"]
    assert result["waiting"]["P02"].startswith("resource lease")


def test_same_chunk_cannot_get_two_writers(manifest):
    find(manifest, "P05-files")["needs"] = ["P01"]
    # Keep the completion barrier dependent on the API while adding a separate sibling.
    manifest["nodes"].append(node("P05-extra", "P05", ["P01"]))
    manifest["chunks"]["P05"] = ["P05-api", "P05-extra", "P05-files"]
    find(manifest, "P05-files")["needs"] = ["P05-api", "P05-extra"]
    result = dag.plan(manifest, state(**{"P05-api": active("P05-api")}))
    assert result["waiting"]["P05-extra"] == "chunk already has a writer"
    with pytest.raises(dag.DagError, match="chunk already has"):
        dag.validate_state(
            manifest, state(**{"P05-api": active("P05-api"), "P05-extra": active("P05-extra")})
        )


def test_blocked_node_is_visible_and_not_scheduled(manifest):
    result = dag.plan(
        manifest, state(P02={"status": "blocked", "blocker": "Fixture upstream unavailable"})
    )
    assert result["blocked"] == {"P02": "Fixture upstream unavailable"}
    assert "P02" not in result["ready"]
    with pytest.raises(dag.DagError, match="concrete blocker"):
        dag.validate_state(manifest, state(P02={"status": "blocked"}))


@pytest.mark.parametrize(
    "damage,message",
    [
        ("duplicate", "duplicate node"),
        ("unknown", "unknown dependency"),
        ("cycle", "cycle"),
        ("core", "P10 must depend on G-CORE"),
        ("consistency", "P11-final must depend on P10"),
        ("coverage", "chunks must cover"),
        ("features", "incomplete scope coverage"),
        ("acceptance", "unknown node in scope"),
        ("scope", "requirements must not be empty"),
        ("model", "model must be"),
        ("resources", "unknown resource"),
        ("terminal", "terminal must depend"),
        ("review", "must require merged"),
    ],
)
def test_invalid_dags_fail_closed(manifest, damage, message):
    if damage == "duplicate":
        manifest["nodes"].append(deepcopy(manifest["nodes"][0]))
    elif damage == "unknown":
        find(manifest, "P02")["needs"] = ["missing"]
    elif damage == "cycle":
        find(manifest, "P00")["needs"] = ["P01"]
    elif damage == "core":
        find(manifest, "P10")["needs"] = ["G-CONNECT"]
    elif damage == "consistency":
        find(manifest, "P11-final")["needs"] = ["P11-ui"]
    elif damage == "coverage":
        del manifest["chunks"]["P13"]
    elif damage == "features":
        del manifest["features"]["F20"]
    elif damage == "acceptance":
        manifest["acceptance"]["AT18"] = ["missing"]
    elif damage == "scope":
        find(manifest, "P02")["requirements"] = []
    elif damage == "model":
        manifest["model"] = "grok-4.7[fast=true]"
    elif damage == "resources":
        find(manifest, "P02")["resources"] = ["missing"]
    elif damage == "terminal":
        find(manifest, "P05-files")["needs"] = ["P01"]
    else:
        find(manifest, "G-REVIEW")["dependency_state"] = "validated"
    with pytest.raises(dag.DagError, match=message):
        dag.validate_manifest(manifest)


@pytest.mark.parametrize(
    "record,message",
    [
        ({"status": "validated"}, "full commit SHA"),
        ({"status": "validated", "commit": "a" * 40, "evidence": []}, "must not be empty"),
        ({**completed("review"), "pr": "not a PR"}, "requires PR URL"),
        ({**completed("merged"), "commit": "abcd"}, "full commit SHA"),
        ({"status": "active"}, "requires agent_id"),
        ({**active("P02"), "branch": "main"}, "main cannot"),
        ({"status": "made_up"}, "invalid status"),
        ({"status": []}, "invalid status"),
    ],
)
def test_false_completion_and_malformed_leases_are_rejected(manifest, record, message):
    with pytest.raises(dag.DagError, match=message):
        dag.validate_state(manifest, state(P02=record))


def test_child_completion_and_execution_require_completed_prerequisites(manifest):
    for record in (completed(), active("P10")):
        with pytest.raises(dag.DagError, match="before dependencies satisfied"):
            dag.validate_state(manifest, state(P10=record))


def test_checkpoint_does_not_accept_unknown_nodes(manifest):
    with pytest.raises(dag.DagError, match="unknown node ids"):
        dag.validate_state(manifest, state(MISSING={"status": "pending"}))


def test_worktree_and_resource_collisions_are_rejected(manifest):
    with pytest.raises(dag.DagError, match="resource overbooked"):
        dag.validate_state(manifest, state(P02=active("P02"), P03=active("P03")))
    second = active("P04")
    second["worktree"] = active("P02")["worktree"]
    with pytest.raises(dag.DagError, match="worktree already"):
        dag.validate_state(manifest, state(P02=active("P02"), P04=second))


def test_review_gate_does_not_accept_unmerged_prs(manifest):
    records = {}
    for n in manifest["nodes"]:
        if n["id"] == "G-REVIEW":
            break
        records[n["id"]] = completed("review")
    review_state = {"version": 1, "nodes": records}
    dag.validate_state(manifest, review_state)
    assert "P13" not in dag.plan(manifest, review_state)["ready"]
    records["G-REVIEW"] = completed()
    with pytest.raises(dag.DagError, match="before dependencies satisfied"):
        dag.validate_state(manifest, review_state)
    for n in find(manifest, "G-REVIEW")["needs"]:
        records[n] = completed("merged")
    assert "P13" in dag.plan(manifest, review_state)["ready"]


def test_forecast_preserves_external_review_gate_prerequisites(manifest):
    forecast = dag.waves(manifest)
    sequence = {node_id: index for index, wave in enumerate(forecast["waves"]) for node_id in wave}
    assert sequence["P13"] > sequence["P12"]
    assert sequence["P10"] > sequence["G-CORE"]
    assert all(len(wave) <= 3 for wave in forecast["waves"])
    assert "not verified" in forecast["assumption"]
    assert all(not find(manifest, n).get("external") for n in sequence)


def test_cli_brief_does_not_change_manifest_or_state(manifest, tmp_path, capsys):
    path = tmp_path / "fixture-dag.json"
    content = json.dumps(manifest)
    path.write_text(content)
    assert dag.main(["--manifest", str(path), "brief", "P10"]) == 0
    brief = json.loads(capsys.readouterr().out)
    assert brief["model"] == dag.MODEL
    assert brief["needs"] == ["G-CORE", "G-CONNECT"]
    assert path.read_text() == content
    assert dag.main(["--manifest", str(path), "brief", "MISSING"]) == 1
    assert "unknown node" in capsys.readouterr().err


def test_secret_checkpoint_paths_are_refused_without_reading(tmp_path, monkeypatch):
    def forbidden_read(*args, **kwargs):
        raise AssertionError("Secret path reached read_text")

    monkeypatch.setattr(Path, "read_text", forbidden_read)
    with pytest.raises(dag.DagError, match="secret file refused"):
        dag._read_json(tmp_path / ".env.fixture")


def test_review_gate_cannot_omit_a_chunk_terminal(manifest):
    find(manifest, "G-REVIEW")["needs"].remove("P05-files")
    with pytest.raises(dag.DagError, match="every P00–P12 terminal"):
        dag.validate_manifest(manifest)


@pytest.mark.parametrize("field", ["chunk", "dependency_state"])
def test_unhashable_manifest_values_fail_with_diagnostic(manifest, field):
    find(manifest, "P02")[field] = []
    with pytest.raises(dag.DagError):
        dag.validate_manifest(manifest)


def test_active_workers_cannot_exceed_global_capacity(manifest):
    with pytest.raises(dag.DagError, match="too many active workers"):
        dag.validate_state(
            manifest, state(**{n: active(n) for n in ["P02", "P04", "P05-api", "P06"]})
        )


def test_worktree_aliases_share_the_same_writer_lease(manifest):
    second = active("P04")
    second["worktree"] = "/fixture/P02/subdirectory/.."
    with pytest.raises(dag.DagError, match="worktree already"):
        dag.validate_state(manifest, state(P02=active("P02"), P04=second))


def test_cli_reports_corrupt_json_without_traceback(tmp_path, capsys):
    path = tmp_path / "fixture.json"
    path.write_text("{broken")
    assert dag.main(["--manifest", str(path), "validate"]) == 1
    assert "Cannot load" in capsys.readouterr().err


def test_core_gate_cannot_become_an_empty_name(manifest):
    find(manifest, "G-CORE")["needs"] = ["P11-ui"]
    find(manifest, "P11-ui")["needs"] = ["P01"]
    with pytest.raises(dag.DagError, match="G-CORE must require"):
        dag.validate_manifest(manifest)


def test_generated_document_and_cursor_configuration_do_not_drift():
    root = Path(__file__).resolve().parents[2]
    manifest = dag.load_manifest()
    assert (root / "docs/AGENT_DAG.md").read_text() == dag.document(manifest)
    agents = root / ".cursor/agents"
    expected = {
        "data-engineer",
        "science-engineer",
        "optimizer-engineer",
        "frontend-engineer",
        "spec-auditor",
        "verifier",
    }
    assert {p.stem for p in agents.glob("*.md")} == expected
    for name in expected:
        content = (agents / f"{name}.md").read_text()
        assert f"name: {name}\n" in content
        assert f'model: "{dag.MODEL}"\n' in content
        assert "is_background: true\n" in content
        assert f"readonly: {'true' if name == 'spec-auditor' else 'false'}\n" in content
    assert "alwaysApply: true\n" in (root / ".cursor/rules/aabflow.mdc").read_text()


def test_checkpoint_duplicate_keys_cannot_silently_replace_a_lease(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"version":1,"nodes":{},"nodes":{"P10":{"status":"merged"}}}')
    with pytest.raises(dag.DagError, match="duplicate JSON key"):
        dag._read_json(path)


def test_json_loader_refuses_a_secret_symlink_without_opening_it(tmp_path):
    # Synthetic unreadable secret fixture: no real environment contents.
    alias = tmp_path / "checkpoint.json"
    alias.symlink_to(tmp_path / ".env")
    with pytest.raises(dag.DagError, match="secret file refused"):
        dag._read_json(alias)


def test_final_release_cannot_skip_independent_p13_merge(manifest):
    find(manifest, "G-RELEASE")["dependency_state"] = "validated"
    with pytest.raises(dag.DagError, match="merged P13 terminal"):
        dag.validate_manifest(manifest)
