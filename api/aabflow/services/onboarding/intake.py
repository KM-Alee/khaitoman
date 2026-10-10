"""Create, review and publish orchestration over the existing onboarding pipeline."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from aabflow import config
from aabflow.api.errors import conflict, invalid
from aabflow.config import Settings
from aabflow.domain.hashes import content_hash
from aabflow.domain.ids import new_id
from aabflow.ingestion.aoi import AoiError
from aabflow.ingestion.common import IngestionError
from aabflow.ingestion.onboarding import pipeline
from aabflow.ingestion.onboarding.catalog import (
    RawIntakeError,
    iter_bundles,
    resolve_raw_package,
)
from aabflow.ingestion.onboarding.layers import LayerError, list_layers, read_layer
from aabflow.ingestion.packages.bundle import BundleError
from aabflow.ingestion.packages.validate import PackageValidationError
from aabflow.jobs import queue

from . import store
from .jobs import enqueue_readiness

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_ACTIVE = {"queued", "running", "cancel_requested"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def aoi_check(geojson: dict, settings: Settings) -> dict[str, Any]:
    """Area and limits only. This does not search scenes or start a job."""
    try:
        checked = pipeline.validate_aoi(geojson)
    except AoiError as exc:
        raise invalid(str(exc), {"aoi": str(exc)}) from exc
    bundles = iter_bundles(settings.data_dir, config.ROOT)
    return {
        **checked,
        "source_availability": {
            "online": "not_contacted",
            "raw_bundle_count": len(bundles),
            "note": "Scene search happens in the process job. This check does not download.",
        },
    }


def list_raw_packages(settings: Settings) -> dict[str, Any]:
    return {
        "intake_kind": "raw_source_bundle",
        "packages": iter_bundles(settings.data_dir, config.ROOT),
    }


def _fail_intake(exc: Exception) -> None:
    if isinstance(exc, RawIntakeError):
        raise invalid(exc.detail, exc.fields) from exc
    if isinstance(exc, AoiError):
        raise invalid(str(exc), {"aoi": str(exc)}) from exc
    if isinstance(exc, (BundleError, IngestionError, pipeline.StageError, ValueError)):
        raise invalid(str(exc)) from exc
    raise exc


def create(conn: sqlite3.Connection, settings: Settings, body: dict[str, Any]) -> dict[str, Any]:
    source_mode = body["source_mode"]
    bundle_ref = None
    pilot_id = body.get("pilot_id")
    if source_mode == "raw_package":
        token = body.get("raw_package_ref") or body.get("raw_package_id")
        if not token:
            raise invalid("raw_package mode needs raw_package_id", {"raw_package_id": "required"})
        try:
            bundle_root, bundle_ref = resolve_raw_package(
                token, data_dir=settings.data_dir, repo_root=config.ROOT
            )
        except RawIntakeError as exc:
            raise invalid(exc.detail, exc.fields) from exc
        from aabflow.ingestion.common import read_json

        manifest = read_json(bundle_root / "bundle_manifest.json")
        pilot_id = pilot_id or manifest.get("pilot_id")
    onboarding_id = new_id("onb")
    workdir = settings.onboarding_dir / onboarding_id
    try:
        st = pipeline.create_intake(
            onboarding_id,
            body["aoi"],
            source_mode,
            bundle_ref,
            workdir,
            name=body.get("name") or None,
            pilot_id=pilot_id,
            geographic_name_basis=body.get("geographic_name_basis"),
            parent_canal_feature_id=body.get("parent_canal_feature_id"),
            repo_root=config.ROOT,
            data_dir=settings.data_dir,
        )
    except Exception as exc:
        _fail_intake(exc)
        raise
    status = {
        "workdir": f"onboarding/{onboarding_id}",
        "aoi_check": _jsonable(st.get("aoi_check")),
        "blockers": [],
        "warnings": list((st.get("aoi_check") or {}).get("warnings") or []),
        "source_mode": source_mode,
        "bundle_ref": bundle_ref,
        "stage": st["state"],
        "progress": None,
        "error": None,
        "inference": None,
    }
    store.insert(
        conn,
        onboarding_id=onboarding_id,
        pilot_id=pilot_id,
        request=body,
        status=status,
        state=st["state"],
    )
    return view(conn, settings, onboarding_id)


def view(conn: sqlite3.Connection, settings: Settings, onboarding_id: str) -> dict[str, Any]:
    row = store.require(conn, onboarding_id)
    status = store_status(row)
    job = queue.get(conn, row["job_id"]) if row["job_id"] else None
    inference = status.get("inference") or {}
    blockers = list(status.get("blockers") or [])
    warnings = list(status.get("warnings") or [])
    state = row["state"]
    job_error = _loads_error(job["error_ref"]) if job is not None and job["error_ref"] else None
    error = job_error or status.get("error")
    return {
        "onboarding_id": row["onboarding_id"],
        "intake_id": row["onboarding_id"],
        "name": (store_request(row).get("name")),
        "state": state,
        "stage": state,
        "review_version": row["review_version"],
        "source_mode": status.get("source_mode"),
        "bundle_ref": status.get("bundle_ref"),
        "pilot_id": row["pilot_id"],
        "pilot_version": row["pilot_version"],
        "aoi_check": status.get("aoi_check"),
        "blockers": blockers,
        "warnings": warnings,
        "validation": {"blockers": blockers, "warnings": warnings},
        "job_id": row["job_id"],
        "job_state": None if job is None else job["state"],
        "progress": None if job is None else job["progress"],
        "job_stage": None if job is None else job["stage"],
        "error": error,
        "inference": inference or None,
        "cache_hit": bool(inference.get("cache_hit")) if isinstance(inference, dict) else False,
        "review_summary": inference.get("review_summary") if isinstance(inference, dict) else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def store_status(row: sqlite3.Row) -> dict[str, Any]:
    from aabflow.repositories.sqlite import loads

    return loads(row["status"]) or {}


def store_request(row: sqlite3.Row) -> dict[str, Any]:
    from aabflow.repositories.sqlite import loads

    return loads(row["request"]) or {}


def _loads_error(text: str) -> Any:
    from aabflow.repositories.sqlite import loads

    return loads(text)


def enqueue_process(conn: sqlite3.Connection, settings: Settings, onboarding_id: str) -> str:
    row = store.require(conn, onboarding_id)
    if row["state"] == "published":
        raise invalid("intake is already published", {"state": "published"})
    if row["job_id"]:
        job = queue.get(conn, row["job_id"])
        if job is not None and job["state"] in _ACTIVE:
            raise conflict(
                "a process job is already active for this intake",
                {"job_id": row["job_id"], "job_state": job["state"]},
            )
    payload = {"onboarding_id": onboarding_id}
    job_id = queue.enqueue(
        conn,
        "onboarding.process",
        payload,
        content_hash(payload),
        subject_id=onboarding_id,
    )
    store.patch(
        conn,
        onboarding_id,
        job_id=job_id,
        status={"stage": "queued", "progress": None, "error": None},
    )
    return job_id


def layers(conn: sqlite3.Connection, settings: Settings, onboarding_id: str) -> dict[str, Any]:
    row = store.require(conn, onboarding_id)
    workdir = store.workdir_for(settings, row)
    try:
        intake = pipeline.status(workdir)
    except pipeline.StageError as exc:
        raise invalid(str(exc)) from exc
    return list_layers(workdir, intake)


def layer(
    conn: sqlite3.Connection, settings: Settings, onboarding_id: str, layer_id: str
) -> dict[str, Any]:
    from aabflow.api.errors import not_found

    row = store.require(conn, onboarding_id)
    workdir = store.workdir_for(settings, row)
    try:
        intake = pipeline.status(workdir)
    except pipeline.StageError as exc:
        raise invalid(str(exc)) from exc
    try:
        return read_layer(workdir, intake, layer_id)
    except LayerError as exc:
        if exc.missing:
            raise not_found("layer_id", layer_id) from exc
        raise invalid(exc.detail, exc.fields) from exc


def apply_review(
    conn: sqlite3.Connection,
    settings: Settings,
    onboarding_id: str,
    expected_version: int,
    edits: dict[str, Any],
) -> dict[str, Any]:
    row = store.require(conn, onboarding_id)
    workdir = store.workdir_for(settings, row)
    try:
        result = pipeline.apply_review(workdir, edits, expected_version)
    except pipeline.VersionConflict as exc:
        current = pipeline.status(workdir).get("review_version")
        raise conflict(
            str(exc),
            {"review_version": current, "expected_version": expected_version},
        ) from exc
    except pipeline.ReviewRejected as exc:
        raise invalid(str(exc), {"review": str(exc)}) from exc
    except pipeline.StageError as exc:
        raise invalid(str(exc), {"state": row["state"]}) from exc
    except ValueError as exc:
        raise invalid(str(exc)) from exc
    st = pipeline.status(workdir)
    store.patch(
        conn,
        onboarding_id,
        state=st["state"],
        review_version=int(st["review_version"]),
        status={
            "stage": st["state"],
            "blockers": result.get("blockers") or [],
            "warnings": result.get("warnings") or [],
        },
    )
    return {
        "onboarding_id": onboarding_id,
        "review_version": result["version"],
        "state": st["state"],
        "blockers": result.get("blockers") or [],
        "warnings": result.get("warnings") or [],
    }


def _segment(value: str, field: str) -> str:
    if not _SEGMENT.fullmatch(value):
        raise invalid(
            f"{field} must be a single path segment",
            {field: "path traversal" if value and ("/" in value or ".." in value) else "invalid"},
        )
    return value


def publish(
    conn: sqlite3.Connection,
    settings: Settings,
    onboarding_id: str,
    *,
    pilot_id: str | None,
    pilot_version: str | None,
) -> dict[str, Any]:
    """Publish only a new version. An existing directory is left untouched."""
    row = store.require(conn, onboarding_id)
    pilot = _segment(pilot_id or row["pilot_id"] or "", "pilot_id")
    version = _segment(pilot_version or "", "pilot_version")
    final = settings.pilots_dir / pilot / version
    resolved = final.resolve()
    if settings.pilots_dir.resolve() not in resolved.parents:
        raise invalid("pilot version escapes the pilot store", {"pilot_version": "path traversal"})
    if final.exists():
        raise conflict(
            f"{pilot}/{version} is already published and cannot be replaced",
            {"pilot_id": pilot, "pilot_version": version, "immutable": True},
        )
    workdir = store.workdir_for(settings, row)
    try:
        st = pipeline.status(workdir)
    except pipeline.StageError as exc:
        raise invalid(str(exc)) from exc
    if st["state"] not in ("reviewed", "validated"):
        raise invalid(
            f"cannot publish from state {st['state']} (review first)",
            {"state": st["state"]},
        )
    try:
        manifest = pipeline.publish(
            workdir,
            pilot,
            version,
            data_dir=settings.data_dir,
            repo_root=config.ROOT,
        )
    except FileExistsError as exc:
        raise conflict(
            f"{pilot}/{version} is already published and cannot be replaced",
            {"pilot_id": pilot, "pilot_version": version, "immutable": True},
        ) from exc
    except pipeline.StructuralBlock as exc:
        raise invalid(str(exc), {"publish": "; ".join(exc.blockers)}) from exc
    except PackageValidationError as exc:
        raise invalid(str(exc), {"publish": "structural validation failed"}) from exc
    except pipeline.StageError as exc:
        raise invalid(str(exc), {"state": st["state"]}) from exc
    published = pipeline.status(workdir)
    readiness = published.get("library_readiness") or {}
    jobs = enqueue_readiness(conn, onboarding_id, pilot, version, readiness)
    store.patch(
        conn,
        onboarding_id,
        state="published",
        pilot_id=pilot,
        pilot_version=version,
        status={
            "stage": "published",
            "published_ref": f"data/pilots/{pilot}/{version}",
            "library_readiness": readiness,
            "readiness_jobs": jobs,
        },
    )
    return {
        "onboarding_id": onboarding_id,
        "pilot_id": pilot,
        "pilot_version": version,
        "state": manifest.state.value,
        "immutable": True,
        "libraries": readiness.get("libraries") or [],
        "readiness": {
            "baseline": readiness.get("baseline"),
            "candidates": readiness.get("candidates"),
            "reused_as_current": False,
        },
        "jobs": jobs,
    }
