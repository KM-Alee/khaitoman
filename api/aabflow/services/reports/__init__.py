"""Report jobs and retrieval (PRD §8.6, T7.5, T9.1, T9.4).

The job copies stored ``MetricValue`` records and immutable run/version ids into a
minimal placeholder file. It does not recompute analytics. It does not write
``report.html``, CSV, GeoJSON, or a self-contained manifest; those belong to P05-files.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from aabflow.api.errors import conflict, invalid, not_found, unavailable
from aabflow.config import Settings
from aabflow.domain.hashes import content_hash, file_sha256
from aabflow.domain.ids import new_id
from aabflow.domain.schemas import CONTRACT_VERSION, StrictModel
from aabflow.jobs import queue
from aabflow.repositories.sqlite import dumps, loads, tx, utcnow
from aabflow.services.analyses import row as analysis_row
from aabflow.services.metrics import REGISTRY
from aabflow.services.runs import LoadedRun, load_run, run_row, verify_bundle

PLACEHOLDER_NAME = "placeholder.json"
PLACEHOLDER_KIND = "p05-api-placeholder"
REPORT_HTML = "report.html"
METRICS_JSON = "metrics.json"
METRICS_CSV = "metrics.csv"
ACTIONS_CSV = "actions.csv"
FIELDS_GEOJSON = "fields.geojson"
MANIFEST_NAME = "manifest.json"
ARTIFACT_KIND = "self-contained-report"
HASH_SCOPE = "sha256 of manifest.json, which lists sha256 for every report file"
NOTE = (
    "Minimal P05-api placeholder. Not the self-contained report. "
    "HTML, CSV, GeoJSON, and the manifest are a later step."
)
_UNSAFE_PARTS = {"", ".", ".."}


def _reject_nonfinite(value: Any, loc: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"nonfinite number at {loc}")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_nonfinite(item, f"{loc}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_nonfinite(item, f"{loc}[{index}]")


class ReportCreate(StrictModel):
    """Body reserved by copilot ``create_report``: run ids, analysis ids, report type."""

    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    run_ids: list[str] = Field(min_length=1, max_length=64)
    analysis_ids: list[str] = Field(default_factory=list, max_length=64)
    report_type: Literal["one_page_plan", "full_report"] = "one_page_plan"

    @model_validator(mode="before")
    @classmethod
    def _nonfinite(cls, value: Any) -> Any:
        if isinstance(value, dict):
            _reject_nonfinite(value, "body")
        return value

    @model_validator(mode="after")
    def _distinct(self) -> ReportCreate:
        for name, values in (("run_ids", self.run_ids), ("analysis_ids", self.analysis_ids)):
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{name} entries must be non-empty strings")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must be distinct")
        return self

    @model_validator(mode="after")
    def _identifiers(self) -> ReportCreate:
        for name, values in (("run_ids", self.run_ids), ("analysis_ids", self.analysis_ids)):
            for item in values:
                parts = item.replace("\\", "/").split("/")
                if "/" in item or "\\" in item or any(part in _UNSAFE_PARTS for part in parts):
                    raise ValueError(f"{name} must be identifiers, not paths")
        return self


ReportRequest = ReportCreate


def run_context(loaded: LoadedRun) -> tuple[str, str]:
    """Immutable pilot context stored on the run. Missing context is not invented."""
    meta = loaded.meta if isinstance(loaded.meta, dict) else {}
    pilot_id = meta.get("pilot_id")
    pilot_version = meta.get("pilot_version")
    if (
        not isinstance(pilot_id, str)
        or not pilot_id
        or not isinstance(pilot_version, str)
        or not pilot_version
    ):
        raise invalid("run has no stored pilot context", {"run_id": loaded.run_id})
    return pilot_id, pilot_version


def _revision_context(
    conn: sqlite3.Connection, revision_id: str, analysis_id: str
) -> tuple[str, str]:
    row = conn.execute(
        "SELECT request FROM scenario_revisions WHERE scenario_revision_id = ?",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise not_found("scenario_revision_id", revision_id)
    request = loads(row["request"]) or {}
    if not isinstance(request, dict):
        raise invalid("analysis revision request is not stored", {"analysis_id": analysis_id})
    pilot_id = request.get("pilot_id")
    pilot_version = request.get("pilot_version")
    if (
        not isinstance(pilot_id, str)
        or not pilot_id
        or not isinstance(pilot_version, str)
        or not pilot_version
    ):
        raise invalid("analysis revision has no stored pilot context", {"analysis_id": analysis_id})
    return pilot_id, pilot_version


def prepare_stored_run(conn: sqlite3.Connection, run_id: str) -> LoadedRun:
    """Verify the stored bundle and refuse to invent metrics or repair identity."""
    row = run_row(conn, run_id)
    directory = Path(row["run_dir"])
    verify_bundle(directory, row["manifest_sha256"])
    try:
        document = json.loads((directory / "run.json").read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise unavailable("stored run.json is unreadable and is not recomputed") from exc
    result = document.get("result") if isinstance(document, dict) else None
    if not isinstance(result, dict):
        raise unavailable("stored run result is unreadable and is not recomputed")
    if (
        result.get("outcome") != row["outcome"]
        or result.get("solver_status") != row["solver_status"]
    ):
        raise unavailable(
            f"stored run identity {result.get('outcome')!r}/{result.get('solver_status')!r} "
            f"does not match the run record {row['outcome']!r}/{row['solver_status']!r}"
        )
    try:
        loaded = load_run(conn, run_id)
    except ValidationError as exc:
        raise unavailable(
            f"run {run_id} stored bundle is not valid canonical data; metrics are not recomputed"
        ) from exc
    copy_run_snapshot(loaded)
    return loaded


def _analysis_contexts(conn: sqlite3.Connection, analysis_id: str) -> list[tuple[str, str]]:
    row = analysis_row(conn, analysis_id)
    found: list[tuple[str, str]] = []
    if row["base_revision_id"]:
        found.append(_revision_context(conn, row["base_revision_id"], analysis_id))
    if row["base_run_id"]:
        found.append(run_context(prepare_stored_run(conn, row["base_run_id"])))
    if not found:
        raise invalid("analysis has no stored pilot context", {"analysis_id": analysis_id})
    return found


def require_context(conn: sqlite3.Connection, body: ReportCreate) -> tuple[str, str]:
    """Load stored runs and analyses. Reject missing ids and mixed pilot contexts."""
    contexts: list[tuple[str, str, str]] = []
    for run_id in body.run_ids:
        pilot_id, pilot_version = run_context(prepare_stored_run(conn, run_id))
        contexts.append((run_id, pilot_id, pilot_version))
    unique = {(pilot_id, pilot_version) for _, pilot_id, pilot_version in contexts}
    if len(unique) != 1:
        raise conflict(
            "runs belong to more than one pilot context",
            {
                "runs": [
                    {"run_id": run_id, "pilot_id": pilot_id, "pilot_version": pilot_version}
                    for run_id, pilot_id, pilot_version in contexts
                ]
            },
        )
    pilot_id, pilot_version = contexts[0][1], contexts[0][2]
    for analysis_id in body.analysis_ids:
        for owner_id, owner_version in _analysis_contexts(conn, analysis_id):
            if (owner_id, owner_version) != (pilot_id, pilot_version):
                raise conflict(
                    f"analysis {analysis_id} belongs to {owner_id}/{owner_version}, "
                    f"not {pilot_id}/{pilot_version}",
                    {
                        "analysis_id": analysis_id,
                        "owner_pilot_id": owner_id,
                        "owner_pilot_version": owner_version,
                        "expected_pilot_id": pilot_id,
                        "expected_pilot_version": pilot_version,
                        "report_pilot_id": pilot_id,
                        "report_pilot_version": pilot_version,
                    },
                )
    return pilot_id, pilot_version


def report_row(conn: sqlite3.Connection, report_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
    if row is None:
        raise not_found("report_id", report_id)
    return row


def _envelope(row: sqlite3.Row) -> dict[str, Any]:
    stored = loads(row["request"])
    if not isinstance(stored, dict) or not isinstance(stored.get("body"), dict):
        raise invalid("stored report request is unreadable", {"report_id": row["report_id"]})
    return stored


def create(conn: sqlite3.Connection, body: ReportCreate) -> tuple[str, str]:
    """Validate stored sources, then insert the report and enqueue ``report``."""
    pilot_id, pilot_version = require_context(conn, body)
    report_id = new_id("rpt")
    request = body.model_dump(mode="json")
    envelope = {"body": request, "pilot_id": pilot_id, "pilot_version": pilot_version}
    now = utcnow()
    with tx(conn):
        conn.execute(
            "INSERT INTO reports (report_id, report_hash, report_type, request, job_id, report_dir, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (report_id, None, body.report_type, dumps(envelope), None, None, now),
        )
    job_id = queue.enqueue(
        conn,
        "report",
        {"report_id": report_id},
        content_hash({"report_id": report_id, "request": request}),
        subject_id=report_id,
    )
    with tx(conn):
        conn.execute("UPDATE reports SET job_id = ? WHERE report_id = ?", (job_id, report_id))
    return report_id, job_id


def definition_snapshots(metrics: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    """Registry text for stored metric ids. Missing ids stay null; values are not filled in."""
    out: dict[str, dict[str, Any] | None] = {}
    for metric in metrics:
        metric_id = metric.get("metric_id")
        if not isinstance(metric_id, str) or metric_id in out:
            continue
        found = REGISTRY.get(metric_id)
        out[metric_id] = found.as_dict() if found else None
    return out


def copy_run_snapshot(loaded: LoadedRun) -> dict[str, Any]:
    """Copy the stored metric records and immutable ids. Does not recompute them."""
    try:
        result = loaded.result
        metrics = [item.model_dump(mode="json") for item in loaded.metrics()]
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        raise unavailable(
            f"run {loaded.run_id} stored bundle is not valid canonical data; "
            "metrics are not recomputed"
        ) from exc
    meta = loaded.meta if isinstance(loaded.meta, dict) else {}
    return {
        "run_id": loaded.run_id,
        "pilot_id": meta.get("pilot_id"),
        "pilot_version": meta.get("pilot_version"),
        "season_id": meta.get("season_id"),
        "scenario_revision_id": result.scenario_revision_id,
        "scenario_hash": result.scenario_hash,
        "candidate_library_hash": result.candidate_library_hash,
        "plan_kind": result.plan_kind.value,
        "outcome": result.outcome,
        "solver_status": result.solver_status.value,
        "proof_scope": result.proof_scope,
        "metrics_version": meta.get("metrics_version"),
        "metrics": metrics,
        "definitions": definition_snapshots(metrics),
        "selected_intervention_instance_ids": list(
            getattr(result, "selected_intervention_instance_ids", []) or []
        ),
    }


def copy_analysis_snapshot(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any]:
    row = analysis_row(conn, analysis_id)
    return {
        "analysis_id": row["analysis_id"],
        "kind": row["kind"],
        "base_revision_id": row["base_revision_id"],
        "base_run_id": row["base_run_id"],
        "stored_result": loads(row["result"]) if row["result"] else None,
    }


def _fsync(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _placeholder_document(path: Path, report_id: str) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    if document.get("artifact_kind") != PLACEHOLDER_KIND:
        return None
    if document.get("final_self_contained_report") is not False:
        return None
    if document.get("report_id") != report_id:
        return None
    return document


def _safe_report_id(report_id: str) -> None:
    if (
        not report_id
        or report_id in _UNSAFE_PARTS
        or "/" in report_id
        or "\\" in report_id
        or report_id.startswith(".")
    ):
        raise invalid("report_id is not a safe path segment", {"report_id": report_id})


def _esc(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _metrics_csv(runs: list[dict[str, Any]]) -> str:
    lines = ["run_id,metric_id,definition_id,value,unit,status,reason"]
    for run in runs:
        for metric in run.get("metrics") or []:
            value = "" if metric.get("value") is None else metric.get("value")
            reason = (metric.get("reason") or "").replace('"', "'")
            lines.append(
                f"{run['run_id']},{metric.get('metric_id')},"
                f"{metric.get('definition_id')},{value},{metric.get('unit')},"
                f'{metric.get("status")},"{reason}"'
            )
    return "\n".join(lines) + "\n"


def _actions_csv(runs: list[dict[str, Any]]) -> str:
    lines = ["run_id,plan_kind,outcome,solver_status,action_id,source"]
    for run in runs:
        actions = run.get("selected_intervention_instance_ids") or []
        if not actions:
            lines.append(
                f"{run['run_id']},{run.get('plan_kind')},{run.get('outcome')},"
                f"{run.get('solver_status')},,not_estimated"
            )
            continue
        for action_id in actions:
            lines.append(
                f"{run['run_id']},{run.get('plan_kind')},{run.get('outcome')},"
                f"{run.get('solver_status')},{action_id},stored_run"
            )
    return "\n".join(lines) + "\n"


def _fields_geojson(runs: list[dict[str, Any]]) -> str:
    features = []
    for run in runs:
        for metric in run.get("metrics") or []:
            field_id = metric.get("field_id")
            if not field_id:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": None,
                    "properties": {
                        "field_id": field_id,
                        "run_id": run["run_id"],
                        "metric_id": metric.get("metric_id"),
                        "value": metric.get("value"),
                        "unit": metric.get("unit"),
                        "status": metric.get("status"),
                        "note": "stored metric; geometry is not recomputed",
                    },
                }
            )
    return (
        json.dumps({"type": "FeatureCollection", "features": features}, indent=1, allow_nan=False)
        + "\n"
    )


def _report_html(document: dict[str, Any]) -> str:
    rows = []
    for run in document["runs"]:
        for metric in run.get("metrics") or []:
            rows.append(
                "<tr>"
                f"<td>{_esc(run['run_id'])}</td>"
                f"<td>{_esc(metric.get('metric_id'))}</td>"
                f"<td>{_esc(metric.get('value'))}</td>"
                f"<td>{_esc(metric.get('unit'))}</td>"
                f"<td>{_esc(metric.get('status'))}</td>"
                f"<td>{_esc(metric.get('definition_id'))}</td>"
                "</tr>"
            )
    body = "\n".join(rows) or "<tr><td colspan='6'>no stored metrics</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AabFlow report {_esc(document["report_id"])}</title>
<style>
body {{ font-family: sans-serif; margin: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #ccc; padding: 0.3rem; text-align: left; }}
</style>
</head>
<body>
<h1>AabFlow local report</h1>
<p>Report {_esc(document["report_id"])} · {_esc(document["report_type"])}</p>
<p>Pilot {_esc(document["pilot_id"])} {_esc(document["pilot_version"])}</p>
<p>Values are copied from stored runs. Nothing here is recomputed.</p>
<table>
<thead><tr><th>Run</th><th>Metric</th><th>Value</th><th>Unit</th><th>Status</th><th>Definition</th></tr></thead>
<tbody>
{body}
</tbody>
</table>
</body>
</html>
"""


