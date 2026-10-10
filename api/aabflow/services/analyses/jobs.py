"""Analysis job handlers (T7.1–T7.4). Each runs in a worker process.

Every child solve goes through ``services.runs.execute`` so points, cells and arms are
ordinary immutable run records (``analysis_id`` set) with their own validation and
metrics. Partial results are saved after every child so ``GET /analyses/{id}`` and
the job event stream show completed points as they arrive (T7.1 "stream completed
point IDs"). Time budgets are global per analysis, not per hidden subsolve.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from itertools import pairwise
from typing import Any

from aabflow.api.errors import DomainError, invalid
from aabflow.domain.schemas import (
    ActionCategory,
    MetricStatus,
    OptimizationMode,
    PlanKind,
    RevisionChange,
)
from aabflow.jobs.cancellation import JobCancelled
from aabflow.services import analyses as A
from aabflow.services.interventions import eligibility
from aabflow.services.metrics import index as metric_index
from aabflow.services.metrics import mv
from aabflow.services.runs import RunContext, SolveOptions, execute, load_run
from aabflow.services.runs.prepare import Prepared, split_state
from aabflow.services.scenarios import child_revision, get_revision

log = logging.getLogger("aabflow.analyses")
STATE_LABELS = {
    "nominal-roster-v1": "nominal roster",
    "shortage-22pct-v1": "22% shortage",
    "interruption-14d-v1": "14-day interruption",
}


@dataclass
class _Env:
    """Light stand-in for ``AppState`` inside a worker (revision validation needs pilots/catalog)."""

    settings: Any
    pilots: Any
    catalog: Any


class Runner:
    def __init__(self, ctx, analysis_id: str):
        self.ctx = ctx
        self.conn = ctx.conn
        self.aid = analysis_id
        self.rc = RunContext.from_settings(ctx.settings)
        self.env = _Env(ctx.settings, self.rc.pilots, self.rc.catalog)
        r = A.row(self.conn, analysis_id)
        self.kind = r["kind"]
        self.request = A.REQUEST_MODELS[self.kind].model_validate_json(r["request"])
        self.result: dict[str, Any] = {
            "kind": self.kind,
            "status": "running",
            "analysis_version": A.ANALYSIS_VERSION,
            "child_run_ids": [],
            "started_at": time.time(),
        }
        self.t0 = time.monotonic()

    # ---- persistence / progress
    def save(self) -> None:
        A.save_result(self.conn, self.aid, self.result)

    def child(self, run_id: str) -> None:
        if run_id not in self.result["child_run_ids"]:
            self.result["child_run_ids"].append(run_id)

    def done(self, n: int, total: int, payload: dict[str, Any]) -> None:
        self.save()
        self.ctx.progress(n / max(1, total), {"completed": n, "total": total})
        self.ctx.event(
            "progress", {"analysis_id": self.aid, "completed": n, "total": total, **payload}
        )

    def finish(self) -> dict[str, Any]:
        self.result["status"] = "cancelled" if self.ctx.cancelled else "completed"
        self.result["wall_ms"] = int((time.monotonic() - self.t0) * 1000)
        self.result.pop("started_at", None)
        self.save()
        return {
            "analysis_id": self.aid,
            "status": self.result["status"],
            "child_run_ids": self.result["child_run_ids"],
        }

    # ---- solving
    def solve(
        self,
        revision_id: str,
        *,
        plan_kind: PlanKind = PlanKind.P,
        time_limit_s: float = 10.0,
        label: str,
        on_prepared=None,
        **opts,
    ) -> str:
        self.ctx.check_cancel()
        so = SolveOptions(
            plan_kind=plan_kind,
            time_limit_s=max(0.2, time_limit_s),
            workers=self.ctx.settings.solver_workers,
            seed=0,
            label=label,
            analysis_id=self.aid,
            job_id=self.ctx.job_id,
            **opts,
        )
        run_id = execute(
            self.rc,
            self.conn,
            revision_id,
            so,
            token=self.ctx.token,
            progress=lambda st: self.ctx.stage(f"{label}: {st}"),
            on_prepared=on_prepared,
        )
        self.child(run_id)
        return run_id

    def remaining(self, total_s: float) -> float:
        return total_s - (time.monotonic() - self.t0)

    def branch(self, parent_id: str, changes: dict[str, Any], origin: str) -> str:
        return child_revision(
            self.conn, self.env, parent_id, RevisionChange.model_validate(changes), origin=origin
        )


def point(conn, run_id: str) -> dict[str, Any]:
    """Comparable summary of one child run, from its stored artifacts only."""
    r = load_run(conn, run_id)
    res = r.result
    out: dict[str, Any] = {
        "run_id": run_id,
        "outcome": res.outcome,
        "solver_status": res.solver_status.value,
        "plan_kind": res.plan_kind.value,
        "scenario_revision_id": res.scenario_revision_id,
        "warnings": res.warnings,
    }
    if res.outcome == "plan":
        m = metric_index(r.metrics())

        def val(mid: str) -> float | None:
            x = m.get((mid, None))
            return x.value if x is not None and x.status is MetricStatus.available else None

        out.update(
            {
                "objective_value": res.objective_value,
                "objective_upper_bound": res.objective_upper_bound
                if res.objective_upper_bound is not None
                else (res.objective_value if res.solver_status.value == "OPTIMAL" else None),
                "relative_gap": res.relative_gap,
                "production_kg": val("production_kg"),
                "capital_commitment_pkr": val("capital_commitment_pkr"),
                "operating_cost_pkr": val("operating_cost_pkr"),
                "pumping_cost_pkr": val("pumping_cost_pkr"),
                "groundwater_m3": val("groundwater_m3"),
                "canal_source_withdrawal_m3": val("canal_source_withdrawal_m3"),
                "min_service_ratio": val("min_service_ratio"),
                "tail_min_service_ratio": val("tail_min_service_ratio"),
                "worst_tested_production_kg": val("worst_tested_production_kg"),
                "quantization_bound": val("objective_quantization_bound_kg") or 0.0,
                "selected_intervention_instance_ids": res.selected_intervention_instance_ids,
                "shared_configuration_id": res.shared_configuration_id,
                "physical_validation": res.physical_validation.status,
            }
        )
    elif res.outcome == "no_plan":
        out.update(
            {
                "objective_value": None,
                "objective_upper_bound": None,
                "infeasibility_kind": res.infeasibility_kind.value
                if res.infeasibility_kind
                else None,
                "diagnostics": res.diagnostics,
            }
        )
    else:
        out.update(
            {
                "objective_value": None,
                "objective_upper_bound": None,
                "physical_validation": res.physical_validation.status,
                "diagnostic_ref": res.diagnostic_ref,
            }
        )
    return out


def _run_view(conn, run_id: str) -> dict[str, Any]:
    r = load_run(conn, run_id)
    return {"run": r.result.model_dump(mode="json")}


# =============================================================================== frontier


def frontier_job(ctx, payload: dict) -> dict:
    R = Runner(ctx, payload["analysis_id"])
    req: A.FrontierRequest = R.request
    base, _ = get_revision(R.conn, req.base_revision_id)
    robust = base.request.optimization_mode is OptimizationMode.worst_case
    R.result.update(
        {
            "base_revision_id": req.base_revision_id,
            "objective": ("worst_case_" if robust else "") + base.request.objective.value,
            "axes": {
                "x": {"metric_id": "capital_commitment_pkr", "unit": "PKR"},
                "y": {
                    "metric_id": "production_kg" if not robust else "worst_tested_production_kg",
                    "unit": "kg",
                },
                "channel": {"metric_id": "min_service_ratio", "unit": "ratio"},
            },
            "points": [],
            "label": "Nondominated among evaluated plans",
            "note": "Each point is an independently solved immutable run over the same finite candidate library. "
            "Observed nondominance is not a proof of a complete Pareto frontier; time-limited points "
            "carry their solver bounds. Lines between points are visual guides only.",
        }
    )
    R.save()
    n = len(req.settings)
    for i, st in enumerate(req.settings):
        pid = f"pt{i + 1:02d}"
        settings = st.model_dump(mode="json")
        pt: dict[str, Any] = {"point_id": pid, "setting": settings}
        try:
            changes = {
                "capital_budget_pkr": st.capital_budget_pkr,
                "minimum_service_ratio": st.minimum_service_ratio,
                "service_group": st.service_group,
            }
            rid = R.branch(req.base_revision_id, changes, origin=f"analysis:{R.aid}")
            left = R.remaining(req.total_budget_s)
            if left <= 0.5:
                pt.update(
                    {
                        "outcome": "not_run",
                        "solver_status": "UNKNOWN",
                        "objective_value": None,
                        "reason": "analysis time budget exhausted before this setting was solved",
                    }
                )
            else:
                limit = min(req.time_limit_per_point_s, left / (n - i))
                run_id = R.solve(
                    rid,
                    plan_kind=PlanKind(req.plan_kind),
                    time_limit_s=limit,
                    label=f"frontier {pid}",
                )
                pt.update(point(R.conn, run_id))
                pt["portfolio_key"] = A.portfolio_key(_run_view(R.conn, run_id))
        except JobCancelled:
            raise
        except DomainError as exc:
            pt.update(
                {
                    "outcome": "rejected",
                    "solver_status": None,
                    "objective_value": None,
                    "reason": exc.detail,
                    "fields": exc.fields,
                }
            )
        R.result["points"].append(pt)
        _frontier_postprocess(R.result)
        R.done(
            i + 1, n, {"point_id": pid, "run_id": pt.get("run_id"), "outcome": pt.get("outcome")}
        )
    return R.finish()


def _frontier_postprocess(res: dict[str, Any]) -> None:
    pts = res["points"]
    A.classify_frontier(pts)
    groups: dict[str, list[str]] = {}
    for p in pts:
        k = p.get("portfolio_key")
        if k:
            groups.setdefault(k, []).append(p["point_id"])
    for p in pts:
        k = p.get("portfolio_key")
        p["same_portfolio_as"] = [x for x in groups.get(k, []) if x != p["point_id"]] if k else []
    res["distinct_portfolios"] = len(groups)
    res["counts"] = {
        "evaluated": len(pts),
        "feasible": sum(1 for p in pts if p.get("outcome") == "plan"),
        "nondominated": sum(1 for p in pts if p.get("dominance") == "nondominated"),
        "dominated": sum(1 for p in pts if p.get("dominance") == "dominated"),
        "dominance_unresolved": sum(1 for p in pts if p.get("dominance") == "dominance_unresolved"),
        "infeasible": sum(1 for p in pts if p.get("solver_status") == "INFEASIBLE"),
        "unknown_or_other": sum(
            1
            for p in pts
            if p.get("outcome") not in ("plan",) and p.get("solver_status") != "INFEASIBLE"
        ),
    }
    res["proof_status"] = (
        "all_points_optimal"
        if pts and all(p.get("solver_status") in ("OPTIMAL", "INFEASIBLE") for p in pts)
        else "some_points_unproven"
    )


# =============================================================================== stress


def _published_states(R: Runner, run) -> list[str]:
    """The tested grid: the revision's uncertainty set, else the season's published set, else library states."""
    meta = run.meta
    cat = R.rc.catalog
    us_id = R.request.uncertainty_set_id or run.json("scenario.json")["request"].get(
        "uncertainty_set_id"
    )
    us = cat.uncertainty_set(us_id) if us_id else None
    if us is not None and (us.pilot_id != meta["pilot_id"] or us.season_id != meta["season_id"]):
        raise invalid(
            "uncertainty set does not belong to the run's pilot/season",
            {"uncertainty_set_id": us_id},
        )
    if us is None:
        sets = cat.uncertainty_sets(meta["pilot_id"], meta["season_id"])
        us = sets[0] if sets else None
    if us is not None:
        return [s.state_id for s in us.states]
    from aabflow.services.runs.prepare import load_library_cached
    from aabflow.services.science import get_bindings

    library, _ = load_library_cached(
        get_bindings(R.rc.settings),
        meta["pilot_id"],
        meta["season_id"],
        run.result.candidate_library_hash,
    )
    return list(library.state_ids)


def stress_job(ctx, payload: dict) -> dict:
    R = Runner(ctx, payload["analysis_id"])
    req: A.StressRequest = R.request
    src = load_run(R.conn, req.run_id)
    res = src.result
    if res.outcome != "plan":
        raise invalid("stress testing needs a run with a validated plan", {"run_id": req.run_id})
    sel = src.json("selection.json")
    fixed_sel = {f: v["candidate_policy_id"] for f, v in sel["fields"].items()}
    instances = set(sel.get("instances") or []) | set(sel.get("repair_instance_ids") or [])
    cfg_id = sel["shared_configuration_id"]
    states = req.state_ids or _published_states(R, src)
    typical = src.meta.get("typical_state")
    src_states = src.meta.get("states") or []
    R.result.update(
        {
            "run_id": req.run_id,
            "mode": req.mode,
            "source_plan_kind": res.plan_kind.value,
            "source_states": src_states,
            "typical_state": typical,
            "cells": [],
            "label": "Fixed-plan delivery test"
            if req.mode == "fixed_plan"
            else "Conditional recovery comparison (investments held fixed, operations re-optimised per state)",
            "note": (
                "Every cell first asks whether this plan's dated receipts, pond operations and pumping can be "
                "delivered in that state. Undeliverable cells carry the violating rule and no achievable yield."
                if req.mode == "fixed_plan"
                else "Recovery runs choose different operations after seeing each whole state; they are scenario-specific "
                "replanning, not one prospective plan."
            ),
            "worst_case_scope": "worst within the tested states only; no probability of success is implied",
        }
    )
    R.save()
    n = len(states)
    for i, sid in enumerate(states):
        w, s = split_state(sid)
        cell: dict[str, Any] = {
            "state_id": sid,
            "weather_scenario_id": w,
            "supply_profile_id": s,
            "supply_label": STATE_LABELS.get(s, s),
        }
        captured: dict[str, Prepared] = {}
        try:
            if req.mode == "fixed_plan":
                run_id = R.solve(
                    res.scenario_revision_id,
                    plan_kind=res.plan_kind,
                    time_limit_s=req.time_limit_per_cell_s,
                    label=f"stress {sid}",
                    states_override=[sid],
                    fixed_selection=fixed_sel,
                    fixed_config_id=cfg_id,
                    on_prepared=lambda p, c=captured: c.setdefault("p", p),
                )
            else:
                run_id = R.solve(
                    res.scenario_revision_id,
                    plan_kind=PlanKind.P,
                    time_limit_s=req.time_limit_per_cell_s,
                    label=f"recovery {sid}",
                    states_override=[sid],
                    fixed_instances=instances,
                    fixed_config_id=cfg_id,
                    on_prepared=lambda p, c=captured: c.setdefault("p", p),
                )
            pt = point(R.conn, run_id)
            cell["run_id"] = run_id
            cell["solver_status"] = pt["solver_status"]
            deliverable = pt["outcome"] == "plan" and pt.get("physical_validation") == "passed"
            cell["deliverable"] = deliverable
            cell["production_kg"] = pt.get("production_kg") if deliverable else None
            cell["objective_upper_bound"] = pt.get("objective_upper_bound") if deliverable else None
            if req.mode == "fixed_plan":
                cell["violations"] = (
                    []
                    if deliverable
                    else _fixed_violations(captured.get("p"), fixed_sel, cfg_id, sid)
                )
            else:
                cell["selected_intervention_instance_ids"] = pt.get(
                    "selected_intervention_instance_ids"
                )
                cell["unused_fixed_investments"] = (
                    sorted(instances - set(pt.get("selected_intervention_instance_ids") or []))
                    if deliverable
                    else None
                )
                if not deliverable:
                    cell["violations"] = [
                        {
                            "rule": "no_recovery_plan",
                            "detail": "; ".join(
                                str(c.get("reason"))
                                for c in (pt.get("diagnostics") or {}).get("configurations", [])
                                if c.get("reason")
                            )
                            or pt["solver_status"],
                        }
                    ]
        except JobCancelled:
            raise
        except DomainError as exc:
            cell.update(
                {
                    "deliverable": False,
                    "production_kg": None,
                    "solver_status": None,
                    "violations": [{"rule": exc.code.value, "detail": exc.detail}],
                }
            )
        R.result["cells"].append(cell)
        _stress_summary(R.result, src)
        R.done(
            i + 1,
            n,
            {"state_id": sid, "run_id": cell.get("run_id"), "deliverable": cell.get("deliverable")},
        )
    if req.reference_run_id:
        _foregone(R, req.reference_run_id, src)
    return R.finish()


def _fixed_violations(
    prep: Prepared | None, sel: dict[str, str], cfg_id: str, sid: str
) -> list[dict[str, Any]]:
    """Name the violating receipt/route/period for an undeliverable fixed-plan cell (PRD §7.3)."""
    if prep is None:
        return [{"rule": "preparation", "detail": "the state could not be prepared"}]
    out: list[dict[str, Any]] = []
    st = prep.states[0].state_id if prep.states else sid
    for f, pid in sorted(sel.items()):
        o = prep.outcomes.get((pid, st))
        if o is None:
            out.append(
                {
                    "rule": "exact_outcome",
                    "field_id": f,
                    "candidate_policy_id": pid,
                    "detail": "no outcome for this policy in the tested state",
                }
            )
        elif not o.deliverable:
            out.append(
                {
                    "rule": "field_delivery",
                    "field_id": f,
                    "candidate_policy_id": pid,
                    "detail": "; ".join(dict.fromkeys(o.violations))
                    or "planned receipts not deliverable",
                    "violations": list(dict.fromkeys(o.violations)),
                }
            )
        elif o.production_kg is None and o.yield_kg_ha is None:
            out.append(
                {
                    "rule": "exact_crop_outcome",
                    "field_id": f,
                    "candidate_policy_id": pid,
                    "detail": "no exact crop outcome for this policy in the tested state",
                }
            )
    cfg = next((c for c in prep.problem.configs if c.config_id == cfg_id), None)
    if cfg is not None:
        caps = cfg.capacities.get(st, {})
        opts = {o.policy_id: o for os_ in cfg.options.values() for o in os_}
        used: dict = {}
        for pid in sel.values():
            o = opts.get(pid)
            if o is None:
                continue
            for k, v in o.resources.get(st, {}).items():
                used[k] = used.get(k, 0.0) + v
        for k, v in sorted(used.items()):
            if k in caps and v > caps[k] + 1e-6 + 1e-9 * abs(caps[k]):
                iv = next((x for x in prep.library.intervals if x.interval_id == k[1]), None)
                out.append(
                    {
                        "rule": "shared_capacity",
                        "resource_id": k[0],
                        "interval_id": k[1],
                        "period": [iv.start.isoformat(), iv.end.isoformat()] if iv else None,
                        "used_m3": v,
                        "capacity_m3": caps[k],
                        "detail": f"{k[0]} needs {v:.1f} m3 but has {caps[k]:.1f} m3 in this interval",
                    }
                )
    if not out:
        out.append(
            {"rule": "finite_model", "detail": "the fixed selection is infeasible in this state"}
        )
    return out


def _stress_summary(res: dict[str, Any], src) -> None:
    cells = res["cells"]
    run_id = src.run_id
    crop = None
    try:
        crop = next((m.crop for m in src.metrics() if m.metric_id == "production_kg"), None)
    except Exception:  # noqa: BLE001
        crop = None
    deliv = [c for c in cells if c.get("deliverable")]
    und = [c["state_id"] for c in cells if not c.get("deliverable")]
    typ = next((c for c in cells if c["state_id"] == res.get("typical_state")), None)
    typ_prod = typ.get("production_kg") if typ and typ.get("deliverable") else None
    metrics: dict[str, Any] = {}
    if und:
        for mid in (
            "worst_tested_production_kg",
            "sdg_13_1_worst_tested_production_kg",
            "sdg_2_4_production_retained_fraction",
        ):
            metrics[mid] = mv(
                mid,
                run_id,
                None,
                status=MetricStatus.blocked,
                reason=f"plan undeliverable in {len(und)} tested state(s): {und}",
            ).model_dump(mode="json")
    elif deliv:
        worst = min(c["production_kg"] for c in deliv)
        metrics["worst_tested_production_kg"] = mv(
            "worst_tested_production_kg", run_id, worst, crop=crop
        ).model_dump(mode="json")
        metrics["sdg_13_1_worst_tested_production_kg"] = mv(
            "sdg_13_1_worst_tested_production_kg", run_id, worst, crop=crop
        ).model_dump(mode="json")
        metrics["sdg_2_4_production_retained_fraction"] = mv(
            "sdg_2_4_production_retained_fraction",
            run_id,
            (worst / typ_prod) if typ_prod else None,
            status=None if typ_prod else MetricStatus.not_applicable,
            reason=None if typ_prod else "typical state not among deliverable tested states",
        ).model_dump(mode="json")
    if res.get("mode") == "recovery_plan":
        metrics = {
            k: {
                **v,
                "reason": "conditional recovery comparison (operations re-optimised per state); "
                + (v.get("reason") or ""),
            }
            for k, v in metrics.items()
        }
    res["metrics_by_id"] = metrics if res.get("mode") == "fixed_plan" else {}
    res["recovery_metrics"] = metrics if res.get("mode") == "recovery_plan" else {}
    res["summary"] = {
        "tested": len(cells),
        "deliverable": len(deliv),
        "undeliverable_state_ids": und,
        "worst_tested_production_kg": metrics.get("worst_tested_production_kg", {}).get("value"),
        "conditional_min_over_deliverable_kg": min(c["production_kg"] for c in deliv)
        if deliv
        else None,
        "conditional_label": "minimum over deliverable cells only; not the plan's worst case"
        if und
        else None,
        "best_tested_production_kg": max(c["production_kg"] for c in deliv) if deliv else None,
        "typical_production_kg": typ_prod,
    }
    weathers = sorted(
        {c["weather_scenario_id"] for c in cells},
        key=lambda w: ("dry", "typical", "wet").index(w) if w in ("dry", "typical", "wet") else 9,
    )
    supplies = list(dict.fromkeys(c["supply_profile_id"] for c in cells))
    res["matrix"] = {
        "rows": weathers,
        "columns": supplies,
        "cells": [
            [
                next(
                    (
                        c["state_id"]
                        for c in cells
                        if c["weather_scenario_id"] == w and c["supply_profile_id"] == s
                    ),
                    None,
                )
                for s in supplies
            ]
            for w in weathers
        ],
    }


def _foregone(R: Runner, ref_id: str, src) -> None:
    """Robust plan vs typical-only plan in the typical state (PRD §7.3)."""
    ref = load_run(R.conn, ref_id)
    typ = R.result.get("typical_state")
    cell = next((c for c in R.result["cells"] if c["state_id"] == typ), None)
    ref_prod = None
    if ref.result.outcome == "plan":
        ref_prod = next(
            (m.value for m in ref.metrics() if m.metric_id == "typical_production_kg"), None
        )
    rob = cell.get("production_kg") if cell else None
    R.result["foregone_typical_output"] = {
        "reference_run_id": ref_id,
        "typical_state": typ,
        "reference_typical_production_kg": ref_prod,
        "this_plan_typical_production_kg": rob,
        "foregone_kg": (ref_prod - rob) if ref_prod is not None and rob is not None else None,
        "note": "output given up in the typical state in exchange for deliverability across all tested states",
    }


# =============================================================================== why-not


def _ensure_base_run(
    R: Runner, revision_id: str, base_run_id: str | None, time_limit_s: float
) -> str:
    if base_run_id:
        r = load_run(R.conn, base_run_id)
        if r.result.scenario_revision_id != revision_id:
            raise invalid(
                "base_run_id belongs to a different scenario revision", {"base_run_id": base_run_id}
            )
        R.child(base_run_id)
        return base_run_id
    existing = R.conn.execute(
        "SELECT run_id FROM runs WHERE scenario_revision_id = ? AND plan_kind IN ('P','R') AND analysis_id IS NULL "
        "AND outcome = 'plan' ORDER BY created_at DESC LIMIT 1",
        (revision_id,),
    ).fetchone()
    if existing is not None:
        R.child(existing["run_id"])
        return existing["run_id"]
    return R.solve(revision_id, time_limit_s=time_limit_s, label="base plan")


def _instance_facts(R: Runner, rev, instance_id: str) -> dict[str, Any]:
    req = rev.request
    pkg = R.rc.pilots.package(req.pilot_id, req.pilot_version)
    inst = pkg.instances.get(instance_id)
    if inst is None:
        return {"instance_id": instance_id, "exists": False}
    season = R.rc.catalog.season(req.season_id)
    planting = (season.planting_date or season.start) if season else None
    on, reasons = eligibility(pkg, inst, req.decision_at, planting)
    lib_reason = None
    users = 0
    try:
        from aabflow.services.runs.prepare import load_library_cached
        from aabflow.services.science import get_bindings

        lib, pols = load_library_cached(
            get_bindings(R.rc.settings), req.pilot_id, req.season_id, rev.candidate_library_hash
        )
        lib_reason = lib.excluded_instances.get(instance_id)
        if inst.category is ActionCategory.shared_repair:
            users = sum(1 for c in lib.configurations if instance_id in c.repair_instance_ids)
        else:
            users = sum(1 for p in pols if instance_id in p.required_instance_ids)
    except Exception:
        log.debug("instance facts unavailable for %s", instance_id, exc_info=True)
    group_peers = sorted(
        j
        for j, i in pkg.instances.items()
        if inst.mutually_exclusive_group
        and i.mutually_exclusive_group == inst.mutually_exclusive_group
        and j != instance_id
    )
    return {
        "instance_id": instance_id,
        "exists": True,
        "category": inst.category.value,
        "capex_pkr": inst.capex_pkr,
        "seasonal_opex_pkr": inst.seasonal_opex_pkr,
        "commissioned_on": on.isoformat() if on else None,
        "eligibility_reasons": reasons,
        "library_excluded_reason": lib_reason,
        "candidate_policies_or_configurations_using_it": users,
        "mutually_exclusive_with": group_peers,
        "capital_budget_pkr": req.capital_budget_pkr,
        "over_capital_budget": inst.capex_pkr > req.capital_budget_pkr,
        "prerequisites": list(inst.prerequisites),
    }


def _explain_infeasible(
    facts: dict[str, Any], req, forced: list[str], pt: dict[str, Any] | None
) -> list[str]:
    out = []
    if not facts.get("exists"):
        return [f"{facts['instance_id']} is not in this pilot version"]
    if facts["eligibility_reasons"]:
        out += [f"ineligible: {r}" for r in facts["eligibility_reasons"]]
    if facts["library_excluded_reason"]:
        out.append(f"the candidate library excludes it: {facts['library_excluded_reason']}")
    if facts["over_capital_budget"]:
        out.append(
            f"its capital cost {facts['capex_pkr']:,} PKR exceeds the capital budget "
            f"{facts['capital_budget_pkr']:,} PKR"
        )
    clash = sorted(set(facts["mutually_exclusive_with"]) & set(forced))
    if clash:
        out.append(f"mutually exclusive with forced {clash}")
    if facts["candidate_policies_or_configurations_using_it"] == 0:
        out.append("no admissible candidate policy uses it in the finite library")
    if pt and pt.get("diagnostics"):
        for c in pt["diagnostics"].get("configurations", []):
            if c.get("reason"):
                out.append(f"{c['shared_configuration_id']}: {c['reason']}")
    if not out:
        out.append(
            "forcing it is incompatible with the scenario's budgets, service floor or shared capacities "
            "within the finite candidate library"
        )
    return out


def why_not_job(ctx, payload: dict) -> dict:
    R = Runner(ctx, payload["analysis_id"])
    req: A.WhyNotRequest = R.request
    rev, _ = get_revision(R.conn, req.base_revision_id)
    j = req.instance_id
    R.result.update(
        {
            "base_revision_id": req.base_revision_id,
            "instance_id": j,
            "action": req.action,
            "objective": rev.request.objective.value,
        }
    )
    facts = _instance_facts(R, rev, j)
    R.result["instance"] = facts
    R.save()
    base_id = _ensure_base_run(R, req.base_revision_id, req.base_run_id, req.time_limit_s)
    base = point(R.conn, base_id)
    R.result["base"] = base
    R.done(1, 2, {"base_run_id": base_id})
    in_base = j in (base.get("selected_intervention_instance_ids") or [])
    if (req.action == "force" and in_base) or (
        req.action == "exclude" and not in_base and base["outcome"] == "plan"
    ):
        R.result.update(
            {
                "alternative": None,
                "difference": {"status": "no_change", "lower": 0.0, "upper": 0.0, "point": 0.0},
                "explanation": [
                    (
                        f"{j} is already {'in' if in_base else 'absent from'} the base plan; "
                        f"{req.action} leaves the plan unchanged"
                    )
                ],
            }
        )
        R.done(2, 2, {})
        return R.finish()
    forced = [x for x in rev.request.forced_instance_ids if x != j]
    excluded = [x for x in rev.request.excluded_instance_ids if x != j]
    if req.action == "force":
        changes = {"forced_instance_ids": forced + [j], "excluded_instance_ids": excluded}
    else:
        changes = {"excluded_instance_ids": excluded + [j], "forced_instance_ids": forced}
    try:
        rid = R.branch(req.base_revision_id, changes, origin=f"analysis:{R.aid}")
    except DomainError as exc:
        R.result.update(
            {
                "alternative": {"outcome": "rejected", "reason": exc.detail, "fields": exc.fields},
                "difference": {
                    "status": "not_comparable",
                    "lower": None,
                    "upper": None,
                    "point": None,
                    "reason": "the forced alternative fails scenario validation",
                },
                "explanation": _explain_infeasible(facts, rev.request, forced, None),
            }
        )
        R.done(2, 2, {})
        return R.finish()
    alt_id = R.solve(rid, time_limit_s=req.time_limit_s, label=f"{req.action} {j}")
    alt = point(R.conn, alt_id)
    R.result["alternative"] = alt
    R.result["alternative_revision_id"] = rid
    diff = A.difference_interval(base, alt)
    R.result["difference"] = {
        **diff,
        "definition": "alternative objective - base objective (same metric "
        "definitions, same finite candidate library)",
    }
    if alt["outcome"] != "plan":
        R.result["explanation"] = _explain_infeasible(facts, rev.request, forced, alt)
        R.result["difference"]["reason"] = (
            "the alternative has no feasible plan; no foregone value is invented"
        )
    else:
        from aabflow.services.insights import certificate, deltas

        a, b = load_run(R.conn, base_id), load_run(R.conn, alt_id)
        cert = certificate([a, b])
        R.result["certificate"] = cert
        R.result["deltas"] = [
            d
            for d in deltas(a, b, label_non_causal=not cert["compatible"])
            if d["field_id"] is None
        ]
        lo, hi = diff.get("lower"), diff.get("upper")
        if req.action == "force":
            txt = (
                f"forcing {j} changes the objective by {lo:,.1f} to {hi:,.1f}"
                if diff["status"] == "interval"
                else f"forcing {j} changes the objective by {diff['point']:,.1f}"
            )
        else:
            txt = (
                f"excluding {j} changes the objective by {lo:,.1f} to {hi:,.1f}"
                if diff["status"] == "interval"
                else f"excluding {j} changes the objective by {diff['point']:,.1f}"
            )
        R.result["explanation"] = [txt]
    R.done(2, 2, {"alternative_run_id": alt_id})
    return R.finish()


# =============================================================================== sensitivity


def _nominal_supply_m3(R: Runner, rev) -> float | None:
    req = rev.request
    pkg = R.rc.pilots.package(req.pilot_id, req.pilot_version)
    total = 0.0
    for w in pkg.roster.get(req.season_id, []):
        if w.volume_cap_m3 is not None:
            total += float(w.volume_cap_m3)
        elif w.rate_m3_s is not None:
            total += float(w.rate_m3_s) * (w.end - w.start) / timedelta(seconds=1)
    return total or None


def sensitivity_job(ctx, payload: dict) -> dict:
    R = Runner(ctx, payload["analysis_id"])
    req: A.SensitivityRequest = R.request
    rev, _ = get_revision(R.conn, req.base_revision_id)
    base_val = getattr(rev.request, req.parameter)
    values = sorted(req.values)
    nominal = _nominal_supply_m3(R, rev) if req.parameter == "uniform_reduction_fraction" else None
    R.result.update(
        {
            "base_revision_id": req.base_revision_id,
            "parameter": req.parameter,
            "base_value": base_val,
            "values": values,
            "points": [],
            "label": "finite-difference sensitivity (child scenarios re-solved; not a derivative)",
            "nominal_roster_volume_m3": nominal,
            "objective_unit": "PKR" if rev.request.objective.value.endswith("_pkr") else "kg",
        }
    )
    R.save()
    n = len(values)
    for i, v in enumerate(values):
        changes: dict[str, Any] = {}
        if req.parameter in ("capital_budget_pkr", "operating_budget_pkr"):
            changes[req.parameter] = round(v)
        elif req.parameter == "uniform_reduction_fraction":
            changes[req.parameter] = float(v)
        else:
            changes["minimum_service_ratio"] = float(v)
            changes["service_group"] = req.service_group or rev.request.service_group or "all"
        pt: dict[str, Any] = {"value": v}
        try:
            rid = R.branch(req.base_revision_id, changes, origin=f"analysis:{R.aid}")
            run_id = R.solve(
                rid, time_limit_s=req.time_limit_per_point_s, label=f"{req.parameter}={v:g}"
            )
            pt.update(point(R.conn, run_id))
            pt["portfolio_key"] = A.portfolio_key(_run_view(R.conn, run_id))
        except JobCancelled:
            raise
        except DomainError as exc:
            pt.update(
                {
                    "outcome": "rejected",
                    "objective_value": None,
                    "reason": exc.detail,
                    "fields": exc.fields,
                }
            )
        R.result["points"].append(pt)
        _sensitivity_steps(R.result, nominal)
        R.done(i + 1, n, {"value": v, "run_id": pt.get("run_id")})
    return R.finish()


def _sensitivity_steps(res: dict[str, Any], nominal: float | None) -> None:
    pts = res["points"]
    steps = []
    for a, b in pairwise(pts):
        d = A.difference_interval(a, b)
        step = {"from_value": a["value"], "to_value": b["value"], "objective_difference": d}
        dv = b["value"] - a["value"]
        if res["parameter"] == "uniform_reduction_fraction" and nominal:
            dvol = -dv * nominal  # more reduction = less available water
            step["delta_available_m3"] = dvol
            if d["status"] != "not_comparable" and abs(dvol) > 0:
                step["marginal_value_per_m3"] = {
                    "lower": min(d["lower"] / dvol, d["upper"] / dvol),
                    "upper": max(d["lower"] / dvol, d["upper"] / dvol),
                    "unit": f"{res.get('objective_unit', 'objective units')} per m3 of available roster volume",
                    "label": f"finite difference over a {abs(dvol):,.0f} m3 step",
                }
        elif (
            res["parameter"] in ("capital_budget_pkr", "operating_budget_pkr")
            and dv
            and d["status"] != "not_comparable"
        ):
            step["marginal_value_per_pkr"] = {
                "lower": min(d["lower"] / dv, d["upper"] / dv),
                "upper": max(d["lower"] / dv, d["upper"] / dv),
            }
        if a.get("portfolio_key") and b.get("portfolio_key"):
            step["decision_changes"] = a["portfolio_key"] != b["portfolio_key"]
            if step["decision_changes"]:
                sa = set(a.get("selected_intervention_instance_ids") or [])
                sb = set(b.get("selected_intervention_instance_ids") or [])
                step["instances_added"] = sorted(sb - sa)
                step["instances_removed"] = sorted(sa - sb)
        steps.append(step)
    res["steps"] = steps
    changes = [s for s in steps if s.get("decision_changes")]
    res["decision_stable"] = not changes
    res["resolving_measurement"] = (
        None
        if not changes
        else f"the selected portfolio changes within the tested range of {res['parameter']} "
        f"(between {changes[0]['from_value']:g} and {changes[0]['to_value']:g}); a firmer quote or measurement of "
        f"{res['parameter']} in that interval would resolve the decision"
    )
    res["note"] = (
        "Selection frequency across these runs is not a probability. A coarse candidate library can "
        "leave small steps without effect; step size and coverage are shown with each step."
    )


# =============================================================================== synergy


def synergy_job(ctx, payload: dict) -> dict:
    R = Runner(ctx, payload["analysis_id"])
    req: A.SynergyRequest = R.request
    rev, _ = get_revision(R.conn, req.base_revision_id)
    a, b = req.instance_a, req.instance_b
    R.result.update(
        {
            "base_revision_id": req.base_revision_id,
            "instance_a": a,
            "instance_b": b,
            "other_actions": req.other_actions,
            "arms": {},
            "formula": "outcome(A+B) - outcome(A) - outcome(B) + outcome(none)",
            "objective": rev.request.objective.value,
        }
    )
    facts = {x: _instance_facts(R, rev, x) for x in (a, b)}
    R.result["instances"] = facts
    R.save()
    forced0 = [x for x in rev.request.forced_instance_ids if x not in (a, b)]
    excluded0 = [x for x in rev.request.excluded_instance_ids if x not in (a, b)]
    others: list[str] = []
    total = 4
    if req.other_actions == "fixed":
        base_id = _ensure_base_run(
            R, req.base_revision_id, req.base_run_id, req.time_limit_per_arm_s
        )
        bp = point(R.conn, base_id)
        R.result["base_run_id"] = base_id
        if bp["outcome"] != "plan":
            R.result["synergy"] = {
                "status": "not_available",
                "value": None,
                "lower": None,
                "upper": None,
                "reason": "base plan is infeasible, so there are no 'other investments' to hold",
            }
            return R.finish()
        others = sorted(set(bp.get("selected_intervention_instance_ids") or []) - {a, b})
        R.result["held_fixed_instance_ids"] = others
    arms_spec = {
        "none": ([], [a, b]),
        "a": ([a], [b]),
        "b": ([b], [a]),
        "ab": ([a, b], []),
    }
    for i, (arm, (inc, exc)) in enumerate(arms_spec.items()):
        changes: dict[str, Any] = {
            "forced_instance_ids": sorted(set(forced0 + inc + others)),
            "excluded_instance_ids": sorted(set(excluded0 + exc)),
        }
        if req.other_actions == "fixed":
            changes["allowed_intervention_instance_ids"] = sorted(set(others + inc))
        entry: dict[str, Any] = {"arm": arm, "includes": inc, "excludes": exc}
        try:
            rid = R.branch(req.base_revision_id, changes, origin=f"analysis:{R.aid}")
            run_id = R.solve(rid, time_limit_s=req.time_limit_per_arm_s, label=f"synergy {arm}")
            entry.update(point(R.conn, run_id))
            entry["scenario_revision_id"] = rid
        except JobCancelled:
            raise
        except DomainError as exc:
            entry.update(
                {
                    "outcome": "rejected",
                    "objective_value": None,
                    "reason": exc.detail,
                    "fields": exc.fields,
                }
            )
        R.result["arms"][arm] = entry
        R.done(
            i + 1,
            total,
            {"arm": arm, "run_id": entry.get("run_id"), "outcome": entry.get("outcome")},
        )
    syn = A.synergy(R.result["arms"])
    runs = [R.result["arms"][k].get("run_id") for k in ("none", "a", "b", "ab")]
    if all(runs) and all(
        R.result["arms"][k].get("outcome") == "plan" for k in ("none", "a", "b", "ab")
    ):
        from aabflow.services.insights import certificate

        cert = certificate([load_run(R.conn, x) for x in runs])
        R.result["certificate"] = cert
        if not cert["compatible"]:
            syn = {
                **syn,
                "status": "not_matched",
                "value": None,
                "reason": "the four runs do not share conditions; synergy would not be causal",
            }
    else:
        bad = [k for k in ("none", "a", "b", "ab") if R.result["arms"][k].get("outcome") != "plan"]
        syn["explanations"] = {
            k: _explain_infeasible(
                facts.get(a if k == "a" else b, facts[a]), rev.request, forced0, R.result["arms"][k]
            )
            if k in ("a", "b")
            else [R.result["arms"][k].get("reason") or R.result["arms"][k].get("solver_status")]
            for k in bad
        }
    R.result["synergy"] = syn
    R.save()
    return R.finish()
