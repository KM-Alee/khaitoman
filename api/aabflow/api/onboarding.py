"""Onboarding routes (PRD §5.3, T2.6, T9.1, T9.4).

AOI check, raw-bundle intake, process jobs, and layer reads. Review conflicts
and immutable publish are enforced here; publishing ``reviewed-v2`` is a later
step and this module never replaces an existing pilot version.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import Field, model_validator

from aabflow.api.errors import invalid
from aabflow.api.idempotency import run_idempotent
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.domain.schemas import CONTRACT_VERSION, StrictModel
from aabflow.jobs import queue
from aabflow.services.onboarding import intake

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]


def _finite(value: Any, path: str = "aoi") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError(f"nonfinite number at {path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _finite(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _finite(item, f"{path}.{key}")
        return
    raise ValueError(f"unsupported value at {path}")


class AoiCheckRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    aoi: dict[str, Any]

    @model_validator(mode="after")
    def _numbers(self) -> AoiCheckRequest:
        _finite(self.aoi)
        return self


class IntakeCreate(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    name: str | None = Field(default=None, max_length=200)
    aoi: dict[str, Any]
    source_mode: Literal["online", "raw_package"]
    raw_package_id: str | None = None
    raw_package_ref: str | None = None
    pilot_id: str | None = None
    geographic_name_basis: str | None = None
    parent_canal_feature_id: str | None = None

    @model_validator(mode="after")
    def _check(self) -> IntakeCreate:
        _finite(self.aoi)
        if self.source_mode == "raw_package" and not (self.raw_package_id or self.raw_package_ref):
            raise ValueError("raw_package mode needs raw_package_id")
        return self


class ProcessRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION


class FieldEdit(StrictModel):
    model_id: str
    action: Literal["reject", "replace_geometry", "split", "merge_with"]
    reason: str
    geometry_wgs84: dict[str, Any] | None = None
    parts_wgs84: list[dict[str, Any]] | None = None
    other_model_ids: list[str] = Field(default_factory=list)


class ReviewRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    expected_version: int = Field(ge=0)
    field_edits: list[FieldEdit] = Field(default_factory=list)
    parent_canal_feature_id: str | None = None
    review_config: dict[str, Any] | None = None
    reviewer: str | None = None


class PublishRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    pilot_id: str | None = None
    pilot_version: str | None = None


def _notify(state: AppState) -> None:
    if state.dispatcher:
        state.dispatcher.notify()


@router.post("/onboarding/aoi-check")
def aoi_check(body: AoiCheckRequest, state: State) -> dict[str, Any]:
    return intake.aoi_check(body.aoi, state.settings)


@router.get("/onboarding/raw-packages")
def raw_packages(state: State) -> dict[str, Any]:
    return intake.list_raw_packages(state.settings)


@router.post("/onboarding", status_code=201)
def create_intake(body: IntakeCreate, state: State, conn: Conn, idem: IdemKey = None):
    def create():
        created = intake.create(conn, state.settings, body.model_dump(mode="json"))
        return 201, created

    return run_idempotent(conn, "POST /onboarding", idem, body.model_dump(mode="json"), create)


@router.get("/onboarding/{onboarding_id}")
def get_intake(onboarding_id: str, state: State, conn: Conn) -> dict[str, Any]:
    return intake.view(conn, state.settings, onboarding_id)


@router.post("/onboarding/{onboarding_id}/process", status_code=202)
def process_intake(
    onboarding_id: str,
    state: State,
    conn: Conn,
    body: ProcessRequest | None = None,
    idem: IdemKey = None,
):
    payload = (body or ProcessRequest()).model_dump(mode="json")

    def create():
        job_id = intake.enqueue_process(conn, state.settings, onboarding_id)
        _notify(state)
        job = queue.row_to_job(queue.get(conn, job_id))
        return 202, {
            "onboarding_id": onboarding_id,
            "job_id": job_id,
            "job": job.model_dump(mode="json"),
        }

    return run_idempotent(
        conn,
        f"POST /onboarding/{onboarding_id}/process",
        idem,
        payload,
        create,
    )


@router.get("/onboarding/{onboarding_id}/layers")
def intake_layers(onboarding_id: str, state: State, conn: Conn) -> dict[str, Any]:
    return intake.layers(conn, state.settings, onboarding_id)


@router.get("/onboarding/{onboarding_id}/layers/{layer_id}")
def intake_layer(onboarding_id: str, layer_id: str, state: State, conn: Conn) -> dict[str, Any]:
    return intake.layer(conn, state.settings, onboarding_id, layer_id)


@router.patch("/onboarding/{onboarding_id}/review")
def review_intake(
    onboarding_id: str,
    body: ReviewRequest,
    state: State,
    conn: Conn,
    idem: IdemKey = None,
):
    edits = body.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"contract_version", "expected_version"},
    )
    edits["field_edits"] = edits.get("field_edits") or []

    def create():
        result = intake.apply_review(
            conn, state.settings, onboarding_id, body.expected_version, edits
        )
        return 200, result

    return run_idempotent(
        conn,
        f"PATCH /onboarding/{onboarding_id}/review",
        idem,
        body.model_dump(mode="json"),
        create,
    )


@router.post("/onboarding/{onboarding_id}/publish")
def publish_intake(
    onboarding_id: str,
    state: State,
    conn: Conn,
    body: PublishRequest | None = None,
    idem: IdemKey = None,
):
    payload = (body or PublishRequest()).model_dump(mode="json")
    if payload.get("pilot_version") in (None, ""):
        raise invalid("pilot_version is required", {"pilot_version": "required"})

    def create():
        result = intake.publish(
            conn,
            state.settings,
            onboarding_id,
            pilot_id=payload.get("pilot_id"),
            pilot_version=payload.get("pilot_version"),
        )
        return 201, result

    return run_idempotent(
        conn,
        f"POST /onboarding/{onboarding_id}/publish",
        idem,
        payload,
        create,
    )
