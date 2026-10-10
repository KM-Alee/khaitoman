"""Load stored run metrics and assemble the impact view (PRD §8.5)."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from pydantic import ValidationError

from aabflow.api.errors import conflict, invalid, not_found, unavailable
from aabflow.domain.schemas import MetricValue
from aabflow.services.analyses import get_analysis
from aabflow.services.impact.cards import ImpactResponse, build_impact, co2_estimate, empty_summary
from aabflow.services.insights import certificate
from aabflow.services.runs import load_run

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def check_id(value: str, field: str) -> str:
    if not _ID.fullmatch(value):
        raise invalid(f"{field} must be a single safe identifier", {field: "rejected"})
    return value


def assemble(
    conn: sqlite3.Connection,
    run_id: str,
    baseline_run_id: str | None = None,
    stress_analysis_id: str | None = None,
) -> dict[str, Any]:
    check_id(run_id, "run_id")
    if baseline_run_id:
        check_id(baseline_run_id, "baseline_run_id")
        if baseline_run_id == run_id:
            raise invalid("baseline_run_id must be a different run", {"baseline_run_id": run_id})
    if stress_analysis_id:
        check_id(stress_analysis_id, "stress_analysis_id")

    run = load_run(conn, run_id)
    if run.result.outcome != "plan":
        body = ImpactResponse(
            available=False,
            run_id=run.run_id,
            reason=f"run outcome {run.result.outcome}",
            field_change_summary=empty_summary(),
            co2=co2_estimate(),
        )
        return body.model_dump(mode="json")

    _own(run.metrics(), run.run_id, "run_id")
    baseline = None
    compatible = True
    label = None
    if baseline_run_id:
        baseline = load_run(conn, baseline_run_id)
        if baseline.result.outcome != "plan":
            raise invalid(
                f"baseline {baseline_run_id} has no validated plan",
                {"baseline_run_id": baseline.result.outcome},
            )
        _own(baseline.metrics(), baseline.run_id, "baseline_run_id")
        _same_pilot(run, baseline)
        compatible, label = _compatibility(baseline, run)

    stress: list[MetricValue] = []
    notes: list[str] = []
    if stress_analysis_id:
        stress, note = _stress(conn, stress_analysis_id, run.run_id)
        if note:
            notes.append(note)

    return build_impact(
        run_id=run.run_id,
        run_metrics=run.metrics(),
        baseline_run_id=baseline.run_id if baseline is not None else None,
        baseline_metrics=baseline.metrics() if baseline is not None else None,
        compatible=compatible,
        incompatibility_reason=label,
        stress_metrics=stress,
        extra_limitations=notes,
    )


def _own(metrics: list[MetricValue], run_id: str, field: str) -> None:
    for metric in metrics:
        if metric.run_id != run_id:
            raise conflict(
                f"stored metric {metric.metric_id} does not belong to this run",
                {"metric_id": metric.metric_id, "metric_run_id": metric.run_id, field: run_id},
            )


def _pilot(run) -> str | None:
    meta = run.meta or {}
    compat = meta.get("compatibility") or {}
    return meta.get("pilot_id") or compat.get("pilot_id")


def _same_pilot(run, baseline) -> None:
    run_pilot = _pilot(run)
    base_pilot = _pilot(baseline)
    if not run_pilot or not base_pilot:
        raise invalid("run is missing pilot_id", {"pilot_id": "missing"})
    if run_pilot != base_pilot:
        raise conflict(
            "baseline run belongs to a different pilot",
            {
                "run_pilot_id": run_pilot,
                "baseline_pilot_id": base_pilot,
                "baseline_run_id": baseline.run_id,
            },
        )


def _compatibility(baseline, run) -> tuple[bool, str | None]:
    try:
        cert = certificate([baseline, run])
    except FileNotFoundError as exc:
        raise unavailable("baseline comparison needs scenario.json on both runs") from exc
    if cert["compatible"]:
        return True, cert["label"]
    return False, cert["label"]


def _stress(
    conn: sqlite3.Connection, analysis_id: str, run_id: str
) -> tuple[list[MetricValue], str | None]:
    analysis = get_analysis(conn, analysis_id)
    if analysis is None:
        raise not_found("analysis_id", analysis_id)
    if analysis.get("kind") != "stress":
        raise invalid(
            "impact stress overlay requires a stress analysis",
            {"stress_analysis_id": str(analysis.get("kind") or "")},
        )
    if analysis.get("base_run_id") != run_id:
        raise conflict(
            "stress analysis is not owned by this run",
            {
                "stress_analysis_id": analysis_id,
                "base_run_id": analysis.get("base_run_id"),
                "run_id": run_id,
            },
        )
    result = analysis.get("result") or {}
    if not result:
        raise invalid("stress analysis has no stored result", {"stress_analysis_id": analysis_id})
    if result.get("mode") == "recovery_plan":
        return [], (
            "Recovery-plan metrics are a conditional comparison and are not used as the "
            "prospective SDG 13.1 outcome."
        )
    raw = result.get("metrics_by_id") or {}
    if not isinstance(raw, dict):
        raise invalid("stress metrics_by_id is not an object", {"metrics_by_id": "invalid"})
    metrics: list[MetricValue] = []
    for key, item in raw.items():
        try:
            metric = MetricValue.model_validate(item)
        except ValidationError as exc:
            raise invalid(
                "stored stress metric is not a finite MetricValue",
                {"metrics_by_id": str(key)},
            ) from exc
        if metric.run_id != run_id:
            raise conflict(
                f"stress metric {metric.metric_id} does not belong to this run",
                {"metric_id": metric.metric_id, "metric_run_id": metric.run_id, "run_id": run_id},
            )
        metrics.append(metric)
    return metrics, None
