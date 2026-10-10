"""Surrogate preview and exact-confirmation routes (T9.1, T8.4)."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header

from aabflow.api.errors import DomainError
from aabflow.api.idempotency import run_idempotent
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.api.system import surrogate_gate
from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import ErrorCode, Job, StrictModel, SurrogatePreview
from aabflow.jobs import queue
from aabflow.services import surrogate_service as svc
from aabflow.services.science import get_bindings

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]


class PreviewView(SurrogatePreview):
    """The stored preview, flat, plus its request and any exact confirmation."""

    request: dict[str, Any]
    verification: dict[str, Any] | None
    verify_job_id: str | None
    created_at: str


class VerifyAccepted(StrictModel):
    preview_id: str
    job_id: str
    job: Job


def _gate(state: AppState) -> None:
    gate = surrogate_gate(state)
    if gate != "passed":
        raise DomainError(
            ErrorCode.ASSET_UNAVAILABLE,
            f"surrogate preview unavailable: evaluation gate is {gate}; use the exact crop model",
        )


@router.post("/surrogate/previews", status_code=201, response_model=PreviewView)
def create_preview(state: State, conn: Conn, body: Annotated[dict[str, Any], Body()]) -> dict:
    _gate(state)
    req, pv = svc.make_preview(state.catalog, get_bindings(state.settings), body)
    svc.store(conn, req, pv)
    return svc.get(conn, pv.preview_id)


@router.get("/surrogate/previews/{preview_id}", response_model=PreviewView)
def get_preview(preview_id: str, conn: Conn) -> dict:
    return svc.get(conn, preview_id)


@router.post(
    "/surrogate/previews/{preview_id}/verify", status_code=202, response_model=VerifyAccepted
)
def verify(preview_id: str, state: State, conn: Conn, idem: IdemKey = None):
    view = svc.get(conn, preview_id)
    payload = {"preview_id": preview_id}

    def create():
        if view["verify_job_id"]:
            row = queue.get(conn, view["verify_job_id"])
            if row is not None and row["state"] not in ("failed", "cancelled", "interrupted"):
                return 202, {
                    "preview_id": preview_id,
                    "job_id": row["job_id"],
                    "job": queue.row_to_job(row).model_dump(mode="json"),
                }
        jid = queue.enqueue(
            conn, "surrogate.verify", payload, content_hash(payload), subject_id=preview_id
        )
        svc.set_job(conn, preview_id, jid)
        if state.dispatcher:
            state.dispatcher.notify()
        return 202, {
            "preview_id": preview_id,
            "job_id": jid,
            "job": queue.row_to_job(queue.get(conn, jid)).model_dump(mode="json"),
        }

    return run_idempotent(
        conn, f"POST /surrogate/previews/{preview_id}/verify", idem, payload, create
    )
