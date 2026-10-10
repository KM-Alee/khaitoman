"""Report routes (T9.1, T9.4).

Parent registers this router in ``main._routers`` immediately before
``copilot_router``. This module does not edit ``main.py``.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import FileResponse

from aabflow.api.idempotency import run_idempotent
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.domain.schemas import Job, StrictModel
from aabflow.jobs import queue
from aabflow.services import reports as svc

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]


class ReportAccepted(StrictModel):
    report_id: str
    job_id: str
    job: Job


class ReportView(StrictModel):
    report_id: str
    status: str
    report_type: str
    run_ids: list[str]
    analysis_ids: list[str]
    job_id: str | None
    job_state: str | None
    job_error: dict[str, Any] | None
    download_url: str | None
    created_at: str
    report_hash: str | None
    report_hash_scope: str | None
    artifact_kind: str | None
    final_self_contained_report: bool


@router.post("/reports", status_code=202, response_model=ReportAccepted)
def create_report(body: svc.ReportCreate, state: State, conn: Conn, idem: IdemKey = None):
    def create():
        report_id, job_id = svc.create(conn, body)
        if state.dispatcher:
            state.dispatcher.notify()
        job = queue.row_to_job(queue.get(conn, job_id))
        return 202, {
            "report_id": report_id,
            "job_id": job_id,
            "job": job.model_dump(mode="json"),
        }

    return run_idempotent(conn, "POST /reports", idem, body.model_dump(mode="json"), create)


@router.get("/reports/{report_id}", response_model=ReportView)
def get_report(report_id: str, state: State, conn: Conn) -> dict[str, Any]:
    return svc.get_report(conn, state.settings, report_id)


@router.get("/reports/{report_id}/files/{rel:path}")
def report_file(report_id: str, rel: str, state: State, conn: Conn) -> FileResponse:
    path = svc.open_report_file(conn, state.settings, report_id, rel)
    media = "application/json" if path.suffix.lower() == ".json" else "application/octet-stream"
    return FileResponse(
        path,
        media_type=media,
        filename=path.name,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