def publish_bundle(
    settings: Settings, report_id: str, document: dict[str, Any]
) -> tuple[Path, str]:
    """Write the self-contained files and a sha256 manifest. No external URLs."""
    _safe_report_id(report_id)
    root = settings.reports_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    final = (root / report_id).resolve()
    if final.parent != root:
        raise invalid("report directory escapes the reports store", {"report_id": report_id})
    if final.exists():
        shutil.rmtree(final)
    tmp = root / f".tmp-{report_id}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    files = {
        METRICS_JSON: json.dumps(document, indent=1, sort_keys=True, allow_nan=False) + "\n",
        METRICS_CSV: _metrics_csv(document["runs"]),
        ACTIONS_CSV: _actions_csv(document["runs"]),
        FIELDS_GEOJSON: _fields_geojson(document["runs"]),
        REPORT_HTML: _report_html(document),
    }
    listed = []
    for name, text in files.items():
        if "http://" in text or "https://" in text:
            raise invalid("report file contains an external URL", {"file": name})
        path = tmp / name
        path.write_text(text)
        _fsync(path)
        listed.append(
            {"path": name, "sha256": file_sha256(path), "size_bytes": path.stat().st_size}
        )
    manifest = {
        "report_id": report_id,
        "artifact_kind": ARTIFACT_KIND,
        "files": listed,
    }
    manifest_path = tmp / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    _fsync(manifest_path)
    digest = file_sha256(manifest_path)
    os.replace(tmp, final)
    return final, digest


