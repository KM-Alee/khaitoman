"""Read-only scheduling and validation for the Cursor workflow.

Run inside the API image. This tool never starts agents, modifies checkpoints,
contacts GitHub, or treats a planned wave as executed evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "docs/agent-dag.json"
MODEL = "grok-4.7[effort=high,context=500k,fast=false]"
STATUSES = {"pending", "active", "validated", "review", "merged", "blocked"}
COMPLETED = {"validated", "review", "merged"}


class DagError(ValueError):
    """An invalid DAG or checkpoint; scheduling must stop."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DagError(message)


def _strings(value: Any, label: str, *, nonempty: bool = True) -> list[str]:
    _require(isinstance(value, list), f"{label} must be a list")
    _require(all(isinstance(x, str) and x.strip() for x in value), f"{label}: invalid string")
    _require(not nonempty or bool(value), f"{label} must not be empty")
    _require(len(value) == len(set(value)), f"{label}: duplicate entries")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    _require(
        not any(
            p == ".env" or p.startswith(".env.")
            for candidate in (path, path.resolve())
            for p in candidate.parts
        ),
        "secret file refused",
    )

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(), object_pairs_hook=unique_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise DagError(f"Cannot load {path}: {exc}") from exc
    _require(isinstance(value, dict), f"{path}: root must be an object")
    return value


def ancestors(nodes: dict[str, dict[str, Any]], node_id: str) -> set[str]:
    result: set[str] = set()
    todo = list(nodes[node_id]["needs"])
    while todo:
        current = todo.pop()
        if current not in result:
            result.add(current)
            todo.extend(nodes[current]["needs"])
    return result


