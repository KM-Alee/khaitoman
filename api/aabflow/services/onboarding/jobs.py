"""Onboarding process job. Importable as ``aabflow.services.onboarding:process_job``."""

from __future__ import annotations

from typing import Any

from aabflow import config
from aabflow.ingestion.onboarding import pipeline
from aabflow.ingestion.onboarding.acquire import Cancelled
from aabflow.jobs.cancellation import JobCancelled

from . import store


def _lineage(out: dict[str, Any]) -> dict[str, Any]:
    inference = dict(out.get("inference") or {})
    completed = inference.get("state") == "done"
    cache_hit = bool(inference.get("cache_hit")) and completed
    device = inference.get("device") if completed else None
    return {
        "inference_completed": completed,
        "cache_hit": cache_hit,
        "device": device if cache_hit or completed else None,
        "inference_key": inference.get("inference_key"),
        "gpkg_sha256": inference.get("gpkg_sha256"),
        "input_sha256": inference.get("input_sha256"),
        "run_record": inference.get("run_record"),
        "command": inference.get("command"),
        "cache_hits": list(out.get("cache_hits") or []),
        "blockers": list(out.get("blockers") or []),
        "warnings": list(out.get("warnings") or []),
        "review_summary": out.get("review_summary"),
        "parent_canal_feature_id": out.get("parent_canal_feature_id"),
    }


def _sync(
    ctx,
    onboarding_id: str,
    workdir,
    *,
    state: str,
    error: dict[str, Any] | None,
) -> None:
    """Record a cancelled or failed process. The intake file wins when it already moved."""
    try:
        st = pipeline.status(workdir)
    except pipeline.StageError:
        st = {"state": state, "review_version": 0}
    file_state = st.get("state") or state
    applied = file_state if file_state in ("cancelled", "failed") else state
    store.patch(
        ctx.conn,
        onboarding_id,
        state=applied,
        review_version=int(st.get("review_version") or 0),
        status={
            "stage": applied,
            "error": error,
            "progress": None,
            "blockers": [] if error is None else [error["detail"]],
            "inference": None,
        },
    )


def process_job(ctx, payload: dict) -> dict:
    """Run one intake through acquisition/processing. Inference is cache-only.

    A cached Delineate run is reused and reported as a cache hit, including the
    device stored on that run record. A miss stays pending and does not start
    a vision container. Cancellation and acquisition errors are recorded on the
    intake instead of a guessed percentage.
    """
    onboarding_id = str(payload["onboarding_id"])
    row = store.require(ctx.conn, onboarding_id)
    workdir = store.workdir_for(ctx.settings, row)

    def progress(stage: str, frac: float | None, detail: str) -> None:
        if ctx.cancelled:
            raise Cancelled("processing cancelled")
        ctx.stage(stage, detail, frac)
        store.patch(
            ctx.conn,
            onboarding_id,
            status={"stage": stage, "progress": frac, "stage_detail": detail, "error": None},
        )

    try:
        out = pipeline.process(
            onboarding_id,
            workdir,
            progress=progress,
            should_cancel=lambda: bool(ctx.cancelled),
            data_dir=ctx.settings.data_dir,
            repo_root=config.ROOT,
            inference_cache_only=True,
        )
    except Cancelled as exc:
        _sync(
            ctx,
            onboarding_id,
            workdir,
            state="cancelled",
            error={"code": "CANCELLED", "detail": str(exc)},
        )
        raise JobCancelled(str(exc)) from exc
    except Exception as exc:
        _sync(
            ctx,
            onboarding_id,
            workdir,
            state="failed",
            error={"code": "JOB_FAILED", "detail": f"{type(exc).__name__}: {exc}"},
        )
        raise

    st = pipeline.status(workdir)
    lineage = _lineage(out if isinstance(out, dict) else {})
    status = {
        "stage": st.get("state"),
        "error": None,
        "inference": lineage,
        "blockers": lineage["blockers"],
        "warnings": list((st.get("aoi_check") or {}).get("warnings") or []) + lineage["warnings"],
    }
    if lineage["inference_completed"]:
        status["progress"] = 1.0
    store.patch(
        ctx.conn,
        onboarding_id,
        state=st.get("state"),
        review_version=int(st.get("review_version") or 0),
        status=status,
    )
    return {"onboarding_id": onboarding_id, "state": st.get("state"), **lineage}
