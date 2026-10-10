"""SDG impact routes (PRD §8.5, T7.5, T9.1).

Registered by the parent in ``main._routers()`` before ``runs.router``. The
existing ``GET /runs/{run_id}/impact`` handler in ``api/runs.py`` matches the
same path and will shadow this router if it is registered first.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header

from aabflow.api.idempotency import run_idempotent
from aabflow.api.state import get_conn
from aabflow.domain.schemas import CONTRACT_VERSION, StrictModel
from aabflow.services.impact.cards import ImpactResponse
from aabflow.services.impact.view import assemble, check_id

router = APIRouter()
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]


class ImpactRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    run_id: str
    baseline_run_id: str | None = None
    stress_analysis_id: str | None = None


def _optional(value: str | None, field: str) -> str | None:
    if value is None or value == "":
        return None
    return check_id(value, field)


@router.get("/runs/{run_id}/impact", response_model=ImpactResponse)
def run_impact(
    run_id: str,
    conn: Conn,
    baseline_run_id: str | None = None,
    stress_analysis_id: str | None = None,
) -> dict:
    return assemble(
        conn,
        run_id,
        _optional(baseline_run_id, "baseline_run_id"),
        _optional(stress_analysis_id, "stress_analysis_id"),
    )


@router.post("/impact", response_model=ImpactResponse)
def create_impact(body: ImpactRequest, conn: Conn, idem: IdemKey = None):
    check_id(body.run_id, "run_id")
    if body.baseline_run_id:
        check_id(body.baseline_run_id, "baseline_run_id")
    if body.stress_analysis_id:
        check_id(body.stress_analysis_id, "stress_analysis_id")

    def create():
        result = assemble(conn, body.run_id, body.baseline_run_id, body.stress_analysis_id)
        return 200, result

    return run_idempotent(conn, "POST /impact", idem, body.model_dump(mode="json"), create)
