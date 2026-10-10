"""Scenario, revision and solve routes (T9.1)."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header

from aabflow.api.errors import DomainError, invalid, not_found
from aabflow.api.idempotency import run_idempotent
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import (
    CONTRACT_VERSION,
    ErrorCode,
    Job,
    OptimizationMode,
    PlanKind,
    RevisionChange,
    ScenarioRequest,
    ScenarioRevision,
    SolveRequest,
    StrictModel,
)
from aabflow.jobs import queue
from aabflow.services import scenarios as svc

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]


class ScenarioCreate(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    label: str | None = None
    request: ScenarioRequest


class RevisionCreate(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    parent_revision_id: str
    changes: RevisionChange


class Issue(StrictModel):
    code: str
    detail: str
    field: str | None = None


class Readiness(StrictModel):
    ready: bool
    blockers: list[Issue]
    warnings: list[Issue]
    max_attainable_service: dict[str, float | None]
    coverage: dict[str, Any] | None = None


class RevisionRun(StrictModel):
    run_id: str
    plan_kind: str
    outcome: str
    solver_status: str
    created_at: str
    job_id: str | None = None
    analysis_id: str | None = None


class RevisionView(StrictModel):
    revision: ScenarioRevision
    dependencies: dict[str, Any]
    readiness: Readiness
    origin: str
    is_head: bool
    runs: list[RevisionRun]


class ScenarioCreated(StrictModel):
    scenario_id: str
    revision: RevisionView


class ScenarioView(StrictModel):
    scenario_id: str
    pilot_id: str
    label: str | None
    head_revision_id: str | None
    revisions: list[dict[str, Any]]


class JobAccepted(StrictModel):
    job_id: str
    job: Job


@router.post("/scenarios", status_code=201, response_model=ScenarioCreated)
def create_scenario(body: ScenarioCreate, state: State, conn: Conn, idem: IdemKey = None):
    def create():
        sid, rid = svc.create_scenario(conn, state, body.request, body.label)
        return 201, {"scenario_id": sid, "revision": svc.revision_view(conn, rid)}

    return run_idempotent(conn, "POST /scenarios", idem, body.model_dump(mode="json"), create)


@router.get("/scenarios/{scenario_id}", response_model=ScenarioView)
def get_scenario(scenario_id: str, conn: Conn) -> ScenarioView:
    row = conn.execute("SELECT * FROM scenarios WHERE scenario_id = ?", (scenario_id,)).fetchone()
    if row is None:
        raise not_found("scenario_id", scenario_id)
    revs = conn.execute(
        "SELECT scenario_revision_id, parent_revision_id, semantic_hash, origin, created_at FROM scenario_revisions "
        "WHERE scenario_id = ? ORDER BY created_at",
        (scenario_id,),
    ).fetchall()
    return ScenarioView(
        scenario_id=scenario_id,
        pilot_id=row["pilot_id"],
        label=row["label"],
        head_revision_id=row["head_revision_id"],
        revisions=[dict(r) for r in revs],
    )


@router.post("/scenarios/{scenario_id}/revisions", status_code=201, response_model=RevisionView)
def create_revision(
    scenario_id: str, body: RevisionCreate, state: State, conn: Conn, idem: IdemKey = None
):
    def create():
        rid = svc.derive_revision(conn, state, scenario_id, body.parent_revision_id, body.changes)
        return 201, svc.revision_view(conn, rid)

    return run_idempotent(
        conn, f"POST /scenarios/{scenario_id}/revisions", idem, body.model_dump(mode="json"), create
    )


@router.get("/scenario-revisions/{revision_id}", response_model=RevisionView)
def get_revision(revision_id: str, conn: Conn) -> dict:
    return svc.revision_view(conn, revision_id)


@router.post("/scenario-revisions/{revision_id}/solve", status_code=202, response_model=JobAccepted)
def solve(
    revision_id: str,
    state: State,
    conn: Conn,
    body: SolveRequest | None = None,
    idem: IdemKey = None,
):
    body = body or SolveRequest()
    rev, deps = svc.get_revision(conn, revision_id)
    req = rev.request
    if body.plan_kind is PlanKind.R and not req.uncertainty_set_id:
        raise invalid(
            "plan R (robust) requires the revision to name an uncertainty_set_id",
            {"uncertainty_set_id": "missing"},
        )
    if (
        body.plan_kind in (PlanKind.B0, PlanKind.B1)
        and req.optimization_mode is OptimizationMode.worst_case
    ):
        raise invalid(
            "B0/B1 are typical-state baselines; use a typical-mode revision",
            {"plan_kind": body.plan_kind},
        )
    pkg = state.pilots.package(req.pilot_id, req.pilot_version)
    if deps.get("pilot_package_sha256") != pkg.package_hash:
        raise DomainError(
            ErrorCode.VERSION_CONFLICT,
            "pilot package changed since this revision was created",
            extra={
                "dependency_diff": {
                    "revision": deps.get("pilot_package_sha256"),
                    "current": pkg.package_hash,
                }
            },
        )
    lib = rev.candidate_library_hash or state.catalog.latest_library_hash(
        req.pilot_id, req.season_id
    )
    if lib is None:
        raise DomainError(
            ErrorCode.ASSET_UNAVAILABLE, "no published candidate library for this pilot/season"
        )
    payload = {
        "scenario_revision_id": revision_id,
        "plan_kind": body.plan_kind.value,
        "time_limit_s": body.time_limit_s,
    }

    def create():
        jid = queue.enqueue(conn, "solve", payload, content_hash(payload), subject_id=revision_id)
        if state.dispatcher:
            state.dispatcher.notify()
        row = queue.get(conn, jid)
        return 202, {"job_id": jid, "job": queue.row_to_job(row).model_dump(mode="json")}

    return run_idempotent(
        conn, f"POST /scenario-revisions/{revision_id}/solve", idem, payload, create
    )