def publish_placeholder(
    settings: Settings, report_id: str, document: dict[str, Any]
) -> tuple[Path, str]:
    """Atomically publish the placeholder. A half-written directory is not reused."""
    _safe_report_id(report_id)
    root = settings.reports_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    final = (root / report_id).resolve()
    if final.parent != root:
        raise invalid("report directory escapes the reports store", {"report_id": report_id})
    existing = final / PLACEHOLDER_NAME
    if existing.is_file() and _placeholder_document(existing, report_id) is not None:
        return final, file_sha256(existing)
    if final.exists():
        shutil.rmtree(final)
    tmp = root / f".tmp-{report_id}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    target = tmp / PLACEHOLDER_NAME
    target.write_text(json.dumps(document, indent=1, sort_keys=True, allow_nan=False) + "\n")
    _fsync(target)
    os.replace(tmp, final)
    return final, file_sha256(final / PLACEHOLDER_NAME)


def report_job(ctx, payload: dict[str, Any]) -> dict[str, Any]:
    """Copy stored metrics into the placeholder. Registered as ``HANDLERS['report']``."""
    ctx.check_cancel()
    report_id = payload.get("report_id") if isinstance(payload, dict) else None
    if not isinstance(report_id, str) or not report_id:
        raise invalid("report job payload has no report_id", {"report_id": "missing"})
    row = report_row(ctx.conn, report_id)
    envelope = _envelope(row)
    body = ReportCreate.model_validate(envelope["body"])
    expected = (envelope.get("pilot_id"), envelope.get("pilot_version"))
    if expected != require_context(ctx.conn, body):
        raise conflict(
            "stored runs no longer match the report's pilot context",
            {"report_id": report_id, "pilot_id": expected[0], "pilot_version": expected[1]},
        )
    ctx.stage("copy_stored_metrics", progress=0.0)
    runs = []
    total = max(1, len(body.run_ids) + len(body.analysis_ids))
    done = 0
    for run_id in body.run_ids:
        ctx.check_cancel()
        snapshot = copy_run_snapshot(prepare_stored_run(ctx.conn, run_id))
        if (snapshot["pilot_id"], snapshot["pilot_version"]) != expected:
            raise conflict(
                f"run {run_id} no longer belongs to {expected[0]}/{expected[1]}",
                {"run_id": run_id},
            )
        runs.append(snapshot)
        done += 1
        ctx.progress(done / total)
    analyses = []
    for analysis_id in body.analysis_ids:
        ctx.check_cancel()
        analyses.append(copy_analysis_snapshot(ctx.conn, analysis_id))
        done += 1
        ctx.progress(done / total)
    document = {
        "artifact_kind": ARTIFACT_KIND,
        "final_self_contained_report": True,
        "note": "Stored metrics copied into local files. Analytics are not recomputed.",
        "report_id": report_id,
        "report_type": body.report_type,
        "contract_version": body.contract_version,
        "pilot_id": expected[0],
        "pilot_version": expected[1],
        "runs": runs,
        "analyses": analyses,
    }
    ctx.check_cancel()
    directory, digest = publish_bundle(ctx.settings, report_id, document)
    with tx(ctx.conn):
        ctx.conn.execute(
            "UPDATE reports SET report_dir = ?, report_hash = ? WHERE report_id = ?",
            (str(directory), digest, report_id),
        )
    ctx.stage("published_report", progress=1.0)
    return {
        "report_id": report_id,
        "artifact": REPORT_HTML,
        "artifact_kind": ARTIFACT_KIND,
        "final_self_contained_report": True,
        "report_hash": digest,
        "report_hash_scope": HASH_SCOPE,
    }


