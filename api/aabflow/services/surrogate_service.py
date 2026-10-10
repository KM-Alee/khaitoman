"""Surrogate preview records and exact confirmation jobs (T8.4, T8.5, PRD §7.4).

A preview is stored with its request so the exact confirmation job can rebuild the
identical crop experiment. The preview never stands in for exact outputs: the
verify job runs the crop model through ``run_experiment`` (cached by experiment
hash) and stores the exact outcome next to the preview with their difference.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from aabflow.api.errors import invalid, not_found
from aabflow.domain.schemas import SurrogatePreview
from aabflow.repositories.sqlite import dumps, loads, tx, utcnow

PRECHECK_LIBRARY = (
    "candidate policy is in the published candidate library, whose ledger validation it passed"
)


def physical_precheck(catalog, bindings, req) -> tuple[str, list[str]]:
    """A preview of a published library policy inherits that policy's ledger validation; anything else is
    honestly ``not_run`` (water/rights validation happens only on exact confirmation and solve)."""
    if not req.candidate_policy_id or not req.pilot_id:
        return "not_run", [
            "no candidate policy reference; water and rights validation run on exact confirmation"
        ]
    lib_hash = catalog.latest_library_hash(req.pilot_id, req.season_id)
    if lib_hash is None:
        return "not_run", ["no published candidate library for this pilot/season"]
    from aabflow.services.runs.prepare import load_library_cached

    _, pols = load_library_cached(bindings, req.pilot_id, req.season_id, lib_hash)
    pol = next((p for p in pols if p.candidate_policy_id == req.candidate_policy_id), None)
    if pol is None:
        return "failed", [f"{req.candidate_policy_id} is not in library {lib_hash[:12]}"]
    sched = sorted((e.date, round(e.gross_depth_mm, 6)) for e in pol.application_schedule)
    asked = sorted((e.date, round(e.gross_depth_mm, 6)) for e in req.schedule)
    if sched != asked:
        return "failed", [
            "schedule differs from the referenced library policy; its validation does not carry over"
        ]
    return "passed", [PRECHECK_LIBRARY]


def make_preview(
    catalog, bindings, body: dict[str, Any]
) -> tuple[dict[str, Any], SurrogatePreview]:
    from aabflow.surrogate.prediction import PreviewRequest, preview

    try:
        req = PreviewRequest.model_validate(body)
    except ValueError as exc:
        raise invalid("invalid preview request", {"request": str(exc)[:500]}) from exc
    status, reasons = physical_precheck(catalog, bindings, req)
    req = req.model_copy(
        update={"physical_precheck_status": status, "physical_precheck_reasons": reasons}
    )
    try:
        pv = preview(req)
    except (KeyError, ValueError) as exc:
        raise invalid(
            f"preview request is not resolvable: {exc}", {"request": str(exc)[:300]}
        ) from exc
    return req.model_dump(mode="json"), pv


def store(conn: sqlite3.Connection, req: dict[str, Any], pv: SurrogatePreview) -> SurrogatePreview:
    row = conn.execute(
        "SELECT * FROM surrogate_previews WHERE preview_id = ?", (pv.preview_id,)
    ).fetchone()
    if row is not None:
        doc = loads(row["result"])
        return SurrogatePreview.model_validate(doc.get("preview", doc))
    with tx(conn):
        conn.execute(
            "INSERT INTO surrogate_previews (preview_id, request, result, verify_job_id, created_at) "
            "VALUES (?,?,?,?,?)",
            (
                pv.preview_id,
                dumps(req),
                dumps({"preview": pv.model_dump(mode="json")}),
                None,
                utcnow(),
            ),
        )
    return pv


def get(conn: sqlite3.Connection, preview_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM surrogate_previews WHERE preview_id = ?", (preview_id,)
    ).fetchone()
    if row is None:
        raise not_found("preview_id", preview_id)
    doc = loads(row["result"])
    pv = doc.get("preview", doc)
    if row["verify_job_id"]:
        pv = {**pv, "exact_confirmation_job_id": row["verify_job_id"]}
    return {
        **pv,
        "request": loads(row["request"]),
        "verification": doc.get("verification"),
        "verify_job_id": row["verify_job_id"],
        "created_at": row["created_at"],
    }


def set_job(conn: sqlite3.Connection, preview_id: str, job_id: str) -> None:
    with tx(conn):
        conn.execute(
            "UPDATE surrogate_previews SET verify_job_id = ? WHERE preview_id = ?",
            (job_id, preview_id),
        )


def verify_job(ctx, payload: dict) -> dict:
    """Run the exact crop model for a stored preview and record exact vs preview."""
    from aabflow.surrogate.prediction import confirm

    pid = payload["preview_id"]
    row = ctx.conn.execute(
        "SELECT * FROM surrogate_previews WHERE preview_id = ?", (pid,)
    ).fetchone()
    if row is None:
        raise not_found("preview_id", pid)
    req = loads(row["request"])
    ctx.stage("running exact crop model")
    outcome, pv, diff = confirm(req)
    ctx.check_cancel()
    verification = {
        "estimate_kind": "exact_crop_model",
        "crop_outcome_hash": getattr(outcome, "crop_outcome_hash", None),
        "crop_experiment_hash": getattr(outcome, "crop_experiment_hash", None),
        "exact_yield_kg_ha": outcome.yield_kg_ha,
        "preview_yield_kg_ha": pv.estimated_yield_kg_ha,
        "preview_minus_exact_kg_ha": diff,
        "preview_domain_status": pv.domain_status,
        "seasonal_irrigation_mm": getattr(outcome, "seasonal_irrigation_mm", None),
        "has_finished": getattr(outcome, "has_finished", None),
        "outcome": outcome.model_dump(mode="json"),
        "note": "exact AquaCrop output replaces the preview for any final use; water and rights validation "
        "still require a candidate policy in a solve",
        "verified_at": utcnow(),
    }
    doc = loads(row["result"])
    doc["verification"] = verification
    with tx(ctx.conn):
        ctx.conn.execute(
            "UPDATE surrogate_previews SET result = ? WHERE preview_id = ?", (dumps(doc), pid)
        )
    return {
        "preview_id": pid,
        "exact_yield_kg_ha": outcome.yield_kg_ha,
        "preview_minus_exact_kg_ha": diff,
    }
