"""Shared tool plumbing: per-call context, membership checks and compact summaries."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from aabflow.copilot.context import PinnedContext
from aabflow.copilot.tools.backend import Backend, ToolFailure
from aabflow.domain.hashes import content_hash

TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled", "interrupted"}
MAX_WAIT_S = 45.0

STATUS_MEANING = {
    "OPTIMAL": "Best plan within the finite candidate library (proof scope: finite_candidate_library); "
    "not a proof over every possible schedule.",
    "FEASIBLE": "A valid, physically validated plan; optimality is not proven (see objective bound and gap).",
    "INFEASIBLE": "No plan satisfies the constraints within the finite candidate library. This is not proof "
    "that no physical plan exists. There is no plan, so there are no plan yields or production figures.",
    "UNKNOWN": "The search ended without a plan and without an infeasibility proof. Neither feasible nor "
    "infeasible is established; no plan metrics exist.",
    "MODEL_INVALID": "Engineering error in the generated optimization model; no recommendation exists.",
}
INVALID_PLAN_MEANING = "The solver's incumbent failed original-precision physical validation (INVALID_PLAN); no recommendation."

# Metric basis labels: which numbers are crop-model outputs versus accounting of inputs.
MODEL_OUTPUT_HINTS = ("production", "yield", "biomass", "crop_value", "productivity")


def metric_basis(metric_id: str) -> str:
    return (
        "model_output"
        if any(h in metric_id for h in MODEL_OUTPUT_HINTS)
        else "computed_from_inputs"
    )


@dataclass
class TurnBudget:
    max_jobs: int = 3
    jobs_submitted: int = 0

    def reserve_job(self, n: int = 1) -> None:
        if self.jobs_submitted + n > self.max_jobs:
            raise ToolFailure(
                "TURN_JOB_LIMIT",
                f"this turn may submit at most {self.max_jobs} analytical jobs; "
                f"{self.jobs_submitted} already submitted. Tell the user what is running and offer to continue.",
            )
        self.jobs_submitted += n


@dataclass
class ToolCtx:
    backend: Backend
    context: PinnedContext
    turn_id: str
    session_id: str
    budget: TurnBudget = field(default_factory=TurnBudget)
    deadline: float = field(default_factory=lambda: time.monotonic() + 90.0)
    job_ids: list[str] = field(default_factory=list)
    view_intents: list[dict[str, Any]] = field(default_factory=list)
    created: list[dict[str, Any]] = field(
        default_factory=list
    )  # branches/runs/reports for action cards
    session_ids: set[str] = field(
        default_factory=set
    )  # ids created/returned earlier in this session
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    idem_namespace: str | None = None  # a retried turn reuses its original turn's keys
    _cache: dict[str, Any] = field(default_factory=dict)

    def idem(self, tool: str, args: Any) -> str:
        """Idempotency key from turn identity and canonical arguments (a provider retry cannot duplicate)."""
        ns = self.idem_namespace or self.turn_id
        return "copilot-" + content_hash({"turn": ns, "tool": tool, "args": args})[:48]

    def remaining_s(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def note_job(self, job_id: str) -> None:
        if job_id not in self.job_ids:
            self.job_ids.append(job_id)
        self.session_ids.add(job_id)

    def note_created(self, kind: str, ref_id: str, label: str) -> None:
        self.session_ids.add(ref_id)
        if not any(c["ref_id"] == ref_id for c in self.created):
            self.created.append({"kind": kind, "ref_id": ref_id, "label": label})

    async def cached_get(self, path: str, **params: Any) -> Any:
        key = path + repr(sorted(params.items()))
        if key not in self._cache:
            self._cache[key] = await self.backend.get(path, **params)
        return self._cache[key]

    # ------------------------------------------------------------ membership

    def default_run(self, run_id: str | None) -> str:
        rid = run_id or self.context.selected_run_id
        if not rid:
            raise ToolFailure("NO_RUN_SELECTED", "no run is selected in the UI and none was given")
        return rid

    def default_revision(self, revision_id: str | None) -> str:
        rid = revision_id or self.context.scenario_revision_id
        if not rid:
            raise ToolFailure(
                "NO_SCENARIO_SELECTED",
                "no scenario revision is selected; ask the user to open a scenario or select a run first",
            )
        return rid

    def default_field(self, field_id: str | None) -> str:
        fid = field_id or self.context.selected_field_id
        if not fid:
            raise ToolFailure(
                "NO_FIELD_SELECTED", "no field is selected in the UI and none was given"
            )
        return fid

    def _cross(self, kind: str, ident: str, owner: Any) -> ToolFailure:
        return ToolFailure(
            "CROSS_PILOT_REFERENCE",
            f"{kind} {ident} is not part of the current pilot {self.context.pilot_id} "
            f"({self.context.pilot_version}); it cannot be used in this conversation. "
            "Switching pilots is a navigation request; the next turn uses the new pilot.",
            extra={"owner": owner},
        )

    async def run_in_pilot(self, run_id: str) -> dict[str, Any]:
        try:
            view = await self.cached_get(f"/runs/{run_id}")
        except ToolFailure as exc:
            if exc.code == "NOT_FOUND":
                raise ToolFailure("NOT_FOUND", f"run {run_id} does not exist") from exc
            raise
        meta = view.get("meta") or {}
        if (
            meta.get("pilot_id") != self.context.pilot_id
            or meta.get("pilot_version") != self.context.pilot_version
        ):
            raise self._cross("run", run_id, None)
        return view

    async def revision_in_pilot(self, revision_id: str) -> dict[str, Any]:
        try:
            rv = await self.backend.get(f"/scenario-revisions/{revision_id}")
        except ToolFailure as exc:
            if exc.code == "NOT_FOUND":
                raise ToolFailure(
                    "NOT_FOUND", f"scenario revision {revision_id} does not exist"
                ) from exc
            raise
        req = rv["revision"]["request"]
        if (
            req["pilot_id"] != self.context.pilot_id
            or req["pilot_version"] != self.context.pilot_version
        ):
            raise self._cross("scenario revision", revision_id, None)
        return rv

    async def field_in_pilot(self, field_id: str) -> dict[str, Any]:
        try:
            fd = await self.cached_get(
                f"/fields/{field_id}",
                pilot_id=self.context.pilot_id,
                pilot_version=self.context.pilot_version,
            )
        except ToolFailure as exc:
            if exc.code == "NOT_FOUND":
                raise self._cross("field", field_id, None) from exc
            raise
        if fd["pilot_id"] != self.context.pilot_id:
            raise self._cross("field", field_id, None)
        return fd

    async def instance_catalog(
        self, season_id: str | None = None, decision_at: str | None = None
    ) -> dict:
        return await self.cached_get(
            "/interventions",
            pilot_id=self.context.pilot_id,
            pilot_version=self.context.pilot_version,
            season_id=season_id or self.context.season_id,
            decision_at=decision_at,
        )

    # ------------------------------------------------------------- jobs

    async def wait_job(self, job_id: str, wait_s: float | None) -> dict[str, Any]:
        """Wait server-side (no model round trips) up to wait_s, bounded by the turn budget."""
        limit = min(float(wait_s or 0), MAX_WAIT_S, max(0.0, self.remaining_s() - 12.0))
        t0 = time.monotonic()
        while True:
            job = await self.backend.get(f"/jobs/{job_id}")
            if (
                job["state"] in TERMINAL_JOB_STATES
                or time.monotonic() - t0 >= limit
                or self.cancel.is_set()
            ):
                return job
            await asyncio.sleep(0.25)


def run_summary(
    view: dict[str, Any],
    revision: dict[str, Any] | None = None,
    field_id: str | None = None,
    *,
    max_field_metrics: int = 12,
) -> dict[str, Any]:
    run = view["run"]
    status = run["solver_status"]
    out: dict[str, Any] = {
        "run_id": run["run_id"],
        "plan_kind": run["plan_kind"],
        "outcome": run["outcome"],
        "solver_status": status,
        "status_meaning": INVALID_PLAN_MEANING
        if run["outcome"] == "invalid_plan"
        else STATUS_MEANING.get(status),
        "proof_scope": run.get("proof_scope"),
        "primary_objective": run.get("primary_objective"),
        "scenario_revision_id": run["scenario_revision_id"],
        "created_at": run.get("created_at"),
        "label": view.get("label"),
        "warnings": run.get("warnings", [])[:8],
        "season_id": (view.get("meta") or {}).get("season_id"),
    }
    if run["outcome"] == "plan":
        out.update(
            objective_value=run.get("objective_value"),
            objective_upper_bound=run.get("objective_upper_bound"),
            relative_gap=run.get("relative_gap"),
            selected_intervention_instance_ids=run.get("selected_intervention_instance_ids", []),
            physical_validation=(run.get("physical_validation") or {}).get("status"),
        )
        metrics = [m for m in view.get("metrics", []) if m.get("field_id") is None]
        out["metrics"] = [_metric(m) for m in metrics]
        if field_id:
            fm = [m for m in view.get("metrics", []) if m.get("field_id") == field_id]
            out["field_metrics"] = [_metric(m) for m in fm[:max_field_metrics]]
    elif run["outcome"] == "no_plan":
        out["infeasibility_kind"] = run.get("infeasibility_kind")
        out["diagnostics"] = _clip(run.get("diagnostics") or {}, 1500)
        out["metrics"] = []
        out["note"] = "No plan exists for this run; do not report plan yields, production or costs."
    else:
        out["physical_validation"] = (run.get("physical_validation") or {}).get("status")
        out["metrics"] = []
        out["note"] = "Invalid plan: no recommendation and no plan metrics."
    if revision:
        req = revision["revision"]["request"]
        out["request"] = {
            k: req.get(k)
            for k in (
                "season_id",
                "planning_mode",
                "capital_budget_pkr",
                "operating_budget_pkr",
                "supply_profile_id",
                "uniform_reduction_fraction",
                "weather_scenario_ids",
                "minimum_service_ratio",
                "service_group",
                "optimization_mode",
                "uncertainty_set_id",
                "permit_groundwater",
                "forced_instance_ids",
                "excluded_instance_ids",
                "blocked_edge_ids",
            )
        }
    return out


def _metric(m: dict[str, Any]) -> dict[str, Any]:
    d = {
        "metric_id": m["metric_id"],
        "value": m.get("value"),
        "unit": m.get("unit"),
        "status": m.get("status"),
        "basis": metric_basis(m["metric_id"]),
    }
    if m.get("field_id"):
        d["field_id"] = m["field_id"]
    if m.get("reason"):
        d["reason"] = m["reason"]
    if m.get("crop"):
        d["crop"] = m["crop"]
    return d


def _clip(obj: Any, limit: int) -> Any:
    """Fit ``obj`` within ``limit`` JSON chars by trimming long lists and rounding floats,
    never by cutting the JSON text (a cut excerpt loses IDs the model needs)."""
    import json

    def compact(o: Any, max_list: int | None) -> Any:
        if isinstance(o, float):
            return float(f"{o:.6g}")
        if isinstance(o, dict):
            return {k: compact(v, max_list) for k, v in o.items()}
        if isinstance(o, list):
            items = [compact(v, max_list) for v in (o if max_list is None else o[:max_list])]
            if max_list is not None and len(o) > max_list:
                items.append({"omitted_items": len(o) - max_list})
            return items
        return o

    for max_list in (None, 24, 12, 6, 3, 1):
        out = compact(obj, max_list)
        if len(json.dumps(out, default=str)) <= limit:
            return out
    if isinstance(obj, dict):  # keep scalars (IDs, statuses, totals); drop nested detail
        return {
            **{k: v for k, v in obj.items() if not isinstance(v, (dict, list))},
            "truncated": True,
            "omitted_keys": sorted(k for k, v in obj.items() if isinstance(v, (dict, list))),
        }
    return {"truncated": True}


def job_view(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "operation": job["operation"],
        "state": job["state"],
        "stage": job.get("stage"),
        "progress": job.get("progress"),
        "result_ref": job.get("result_ref"),
        "error": {k: v for k, v in (job.get("error") or {}).items() if k != "trace"} or None,
        "state_meaning": {
            "queued": "waiting for a worker",
            "running": "still computing; results are not available yet",
            "succeeded": "finished; see result_ref",
            "failed": "the job failed; there is no result (this is not an infeasible plan)",
            "cancelled": "cancelled by request; there is no result",
            "interrupted": "interrupted by a restart; there is no result",
            "cancel_requested": "cancellation requested",
            "waiting_for_review": "waiting for review",
        }.get(job["state"]),
    }