def contained_report_dir(settings: Settings, row: sqlite3.Row) -> Path | None:
    raw = row["report_dir"]
    if not raw:
        return None
    root = settings.reports_dir.resolve()
    path = Path(raw).resolve()
    if path.parent != root or path.name != row["report_id"]:
        return None
    return path


def artifact_ready(settings: Settings, row: sqlite3.Row) -> bool:
    """A succeeded job still needs every manifest file at its recorded hash."""
    digest = row["report_hash"]
    directory = contained_report_dir(settings, row)
    if not isinstance(digest, str) or not digest or directory is None:
        return False
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file() or file_sha256(manifest_path) != digest:
        return False
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict) or manifest.get("report_id") != row["report_id"]:
        return False
    for entry in manifest.get("files") or []:
        if not isinstance(entry, dict):
            return False
        rel = entry.get("path")
        if not isinstance(rel, str) or rel != Path(rel).name or rel in _UNSAFE_PARTS:
            return False
        path = directory / rel
        if not path.is_file() or file_sha256(path) != entry.get("sha256"):
            return False
    return (directory / REPORT_HTML).is_file()


def _job_error(job: sqlite3.Row | None) -> dict[str, Any] | None:
    if job is None or not job["error_ref"]:
        return None
    raw = loads(job["error_ref"])
    if isinstance(raw, dict):
        return raw
    return {"code": "JOB_FAILED", "detail": "unreadable job error"}


