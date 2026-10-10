"""Decision explanations for one run (PRD §7.5, T7.3): why selected, why rejected, why no solution,
and bottlenecks. Everything is derived from validations and the run's own stored selection; any
quantitative opportunity cost or relaxation benefit is deferred to an explicit new solve (why-not /
sensitivity analyses), never estimated here.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from aabflow.domain.schemas import ActionCategory, PlanKind, ScenarioRequest
from aabflow.services.interventions import eligibility
from aabflow.services.runs import LoadedRun, RunContext
from aabflow.services.runs.prepare import prepare
from aabflow.services.science import get_bindings

SATURATION = 0.99


def explain(rc: RunContext, run: LoadedRun) -> dict[str, Any]:
    return _cached(rc, run.run_id, run)


_CACHE: dict[str, dict[str, Any]] = {}


def _cached(rc: RunContext, run_id: str, run: LoadedRun) -> dict[str, Any]:
    hit = _CACHE.get(run_id)
    if hit is None:
        hit = _explain(rc, run)
        if len(_CACHE) > 64:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[run_id] = hit
    return hit


def _explain(rc: RunContext, run: LoadedRun) -> dict[str, Any]:
    res = run.result
    scen = run.json("scenario.json")
    req = ScenarioRequest.model_validate(scen["request"])
    pkg = rc.pilots.package(req.pilot_id, req.pilot_version)
    season = rc.catalog.season(req.season_id)
    planting = (season.planting_date or season.start) if season else None
    out: dict[str, Any] = {
        "run_id": run.run_id,
        "outcome": res.outcome,
        "plan_kind": res.plan_kind.value,
        "proof_scope": "finite_candidate_library",
    }
    if res.outcome != "plan":
        out["why_no_solution"] = _why_no_solution(run, req)
        return out
    sel = run.json("selection.json")
    chosen = set(res.selected_intervention_instance_ids)
    users: dict[str, list[str]] = defaultdict(list)
    for f, v in sel["fields"].items():
        for j in v.get("required_instance_ids") or []:
            users[j].append(f)
    repairs = set(sel.get("repair_instance_ids") or [])
    capital_used = sum(pkg.instances[j].capex_pkr for j in chosen if j in pkg.instances)
    remaining = req.capital_budget_pkr - capital_used
    selected, rejected = [], []
    for j, inst in sorted(pkg.instances.items()):
        on, reasons = eligibility(pkg, inst, req.decision_at, planting)
        base = {
            "instance_id": j,
            "category": inst.category.value,
            "capex_pkr": inst.capex_pkr,
            "seasonal_opex_pkr": inst.seasonal_opex_pkr,
            "commissioned_on": on.isoformat() if on else None,
            "evidence_ids": inst.evidence_ids,
        }
        if j in chosen:
            affected = sorted(users.get(j, []))
            if j in repairs:
                affected = sorted(f for f, v in sel["fields"].items())
                role = (
                    "shared repair: changes routed delivery factors for every downstream candidate; capex "
                    "charged once"
                )
            else:
                role = (
                    f"prerequisite of the selected policy for {', '.join(affected) or 'no field'}"
                )
            selected.append(
                {
                    **base,
                    "why": [
                        "prerequisites met and commissioned before planting"
                        if not reasons
                        else "; ".join(reasons),
                        role,
                        f"capital {inst.capex_pkr:,} PKR within the gross capital budget",
                    ],
                    "affected_field_ids": affected,
                    "marginal_role": {
                        "status": "needs_solve",
                        "how": "POST /analyses/why-not with action=exclude",
                    },
                }
            )
            continue
        why: list[str] = []
        kind = "not_selected"
        if reasons:
            kind, why = "ineligible", reasons
        elif j in req.excluded_instance_ids:
            kind, why = "excluded_by_scenario", ["excluded in this scenario revision"]
        elif (
            req.allowed_intervention_instance_ids is not None
            and j not in req.allowed_intervention_instance_ids
        ):
            kind, why = "not_allowed", ["not in the scenario's allowed interventions"]
        elif res.plan_kind in (PlanKind.B0, PlanKind.B1):
            kind, why = "no_new_capital", [f"{res.plan_kind.value} fixes new capital at zero"]
        elif inst.capex_pkr > req.capital_budget_pkr:
            kind, why = (
                "over_budget",
                [
                    (
                        f"capex {inst.capex_pkr:,} PKR exceeds the whole capital budget "
                        f"{req.capital_budget_pkr:,} PKR"
                    )
                ],
            )
        elif inst.capex_pkr > remaining and inst.category is not ActionCategory.shared_repair:
            why = [
                (
                    f"capex {inst.capex_pkr:,} PKR exceeds the capital left after this plan "
                    f"({remaining:,} PKR); choosing it would displace selected investments"
                )
            ]
        else:
            why = [
                (
                    "eligible and affordable, but the optimizer found a better use of water, money or land in "
                    "this finite model"
                )
            ]
        rejected.append(
            {
                **base,
                "kind": kind,
                "why": why,
                "opportunity_cost": {
                    "status": "needs_solve",
                    "how": "POST /analyses/why-not with action=force",
                },
            }
        )
    out["selected"] = selected
    out["rejected"] = rejected
    out["bottlenecks"] = _bottlenecks(rc, run, req, res, capital_used)
    return out


def _why_no_solution(run: LoadedRun, req: ScenarioRequest) -> dict[str, Any]:
    res = run.result
    diags = getattr(res, "diagnostics", {}) or {}
    groups = diags.get("constraint_groups", [])
    branches = []
    if req.minimum_service_ratio is not None:
        best = (diags.get("max_attainable_service") or {}).get(req.service_group)
        branches.append(
            {
                "change": {"minimum_service_ratio": round(best, 3) if best else None},
                "label": "lower the service floor to the best attainable ratio"
                + (f" ({best:.3f})" if best else ""),
            }
        )
    branches.append(
        {
            "change": {"capital_budget_pkr": req.capital_budget_pkr * 2},
            "label": "double the capital budget",
        }
    )
    branches.append(
        {
            "change": {"operating_budget_pkr": req.operating_budget_pkr * 2},
            "label": "double the operating budget",
        }
    )
    return {
        "solver_status": res.solver_status.value,
        "infeasibility_kind": getattr(res, "infeasibility_kind", None),
        "constraint_groups": groups,
        "configurations": diags.get("configurations", []),
        "empty_fields": diags.get("empty_fields", {}),
        "coverage_note": diags.get("candidate_coverage_note"),
        "statement": "No feasible plan exists in the finite candidate library under these settings. This is not "
        "proof of physical impossibility unless a bound contradiction is shown.",
        "relaxation_branches": branches,
        "relaxation_note": "Each branch is an explicit new revision you can solve; nothing is relaxed silently.",
    }


def _bottlenecks(
    rc: RunContext, run: LoadedRun, req: ScenarioRequest, res, capital_used: int
) -> dict[str, Any]:
    prep = prepare(
        get_bindings(rc.settings),
        rc.pilots.package(req.pilot_id, req.pilot_version),
        rc.catalog,
        req,
        res.plan_kind,
        library_hash=res.candidate_library_hash,
    )
    sel = run.json("selection.json")
    cfg = next(c for c in prep.problem.configs if c.config_id == res.shared_configuration_id)
    opts = {o.policy_id: o for os_ in cfg.options.values() for o in os_}
    ivs = {i.interval_id: i for i in prep.library.intervals}
    resources = []
    for st in prep.problem.states:
        caps = cfg.capacities.get(st, {})
        used: dict = defaultdict(float)
        users: dict = defaultdict(list)
        for f, v in sel["fields"].items():
            o = opts.get(v["candidate_policy_id"])
            if o is None:
                continue
            for k, vol in o.resources.get(st, {}).items():
                used[k] += vol
                users[k].append(f)
        for k, vol in used.items():
            cap = caps.get(k)
            if cap is None or cap <= 0:
                continue
            u = vol / cap
            if u >= SATURATION:
                iv = ivs.get(k[1])
                resources.append(
                    {
                        "state_id": st,
                        "resource_id": k[0],
                        "interval_id": k[1],
                        "period": [iv.start.isoformat(), iv.end.isoformat()] if iv else None,
                        "used_m3": vol,
                        "capacity_m3": cap,
                        "utilization": u,
                        "field_ids": sorted(users[k]),
                    }
                )
    resources.sort(key=lambda r: -r["utilization"])
    opex = next((m.value for m in run.metrics() if m.metric_id == "operating_cost_pkr"), None)
    budgets = [
        {
            "constraint": "capital_budget",
            "used_pkr": capital_used,
            "limit_pkr": req.capital_budget_pkr,
            "utilization": capital_used / req.capital_budget_pkr
            if req.capital_budget_pkr
            else None,
        },
        {
            "constraint": "operating_budget",
            "used_pkr": opex,
            "limit_pkr": req.operating_budget_pkr,
            "utilization": (opex / req.operating_budget_pkr)
            if opex is not None and req.operating_budget_pkr
            else None,
        },
    ]
    for b in budgets:
        b["binding"] = b["utilization"] is not None and b["utilization"] >= SATURATION
    return {
        "saturated_resources": resources[:50],
        "saturated_count": len(resources),
        "budgets": budgets,
        "threshold": SATURATION,
        "note": "A saturated resource or binding budget does not prove that relaxing it raises production; "
        "quantify any improvement with a sensitivity analysis (a new solve).",
    }
