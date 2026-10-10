"""Reversible create/compute tools: branches, solves, analyses, previews and reports (T11.2, T11.3).

Mutations go through the same idempotent routes as the UI. Keys derive from the
turn and canonical arguments, so a provider retry of the same call returns the
existing branch/job/report instead of creating a second one.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import Field

from aabflow.copilot.registry import PLANNER, ToolArgs, tool
from aabflow.copilot.tools.backend import RouteUnavailable, ToolFailure
from aabflow.copilot.tools.base import ToolCtx, job_view, run_summary
from aabflow.copilot.tools.money import AmountNeedsClarification, parse_pkr
from aabflow.copilot.tools.presets import PRESETS, PresetId
from aabflow.copilot.tools.read import (
    analysis_summary,
    comparison_view,
    describe_job,
    run_datasets,
)

PLAN_SHORT = {
    "B0": "fixed roster (B0)",
    "B1": "no-new-capital plan (B1)",
    "P": "plan (P)",
    "R": "robust plan (R)",
}

PlanKindArg = Literal["P", "R", "B0", "B1"]


def _pkr(text: str | None, what: str) -> tuple[int | None, str | None]:
    if text is None:
        return None, None
    try:
        p = parse_pkr(text)
    except AmountNeedsClarification as exc:
        raise ToolFailure("NEEDS_CLARIFICATION", f"{what}: {exc}") from exc
    return p.pkr, f"{what} {p.display} (parsed from '{p.source_text}')"


def _service(
    preset: str | None, ratio: float | None, group: str | None
) -> tuple[dict[str, Any], list[str]]:
    shown: list[str] = []
    if preset:
        if ratio is not None or group is not None:
            raise ToolFailure(
                "INVALID_INPUT",
                "give either a service preset or an explicit floor and group, not both",
            )
        p = PRESETS[preset]
        shown.append(
            f"service preset '{preset}': {p['note']} (floor {p['minimum_service_ratio']:.2f}, "
            f"group {p['service_group']}, basis {p['basis']})"
        )
        return {
            "minimum_service_ratio": p["minimum_service_ratio"],
            "service_group": p["service_group"],
        }, shown
    if ratio is None and group is None:
        return {}, shown
    if ratio is None or group is None:
        raise ToolFailure(
            "NEEDS_CLARIFICATION",
            "a service floor needs both a numerical floor and the field group it protects; ask the user "
            "(or use a named preset such as tail-protect-standard, whose floor is shown)",
        )
    if not 0 <= ratio <= 1:
        raise ToolFailure("INVALID_INPUT", "minimum_service_ratio is a fraction between 0 and 1")
    shown.append(f"service floor {ratio:.2f} of reference allowance for {group} fields")
    return {"minimum_service_ratio": ratio, "service_group": group}, shown


async def _check_instances(ctx: ToolCtx, ids: list[str] | None) -> None:
    if not ids:
        return
    cat = await ctx.instance_catalog()
    known = {i["instance"]["instance_id"] for i in cat["interventions"]}
    bad = [i for i in ids if i not in known]
    if bad:
        raise ToolFailure(
            "NOT_FOUND", f"intervention instances not in the current pilot/season: {bad}"
        )


async def _submit_solve(
    ctx: ToolCtx, revision_id: str, plan_kind: str, wait_s: int | None
) -> dict[str, Any]:
    ctx.budget.reserve_job()
    body = {"plan_kind": plan_kind, "time_limit_s": 10.0}
    acc = await ctx.backend.post(
        f"/scenario-revisions/{revision_id}/solve",
        body,
        idempotency_key=ctx.idem("solve", {"revision": revision_id, **body}),
    )
    ctx.note_job(acc["job_id"])
    job = await ctx.wait_job(acc["job_id"], wait_s if wait_s is not None else 30)
    out = await describe_job(ctx, job)
    if out.get("run"):
        ctx.note_created("run", out["run"]["run_id"], f"{plan_kind} run")
    elif job["state"] in ("queued", "running"):
        out["note"] = (
            "still running; it continues as a job and the result appears in the workspace when done. "
            "Tell the user it is running instead of polling repeatedly."
        )
    return out


# --------------------------------------------------------------- branch_scenario


class BranchChanges(ToolArgs):
    capital_budget: str | None = Field(
        None,
        description="New capital budget exactly as the user said it, e.g. '20 lakh', 'PKR 2 million', "
        "'bees lakh'. The server converts it to PKR; do not convert yourself.",
    )
    operating_budget: str | None = Field(
        None, description="New operating budget as the user said it"
    )
    supply_profile_id: str | None = None
    uniform_reduction_percent: float | None = Field(
        None, description="Uniform canal supply cut in percent (0-100)"
    )
    weather_scenario_ids: list[str] | None = None
    service_preset: PresetId | None = Field(
        None,
        description="Named service-protection preset, e.g. tail-protect-standard for 'protect the tail'",
    )
    minimum_service_ratio: float | None = Field(
        None, description="Explicit service floor (fraction 0-1) only if the user stated a number"
    )
    service_group: Literal["all", "head", "middle", "tail"] | None = None
    allowed_intervention_instance_ids: list[str] | None = None
    forced_instance_ids: list[str] | None = None
    excluded_instance_ids: list[str] | None = None
    permit_groundwater: bool | None = None
    blocked_edge_ids: list[str] | None = None


class BranchArgs(ToolArgs):
    base_revision_id: str | None = Field(
        None, description="Parent revision; null = the current revision"
    )
    changes: BranchChanges
    label: str | None = None
    solve: bool = Field(
        description="Also solve the new revision now (true for explicit what-if requests)"
    )
    plan_kind: PlanKindArg | None = Field(
        None, description="Plan to solve when solve=true; null = P"
    )
    wait_s: int | None = Field(
        None, description="Seconds to wait for the solve (default 30, max 45)"
    )


@tool(
    "branch_scenario",
    args=BranchArgs,
    semantics="create",
    roles=PLANNER,
    submits_jobs=True,
    activity="Running a new scenario branch",
    timeout_s=75,
)
async def branch_scenario(ctx: ToolCtx, args: BranchArgs) -> dict[str, Any]:
    """Create a new immutable scenario revision from typed changes (budgets, supply, weather, service
    floor/preset, allowed/forced/excluded interventions, groundwater permission, blocked edges) and optionally
    solve it. The parent stays unchanged. Budgets are passed as the user said them and parsed to PKR by the
    server; an unknown currency returns NEEDS_CLARIFICATION. It cannot edit rights, sources, dates or
    provenance."""
    base = ctx.default_revision(args.base_revision_id)
    rv, nid, shown, new = await _make_branch(ctx, base, args.changes, args.label)
    out: dict[str, Any] = {
        "ok": True,
        "scenario_revision_id": nid,
        "parent_revision_id": base,
        "applied_changes": shown,
        "readiness": new["readiness"],
        "parent_runs": [r for r in rv["runs"] if r["outcome"]][-6:],
        "note": "The parent revision is unchanged; the branch is offered to the UI to open.",
    }
    if args.solve:
        if not new["readiness"]["ready"]:
            out["solve"] = {
                "submitted": False,
                "reason": "revision not ready",
                "blockers": new["readiness"]["blockers"],
            }
        else:
            out["solve"] = await _submit_solve(ctx, nid, args.plan_kind or "P", args.wait_s)
    return out


async def _make_branch(
    ctx: ToolCtx, base: str, ch: BranchChanges, label: str | None
) -> tuple[dict[str, Any], str, list[str], dict[str, Any]]:
    """Validate typed changes and create the child revision (idempotent per turn and arguments)."""
    rv = await ctx.revision_in_pilot(base)
    changes: dict[str, Any] = {}
    shown: list[str] = []
    for key, text, what in (
        ("capital_budget_pkr", ch.capital_budget, "capital budget"),
        ("operating_budget_pkr", ch.operating_budget, "operating budget"),
    ):
        val, disp = _pkr(text, what)
        if val is not None:
            changes[key] = val
            shown.append(disp)
    svc, svc_shown = _service(ch.service_preset, ch.minimum_service_ratio, ch.service_group)
    changes.update(svc)
    shown += svc_shown
    if ch.uniform_reduction_percent is not None:
        if not 0 <= ch.uniform_reduction_percent <= 100:
            raise ToolFailure("INVALID_INPUT", "uniform_reduction_percent must be 0-100")
        changes["uniform_reduction_fraction"] = round(ch.uniform_reduction_percent / 100.0, 6)
        shown.append(f"uniform supply reduction {ch.uniform_reduction_percent:g}%")
    for key in (
        "supply_profile_id",
        "weather_scenario_ids",
        "allowed_intervention_instance_ids",
        "forced_instance_ids",
        "excluded_instance_ids",
        "permit_groundwater",
        "blocked_edge_ids",
    ):
        v = getattr(ch, key)
        if v is not None:
            changes[key] = v
            shown.append(f"{key.replace('_', ' ')}: {v}")
    for key in (
        "allowed_intervention_instance_ids",
        "forced_instance_ids",
        "excluded_instance_ids",
    ):
        await _check_instances(ctx, changes.get(key))
    if not changes:
        raise ToolFailure(
            "INVALID_INPUT", "no changes given; a branch needs at least one typed change"
        )
    sid = rv["revision"]["scenario_id"]
    body = {"parent_revision_id": base, "changes": changes}
    new = await ctx.backend.post(
        f"/scenarios/{sid}/revisions", body, idempotency_key=ctx.idem("branch_scenario", body)
    )
    nid = new["revision"]["scenario_revision_id"]
    ctx.note_created("branch", nid, label or "New scenario branch")
    return rv, nid, shown, new


# -------------------------------------------------------------------- run_what_if


class WhatIfArgs(ToolArgs):
    changes: BranchChanges
    label: str | None = Field(
        None,
        description="Short name for the new scenario, e.g. 'Budget 20 lakh' or 'Canal closed 14 days'",
    )
    plan_kind: PlanKindArg | None = Field(
        None, description="Plan to solve; null = the selected run's plan kind (P if none)"
    )
    compare_with_run_id: str | None = Field(
        None,
        description="Run to compare the new result with; null = the current scenario's run of the same kind",
    )


@tool(
    "run_what_if",
    args=WhatIfArgs,
    semantics="create",
    roles=PLANNER,
    submits_jobs=True,
    activity="Running your what-if as a new scenario",
    timeout_s=80,
)
async def run_what_if(ctx: ToolCtx, args: WhatIfArgs) -> dict[str, Any]:
    """One-step what-if: create a reversible branch of the current scenario with typed changes (budget as said,
    supply profile e.g. interruption-14d-v1 for a two-week canal closure, uniform supply cut, weather, service
    preset/floor, forced/excluded investments, groundwater permission), solve it, and compare the new run with
    the current plan using the comparison service. Returns the new run's status, server-computed deltas and
    chart datasets. The parent scenario is unchanged. Prefer this over branch_scenario + solve + compare."""
    base = ctx.default_revision(None)
    _, nid, shown, new = await _make_branch(ctx, base, args.changes, args.label)
    sel_kind = ctx.context.selected_run_plan_kind
    kind = args.plan_kind or (sel_kind if sel_kind in ("P", "R", "B1") else "P")
    out: dict[str, Any] = {
        "ok": True,
        "scenario_revision_id": nid,
        "parent_revision_id": base,
        "applied_changes": shown,
        "plan_kind": kind,
    }
    if not new["readiness"]["ready"]:
        out["solve"] = {"submitted": False, "blockers": new["readiness"]["blockers"]}
        out["note"] = "The changed scenario is not ready to solve; explain the blockers."
        return out
    solved = await _submit_solve(ctx, nid, kind, 40)
    run = solved.get("run")
    out["job"] = {k: solved.get(k) for k in ("job_id", "state", "state_meaning", "error")}
    if not run:
        out["note"] = solved.get("note") or "The solve did not finish; no result exists yet."
        return out
    out["new_run"] = {
        k: run.get(k)
        for k in (
            "run_id",
            "plan_kind",
            "solver_status",
            "status_meaning",
            "outcome",
            "selected_intervention_instance_ids",
            "infeasibility_kind",
            "diagnostics",
            "note",
        )
        if run.get(k) is not None
    }
    base_run = args.compare_with_run_id
    if base_run is None:
        from aabflow.copilot.tools.insight import latest_runs

        parent = (await latest_runs(ctx, base)).get(kind)
        base_run = parent["run_id"] if parent and parent.get("outcome") == "plan" else None
        base_run = base_run or ctx.context.selected_run_id
    if not base_run:
        out["note"] = "No run of the current scenario to compare with; report the new run alone."
        out["datasets"] = await run_datasets(ctx, await ctx.run_in_pilot(run["run_id"]))
        return out
    base_view = await ctx.run_in_pilot(base_run)
    out["compared_with_run_id"] = base_run
    if run["outcome"] != "plan" or base_view["run"]["outcome"] != "plan":
        out["note"] = (
            f"The new run is {run['solver_status']}: there is no plan to compare, so no production or "
            "cost change exists. Explain the status and diagnostics; do not invent a loss."
        )
        return out
    ids = [base_run, run["run_id"]]
    cmp = await ctx.backend.post(
        "/comparisons", {"run_ids": ids}, idempotency_key=ctx.idem("compare_runs", ids)
    )
    labels = {
        base_run: f"Current {PLAN_SHORT.get(base_view['run']['plan_kind'], 'plan')}",
        run["run_id"]: args.label or "What-if",
    }
    view = await comparison_view(ctx, cmp, labels)
    ctx.note_created("comparison", cmp["comparison_id"], "Compare with the current plan")
    out["comparison"] = view
    out["datasets"] = view.pop("datasets")
    return out


# ---------------------------------------------------------------- solve_scenario


class SolveArgs(ToolArgs):
    revision_id: str | None = Field(None, description="Revision to solve; null = current revision")
    plan_kind: PlanKindArg = Field(
        description="P = optimized plan; B0/B1 = baselines; R = robust (needs an uncertainty set)"
    )
    wait_s: int | None = Field(None, description="Seconds to wait (default 30, max 45)")


@tool(
    "solve_scenario",
    args=SolveArgs,
    semantics="compute",
    roles=PLANNER,
    submits_jobs=True,
    activity="Solving the scenario",
    timeout_s=75,
)
async def solve_scenario(ctx: ToolCtx, args: SolveArgs) -> dict[str, Any]:
    """Start a solve job for an existing validated revision of the current pilot and wait briefly for it.
    Returns the job and, when finished, the run summary with its real solver status."""
    rid = ctx.default_revision(args.revision_id)
    await ctx.revision_in_pilot(rid)
    return await _submit_solve(ctx, rid, args.plan_kind, args.wait_s)


# ----------------------------------------------------------- evaluate_alternative


class AlternativeArgs(ToolArgs):
    instance_id: str = Field(
        description="Intervention instance ID, e.g. pilot-a:field-007:pond-small"
    )
    action: Literal["force", "exclude"]
    base_revision_id: str | None = None
    base_run_id: str | None = Field(None, description="Run to compare against; null = selected run")
    wait_s: int | None = None


def _interval(alt: dict, base: dict) -> dict[str, Any] | None:
    """Supported objective-difference interval [L1-U2, U1-L2] (T7.3); alt = 1, base = 2."""

    def bounds(r):
        lo = r.get("objective_value")
        if lo is None:
            return None
        up = r.get("objective_upper_bound")
        if up is None and r.get("solver_status") == "OPTIMAL":
            up = lo
        return lo, up

    a, b = bounds(alt), bounds(base)
    if not a or not b or a[1] is None or b[1] is None:
        return None
    lo, hi = a[0] - b[1], a[1] - b[0]
    return {
        "objective": alt.get("primary_objective"),
        "difference_low": lo,
        "difference_high": hi,
        "exact": abs(hi - lo) < 1e-6,
        "note": "alternative minus base; an interval because solver bounds are not closed"
        if abs(hi - lo) >= 1e-6
        else "alternative minus base; both runs proven optimal within the finite library",
    }


@tool(
    "evaluate_alternative",
    args=AlternativeArgs,
    semantics="compute",
    roles=PLANNER,
    submits_jobs=True,
    activity="Checking investment {instance_id}",
    timeout_s=80,
)
async def evaluate_alternative(ctx: ToolCtx, args: AlternativeArgs) -> dict[str, Any]:
    """Why-not analysis: force or exclude one intervention instance and compare with the base plan using the
    same metric definitions. First checks eligibility (commissioning date, prerequisites, budget); an
    ineligible or too-late investment returns the reasons and submits no job."""
    base_rev = ctx.default_revision(args.base_revision_id)
    rv = await ctx.revision_in_pilot(base_rev)
    req = rv["revision"]["request"]
    cat = await ctx.instance_catalog(req["season_id"], req["decision_at"])
    entry = next(
        (i for i in cat["interventions"] if i["instance"]["instance_id"] == args.instance_id), None
    )
    if entry is None:
        raise ToolFailure(
            "NOT_FOUND",
            f"intervention {args.instance_id} is not in pilot {ctx.context.pilot_id} "
            f"for season {req['season_id']}",
        )
    elig = {
        "eligible": entry["eligible"],
        "reasons": entry["reasons"],
        "commissioned_on": entry["commissioned_on"],
        "in_library": entry["in_library"],
        "capex_pkr": entry["instance"]["capex_pkr"],
        "category": entry["category"],
    }
    if args.action == "force" and not entry["eligible"]:
        return {
            "ok": True,
            "submitted": False,
            "instance_id": args.instance_id,
            "eligibility": elig,
            "note": "Not eligible: no analysis was run because forcing it would be an impossible "
            "recommendation. Explain the reasons instead.",
        }
    base_run_id = args.base_run_id or ctx.context.selected_run_id
    base_view = await ctx.run_in_pilot(base_run_id) if base_run_id else None
    payload = {
        "base_revision_id": base_rev,
        "base_run_id": base_run_id,
        "instance_id": args.instance_id,
        "action": args.action,
    }
    try:
        ctx.budget.reserve_job()
        acc = await ctx.backend.post(
            "/analyses/why-not", payload, idempotency_key=ctx.idem("why_not", payload)
        )
    except RouteUnavailable:
        ctx.budget.jobs_submitted -= 1
        return await _why_not_by_branch(ctx, rv, base_view, args, elig)
    ctx.note_job(acc["job_id"])
    ctx.note_created("analysis", acc["analysis_id"], f"Why-not: {args.action} {args.instance_id}")
    job = await ctx.wait_job(acc["job_id"], args.wait_s if args.wait_s is not None else 35)
    out = {
        "ok": True,
        "submitted": True,
        "eligibility": elig,
        "analysis_id": acc["analysis_id"],
        "job": job_view(job),
    }
    if job["state"] == "succeeded":
        out["analysis"] = await analysis_summary(ctx, acc["analysis_id"])
    return out


async def _why_not_by_branch(
    ctx: ToolCtx, rv: dict, base_view: dict | None, args: AlternativeArgs, elig: dict
) -> dict[str, Any]:
    """T7.3 via existing services: child revision requiring/excluding the instance, solve P, compare."""
    key = "forced_instance_ids" if args.action == "force" else "excluded_instance_ids"
    req = rv["revision"]["request"]
    ids = sorted(set(req.get(key) or []) | {args.instance_id})
    other = "excluded_instance_ids" if key == "forced_instance_ids" else "forced_instance_ids"
    changes: dict[str, Any] = {key: ids}
    if args.instance_id in (req.get(other) or []):
        changes[other] = [i for i in req[other] if i != args.instance_id]
    body = {"parent_revision_id": rv["revision"]["scenario_revision_id"], "changes": changes}
    new = await ctx.backend.post(
        f"/scenarios/{rv['revision']['scenario_id']}/revisions",
        body,
        idempotency_key=ctx.idem("why_not_branch", body),
    )
    nid = new["revision"]["scenario_revision_id"]
    ctx.note_created("branch", nid, f"{args.action.title()} {args.instance_id}")
    out: dict[str, Any] = {
        "ok": True,
        "submitted": True,
        "method": "child revision + solve (T7.3)",
        "eligibility": elig,
        "scenario_revision_id": nid,
        "readiness": new["readiness"],
    }
    if not new["readiness"]["ready"]:
        out["solve"] = {"submitted": False, "blockers": new["readiness"]["blockers"]}
        return out
    solved = await _submit_solve(ctx, nid, "P", args.wait_s if args.wait_s is not None else 35)
    out["solve"] = solved
    alt = solved.get("run")
    if alt and base_view:
        base = run_summary(base_view)
        out["base_run_id"] = base["run_id"]
        if alt["outcome"] == "plan" and base["outcome"] == "plan":
            ids2 = [base["run_id"], alt["run_id"]]
            cmp = await ctx.backend.post(
                "/comparisons", {"run_ids": ids2}, idempotency_key=ctx.idem("compare_runs", ids2)
            )
            out["comparison_id"] = cmp["comparison_id"]
            out["compatible"] = cmp["compatible"]
            out["run_level_deltas"] = [
                {k: d[k] for k in ("metric_id", "unit", "a", "b", "delta", "status")}
                for d in cmp["deltas"]
                if d["field_id"] is None
            ]
            out["objective_difference"] = _interval(alt, base)
        else:
            out["note"] = (
                f"alternative run is {alt['solver_status']}: no plan to compare. Explain the verified "
                "prerequisites/budget/conflicts instead of a foregone value."
            )
    return out


# --------------------------------------------------------------- run_stress_test


class StressArgs(ToolArgs):
    run_id: str | None = Field(None, description="Plan run to stress; null = selected run")
    mode: Literal["fixed_plan", "recovery_plan"] = Field(
        description="fixed_plan = same investments and dated operations in each state; recovery_plan = "
        "investments fixed, operations re-optimized per state (conditional, not a prospective plan)"
    )
    uncertainty_set_id: str | None = None
    state_ids: list[str] | None = Field(None, description="Subset of states; null = all nine")
    wait_s: int | None = None


@tool(
    "run_stress_test",
    args=StressArgs,
    semantics="compute",
    roles=PLANNER,
    submits_jobs=True,
    activity="Running a stress test",
    timeout_s=80,
)
async def run_stress_test(ctx: ToolCtx, args: StressArgs) -> dict[str, Any]:
    """Stress a plan over the weather x supply grid. Undeliverable cells have no achievable production and
    must be reported as undeliverable, not as low yield."""
    rid = ctx.default_run(args.run_id)
    view = await ctx.run_in_pilot(rid)
    if view["run"]["outcome"] != "plan":
        raise ToolFailure(
            "NO_PLAN", f"run {rid} is {view['run']['solver_status']}; there is no plan to stress"
        )
    # null uses the run's own uncertainty set (server default)
    payload = {
        "run_id": rid,
        "mode": args.mode,
        "uncertainty_set_id": args.uncertainty_set_id,
        "state_ids": args.state_ids,
    }
    return await _analysis(ctx, "stress", payload, f"Stress test ({args.mode})", args.wait_s)


async def _analysis(
    ctx: ToolCtx, route: str, payload: dict, label: str, wait_s: int | None
) -> dict[str, Any]:
    ctx.budget.reserve_job()
    try:
        acc = await ctx.backend.post(
            f"/analyses/{route}", payload, idempotency_key=ctx.idem(route, payload)
        )
    except ToolFailure:
        ctx.budget.jobs_submitted -= 1
        raise
    ctx.note_job(acc["job_id"])
    ctx.note_created("analysis", acc["analysis_id"], label)
    job = await ctx.wait_job(acc["job_id"], wait_s if wait_s is not None else 35)
    out: dict[str, Any] = {"ok": True, "analysis_id": acc["analysis_id"], "job": job_view(job)}
    if job["state"] == "succeeded":
        out["analysis"] = await analysis_summary(ctx, acc["analysis_id"])
    elif job["state"] in ("queued", "running"):
        out["note"] = (
            "still running as a job; tell the user and link the analysis instead of polling."
        )
    return out


# ---------------------------------------------------------------- build_frontier


class FrontierPoint(ToolArgs):
    capital_budget: str = Field(description="Capital budget as said, e.g. '10 lakh'")
    service_preset: PresetId | None = None
    minimum_service_ratio: float | None = None
    service_group: Literal["all", "head", "middle", "tail"] | None = None


class FrontierArgs(ToolArgs):
    base_revision_id: str | None = None
    settings: list[FrontierPoint] = Field(
        description="6 to 9 explicit (budget, service floor) settings"
    )
    wait_s: int | None = None


@tool(
    "build_frontier",
    args=FrontierArgs,
    semantics="compute",
    roles=PLANNER,
    submits_jobs=True,
    activity="Building the spending/service frontier",
    timeout_s=80,
)
async def build_frontier(ctx: ToolCtx, args: FrontierArgs) -> dict[str, Any]:
    """Build a resilience frontier from 6-9 explicit (capital budget, service floor) settings as one batch
    analysis job. Points carry run IDs; unknown points stay unknown (no invented curve)."""
    base = ctx.default_revision(args.base_revision_id)
    await ctx.revision_in_pilot(base)
    if not 6 <= len(args.settings) <= 9:
        raise ToolFailure("INVALID_INPUT", "a frontier needs 6 to 9 explicit settings")
    pts = []
    for s in args.settings:
        pkr, _ = _pkr(s.capital_budget, "capital budget")
        svc, _ = _service(s.service_preset, s.minimum_service_ratio, s.service_group)
        pts.append(
            {
                "capital_budget_pkr": pkr,
                "minimum_service_ratio": svc.get("minimum_service_ratio"),
                "service_group": svc.get("service_group"),
            }
        )
    if len(
        {(p["capital_budget_pkr"], p["minimum_service_ratio"], p["service_group"]) for p in pts}
    ) != len(pts):
        raise ToolFailure("INVALID_INPUT", "frontier settings must be distinct")
    payload = {"base_revision_id": base, "settings": pts, "plan_kind": "P"}
    return await _analysis(ctx, "frontier", payload, "Frontier", args.wait_s)


# ----------------------------------------------------------- analyze_sensitivity


class SensitivityArgs(ToolArgs):
    analysis_id: str | None = Field(
        None, description="Read an existing sensitivity analysis instead of running"
    )
    base_revision_id: str | None = None
    parameter: (
        Literal[
            "capital_budget_pkr",
            "operating_budget_pkr",
            "uniform_reduction_fraction",
            "minimum_service_ratio",
        ]
        | None
    ) = Field(None, description="Parameter to vary")
    values: list[str] | None = Field(
        None,
        description="2 to 12 explicit values as said (PKR amounts may use lakh/crore). For a range "
        "such as 'between 50,000 and 400,000' pass several points spanning it, ends included",
    )
    service_group: Literal["all", "head", "middle", "tail"] | None = Field(
        None, description="Group the service floor applies to (minimum_service_ratio only)"
    )
    wait_s: int | None = None


@tool(
    "analyze_sensitivity",
    args=SensitivityArgs,
    semantics="compute",
    roles=PLANNER,
    submits_jobs=True,
    activity="Analyzing sensitivity",
    timeout_s=80,
)
async def analyze_sensitivity(ctx: ToolCtx, args: SensitivityArgs) -> dict[str, Any]:
    """Read or run a sensitivity analysis over an explicit parameter range: which inputs change the decision,
    the bottleneck, and the measurement that would resolve it. Selection frequency is not a probability."""
    if args.analysis_id:
        return {"ok": True, "analysis": await analysis_summary(ctx, args.analysis_id)}
    if not args.parameter or not args.values:
        raise ToolFailure(
            "INVALID_INPUT", "give an existing analysis_id or a parameter with explicit values"
        )
    base = ctx.default_revision(args.base_revision_id)
    await ctx.revision_in_pilot(base)
    values: list[Any] = []
    for v in args.values:
        if args.parameter.endswith("_pkr"):
            values.append(_pkr(v, args.parameter)[0])
        else:
            try:
                f = float(v.strip().rstrip("%"))
            except ValueError as exc:
                raise ToolFailure(
                    "INVALID_INPUT", f"{v!r} is not a number for {args.parameter}"
                ) from exc
            values.append(f / 100 if v.strip().endswith("%") or f > 1 else f)
    values = sorted(set(values))
    if not 2 <= len(values) <= 12:
        raise ToolFailure("INVALID_INPUT", "a sensitivity analysis needs 2 to 12 distinct values")
    payload: dict[str, Any] = {
        "base_revision_id": base,
        "parameter": args.parameter,
        "values": values,
    }
    if args.service_group and args.parameter == "minimum_service_ratio":
        payload["service_group"] = args.service_group
    return await _analysis(
        ctx, "sensitivity", payload, f"Sensitivity: {args.parameter}", args.wait_s
    )


# --------------------------------------------------------------- analyze_synergy


class SynergyArgs(ToolArgs):
    instance_a: str
    instance_b: str
    other_actions: Literal["fixed", "reoptimize"] = Field(
        description="Whether other investments stay fixed or may re-optimize, used consistently in all four runs"
    )
    base_revision_id: str | None = None
    wait_s: int | None = None


@tool(
    "analyze_synergy",
    args=SynergyArgs,
    semantics="compute",
    roles=PLANNER,
    submits_jobs=True,
    activity="Analyzing synergy",
    timeout_s=80,
)
async def analyze_synergy(ctx: ToolCtx, args: SynergyArgs) -> dict[str, Any]:
    """Matched none/A/B/both runs for two intervention instances and the synergy
    outcome_AB - outcome_A - outcome_B + outcome_none computed by the server."""
    base = ctx.default_revision(args.base_revision_id)
    await ctx.revision_in_pilot(base)
    await _check_instances(ctx, [args.instance_a, args.instance_b])
    payload = {
        "base_revision_id": base,
        "instance_a": args.instance_a,
        "instance_b": args.instance_b,
        "other_actions": args.other_actions,
    }
    return await _analysis(ctx, "synergy", payload, "Synergy", args.wait_s)


# ---------------------------------------------------------------- preview_policy


class ScheduleItem(ToolArgs):
    date: str = Field(description="YYYY-MM-DD")
    gross_depth_mm: float


class PreviewArgs(ToolArgs):
    mode: Literal["preview", "exact_confirm"] = Field(
        description="preview = approximate surrogate estimate; exact_confirm = run the crop model"
    )
    field_id: str | None = Field(
        None, description="Field whose crop/soil/efficiency to use; null = selected"
    )
    schedule: list[ScheduleItem] | None = Field(
        None, description="Irrigation events; null = the field's schedule in the selected run"
    )
    weather_scenario_id: str | None = None
    preview_id: str | None = Field(None, description="Existing preview to confirm (exact_confirm)")


@tool(
    "preview_policy",
    args=PreviewArgs,
    semantics="compute",
    roles=PLANNER,
    activity="Previewing an irrigation schedule",
    timeout_s=60,
)
async def preview_policy(ctx: ToolCtx, args: PreviewArgs) -> dict[str, Any]:
    """Approximate a field irrigation schedule with the validated surrogate (estimate_kind surrogate_preview,
    never a final result) or confirm it exactly with the crop model. Out-of-domain inputs return no estimate."""
    fid = ctx.default_field(args.field_id)
    fd = await ctx.field_in_pilot(fid)
    season = ctx.context.season_id
    if not season:
        raise ToolFailure("NO_SEASON_SELECTED", "select a crop season first")
    seasons = await ctx.cached_get("/seasons", pilot_id=ctx.context.pilot_id)
    s = next((x["season"] for x in seasons["seasons"] if x["season"]["season_id"] == season), None)
    if s is None:
        raise ToolFailure("NOT_FOUND", f"season {season} is not configured")
    schedule = (
        [e.model_dump() for e in args.schedule]
        if args.schedule
        else await _selected_schedule(ctx, fid)
    )
    req = {
        "crop_profile_id": s["crop_profile_id"],
        "soil_profile_id": fd["field"]["soil_profile_id"],
        "application_efficiency": fd["field"]["existing_application_efficiency"],
        "schedule": schedule,
        "season_id": season,
        "weather_scenario_id": args.weather_scenario_id or "typical",
        "pilot_id": ctx.context.pilot_id,
    }
    if args.mode == "preview":
        try:
            pv = await ctx.backend.post(
                "/surrogate/previews", req, idempotency_key=ctx.idem("preview", req)
            )
        except ToolFailure as exc:
            if exc.status == 503:
                return {
                    "ok": False,
                    "code": "SURROGATE_NOT_VALIDATED",
                    "detail": exc.detail,
                    "note": "The surrogate has not passed its validation gate, so no approximate "
                    "preview is offered. Offer exact_confirm (crop model) instead.",
                }
            if not isinstance(exc, RouteUnavailable):
                raise
            from aabflow.surrogate.prediction import preview

            try:
                pv = (await asyncio.to_thread(preview, req)).model_dump(mode="json")
            except (ValueError, FileNotFoundError) as exc:
                raise ToolFailure(
                    "ASSET_UNAVAILABLE", f"surrogate preview unavailable: {exc}"
                ) from exc
        pv["label"] = (
            "Approximate preview (surrogate_preview); not a computed recommendation until exact-confirmed"
        )
        return {"ok": True, "field_id": fid, "preview": pv}
    if args.preview_id:
        try:
            ctx.budget.reserve_job()
            acc = await ctx.backend.post(
                f"/surrogate/previews/{args.preview_id}/verify",
                {},
                idempotency_key=ctx.idem("verify", args.preview_id),
            )
            ctx.note_job(acc["job_id"])
            job = await ctx.wait_job(acc["job_id"], 30)
            return {"ok": True, "field_id": fid, "job": await describe_job(ctx, job)}
        except RouteUnavailable:
            ctx.budget.jobs_submitted -= 1
    from aabflow.surrogate.prediction import confirm

    try:
        outcome, pv, diff = await asyncio.to_thread(confirm, req)
    except (ValueError, FileNotFoundError) as exc:
        raise ToolFailure("ASSET_UNAVAILABLE", f"exact confirmation unavailable: {exc}") from exc
    o = outcome.model_dump(mode="json")
    return {
        "ok": True,
        "field_id": fid,
        "exact": {
            "estimate_kind": "model_output",
            "yield_kg_ha": o.get("yield_kg_ha"),
            "experiment_hash": o.get("experiment_hash"),
            "crop_profile_id": o.get("crop_profile_id"),
        },
        "preview_estimated_yield_kg_ha": pv.estimated_yield_kg_ha,
        "preview_minus_exact_kg_ha": diff,
        "note": "Exact AquaCrop output for this field schedule. It becomes plan-eligible only after it is "
        "added to a candidate library and passes physical validation in a solve.",
    }


async def _selected_schedule(ctx: ToolCtx, fid: str) -> list[dict[str, Any]]:
    rid = ctx.context.selected_run_id
    if not rid:
        raise ToolFailure(
            "INVALID_INPUT", "give a schedule or select a run whose field schedule to use"
        )
    view = await ctx.run_in_pilot(rid)
    sel = ((view.get("selection") or {}).get("fields") or {}).get(fid) or {}
    sched = sel.get("application_schedule") or sel.get("schedule")
    if not sched:
        raise ToolFailure(
            "INVALID_INPUT", f"run {rid} does not expose a schedule for {fid}; give one explicitly"
        )
    return [{"date": e["date"], "gross_depth_mm": e["gross_depth_mm"]} for e in sched]


# ----------------------------------------------------------------- create_report


class ReportArgs(ToolArgs):
    run_ids: list[str] = Field(
        description="Runs of the current pilot to include (first = main plan)"
    )
    analysis_ids: list[str] | None = None
    report_type: Literal["one_page_plan", "full_report"] = "one_page_plan"
    wait_s: int | None = None


@tool(
    "create_report",
    args=ReportArgs,
    semantics="create",
    roles=PLANNER,
    submits_jobs=True,
    activity="Preparing a local report",
    timeout_s=80,
)
async def create_report(ctx: ToolCtx, args: ReportArgs) -> dict[str, Any]:
    """Create a versioned local report (no email or upload) from specified runs/analyses and return its
    report ID and local download link."""
    if not args.run_ids:
        raise ToolFailure("INVALID_INPUT", "a report needs at least one run")
    for rid in args.run_ids:
        await ctx.run_in_pilot(rid)
    payload = {
        "run_ids": args.run_ids,
        "analysis_ids": args.analysis_ids or [],
        "report_type": args.report_type,
    }
    ctx.budget.reserve_job()
    try:
        acc = await ctx.backend.post(
            "/reports", payload, idempotency_key=ctx.idem("report", payload)
        )
    except ToolFailure:
        ctx.budget.jobs_submitted -= 1
        raise
    if acc.get("job_id"):
        ctx.note_job(acc["job_id"])
    rid = acc.get("report_id")
    if rid:
        ctx.note_created("report", rid, "Report")
    out: dict[str, Any] = {"ok": True, "report_id": rid}
    if acc.get("job_id"):
        job = await ctx.wait_job(acc["job_id"], args.wait_s if args.wait_s is not None else 30)
        out["job"] = job_view(job)
    if rid:
        try:
            rep = await ctx.backend.get(f"/reports/{rid}")
            out["report"] = {
                k: rep.get(k)
                for k in (
                    "report_id",
                    "status",
                    "report_type",
                    "run_ids",
                    "download_url",
                    "created_at",
                )
                if k in rep
            }
        except ToolFailure:
            pass
    return out