def get_report(conn: sqlite3.Connection, settings: Settings, report_id: str) -> dict[str, Any]:
    row = report_row(conn, report_id)
    body = _envelope(row)["body"]
    job = queue.get(conn, row["job_id"]) if row["job_id"] else None
    job_state = job["state"] if job is not None else None
    job_error = _job_error(job)
    ready = job_state == "succeeded" and artifact_ready(settings, row)
    if job is None and row["job_id"]:
        status = "failed"
        job_error = job_error or {"code": "NOT_FOUND", "detail": "job record is missing"}
    elif ready:
        status = "succeeded"
    elif job_state == "succeeded":
        status = "failed"
        job_error = {
            "code": "ASSET_UNAVAILABLE",
            "detail": "report job has no intact manifest; success is not claimed",
        }
    else:
        status = job_state or "failed"
    download_url = None
    if ready:
        download_url = f"/api/v2/reports/{report_id}/files/{REPORT_HTML}"
    return {
        "report_id": row["report_id"],
        "status": status,
        "report_type": row["report_type"],
        "run_ids": list(body.get("run_ids") or []),
        "analysis_ids": list(body.get("analysis_ids") or []),
        "job_id": row["job_id"],
        "job_state": job_state,
        "job_error": job_error,
        "download_url": download_url,
        "created_at": row["created_at"],
        "report_hash": row["report_hash"],
        "report_hash_scope": HASH_SCOPE if row["report_hash"] else None,
        "artifact_kind": ARTIFACT_KIND if ready else None,
        "final_self_contained_report": ready,
    }


