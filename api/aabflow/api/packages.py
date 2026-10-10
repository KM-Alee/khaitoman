"""Completed pilot package export and import (T2.6, T9.1, T9.3).

``GET/POST /pilots/{pilot_id}/versions/{version}/package`` exchanges a zip of a
published package. Raw source bundles are rejected; they stay on onboarding.
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response
from pydantic import ValidationError

from aabflow.api.errors import invalid
from aabflow.api.idempotency import run_idempotent
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.domain.hashes import sha256_hex
from aabflow.domain.schemas import CONTRACT_VERSION, StrictModel
from aabflow.services.packages import export_completed_package, import_completed_package
from aabflow.services.pilots import safe_id

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]

_FORM_FIELDS = {"contract_version", "package"}


class PackageImport(StrictModel):
    contract_version: Literal["2.0.0"]


def _nonfinite_fields(node: Any, prefix: str = "") -> dict[str, str]:
    found: dict[str, str] = {}
    if isinstance(node, float) and not math.isfinite(node):
        found[prefix or "request"] = "nonfinite"
    elif isinstance(node, dict):
        for key, value in node.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            found.update(_nonfinite_fields(value, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.update(_nonfinite_fields(value, f"{prefix}.{index}" if prefix else str(index)))
    return found


def _reject_json_body(raw: bytes) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise invalid("request failed validation", {"body": "invalid JSON"}) from exc
    if not isinstance(data, dict):
        raise invalid("request failed validation", {"body": "object required"})
    nonfinite = _nonfinite_fields(data)
    if nonfinite:
        raise invalid("nonfinite number", nonfinite)
    try:
        PackageImport.model_validate(data)
    except ValidationError as exc:
        fields = {
            ".".join(str(part) for part in err.get("loc", ())) or "request": err.get(
                "msg", "invalid"
            )
            for err in exc.errors()
        }
        raise invalid("request failed validation", fields) from exc
    raise invalid(
        "completed package import requires multipart file 'package'; a JSON body is not an archive",
        {"package": "required"},
    )


def _filename(pilot_id: str, pilot_version: str) -> str:
    return f"{pilot_id}-{pilot_version}.zip"


@router.get("/pilots/{pilot_id}/versions/{version}/package")
def export_pilot_package(pilot_id: str, version: str, state: State) -> Response:
    safe_id(pilot_id, "pilot_id")
    safe_id(version, "pilot_version")
    blob, summary = export_completed_package(state.settings.pilots_dir, pilot_id, version)
    return Response(
        content=blob,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(pilot_id, version)}"',
            "X-Package-Sha256": summary["package_sha256"],
            "X-Aabflow-Package-Kind": summary["kind"],
        },
    )


@router.post("/pilots/{pilot_id}/versions/{version}/package", status_code=201)
async def import_pilot_package(
    pilot_id: str,
    version: str,
    request: Request,
    state: State,
    conn: Conn,
    idem: IdemKey = None,
):
    safe_id(pilot_id, "pilot_id")
    safe_id(version, "pilot_version")
    if request.query_params:
        raise invalid(
            "unknown query fields",
            {key: "unknown field" for key in request.query_params},
        )
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        _reject_json_body(await request.body())
    form = await request.form()
    unknown = sorted(set(form.keys()) - _FORM_FIELDS)
    if unknown:
        raise invalid("unknown form fields", {key: "unknown field" for key in unknown})
    raw_version = form.get("contract_version")
    if not isinstance(raw_version, str):
        raise invalid("contract_version is required", {"contract_version": "required"})
    try:
        PackageImport.model_validate({"contract_version": raw_version})
    except ValidationError as exc:
        raise invalid(
            "request failed validation",
            {"contract_version": exc.errors()[0]["msg"]},
        ) from exc
    upload = form.get("package")
    if upload is None or not hasattr(upload, "read"):
        raise invalid("package file is required", {"package": "required"})
    blob = await upload.read()
    payload = {
        "contract_version": CONTRACT_VERSION,
        "pilot_id": pilot_id,
        "pilot_version": version,
        "package_sha256": sha256_hex(blob),
    }

    def create() -> tuple[int, dict[str, Any]]:
        body = import_completed_package(state.settings.pilots_dir, pilot_id, version, blob)
        return 201, body

    return run_idempotent(conn, "POST /pilots/package", idem, payload, create)
