"""Scenarios and immutable revisions (T3.5, T3.6, PRD §4.3).

A revision stores the full canonical request snapshot, its dependency hashes
(pilot package, candidate library, supply/weather/uncertainty records, solver and
metric versions) and a semantic hash over both. Editing never mutates a revision;
it derives a child from an explicit parent with typed ``RevisionChange``s.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from aabflow.api.errors import DomainError, conflict, invalid, not_found
from aabflow.domain.calendar import local_crop_date
from aabflow.domain.hashes import content_hash
from aabflow.domain.ids import new_id
from aabflow.domain.schemas import (
    ErrorCode,
    Objective,
    OptimizationMode,
    PlanKind,
    RevisionChange,
    ScenarioRequest,
    ScenarioRevision,
)
from aabflow.repositories.sqlite import dumps, loads, tx, utcnow
from aabflow.services.catalog import Catalog
from aabflow.services.interventions import eligibility
from aabflow.services.metrics import METRICS_VERSION
from aabflow.services.pilots import PilotPackage, PilotRepository

SOLVER_VERSION = "aabflow-optimizer-1.0.0"
SET_LIKE = (
    "weather_scenario_ids",
    "blocked_edge_ids",
    "allowed_intervention_instance_ids",
    "forced_instance_ids",
    "excluded_instance_ids",
)


def canonical_request(req: ScenarioRequest) -> dict[str, Any]:
    d = req.model_dump(mode="python")
    for k in SET_LIKE:
        if d.get(k) is not None:
            d[k] = sorted(set(d[k]))
    for k, v in list(d.items()):
        if hasattr(v, "value"):
            d[k] = v.value
    return d


def solver_config() -> dict[str, Any]:
    from aabflow.domain.units import DEFAULT_PRODUCTION_QUANTUM_KG, DEFAULT_WATER_QUANTUM_M3

    return {
        "solver_version": SOLVER_VERSION,
        "water_quantum_m3": DEFAULT_WATER_QUANTUM_M3,
        "production_quantum_kg": DEFAULT_PRODUCTION_QUANTUM_KG,
        "metrics_version": METRICS_VERSION,
    }


def validate(
    pilots: PilotRepository, catalog: Catalog, req: ScenarioRequest
) -> tuple[PilotPackage, dict, list[dict]]:
    """Typed validation (T9.3); returns (package, dependencies, warnings)."""
    pkg = pilots.package(req.pilot_id, req.pilot_version)
    fields: dict[str, str] = {}
    season = catalog.season(req.season_id)
    if season is None:
        raise not_found("season_id", req.season_id)
    if req.planning_mode.value not in season.planning_modes:
        fields["planning_mode"] = (
            f"{req.planning_mode.value} is not offered for {req.season_id} ({season.planning_modes})"
        )
    if req.season_id not in pkg.roster:
        fields["season_id"] = (
            f"pilot {req.pilot_id}/{req.pilot_version} has no roster configured for {req.season_id}"
        )
    weather = {
        w.weather_scenario_id: w for w in catalog.weather_scenarios(req.pilot_id, req.season_id)
    }
    unknown_w = [w for w in req.weather_scenario_ids if w not in weather]
    if unknown_w:
        fields["weather_scenario_ids"] = f"unknown for {req.season_id}: {unknown_w}"
    elif len(req.weather_scenario_ids) > 1 and not any(
        weather[w].is_typical for w in req.weather_scenario_ids
    ):
        fields["weather_scenario_ids"] = (
            "include the designated typical member or a single scenario"
        )
    supply = catalog.supply_profile(req.pilot_id, req.season_id, req.supply_profile_id)
    if supply is None:
        fields["supply_profile_id"] = (
            f"unknown supply profile {req.supply_profile_id!r} for {req.season_id}"
        )
    elif supply.pre_reduced and req.uniform_reduction_fraction > 0:
        fields["uniform_reduction_fraction"] = (
            f"{req.supply_profile_id} is pre-reduced; an extra reduction would apply the curtailment twice"
        )
    us = None
    if req.uncertainty_set_id is not None:
        us = catalog.uncertainty_set(req.uncertainty_set_id)
        if us is None or us.pilot_id != req.pilot_id or us.season_id != req.season_id:
            fields["uncertainty_set_id"] = (
                f"no published uncertainty set {req.uncertainty_set_id!r} for this pilot/season"
            )
    if req.optimization_mode is OptimizationMode.worst_case and req.uncertainty_set_id is None:
        fields["uncertainty_set_id"] = "worst_case requires a published uncertainty set"
    if (
        req.objective is Objective.irrigation_contribution_pkr
        and catalog.price(season.crop.value, req.season_id) is None
    ):
        fields["objective"] = (
            "irrigation_contribution_pkr needs a dated crop price record; none is published"
        )
    bad_edges = [e for e in req.blocked_edge_ids if e not in pkg.edges]
    if bad_edges:
        fields["blocked_edge_ids"] = f"not in pilot network: {bad_edges}"
    planting = season.planting_date or season.start
    for key in (
        "allowed_intervention_instance_ids",
        "forced_instance_ids",
        "excluded_instance_ids",
    ):
        ids = getattr(req, key) or []
        unknown = [i for i in ids if i not in pkg.instances]
        if unknown:
            fields[key] = f"not in pilot version {req.pilot_version}: {unknown}"
    for key in ("allowed_intervention_instance_ids", "forced_instance_ids"):
        for j in getattr(req, key) or []:
            if j in pkg.instances:
                _, reasons = eligibility(pkg, pkg.instances[j], req.decision_at, planting)
                if reasons:
                    fields[key] = f"{j} is not eligible: {'; '.join(reasons)}"
    if (
        req.planning_mode.value != "historical_replay"
        and local_crop_date(req.decision_at) > planting
    ):
        fields["decision_at"] = (
            f"decision after planting ({planting}); v2 supports pre-season planning only"
        )
    if (
        req.service_group
        and req.service_group != "all"
        and not any(f.group == req.service_group for f in pkg.fields.values())
    ):
        fields["service_group"] = f"no {req.service_group} fields in this pilot"
    if fields:
        raise invalid("scenario request failed domain validation", fields)
    lib_hash = catalog.latest_library_hash(req.pilot_id, req.season_id)
    warnings: list[dict] = []
    deps = {
        "pilot_package_sha256": pkg.package_hash,
        "candidate_library_hash": lib_hash,
        "supply_profile_resolved_hash": supply.resolved_hash if supply else None,
        "weather_sha256": {
            w: weather[w].transformed_sha256 for w in sorted(req.weather_scenario_ids)
        },
        "uncertainty_set_hash": content_hash(us.model_dump(mode="json")) if us else None,
        "season_hash": content_hash(season.model_dump(mode="json")),
        "solver": solver_config(),
    }
    if lib_hash is not None:
        summary = catalog.library_summary(req.pilot_id, req.season_id)
        if summary.get("pilot_version") not in (None, req.pilot_version):
            raise conflict(
                "the published candidate library is stale for this pilot version",
                {
                    "library_pilot_version": summary.get("pilot_version"),
                    "request_pilot_version": req.pilot_version,
                },
            )
    return pkg, deps, warnings


def semantic_hash(req: ScenarioRequest, deps: dict) -> str:
    return content_hash({"request": canonical_request(req), "dependencies": deps})


def readiness(state, pkg: PilotPackage, req: ScenarioRequest, deps: dict) -> dict[str, Any]:
    """Pre-solve readiness, including the PRD §8.3 maximum attainable service per group."""
    blockers: list[dict] = []
    warnings: list[dict] = []
    max_service: dict[str, float | None] = {}
    coverage = None
    if deps.get("candidate_library_hash") is None:
        blockers.append(
            {
                "code": "ASSET_UNAVAILABLE",
                "detail": "no published candidate library for this pilot/season",
                "field": "season_id",
            }
        )
    else:
        try:
            from aabflow.services.runs.prepare import prepare
            from aabflow.services.science import get_bindings

            prep = prepare(
                get_bindings(state.settings),
                pkg,
                state.catalog,
                req,
                PlanKind.P,
                library_hash=deps["candidate_library_hash"],
            )
            max_service = prep.max_attainable_service
            coverage = {
                "fields": len(prep.coverage["fields"]),
                "retained": sum(c["retained"] for c in prep.coverage["fields"]),
                "states": prep.coverage["states"],
            }
            for w in prep.warnings:
                warnings.append(
                    {
                        "code": "CANDIDATE_COVERAGE_LIMITED" if "COVERAGE" in w else "NOTE",
                        "detail": w,
                    }
                )
            if req.minimum_service_ratio is not None and req.service_group:
                cap = max_service.get(req.service_group)
                if cap is not None and req.minimum_service_ratio > cap + 1e-9:
                    warnings.append(
                        {
                            "code": "SERVICE_FLOOR_ABOVE_ATTAINABLE",
                            "detail": f"floor {req.minimum_service_ratio:.2f} exceeds the maximum attainable "
                            f"{req.service_group} service {cap:.3f} under the selected supply and repair options; "
                            "the finite model will be infeasible",
                            "field": "minimum_service_ratio",
                        }
                    )
        except DomainError as exc:
            blockers.append({"code": exc.code.value, "detail": exc.detail, "field": None})
    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "max_attainable_service": {
            k: max_service.get(k) for k in ("head", "middle", "tail", "all")
        },
        "coverage": coverage,
    }


# ------------------------------------------------------------------------- persistence


def _revision_from_row(row: sqlite3.Row) -> ScenarioRevision:
    return ScenarioRevision(
        scenario_revision_id=row["scenario_revision_id"],
        scenario_id=row["scenario_id"],
        parent_revision_id=row["parent_revision_id"],
        request=ScenarioRequest.model_validate(loads(row["request"])),
        semantic_hash=row["semantic_hash"],
        candidate_library_hash=row["candidate_library_hash"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def revision_view(conn: sqlite3.Connection, revision_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM scenario_revisions WHERE scenario_revision_id = ?", (revision_id,)
    ).fetchone()
    if row is None:
        raise not_found("scenario_revision_id", revision_id)
    rev = _revision_from_row(row)
    head = conn.execute(
        "SELECT head_revision_id FROM scenarios WHERE scenario_id = ?", (rev.scenario_id,)
    ).fetchone()
    runs = conn.execute(
        "SELECT run_id, plan_kind, outcome, solver_status, created_at, job_id, analysis_id FROM runs "
        "WHERE scenario_revision_id = ? ORDER BY created_at",
        (revision_id,),
    ).fetchall()
    return {
        "revision": rev.model_dump(mode="json"),
        "dependencies": loads(row["dependencies"]),
        "readiness": loads(row["readiness"]),
        "origin": row["origin"],
        "is_head": bool(head and head[0] == revision_id),
        "runs": [dict(r) for r in runs],
    }


def get_revision(conn: sqlite3.Connection, revision_id: str) -> tuple[ScenarioRevision, dict]:
    row = conn.execute(
        "SELECT * FROM scenario_revisions WHERE scenario_revision_id = ?", (revision_id,)
    ).fetchone()
    if row is None:
        raise not_found("scenario_revision_id", revision_id)
    return _revision_from_row(row), loads(row["dependencies"])


def insert_revision(
    conn: sqlite3.Connection,
    state,
    scenario_id: str,
    parent_id: str | None,
    req: ScenarioRequest,
    *,
    origin: str = "user",
    set_head: bool = True,
) -> str:
    pkg, deps, _ = validate(state.pilots, state.catalog, req)
    ready = readiness(state, pkg, req, deps)
    rid = new_id("rev")
    now = utcnow()
    with tx(conn):
        conn.execute(
            "INSERT INTO scenario_revisions (scenario_revision_id, scenario_id, parent_revision_id, request, "
            "semantic_hash, candidate_library_hash, dependencies, readiness, origin, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                scenario_id,
                parent_id,
                dumps(req.model_dump(mode="json")),
                semantic_hash(req, deps),
                deps["candidate_library_hash"],
                dumps(deps),
                dumps(ready),
                origin,
                now,
            ),
        )
        if set_head:
            conn.execute(
                "UPDATE scenarios SET head_revision_id = ? WHERE scenario_id = ?",
                (rid, scenario_id),
            )
    return rid


def create_scenario(
    conn: sqlite3.Connection, state, req: ScenarioRequest, label: str | None, origin: str = "user"
) -> tuple[str, str]:
    validate(state.pilots, state.catalog, req)
    sid = new_id("scn")
    with tx(conn):
        conn.execute(
            "INSERT INTO scenarios (scenario_id, pilot_id, label, head_revision_id, created_at) VALUES (?,?,?,?,?)",
            (sid, req.pilot_id, label, None, utcnow()),
        )
    try:
        rid = insert_revision(conn, state, sid, None, req, origin=origin)
    except BaseException:
        with tx(conn):
            conn.execute("DELETE FROM scenarios WHERE scenario_id = ?", (sid,))
        raise
    return sid, rid


def apply_changes(req: ScenarioRequest, changes: RevisionChange) -> ScenarioRequest:
    data = req.model_dump(mode="python")
    for k, v in changes.model_dump(exclude_unset=True).items():
        data[k] = v
    if "service_group" in changes.model_fields_set and changes.service_group is None:
        data["minimum_service_ratio"] = None
    if (
        "minimum_service_ratio" in changes.model_fields_set
        and changes.minimum_service_ratio is None
    ):
        data["service_group"] = None
    try:
        return ScenarioRequest.model_validate(data)
    except ValueError as exc:
        raise invalid(
            f"changes produce an invalid scenario: {exc}", {"changes": str(exc)[:300]}
        ) from exc


def derive_revision(
    conn: sqlite3.Connection,
    state,
    scenario_id: str,
    parent_id: str,
    changes: RevisionChange,
    origin: str = "user",
) -> str:
    srow = conn.execute("SELECT * FROM scenarios WHERE scenario_id = ?", (scenario_id,)).fetchone()
    if srow is None:
        raise not_found("scenario_id", scenario_id)
    parent, _ = get_revision(conn, parent_id)
    if parent.scenario_id != scenario_id:
        raise DomainError(
            ErrorCode.VERSION_CONFLICT,
            "parent revision belongs to a different scenario",
            extra={"dependency_diff": {"parent_scenario_id": parent.scenario_id}},
        )
    req = apply_changes(parent.request, changes)
    return insert_revision(conn, state, scenario_id, parent_id, req, origin=origin)


def child_revision(
    conn: sqlite3.Connection,
    state,
    parent_id: str,
    changes: dict[str, Any] | RevisionChange,
    origin: str,
) -> str:
    """Analysis-created child revisions (frontier/why-not/synergy); never moves the user's head."""
    parent, _ = get_revision(conn, parent_id)
    ch = changes if isinstance(changes, RevisionChange) else RevisionChange.model_validate(changes)
    req = apply_changes(parent.request, ch)
    return insert_revision(
        conn, state, parent.scenario_id, parent_id, req, origin=origin, set_head=False
    )
