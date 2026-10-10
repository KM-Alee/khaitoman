"""Analysis routes: frontier, stress, why-not, sensitivity, synergy (T9.1, T7)."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query

from aabflow.api.errors import invalid, not_found
from aabflow.api.idempotency import run_idempotent
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.domain.schemas import Job, StrictModel
from aabflow.jobs import queue
from aabflow.services import analyses as svc
from aabflow.services.runs import load_run
from aabflow.services.scenarios import get_revision

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]


class AnalysisAccepted(StrictModel):
    analysis_id: str
    job_id: str
    job: Job


class AnalysisView(StrictModel):
    analysis_id: str
    kind: str
    pilot_id: str | None
    base_revision_id: str | None
    base_run_id: str | None
    job_id: str | None
    job_state: str | None
    job_error: dict[str, Any] | None
    status: str
    request: dict[str, Any]
    result: dict[str, Any] | None
    child_run_ids: list[str]
    created_at: str
    updated_at: str


class AnalysisList(StrictModel):
    analyses: list[dict[str, Any]]


def _accept(
    conn: sqlite3.Connection,
    state: AppState,
    kind: str,
    body: StrictModel,
    idem: str | None,
    *,
    base_revision_id: str | None,
    base_run_id: str | None,
):
    def create():
        aid, jid = svc.create(
            conn, kind, body, base_revision_id=base_revision_id, base_run_id=base_run_id
        )
        if state.dispatcher:
            state.dispatcher.notify()
        job = queue.row_to_job(queue.get(conn, jid))
        return 202, {"analysis_id": aid, "job_id": jid, "job": job.model_dump(mode="json")}

    return run_idempotent(
        conn, f"POST /analyses/{kind}", idem, body.model_dump(mode="json"), create
    )


def _package(state: AppState, conn: sqlite3.Connection, revision_id: str):
    rev, _ = get_revision(conn, revision_id)
    return rev, state.pilots.package(rev.request.pilot_id, rev.request.pilot_version)


def _check_instance(pkg, instance_id: str, field: str) -> None:
    if instance_id not in pkg.instances:
        raise invalid(
            f"{instance_id} is not an intervention instance in pilot version {pkg.pilot_version}",
            {field: instance_id},
        )


def _plan_run(conn: sqlite3.Connection, run_id: str, field: str):
    r = load_run(conn, run_id)
    if r.result.outcome != "plan":
        raise invalid(
            f"{run_id} has no validated plan (outcome {r.result.outcome})", {field: run_id}
        )
    return r


@router.post("/analyses/frontier", status_code=202, response_model=AnalysisAccepted)
def frontier(body: svc.FrontierRequest, state: State, conn: Conn, idem: IdemKey = None):
    get_revision(conn, body.base_revision_id)
    return _accept(
        conn,
        state,
        "frontier",
        body,
        idem,
        base_revision_id=body.base_revision_id,
        base_run_id=None,
    )


@router.post("/analyses/stress", status_code=202, response_model=AnalysisAccepted)
def stress(body: svc.StressRequest, state: State, conn: Conn, idem: IdemKey = None):
    run = _plan_run(conn, body.run_id, "run_id")
    if body.reference_run_id:
        _plan_run(conn, body.reference_run_id, "reference_run_id")
    if body.state_ids is not None and len(set(body.state_ids)) != len(body.state_ids):
        raise invalid("state_ids must be distinct", {"state_ids": "duplicates"})
    return _accept(
        conn,
        state,
        "stress",
        body,
        idem,
        base_revision_id=run.result.scenario_revision_id,
        base_run_id=body.run_id,
    )


@router.post("/analyses/why-not", status_code=202, response_model=AnalysisAccepted)
def why_not(body: svc.WhyNotRequest, state: State, conn: Conn, idem: IdemKey = None):
    _, pkg = _package(state, conn, body.base_revision_id)
    _check_instance(pkg, body.instance_id, "instance_id")
    if body.base_run_id:
        r = _plan_run(conn, body.base_run_id, "base_run_id")
        if r.result.scenario_revision_id != body.base_revision_id:
            raise invalid(
                "base_run_id belongs to a different revision", {"base_run_id": body.base_run_id}
            )
    return _accept(
        conn,
        state,
        "why_not",
        body,
        idem,
        base_revision_id=body.base_revision_id,
        base_run_id=body.base_run_id,
    )


@router.post("/analyses/sensitivity", status_code=202, response_model=AnalysisAccepted)
def sensitivity(body: svc.SensitivityRequest, state: State, conn: Conn, idem: IdemKey = None):
    get_revision(conn, body.base_revision_id)
    return _accept(
        conn,
        state,
        "sensitivity",
        body,
        idem,
        base_revision_id=body.base_revision_id,
        base_run_id=None,
    )


@router.post("/analyses/synergy", status_code=202, response_model=AnalysisAccepted)
def synergy(body: svc.SynergyRequest, state: State, conn: Conn, idem: IdemKey = None):
    _, pkg = _package(state, conn, body.base_revision_id)
    _check_instance(pkg, body.instance_a, "instance_a")
    _check_instance(pkg, body.instance_b, "instance_b")
    ga = pkg.instances[body.instance_a].mutually_exclusive_group
    gb = pkg.instances[body.instance_b].mutually_exclusive_group
    if ga and ga == gb:
        raise invalid(
            "the two instances are mutually exclusive alternatives, so A+B is not a compatible "
            "combination",
            {"instance_b": f"same exclusive group {ga}"},
        )
    if body.base_run_id:
        r = _plan_run(conn, body.base_run_id, "base_run_id")
        if r.result.scenario_revision_id != body.base_revision_id:
            raise invalid(
                "base_run_id belongs to a different revision", {"base_run_id": body.base_run_id}
            )
    return _accept(
        conn,
        state,
        "synergy",
        body,
        idem,
        base_revision_id=body.base_revision_id,
        base_run_id=body.base_run_id,
    )


@router.get("/analyses", response_model=AnalysisList)
def list_analyses(
    conn: Conn,
    kind: str | None = None,
    base_revision_id: str | None = None,
    base_run_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AnalysisList:
    if kind is not None and kind not in svc.KINDS:
        raise invalid(f"unknown analysis kind {kind}", {"kind": kind})
    return AnalysisList(
        analyses=svc.list_analyses(
            conn, kind=kind, base_revision_id=base_revision_id, base_run_id=base_run_id, limit=limit
        )
    )


@router.get("/analyses/{analysis_id}", response_model=AnalysisView)
def get_analysis(analysis_id: str, conn: Conn) -> dict:
    a = svc.get_analysis(conn, analysis_id)
    if a is None:
        raise not_found("analysis_id", analysis_id)
    return a