def validate_manifest(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _require(
        type(manifest.get("version")) is int and manifest["version"] == 1,
        "manifest version must be 1",
    )
    _require(manifest.get("model") == MODEL, f"model must be {MODEL}")
    workers = manifest.get("max_workers")
    _require(type(workers) is int and 1 <= workers <= 6, "max_workers must be between 1 and 6")
    resources = manifest.get("resources")
    _require(isinstance(resources, dict) and bool(resources), "resources must be a nonempty object")
    _require(
        all(isinstance(k, str) and k and type(v) is int and v > 0 for k, v in resources.items()),
        "resource capacities must be positive integers",
    )
    raw_nodes = manifest.get("nodes")
    _require(isinstance(raw_nodes, list) and bool(raw_nodes), "nodes must be a nonempty list")
    nodes: dict[str, dict[str, Any]] = {}
    for node in raw_nodes:
        _require(isinstance(node, dict), "node must be an object")
        node_id = node.get("id")
        _require(
            isinstance(node_id, str) and bool(re.fullmatch(r"[A-Z0-9][A-Za-z0-9-]*", node_id)),
            "invalid node id",
        )
        _require(node_id not in nodes, f"duplicate node: {node_id}")
        _require(
            node.get("chunk") is None or isinstance(node["chunk"], str),
            f"{node_id}: chunk must be a string or null",
        )
        for key in ("title", "role"):
            _require(
                isinstance(node.get(key), str) and bool(node[key].strip()),
                f"{node_id}: missing {key}",
            )
        for key in ("needs", "resources", "paths"):
            _strings(node.get(key), f"{node_id}.{key}", nonempty=False)
        for key in ("specs", "requirements", "checks"):
            _strings(node.get(key), f"{node_id}.{key}")
        _require(all(r in resources for r in node["resources"]), f"{node_id}: unknown resource")
        _require(type(node.get("external", False)) is bool, f"{node_id}: external must be boolean")
        dependency_state = node.get("dependency_state", "validated")
        _require(
            isinstance(dependency_state, str) and dependency_state in {"validated", "merged"},
            f"{node_id}: invalid dependency_state",
        )
        nodes[node_id] = node
    for node_id, node in nodes.items():
        _require(all(n in nodes for n in node["needs"]), f"{node_id}: unknown dependency")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        _require(node_id not in visiting, f"dependency cycle at {node_id}")
        if node_id in visited:
            return
        visiting.add(node_id)
        for parent in nodes[node_id]["needs"]:
            visit(parent)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in nodes:
        visit(node_id)
    chunks = manifest.get("chunks")
    _require(isinstance(chunks, dict), "chunks must be an object")
    _require(set(chunks) == {f"P{i:02d}" for i in range(14)}, "chunks must cover P00 through P13")
    assigned: set[str] = set()
    for chunk, children in chunks.items():
        _strings(children, f"chunks.{chunk}")
        for node_id in children:
            _require(node_id in nodes, f"{chunk}: unknown node {node_id}")
            _require(node_id not in assigned, f"node {node_id} belongs to multiple chunks")
            _require(nodes[node_id].get("chunk") == chunk, f"{node_id}: chunk mismatch")
            assigned.add(node_id)
    for node_id, node in nodes.items():
        _require(
            (node.get("chunk") is None and node_id not in assigned) or node_id in assigned,
            f"{node_id}: missing chunk mapping",
        )
    for chunk, children in chunks.items():
        _require(
            set(children[:-1]) <= ancestors(nodes, children[-1]),
            f"{chunk}: terminal must depend on every subnode",
        )
    for key, expected in (
        ("features", {f"F{i:02d}" for i in range(1, 21)}),
        ("acceptance", {f"AT{i:02d}" for i in range(1, 19)}),
    ):
        mapping = manifest.get(key)
        _require(
            isinstance(mapping, dict) and set(mapping) == expected,
            f"{key}: incomplete scope coverage",
        )
        for item, node_ids in mapping.items():
            _strings(node_ids, f"{key}.{item}")
            _require(set(node_ids) <= set(nodes), f"{item}: unknown node in scope mapping")
    _require("G-CORE" in nodes and "P10" in nodes, "missing core or copilot gate")
    core_terminals = {chunks[f"P{i:02d}"][-1] for i in range(10)}
    _require(
        len(chunks["P11"]) >= 2 and chunks["P11"][-1] == "P11-final",
        "P11 must separate pre-copilot work from P11-final",
    )
    core_terminals.update(chunks["P11"][:-1])
    _require(
        core_terminals <= ancestors(nodes, "G-CORE"),
        "G-CORE must require P00–P09 and the pre-copilot P11 terminal",
    )
    _require("G-CORE" in ancestors(nodes, "P10"), "P10 must depend on G-CORE (T13.2)")
    _require("P11-final" in nodes, "missing P11-final consistency gate")
    _require("P10" in ancestors(nodes, "P11-final"), "P11-final must depend on P10")
    _require("G-REVIEW" in nodes, "missing human review gate")
    _require(
        nodes["G-REVIEW"].get("dependency_state") == "merged",
        "G-REVIEW must require merged dependencies",
    )
    terminals = {chunks[f"P{i:02d}"][-1] for i in range(13)}
    _require(
        terminals <= set(nodes["G-REVIEW"]["needs"]),
        "G-REVIEW must directly require every P00–P12 terminal to be merged",
    )
    final_terminal = chunks["P13"][-1]
    _require(
        "G-REVIEW" in ancestors(nodes, final_terminal),
        "P13 release must depend on independent review",
    )
    _require(
        "G-RELEASE" in nodes
        and nodes["G-RELEASE"].get("dependency_state") == "merged"
        and final_terminal in nodes["G-RELEASE"]["needs"],
        "G-RELEASE must directly require the merged P13 terminal",
    )
    return nodes


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(path)
    validate_manifest(manifest)
    return manifest


def _status(state: dict[str, Any], node_id: str) -> str:
    return state.get("nodes", {}).get(node_id, {}).get("status", "pending")


def _missing_dependencies(node: dict[str, Any], state: dict[str, Any]) -> list[str]:
    allowed = {"merged"} if node.get("dependency_state") == "merged" else COMPLETED
    return [node_id for node_id in node["needs"] if _status(state, node_id) not in allowed]


def validate_state(manifest: dict[str, Any], state: dict[str, Any]) -> None:
    nodes = validate_manifest(manifest)
    _require(
        isinstance(state, dict) and type(state.get("version")) is int and state["version"] == 1,
        "state version must be 1",
    )
    records = state.get("nodes")
    _require(isinstance(records, dict), "state.nodes must be an object")
    _require(set(records) <= set(nodes), "state has unknown node ids")
    worktrees: set[str] = set()
    branches: set[str] = set()
    chunks: set[str] = set()
    resource_use = dict.fromkeys(manifest["resources"], 0)
    active = 0
    for node_id, record in records.items():
        _require(isinstance(record, dict), f"{node_id}: state record must be an object")
        status = record.get("status")
        _require(isinstance(status, str) and status in STATUSES, f"{node_id}: invalid status")
        if status in COMPLETED:
            _require(
                isinstance(record.get("commit"), str)
                and bool(re.fullmatch(r"[0-9a-fA-F]{40}", record["commit"])),
                f"{node_id}: completed status requires full commit SHA",
            )
            _strings(record.get("evidence"), f"{node_id}.evidence")
        if status in {"review", "merged"}:
            _require(
                isinstance(record.get("pr"), str)
                and bool(
                    re.fullmatch(r"https://[^/\s]+/[^/\s]+/[^/\s]+/pull/[1-9][0-9]*", record["pr"])
                ),
                f"{node_id}: review/merged requires PR URL",
            )
        if status == "blocked":
            _require(
                isinstance(record.get("blocker"), str) and bool(record["blocker"].strip()),
                f"{node_id}: blocked status requires concrete blocker",
            )
        if status == "active":
            _require(
                not nodes[node_id].get("external"),
                f"{node_id}: external node cannot be leased to a worker",
            )
            for key in ("agent_id", "worktree", "branch"):
                _require(
                    isinstance(record.get(key), str) and bool(record[key].strip()),
                    f"{node_id}: active status requires {key}",
                )
            _require(
                record["branch"]
                not in {"main", "refs/heads/main", "origin/main", "refs/remotes/origin/main"},
                f"{node_id}: main cannot be a worker branch",
            )
            _require(
                Path(record["worktree"]).is_absolute(), f"{node_id}: worktree must be absolute"
            )
            worktree = str(Path(record["worktree"]).resolve())
            _require(
                worktree not in worktrees,
                f"{node_id}: worktree already has an active writer",
            )
            _require(
                record["branch"] not in branches, f"{node_id}: branch already has an active writer"
            )
            worktrees.add(worktree)
            branches.add(record["branch"])
            chunk = nodes[node_id].get("chunk")
            _require(
                chunk is None or chunk not in chunks,
                f"{node_id}: chunk already has an active writer",
            )
            if chunk is not None:
                chunks.add(chunk)
            active += 1
            for resource in nodes[node_id]["resources"]:
                resource_use[resource] += 1
        if status in COMPLETED | {"active"}:
            missing = _missing_dependencies(nodes[node_id], state)
            _require(
                not missing,
                f"{node_id}: {status} before dependencies satisfied: {', '.join(missing)}",
            )
    _require(active <= manifest["max_workers"], "too many active workers")
    for resource, used in resource_use.items():
        _require(used <= manifest["resources"][resource], f"resource overbooked: {resource}")


def load_state(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    state = _read_json(path)
    validate_state(manifest, state)
    return state


def plan(manifest: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    validate_state(manifest, state)
    nodes = validate_manifest(manifest)
    active = [n for n in nodes if _status(state, n) == "active"]
    selected: list[str] = []
    chunks = {nodes[n].get("chunk") for n in active if nodes[n].get("chunk")}
    resources = dict(manifest["resources"])
    for node_id in active:
        for resource in nodes[node_id]["resources"]:
            resources[resource] -= 1
    waiting: dict[str, str] = {}
    external: list[str] = []
    blocked: dict[str, str] = {}
    for node_id, node in nodes.items():
        status = _status(state, node_id)
        if status == "blocked":
            blocked[node_id] = state["nodes"][node_id]["blocker"]
            continue
        if status != "pending":
            continue
        if node.get("external"):
            external.append(node_id)
            continue
        missing = _missing_dependencies(node, state)
        if missing:
            waiting[node_id] = "dependencies: " + ", ".join(missing)
        elif node.get("chunk") is not None and node["chunk"] in chunks:
            waiting[node_id] = "chunk already has a writer"
        elif any(resources[r] <= 0 for r in node["resources"]):
            waiting[node_id] = "resource lease: " + ", ".join(
                r for r in node["resources"] if resources[r] <= 0
            )
        elif len(selected) + len(active) >= manifest["max_workers"]:
            waiting[node_id] = "worker capacity"
        else:
            selected.append(node_id)
            if node.get("chunk"):
                chunks.add(node["chunk"])
            for resource in node["resources"]:
                resources[resource] -= 1
    return {
        "ready": selected,
        "active": active,
        "waiting_external": external,
        "blocked": blocked,
        "waiting": waiting,
    }


def waves(manifest: dict[str, Any]) -> dict[str, Any]:
    """A capacity-bounded structural forecast, assuming all external gates pass."""
    nodes = validate_manifest(manifest)
    remaining = {n for n in nodes if not nodes[n].get("external")}
    completed: set[str] = set()
    result: list[list[str]] = []
    while remaining:
        while True:
            unlocked = {
                n
                for n, node in nodes.items()
                if node.get("external") and n not in completed and set(node["needs"]) <= completed
            }
            if not unlocked:
                break
            completed.update(unlocked)
        resources = dict(manifest["resources"])
        chunks: set[str] = set()
        wave: list[str] = []
        for node_id, node in nodes.items():
            if node_id not in remaining or not set(node["needs"]) <= completed:
                continue
            chunk = node.get("chunk")
            if len(wave) >= manifest["max_workers"] or (chunk is not None and chunk in chunks):
                continue
            if any(resources[r] <= 0 for r in node["resources"]):
                continue
            wave.append(node_id)
            if chunk is not None:
                chunks.add(chunk)
            for resource in node["resources"]:
                resources[resource] -= 1
        _require(bool(wave), "no runnable forecast wave")
        result.append(wave)
        completed.update(wave)
        remaining.difference_update(wave)
    return {
        "assumption": "Structural forecast only; every external gate is assumed satisfied, not verified.",
        "external_gates": [n for n in nodes if nodes[n].get("external")],
        "waves": result,
    }


def mermaid(manifest: dict[str, Any]) -> str:
    nodes = validate_manifest(manifest)
    lines = ["flowchart TD"]
    for node_id, node in nodes.items():
        label = node_id + ": " + node["title"]
        label = (
            label.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", " ")
        )
        lines.append(f'  {node_id.replace("-", "_")}["{label}"]')
        for parent in node["needs"]:
            lines.append(f"  {parent.replace('-', '_')} --> {node_id.replace('-', '_')}")
    return "\n".join(lines)


def document(manifest: dict[str, Any]) -> str:
    """Generate the human-readable graph from its sole edge source."""
    lines = [
        "# AabFlow complete work DAG",
        "",
        (
            "Generated from [agent-dag.json](agent-dag.json); regenerate with "
            "`python scripts/agent_dag.py document` inside Docker."
        ),
        (
            "Read [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md) for execution, ownership, "
            "isolated runtimes, checkpoints and reviewer gates."
        ),
        "This graph is a plan, not evidence of executed product work.",
        "",
        "```mermaid",
        mermaid(manifest),
        "```",
        "",
        "| Node | Owner | Prerequisites | Exclusive resources |",
        "|---|---|---|---|",
    ]
    for node in manifest["nodes"]:
        lines.append(
            f"| {node['id']} | {node['role']} | "
            f"{', '.join(node['needs']) or '—'} | {', '.join(node['resources']) or '—'} |"
        )
    lines.extend(
        [
            "",
            (
                "Forecast waves below assume existing prerequisites and future reviews succeed; "
                "they are not dispatch permission or time estimates. Runtime `plan --state` "
                "uses actual checkpoint/lease records. Bases must contain all prerequisite SHAs."
            ),
            "",
        ]
    )
    for index, wave in enumerate(waves(manifest)["waves"], 1):
        lines.append(f"{index}. {', '.join(wave)}")
    lines.extend(
        [
            "",
            (
                "All split nodes retain their parent PNN completion barrier. "
                "P11-core is partial AT13/AT14; G-CORE unlocks P10; P11-final completes both ATs. "
                "G-REVIEW and G-RELEASE require actual independent reviewer merges/evidence."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("waves")
    sub.add_parser("mermaid")
    sub.add_parser("document")
    brief = sub.add_parser("brief")
    brief.add_argument("id")
    scheduler = sub.add_parser("plan")
    scheduler.add_argument("--state", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "validate":
            print(f"Valid DAG: {len(manifest['nodes'])} nodes, 14 chunks; no execution claimed.")
        elif args.command == "mermaid":
            print(mermaid(manifest))
        elif args.command == "document":
            print(document(manifest), end="")
        elif args.command == "waves":
            print(json.dumps(waves(manifest), indent=2))
        elif args.command == "brief":
            nodes = validate_manifest(manifest)
            _require(args.id in nodes, f"unknown node: {args.id}")
            print(json.dumps({"model": manifest["model"], **nodes[args.id]}, indent=2))
        else:
            print(json.dumps(plan(manifest, load_state(args.state, manifest)), indent=2))
        return 0
    except DagError as exc:
        print(f"DAG error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
