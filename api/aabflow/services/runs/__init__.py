"""Run execution, original-precision reconstruction and immutable bundles (T6.6, T9.5).

A solver incumbent is provisional until the selected policies are resolved from
the library, the full ledger is reconstructed by the science stream at original
precision, shared/field/budget/service constraints are re-verified with floats,
and metrics are recomputed from exact outcomes. Artifacts are written to a
temporary directory, hashed, atomically renamed, and only then referenced from
SQLite. Validation failure produces an ``InvalidPlanRun`` (INVALID_PLAN) with a
diagnostic artifact and no recommendation.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import TypeAdapter

from aabflow.api.errors import DomainError, not_found
from aabflow.config import Settings
from aabflow.domain.calendar import local_crop_date
from aabflow.domain.hashes import content_hash, file_sha256
from aabflow.domain.ids import new_id
from aabflow.domain.schemas import (
    ErrorCode,
    InfeasibilityKind,
    InvalidPlanRun,
    LedgerEvent,
    MetricValue,
    NoPlanRun,
    PhysicalValidationReport,
    PlanKind,
    PlanRun,
    RuleResidual,
    RunResult,
    SolverStatus,
)
from aabflow.domain.schemas.run import ConfigurationStatus
from aabflow.jobs.cancellation import NEVER, CancelToken
from aabflow.optimizer.configurations import SolveOutcome, describe, solve_problem
from aabflow.repositories.sqlite import connect, dumps, loads, tx, utcnow
from aabflow.services.catalog import Catalog
from aabflow.services.metrics import METRICS_VERSION, FieldFacts, PlanFacts, compute_plan_metrics
from aabflow.services.pilots import PilotPackage, PilotRepository
from aabflow.services.runs.prepare import Prepared, prepare
from aabflow.services.scenarios import get_revision
from aabflow.services.science import get_bindings

RUN_ADAPTER = TypeAdapter(RunResult)
ABS_TOL = 1e-6
REL_TOL = 1e-9
ARTIFACTS = (
    "run.json",
    "scenario.json",
    "selection.json",
    "solver.json",
    "ledger.parquet",
    "timeline.parquet",
    "metrics.json",
    "validation.json",
    "coverage.json",
)


def _tol(mag: float) -> float:
    return ABS_TOL + REL_TOL * abs(mag)


@dataclass
class RunContext:
    settings: Settings
    pilots: PilotRepository
    catalog: Catalog

    @classmethod
    def from_settings(cls, settings: Settings) -> RunContext:
        return cls(settings, PilotRepository(settings.pilots_dir), Catalog(settings.libraries_dir))


@dataclass
class SolveOptions:
    plan_kind: PlanKind = PlanKind.P
    time_limit_s: float = 10.0
    workers: int = 2
    seed: int = 0
    states_override: list[str] | None = None
    fixed_selection: dict[str, str] | None = None
    fixed_instances: set[str] | None = None
    fixed_config_id: str | None = None
    label: str | None = None
    analysis_id: str | None = None
    job_id: str | None = None
    extra_warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------ execution


def execute(
    rc: RunContext,
    conn: sqlite3.Connection,
    revision_id: str,
    opts: SolveOptions,
    token: CancelToken = NEVER,
    progress=None,
    on_prepared=None,
) -> str:
    """Prepare, solve, reconstruct, validate and persist one run; returns run_id.

    ``on_prepared(prep)`` lets analysis services read the prepared candidate outcomes (for example the
    violations that make a fixed plan undeliverable in a stress state) without preparing twice.
    """
    rev, deps = get_revision(conn, revision_id)
    req = rev.request
    pkg = rc.pilots.package(req.pilot_id, req.pilot_version)
    if deps.get("pilot_package_sha256") != pkg.package_hash:
        raise DomainError(
            ErrorCode.VERSION_CONFLICT,
            "pilot package changed since this revision was created",
            extra={
                "dependency_diff": {
                    "revision": deps.get("pilot_package_sha256"),
                    "current": pkg.package_hash,
                }
            },
        )
    lib_hash = rev.candidate_library_hash
    if lib_hash is None:
        lib_hash = rc.catalog.latest_library_hash(req.pilot_id, req.season_id)
        if lib_hash is None:
            raise DomainError(
                ErrorCode.ASSET_UNAVAILABLE, "no published candidate library for this pilot/season"
            )
    bindings = get_bindings(rc.settings)
    hint = _b1_hint(conn, revision_id) if opts.plan_kind is PlanKind.P else None
    _p(progress, "preparing candidates")
    prep = prepare(
        bindings,
        pkg,
        rc.catalog,
        req,
        opts.plan_kind,
        library_hash=lib_hash,
        states_override=opts.states_override,
        fixed_selection=opts.fixed_selection,
        fixed_instances=opts.fixed_instances,
        fixed_config_id=opts.fixed_config_id,
        hint=hint,
    )
    if on_prepared is not None:
        on_prepared(prep)
    token.check()
    _p(progress, "solving")
    outcome = solve_problem(
        prep.problem,
        time_limit_s=opts.time_limit_s,
        workers=opts.workers,
        seed=opts.seed,
        token=token,
    )
    token.check()
    _p(progress, "reconstructing")
    run_id = new_id("run")
    result, artifacts = complete(rc, run_id, rev, deps, prep, outcome, opts, bindings, pkg)
    token.check()
    _p(progress, "writing artifacts")
    persist(rc.settings, conn, run_id, result, artifacts, opts)
    return run_id


def _p(progress, stage: str) -> None:
    if progress is not None:
        progress(stage)


def _b1_hint(conn: sqlite3.Connection, revision_id: str) -> dict[str, str] | None:
    row = conn.execute(
        "SELECT run_dir FROM runs WHERE scenario_revision_id = ? AND plan_kind = 'B1' AND outcome = 'plan' "
        "ORDER BY created_at DESC LIMIT 1",
        (revision_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        sel = json.loads((Path(row["run_dir"]) / "selection.json").read_text())
        return {f: v["candidate_policy_id"] for f, v in sel["fields"].items()}
    except (OSError, KeyError, ValueError):
        return None


def _config_statuses(outcome: SolveOutcome) -> list[ConfigurationStatus]:
    return [
        ConfigurationStatus(
            shared_configuration_id=r.config_id,
            status=r.status,
            objective_value=float(r.primary) if r.primary is not None else None,
            upper_bound=float(r.primary_bound) if r.primary_bound is not None else None,
            wall_ms=r.wall_ms,
        )
        for r in outcome.configs
    ]


def _infeasibility_kind(prep: Prepared, outcome: SolveOutcome) -> InfeasibilityKind:
    reasons = " ".join(r.reason or "" for r in outcome.configs)
    if "no candidate policies in the library" in reasons:
        return InfeasibilityKind.missing_input
    if "service floor" in reasons:
        return InfeasibilityKind.finite_candidate_incompatibility
    if any(c.empty_fields for c in prep.problem.configs) and all(
        r.reason and "no admissible candidate" in r.reason
        for r in outcome.configs
        if r.status is SolverStatus.INFEASIBLE
    ):
        return InfeasibilityKind.empty_option_set
    return InfeasibilityKind.finite_candidate_incompatibility


def _objective_kg(prep: Prepared, value_int: int | None) -> float | None:
    if value_int is None:
        return None
    if prep.problem.objective == "irrigation_contribution_pkr":
        return float(value_int)
    return value_int * prep.problem.production_quantum_kg


def complete(
    rc: RunContext,
    run_id: str,
    rev,
    deps: dict,
    prep: Prepared,
    outcome: SolveOutcome,
    opts: SolveOptions,
    bindings,
    pkg: PilotPackage,
) -> tuple[Any, dict[str, Any]]:
    req = prep.request
    now = datetime.now(UTC)
    warnings = list(prep.warnings) + list(outcome.notes) + list(opts.extra_warnings)
    if opts.plan_kind is PlanKind.B0:
        warnings.append("B0 fixed-roster policy: executed operating habit, not an optimized plan")
    base = {
        "run_id": run_id,
        "scenario_revision_id": rev.scenario_revision_id,
        "scenario_hash": rev.semantic_hash,
        "candidate_library_hash": prep.library.candidate_library_hash,
        "plan_kind": opts.plan_kind,
        "primary_objective": "worst_case_" + req.objective.value
        if len(prep.problem.objective_states) > 1
        else req.objective.value,
        "solve_wall_ms": outcome.wall_ms,
        "configurations": _config_statuses(outcome),
        "candidate_coverage_ref": "coverage.json",
        "warnings": warnings,
        "created_at": now,
    }
    common = {
        "scenario": {
            "request": req.model_dump(mode="json"),
            "dependencies": deps,
            "revision": rev.model_dump(mode="json"),
        },
        "solver": {
            **describe(outcome),
            "settings": {
                "time_limit_s": opts.time_limit_s,
                "workers": opts.workers,
                "seed": opts.seed,
                "water_quantum_m3": prep.problem.water_quantum_m3,
                "production_quantum_kg": prep.problem.production_quantum_kg,
            },
            "states": [s.state_id for s in prep.states],
            "objective_states": prep.problem.objective_states,
            "typical_state": prep.typical_state.state_id,
            "hint_used": prep.problem.hint is not None,
        },
        "coverage": prep.coverage,
    }
    if outcome.best is None:
        diags = {
            "configurations": [
                {
                    "shared_configuration_id": r.config_id,
                    "status": r.status.value,
                    "reason": r.reason,
                }
                for r in outcome.configs
            ],
            "empty_fields": {
                c.config_id: c.empty_fields for c in prep.problem.configs if c.empty_fields
            },
            "max_attainable_service": prep.max_attainable_service,
            "constraint_groups": _constraint_groups(prep),
            "candidate_coverage_note": prep.coverage["note"],
            "cancelled": outcome.cancelled,
        }
        status = outcome.status
        if status is SolverStatus.OPTIMAL or status is SolverStatus.FEASIBLE:
            status = SolverStatus.UNKNOWN
        result = NoPlanRun(
            **base,
            solver_status=status,
            infeasibility_kind=_infeasibility_kind(prep, outcome)
            if status is SolverStatus.INFEASIBLE
            else None,
            diagnostics=diags,
        )
        return result, {
            **common,
            "selection": None,
            "ledger": [],
            "metrics": [],
            "timeline": [],
            "validation": {"status": "not_run", "reason": "no incumbent plan"},
            "meta": _meta(prep),
        }

    best = outcome.best
    cfg_id = best.config_id
    if opts.plan_kind is PlanKind.B1:
        from aabflow.services.runs.prepare import _baseline_selection

        b0 = _baseline_selection(prep.problem.configs)
        if b0 and all(best.selection.get(f) == b0.get(f) for f in prep.problem.fields):
            base["warnings"].append(
                "B1 selects the same policy as B0 for every field: re-operating existing assets adds nothing "
                "under these conditions, so the value-of-investment comparison collapses (T6.5)"
            )
    sel_ids = [best.selection[f] for f in sorted(best.selection)]
    # ---- original-precision reconstruction per evaluated state
    ledgers: dict[str, list[LedgerEvent]] = {}
    residuals: list[RuleResidual] = []
    status_ok = True
    for st in prep.states:
        try:
            events, report = bindings.reconstruct(
                sel_ids,
                prep.library,
                st.base_state,
                cfg_id,
                resolved_supply=st.resolved_supply,
                extra_closures=st.extra_closures,
                policies=prep.policies,
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001 - a reconstruction crash invalidates the plan
            events, report = (
                [],
                PhysicalValidationReport(
                    status="failed",
                    residuals=[
                        RuleResidual(
                            rule="reconstruction",
                            passed=False,
                            detail=f"{type(exc).__name__}: {exc}",
                        )
                    ],
                ),
            )
        ledgers[st.state_id] = events
        for r in report.residuals:
            residuals.append(
                r.model_copy(update={"detail": f"[{st.state_id}] {r.detail or ''}".strip()})
            )
        status_ok &= report.status == "passed"
    own = verify_selection(prep, best, cfg_id)
    residuals.extend(own)
    status_ok &= all(r.passed for r in own)
    validation = PhysicalValidationReport(
        status="passed" if status_ok else "failed", residuals=residuals
    )
    selection = _selection_doc(prep, best, cfg_id)
    if not status_ok:
        result = InvalidPlanRun(
            **base,
            solver_status=outcome.status,
            physical_validation=validation,
            diagnostic_ref="validation.json",
        )
        return result, {
            **common,
            "selection": selection,
            "ledger": _ledger_rows(ledgers),
            "metrics": [],
            "timeline": [],
            "validation": validation.model_dump(mode="json"),
            "meta": _meta(prep),
        }
    metrics = plan_metrics(run_id, prep, best, cfg_id, ledgers, pkg, rc.catalog)
    obj = _objective_value(prep, best, metrics)
    ub = _objective_kg(prep, outcome.upper_bound)
    if ub is not None and prep.problem.objective == "production_kg":
        ub += (
            len(prep.problem.fields) * prep.problem.production_quantum_kg
        )  # floor-quantization margin
    gap = None
    if outcome.upper_bound is not None and best.primary is not None:
        gap = max(0.0, (outcome.upper_bound - best.primary) / max(1, abs(outcome.upper_bound)))
    compat = compatibility_key(prep)
    status = outcome.status
    if opts.plan_kind is PlanKind.B0:
        status = SolverStatus.FEASIBLE
    result = PlanRun(
        **base,
        solver_status=status,
        objective_value=obj,
        objective_upper_bound=None if opts.plan_kind is PlanKind.B0 else ub,
        relative_gap=None if opts.plan_kind is PlanKind.B0 else gap,
        selected_candidate_policy_ids=sel_ids,
        selected_intervention_instance_ids=sorted(
            set(best.instances) | set(prep.library_config(cfg_id))
        ),
        shared_configuration_id=cfg_id,
        metric_refs=[f"{m.metric_id}{'@' + m.field_id if m.field_id else ''}" for m in metrics],
        physical_validation=validation,
        trajectory_bundle_ref="timeline.parquet",
        comparison_compatibility_key=compat,
    )
    timeline = build_timeline(
        prep, best, ledgers.get(prep.typical_state.state_id, []), bindings, pkg
    )
    return result, {
        **common,
        "selection": selection,
        "ledger": _ledger_rows(ledgers),
        "metrics": [m.model_dump(mode="json") for m in metrics],
        "timeline": timeline,
        "validation": validation.model_dump(mode="json"),
        "meta": _meta(prep),
    }


def _meta(prep: Prepared) -> dict[str, Any]:
    req = prep.request
    return {
        "pilot_id": req.pilot_id,
        "pilot_version": req.pilot_version,
        "season_id": req.season_id,
        "planning_mode": req.planning_mode.value,
        "states": [s.state_id for s in prep.states],
        "typical_state": prep.typical_state.state_id,
        "metrics_version": METRICS_VERSION,
        "compatibility": compatibility_doc(prep),
    }


def compatibility_doc(prep: Prepared) -> dict[str, Any]:
    req = prep.request
    return {
        "pilot_id": req.pilot_id,
        "pilot_version": req.pilot_version,
        "season_id": req.season_id,
        "states": sorted(s.state_id for s in prep.states),
        "typical_state": prep.typical_state.state_id,
        "uniform_reduction_fraction": req.uniform_reduction_fraction,
        "blocked_edge_ids": sorted(req.blocked_edge_ids),
        "metrics_version": METRICS_VERSION,
        "initial_state": "library-declared initial soil and pond state",
    }


def compatibility_key(prep: Prepared) -> str:
    return content_hash(compatibility_doc(prep))


def _constraint_groups(prep: Prepared) -> list[dict[str, Any]]:
    req = prep.request
    out = [
        {"group": "capital_budget", "value": req.capital_budget_pkr, "unit": "PKR"},
        {"group": "operating_budget", "value": req.operating_budget_pkr, "unit": "PKR"},
    ]
    if req.minimum_service_ratio is not None:
        out.append(
            {
                "group": "service_floor",
                "value": req.minimum_service_ratio,
                "service_group": req.service_group,
                "max_attainable": prep.max_attainable_service.get(req.service_group),
            }
        )
    out.append({"group": "shared_resources", "states": [s.state_id for s in prep.states]})
    return out


def _selection_doc(prep: Prepared, best, cfg_id: str) -> dict[str, Any]:
    fields = {}
    for f, pid in sorted(best.selection.items()):
        p = prep.policies[pid]
        fields[f] = {
            "candidate_policy_id": pid,
            "candidate_policy_hash": p.candidate_policy_hash,
            "family": p.family,
            "coverage_tags": p.coverage_tags,
            "required_instance_ids": p.required_instance_ids,
            "uses_asset_ids": p.uses_asset_ids,
            "cropped_area_ha": p.cropped_area_ha,
            "application_efficiency": p.application_efficiency,
            "seasonal_opex_pkr": p.seasonal_opex_pkr,
            "receipt_volume_m3": p.receipt_volume_m3,
            "pump_volume_m3": p.pump_volume_m3,
            "gross_application_mm": p.gross_application_mm,
            "application_schedule": [e.model_dump(mode="json") for e in p.application_schedule],
            "outcomes": {
                s.state_id: prep.outcomes[(pid, s.state_id)].model_dump(mode="json")
                for s in prep.states
                if (pid, s.state_id) in prep.outcomes
            },
        }
    return {
        "shared_configuration_id": cfg_id,
        "instances": best.instances,
        "repair_instance_ids": prep.library_config(cfg_id),
        "fields": fields,
    }


def verify_selection(prep: Prepared, best, cfg_id: str) -> list[RuleResidual]:
    """Independent float re-check of the selection (T6.6 step 3)."""
    p = prep.problem
    out: list[RuleResidual] = []
    cfg = next(c for c in p.configs if c.config_id == cfg_id)
    opts = {o.policy_id: o for os_ in cfg.options.values() for o in os_}
    missing = [f for f in p.fields if f not in best.selection]
    out.append(
        RuleResidual(
            rule="one_policy_per_field",
            passed=not missing,
            entity_ids=missing,
            detail="every field has exactly one selected policy"
            if not missing
            else "fields without a policy",
        )
    )
    chosen = [opts[pid] for pid in best.selection.values() if pid in opts]
    insts = sorted({j for o in chosen for j in o.required_instance_ids})
    unused = sorted(set(best.instances) - set(insts))
    out.append(
        RuleResidual(
            rule="instances_required_and_used",
            passed=not unused and set(insts) <= set(best.instances),
            entity_ids=unused,
            detail="purchased instances match policy prerequisites",
        )
    )
    groups: dict[str, list[str]] = defaultdict(list)
    for j in insts:
        g = p.instances[j].exclusive_group if j in p.instances else None
        if g:
            groups[g].append(j)
    clash = [g for g, js in groups.items() if len(js) > 1]
    out.append(
        RuleResidual(rule="mutually_exclusive_instances", passed=not clash, entity_ids=clash)
    )
    capex = cfg.capex_pkr + sum(p.instances[j].capex_pkr for j in insts if j in p.instances)
    opex = (
        cfg.opex_pkr
        + sum(o.opex_pkr for o in chosen)
        + sum(p.instances[j].opex_pkr for j in insts if j in p.instances)
    )
    if p.apply_budgets and p.capital_budget_pkr is not None:
        out.append(
            RuleResidual(
                rule="capital_budget",
                passed=capex <= p.capital_budget_pkr,
                unit="PKR",
                max_violation=float(max(0, capex - p.capital_budget_pkr)),
                detail=f"gross capital {capex} PKR (shared repairs charged once) <= {p.capital_budget_pkr}",
            )
        )
    if p.apply_budgets and p.operating_budget_pkr is not None:
        out.append(
            RuleResidual(
                rule="operating_budget",
                passed=opex <= p.operating_budget_pkr,
                unit="PKR",
                max_violation=float(max(0, opex - p.operating_budget_pkr)),
                detail=f"seasonal operating {opex} PKR (incl. pumping) <= {p.operating_budget_pkr}",
            )
        )
    for s in p.states:
        caps = cfg.capacities.get(s, {})
        used: dict = defaultdict(float)
        for o in chosen:
            for k, v in o.resources.get(s, {}).items():
                used[k] += v
        worst = 0.0
        bad = []
        for k, v in used.items():
            if k in caps and v > caps[k] + _tol(caps[k]):
                worst = max(worst, v - caps[k])
                bad.append(f"{k[0]}@{k[1]}")
        out.append(
            RuleResidual(
                rule="shared_capacity",
                passed=not bad,
                max_violation=worst,
                entity_ids=bad[:20],
                detail=f"[{s}] summed selected use within shared capacities at original precision",
            )
        )
        for o in chosen:
            if o.production_kg.get(s) is None:
                out.append(
                    RuleResidual(
                        rule="exact_crop_outcome",
                        passed=False,
                        entity_ids=[o.policy_id],
                        detail=f"[{s}] no exact outcome",
                    )
                )
    req = prep.request
    if req.minimum_service_ratio is not None and p.fixed_selection is None:
        bad = []
        grp = req.service_group
        for f in [f for f in p.fields if grp == "all" or prep.field_groups.get(f) == grp]:
            ref = prep.reference_m3.get(f, 0)
            pid = best.selection.get(f)
            if not ref or pid not in opts:
                continue
            for s in p.states:
                if (
                    opts[pid].service_credit_m3.get(s, 0.0) + _tol(ref)
                    < req.minimum_service_ratio * ref
                ):
                    bad.append(f)
        out.append(
            RuleResidual(
                rule="service_floor",
                passed=not bad,
                entity_ids=sorted(set(bad)),
                unit="ratio",
                detail=f"receipt / reference >= {req.minimum_service_ratio} for {req.service_group}",
            )
        )
    for f, pid in best.selection.items():
        pol = prep.policies.get(pid)
        if pol is not None and pol.application_schedule and pol.cropped_area_ha <= 0:
            out.append(
                RuleResidual(
                    rule="cropped_area",
                    passed=False,
                    entity_ids=[f],
                    unit="ha",
                    detail="crop policy requires positive cropped area",
                )
            )
    return out


def plan_metrics(
    run_id: str,
    prep: Prepared,
    best,
    cfg_id: str,
    ledgers: dict[str, list[LedgerEvent]],
    pkg: PilotPackage,
    catalog: Catalog,
) -> list[MetricValue]:
    typ = prep.typical_state.state_id
    p = prep.problem
    cfg = next(c for c in p.configs if c.config_id == cfg_id)
    opts = {o.policy_id: o for os_ in cfg.options.values() for o in os_}
    season = catalog.season(prep.request.season_id)
    crop = season.crop.value if season else None
    facts = []
    for f in p.fields:
        pid = best.selection[f]
        pol = prep.policies[pid]
        o = prep.outcomes.get((pid, typ))
        ev = [o.validation_ref] if o and o.validation_ref else []
        facts.append(
            FieldFacts(
                field_id=f,
                group=pkg.fields[f].group,
                policy_id=pid,
                family=pol.family,
                cropped_area_ha=pol.cropped_area_ha,
                yield_kg_ha=o.yield_kg_ha if o else None,
                production_kg=opts[pid].production_kg.get(typ),
                canal_receipt_m3=o.canal_receipt_m3 if o else 0.0,
                service_credit_m3=o.service_credit_m3 if o else 0.0,
                reference_m3=prep.reference_m3.get(f),
                groundwater_m3=o.groundwater_m3 if o else 0.0,
                pumping_cost_pkr=pol.seasonal_opex_pkr,
                terminal_pond_m3=o.terminal_pond_m3 if o else 0.0,
                evidence_ids=[x for x in ev if x],
            )
        )
    insts = sorted(set(best.instances))
    capex = cfg.capex_pkr + sum(p.instances[j].capex_pkr for j in insts if j in p.instances)
    pumping = sum(prep.policies[best.selection[f]].seasonal_opex_pkr for f in p.fields)
    opex = cfg.opex_pkr + pumping + sum(p.instances[j].opex_pkr for j in insts if j in p.instances)
    per_state = {
        s: sum(opts[best.selection[f]].production_kg.get(s, 0.0) for f in p.fields)
        for s in p.states
    }
    price = catalog.price(crop, prep.request.season_id)
    pf = PlanFacts(
        run_id=run_id,
        crop=crop or "",
        state_id=typ,
        fields=facts,
        ledger=ledgers.get(typ),
        capital_pkr=capex,
        operating_pkr=opex,
        pumping_pkr=pumping,
        new_instance_ids=insts + list(prep.library_config(cfg_id)),
        price_pkr_per_kg=price["price_pkr_per_kg"] if price else None,
        price_evidence_id=price.get("evidence_id") if price else None,
        per_state_production=per_state if len(p.states) > 1 else {},
        typical_state_id=typ,
        production_quantum_kg=p.production_quantum_kg,
    )
    return compute_plan_metrics(pf)


def _objective_value(prep: Prepared, best, metrics: list[MetricValue]) -> float:
    by = {(m.metric_id, m.field_id): m for m in metrics}
    if prep.problem.objective == "irrigation_contribution_pkr":
        v = by[("irrigation_contribution_pkr", None)].value
    elif len(prep.problem.objective_states) > 1:
        v = by[("worst_tested_production_kg", None)].value
    else:
        v = by[("production_kg", None)].value
    return float(v) if v is not None else 0.0


def _ledger_rows(ledgers: dict[str, list[LedgerEvent]]) -> list[dict[str, Any]]:
    rows = []
    for sid, evs in ledgers.items():
        for e in evs:
            d = e.model_dump(mode="python")
            d["kind"] = e.kind.value
            d["state_id"] = sid
            rows.append(d)
    return rows


SERIES = {
    "permitted_receipt_m3": ("Permitted receipt window cap", "m3", "water"),
    "canal_receipt_m3": ("Canal receipt at field", "m3", "water"),
    "field_application_m3": ("Gross field application", "m3", "water"),
    "pump_m3": ("Groundwater pumping", "m3", "water"),
    "pond_fill_m3": ("Pond fill", "m3", "water"),
    "pond_release_m3": ("Pond release", "m3", "water"),
    "pond_loss_m3": ("Pond evaporation + seepage", "m3", "water"),
    "pond_rain_m3": ("Pond rain capture", "m3", "water"),
    "pond_spill_m3": ("Pond spill", "m3", "water"),
    "gross_irrigation_mm": ("Gross irrigation (crop model input)", "mm", "crop"),
    "precipitation_mm": ("Precipitation", "mm", "weather"),
    "reference_et_mm": ("Reference ET0", "mm", "weather"),
    "canopy_fraction": ("Canopy cover (crop model)", "fraction", "crop"),
    "biomass_kg_ha": ("Above-ground biomass (crop model)", "kg/ha", "crop"),
    "soil_profile_water_mm": ("Total soil-profile water (crop model)", "mm", "crop"),
    "root_zone_water_mm": ("Root-zone water (crop model)", "mm", "crop"),
    "et_mm": ("Crop evapotranspiration (crop model)", "mm", "crop"),
    "transpiration_mm": ("Transpiration (crop model)", "mm", "crop"),
    "evaporation_mm": ("Soil evaporation (crop model)", "mm", "crop"),
    "runoff_mm": ("Runoff (crop model)", "mm", "crop"),
    "deep_percolation_mm": ("Deep percolation (crop model)", "mm", "crop"),
}
LEDGER_SERIES = {
    "outlet_receipt": "canal_receipt_m3",
    "field_application": "field_application_m3",
    "pump_abstraction": "pump_m3",
    "pond_fill": "pond_fill_m3",
    "pond_release": "pond_release_m3",
    "pond_evaporation": "pond_loss_m3",
    "pond_seepage": "pond_loss_m3",
    "pond_rain": "pond_rain_m3",
    "pond_spill": "pond_spill_m3",
}
POND_DELTA = {
    "pond_fill": 1,
    "pond_rain": 1,
    "pond_release": -1,
    "pond_evaporation": -1,
    "pond_seepage": -1,
    "pond_spill": -1,
}


def build_timeline(
    prep: Prepared, best, events: list[LedgerEvent], bindings, pkg: PilotPackage
) -> list[dict]:
    """Long-format daily series: crop trajectories (exact outcomes) + ledger aggregates."""
    rows: list[dict] = []
    typ = prep.typical_state.state_id
    for f, pid in best.selection.items():
        o = prep.outcomes.get((pid, typ))
        if o is None or not o.crop_outcome_hash:
            continue
        try:
            traj = bindings.load_trajectory(o.crop_outcome_hash)
        except Exception:  # noqa: BLE001 - a missing trajectory leaves gaps, never zeros
            traj = None
        if traj is None or len(traj) == 0:
            continue
        df = traj if isinstance(traj, pd.DataFrame) else pd.DataFrame(traj)
        for col in [c for c in df.columns if c in SERIES]:
            for d, v in zip(df["date"], df[col], strict=True):
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    continue
                rows.append(
                    {
                        "date": pd.Timestamp(d).date().isoformat(),
                        "field_id": f,
                        "entity_id": f,
                        "series_id": col,
                        "value": float(v),
                    }
                )
    daily: dict[tuple, float] = defaultdict(float)
    inv_delta: dict[tuple[str, str], float] = defaultdict(float)
    for e in events:
        d = local_crop_date(e.timestamp).isoformat()
        k = e.kind.value
        if k in LEDGER_SERIES and e.field_id:
            daily[(d, e.field_id, e.field_id, LEDGER_SERIES[k])] += e.volume_m3
        if k == "edge_transfer" and e.edge_id:
            daily[(d, None, e.edge_id, "edge_delivered_m3")] += e.volume_m3
        if k in POND_DELTA and e.asset_id:
            inv_delta[(d, e.asset_id)] += POND_DELTA[k] * e.volume_m3
    for (d, f, ent, sid), v in daily.items():
        rows.append({"date": d, "field_id": f, "entity_id": ent, "series_id": sid, "value": v})
    # pond inventory trace (start inventory + chronological deltas)
    by_pond: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (d, a), v in inv_delta.items():
        by_pond[a].append((d, v))
    for a, lst in by_pond.items():
        inv = pkg.assets[a].initial_inventory_m3 if a in pkg.assets else 0.0
        for d, v in sorted(lst):
            inv += v
            rows.append(
                {
                    "date": d,
                    "field_id": None,
                    "entity_id": a,
                    "series_id": "pond_inventory_m3",
                    "value": max(0.0, inv),
                }
            )
    return rows


# ------------------------------------------------------------------------ persistence


def persist(
    settings: Settings,
    conn: sqlite3.Connection,
    run_id: str,
    result,
    artifacts: dict[str, Any],
    opts: SolveOptions,
) -> Path:
    root = settings.runs_dir
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".tmp-{run_id}"
    final = root / run_id
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    run_doc = {
        "result": json.loads(RUN_ADAPTER.dump_json(result)),
        "meta": artifacts["meta"],
        "label": opts.label,
        "analysis_id": opts.analysis_id,
        "job_id": opts.job_id,
        "software": _software(),
    }
    _wj(tmp / "run.json", run_doc)
    _wj(tmp / "scenario.json", artifacts["scenario"])
    _wj(tmp / "selection.json", artifacts["selection"])
    _wj(tmp / "solver.json", artifacts["solver"])
    _wj(tmp / "metrics.json", artifacts["metrics"])
    _wj(tmp / "validation.json", artifacts["validation"])
    _wj(tmp / "coverage.json", artifacts["coverage"])
    ledger = pd.DataFrame(
        artifacts["ledger"],
        columns=[
            "event_id",
            "timestamp",
            "explicit_order",
            "kind",
            "volume_m3",
            "field_id",
            "asset_id",
            "edge_id",
            "window_id",
            "note",
            "state_id",
        ],
    )
    ledger.to_parquet(tmp / "ledger.parquet", index=False)
    tl = pd.DataFrame(
        artifacts["timeline"], columns=["date", "field_id", "entity_id", "series_id", "value"]
    )
    tl.to_parquet(tmp / "timeline.parquet", index=False)
    files = []
    for name in ARTIFACTS:
        p = tmp / name
        files.append({"path": name, "size_bytes": p.stat().st_size, "sha256": file_sha256(p)})
    _wj(tmp / "manifest.json", {"run_id": run_id, "files": files, "created_at": utcnow()})
    for p in tmp.iterdir():
        with open(p, "rb") as fh:
            os.fsync(fh.fileno())
    os.replace(tmp, final)
    manifest_sha = file_sha256(final / "manifest.json")
    with tx(conn):
        conn.execute(
            "INSERT INTO runs (run_id, scenario_revision_id, plan_kind, outcome, solver_status, scenario_hash, "
            "candidate_library_hash, run_dir, manifest_sha256, job_id, analysis_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                result.scenario_revision_id,
                result.plan_kind.value,
                result.outcome,
                result.solver_status.value,
                result.scenario_hash,
                result.candidate_library_hash,
                str(final),
                manifest_sha,
                opts.job_id,
                opts.analysis_id,
                utcnow(),
            ),
        )
    return final


def _wj(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str, allow_nan=False))


def _software() -> dict[str, str | None]:
    from importlib.metadata import PackageNotFoundError, version

    out = {}
    for d in ("ortools", "aquacrop", "pandas", "pydantic"):
        try:
            out[d] = version(d)
        except PackageNotFoundError:
            out[d] = None
    from aabflow.services.scenarios import SOLVER_VERSION

    out["optimizer"] = SOLVER_VERSION
    out["metrics"] = METRICS_VERSION
    return out


# ------------------------------------------------------------------------ loading


class RunIntegrityError(DomainError):
    pass


def run_row(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise not_found("run_id", run_id)
    return row


_VERIFIED: dict[str, float] = {}


def verify_bundle(run_dir: Path, manifest_sha: str) -> None:
    """Recompute artifact hashes against the manifest (AT18); cached by manifest mtime."""
    mpath = run_dir / "manifest.json"
    if not mpath.exists():
        raise RunIntegrityError(
            ErrorCode.ASSET_UNAVAILABLE, f"run bundle {run_dir.name} is missing its manifest"
        )
    stamp = mpath.stat().st_mtime
    if _VERIFIED.get(str(run_dir)) == stamp:
        return
    if file_sha256(mpath) != manifest_sha:
        raise RunIntegrityError(
            ErrorCode.ASSET_UNAVAILABLE, f"run {run_dir.name}: manifest hash mismatch"
        )
    man = json.loads(mpath.read_text())
    for f in man["files"]:
        p = run_dir / f["path"]
        if not p.exists() or file_sha256(p) != f["sha256"]:
            raise RunIntegrityError(
                ErrorCode.ASSET_UNAVAILABLE,
                f"run {run_dir.name}: artifact {f['path']} does not match its recorded hash",
            )
    _VERIFIED[str(run_dir)] = stamp


@dataclass
class LoadedRun:
    run_id: str
    row: sqlite3.Row
    dir: Path
    doc: dict[str, Any]

    @property
    def result(self):
        return RUN_ADAPTER.validate_python(self.doc["result"])

    @property
    def meta(self) -> dict[str, Any]:
        return self.doc["meta"]

    def json(self, name: str) -> Any:
        return json.loads((self.dir / name).read_text())

    def metrics(self) -> list[MetricValue]:
        return [MetricValue.model_validate(m) for m in self.json("metrics.json")]

    def ledger(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "ledger.parquet")

    def timeline(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "timeline.parquet")


def load_run(conn: sqlite3.Connection, run_id: str) -> LoadedRun:
    row = run_row(conn, run_id)
    d = Path(row["run_dir"])
    verify_bundle(d, row["manifest_sha256"])
    return LoadedRun(run_id, row, d, json.loads((d / "run.json").read_text()))


def list_runs(
    conn: sqlite3.Connection,
    *,
    pilot_id: str | None = None,
    pilot_version: str | None = None,
    scenario_revision_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT r.*, sr.request FROM runs r JOIN scenario_revisions sr "
        "ON sr.scenario_revision_id = r.scenario_revision_id"
    )
    args: list[Any] = []
    where = []
    if scenario_revision_id:
        where.append("r.scenario_revision_id = ?")
        args.append(scenario_revision_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.created_at DESC LIMIT ?"
    args.append(limit)
    out = []
    for row in conn.execute(sql, args).fetchall():
        req = loads(row["request"])
        if pilot_id and req["pilot_id"] != pilot_id:
            continue
        if pilot_version and req["pilot_version"] != pilot_version:
            continue
        out.append(
            {
                "run_id": row["run_id"],
                "plan_kind": row["plan_kind"],
                "outcome": row["outcome"],
                "solver_status": row["solver_status"],
                "scenario_revision_id": row["scenario_revision_id"],
                "created_at": row["created_at"],
                "pilot_id": req["pilot_id"],
                "pilot_version": req["pilot_version"],
                "season_id": req["season_id"],
                "analysis_id": row["analysis_id"],
                "job_id": row["job_id"],
            }
        )
    return out


def open_conn(settings: Settings) -> sqlite3.Connection:
    return connect(settings.db_path)


def run_dir(settings: Settings, run_id: str) -> Path:
    return settings.runs_dir / run_id


__all__ = ["RunContext", "SolveOptions", "dumps", "execute", "list_runs", "load_run"]