def reject_unsafe_relative(rel: str) -> None:
    """Reject traversal, absolute paths, and encoded separators before any read."""
    if not isinstance(rel, str) or not rel:
        raise not_found("file", rel or "")
    if rel.startswith(("/", "\\", "~")) or "\\" in rel or "\x00" in rel:
        raise not_found("file", rel)
    lowered = rel.lower()
    if "%2e" in lowered or "%2f" in lowered or "%5c" in lowered:
        raise not_found("file", rel)
    if any(part in _UNSAFE_PARTS for part in rel.split("/")):
        raise not_found("file", rel)


def resolve_report_file(report_dir: Path, rel: str) -> Path:
    """Return a file inside ``report_dir``. Symlinks that escape are rejected."""
    reject_unsafe_relative(rel)
    base = Path(report_dir).resolve()
    candidate = base.joinpath(*rel.split("/")).resolve()
    if base not in candidate.parents or not candidate.is_file():
        raise not_found("file", rel)
    return candidate


safe_report_file = resolve_report_file


def open_report_file(
    conn: sqlite3.Connection, settings: Settings, report_id: str, rel: str
) -> Path:
    row = report_row(conn, report_id)
    reject_unsafe_relative(rel)
    view = get_report(conn, settings, report_id)
    directory = contained_report_dir(settings, row)
    if view["status"] != "succeeded" or directory is None:
        raise not_found("file", rel)
    return resolve_report_file(directory, rel)


__all__ = [
    "ARTIFACT_KIND",
    "HASH_SCOPE",
    "PLACEHOLDER_KIND",
    "PLACEHOLDER_NAME",
    "ReportCreate",
    "ReportRequest",
    "copy_run_snapshot",
    "create",
    "get_report",
    "open_report_file",
    "report_job",
    "resolve_report_file",
    "safe_report_file",
]
