"""Shared-configuration enumeration with one global time budget (T6.3, T6.4).

For each admissible configuration the primary objective is solved; the global
incumbent is the best validated configuration and the global upper bound the
maximum valid bound over unresolved/solved configurations. Lexicographic
secondary stages (operating spend, then capital, then source withdrawal) run for
every configuration tied on the integer primary value, each preserving the
earlier stages' attained values.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from ortools.sat.python import cp_model

from aabflow.domain.schemas import SolverStatus
from aabflow.jobs.cancellation import NEVER, CancelToken
from aabflow.optimizer.model import BuiltModel, ConfigSpec, Option, Problem, build

_STATUS = {
    cp_model.OPTIMAL: SolverStatus.OPTIMAL,
    cp_model.FEASIBLE: SolverStatus.FEASIBLE,
    cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
    cp_model.UNKNOWN: SolverStatus.UNKNOWN,
    cp_model.MODEL_INVALID: SolverStatus.MODEL_INVALID,
}
PRIMARY_SHARE = 0.65
SECONDARY_STAGES = ("operating_pkr", "capital_pkr", "withdrawal_q")


@dataclass
class StageResult:
    stage: str
    status: SolverStatus
    value: int | None
    bound: int | None
    wall_ms: int


@dataclass
class ConfigResult:
    config_id: str
    status: SolverStatus
    primary: int | None
    primary_bound: int | None
    wall_ms: int
    selection: dict[str, str] = field(default_factory=dict)  # field -> policy id
    instances: list[str] = field(default_factory=list)
    stages: list[StageResult] = field(default_factory=list)
    reason: str | None = None
    opex_pkr: int | None = None
    capex_pkr: int | None = None
    withdrawal_q: int | None = None
    n_variables: int = 0
    n_resource_constraints: int = 0


@dataclass
class SolveOutcome:
    status: SolverStatus
    best: ConfigResult | None
    configs: list[ConfigResult]
    upper_bound: int | None
    wall_ms: int
    cancelled: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def selection(self) -> dict[str, str]:
        return self.best.selection if self.best else {}


def _solver(time_s: float, workers: int, seed: int) -> cp_model.CpSolver:
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = max(0.05, time_s)
    s.parameters.num_workers = max(1, workers)
    s.parameters.random_seed = seed
    return s


def _run(
    bm: BuiltModel, time_s: float, workers: int, seed: int, token: CancelToken
) -> tuple[int, cp_model.CpSolver]:
    s = _solver(time_s, workers, seed)
    stop = s.stop_search
    token.on_cancel(stop)
    try:
        st = s.solve(bm.model)
    finally:
        token.remove(stop)
    return st, s


def _val(s: cp_model.CpSolver, expr) -> int:
    return int(expr) if isinstance(expr, int) else int(s.value(expr))


def _extract(bm: BuiltModel, s: cp_model.CpSolver, r: ConfigResult) -> None:
    r.selection = {f: pid for (f, pid), v in bm.x.items() if s.value(v)}
    r.instances = sorted(j for j, v in bm.z.items() if s.value(v))
    r.opex_pkr = _val(s, bm.opex_expr) + bm.constant_opex
    r.capex_pkr = _val(s, bm.capex_expr) + bm.constant_capex
    r.withdrawal_q = _val(s, bm.withdrawal_expr)


def _fix_hint(bm: BuiltModel, selection: dict[str, str]) -> None:
    bm.model.clear_hints()
    for (f, pid), v in bm.x.items():
        bm.model.add_hint(v, 1 if selection.get(f) == pid else 0)


def solve_config(
    p: Problem, c: ConfigSpec, time_s: float, workers: int, seed: int, token: CancelToken
) -> tuple[ConfigResult, BuiltModel | None]:
    t0 = time.monotonic()
    bm = build(p, c)
    r = ConfigResult(
        c.config_id,
        SolverStatus.UNKNOWN,
        None,
        None,
        0,
        n_variables=len(bm.x),
        n_resource_constraints=bm.n_resource_constraints,
    )
    if bm.infeasible_reason is not None:
        r.status = SolverStatus.INFEASIBLE
        r.reason = bm.infeasible_reason
        r.wall_ms = int((time.monotonic() - t0) * 1000)
        return r, None
    if isinstance(bm.primary, int):
        bm.model.maximize(0)
    else:
        bm.model.maximize(bm.primary)
    st, s = _run(bm, time_s, workers, seed, token)
    r.status = _STATUS.get(st, SolverStatus.UNKNOWN)
    if r.status is SolverStatus.INFEASIBLE:
        r.reason = r.reason or "finite candidate incompatibility under the scenario constraints"
    if r.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
        r.primary = _val(s, bm.primary)
        _extract(bm, s, r)
    if r.status is not SolverStatus.INFEASIBLE and r.status is not SolverStatus.MODEL_INVALID:
        bound = s.best_objective_bound
        r.primary_bound = int(bound + 1e-6) if math.isfinite(bound) and abs(bound) < 2**62 else None
        if r.status is SolverStatus.OPTIMAL:
            r.primary_bound = r.primary
    r.stages.append(
        StageResult("primary", r.status, r.primary, r.primary_bound, int(s.wall_time * 1000))
    )
    r.wall_ms = int((time.monotonic() - t0) * 1000)
    return r, bm


def secondary(
    bm: BuiltModel, r: ConfigResult, budget_s: float, workers: int, seed: int, token: CancelToken
) -> None:
    """Lexicographic refinement preserving the attained integer primary value."""
    if r.primary is None:
        return
    m = bm.model
    if not isinstance(bm.primary, int):
        m.add(bm.primary >= r.primary)
    per = budget_s / len(SECONDARY_STAGES)
    exprs = {
        "operating_pkr": bm.opex_expr,
        "capital_pkr": bm.capex_expr,
        "withdrawal_q": bm.withdrawal_expr,
    }
    for stage in SECONDARY_STAGES:
        if token.cancelled:
            return
        e = exprs[stage]
        current = _val_from(r, stage, bm)
        if isinstance(e, int):
            r.stages.append(StageResult(stage, SolverStatus.OPTIMAL, current, current, 0))
            continue
        _fix_hint(bm, r.selection)
        m.minimize(e)
        st, s = _run(bm, per, workers, seed, token)
        status = _STATUS.get(st, SolverStatus.UNKNOWN)
        if status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
            val = _val(s, e)
            if val <= current:
                _extract(bm, s, r)
                current = val
            bound = int(s.best_objective_bound - 1e-6) if status is SolverStatus.FEASIBLE else val
            r.stages.append(StageResult(stage, status, current, bound, int(s.wall_time * 1000)))
        else:
            # keep the earlier incumbent; this stage is unproven
            r.stages.append(
                StageResult(
                    stage,
                    SolverStatus.UNKNOWN if status is not SolverStatus.INFEASIBLE else status,
                    current,
                    None,
                    int(s.wall_time * 1000),
                )
            )
        m.add(e <= current)


def _val_from(r: ConfigResult, stage: str, bm: BuiltModel) -> int:
    if stage == "operating_pkr":
        return (r.opex_pkr or 0) - bm.constant_opex
    if stage == "capital_pkr":
        return (r.capex_pkr or 0) - bm.constant_capex
    return r.withdrawal_q or 0


def global_status(
    results: list[ConfigResult],
) -> tuple[SolverStatus, ConfigResult | None, int | None]:
    feasible = [r for r in results if r.primary is not None]
    if any(r.status is SolverStatus.MODEL_INVALID for r in results) and not feasible:
        return SolverStatus.MODEL_INVALID, None, None
    if not feasible:
        if results and all(r.status is SolverStatus.INFEASIBLE for r in results):
            return SolverStatus.INFEASIBLE, None, None
        bounds = [r.primary_bound for r in results if r.primary_bound is not None]
        return SolverStatus.UNKNOWN, None, (max(bounds) if bounds else None)
    best_val = max(r.primary for r in feasible)
    bounds = []
    unbounded = False
    for r in results:
        if r.status is SolverStatus.INFEASIBLE:
            continue
        if r.primary_bound is None:
            unbounded = True
        else:
            bounds.append(r.primary_bound)
    ub = None if unbounded else max(bounds + [best_val])
    optimal = (
        not unbounded
        and all(
            r.status is SolverStatus.INFEASIBLE
            or (r.primary_bound is not None and r.primary_bound <= best_val)
            for r in results
        )
        and any(r.status is SolverStatus.OPTIMAL and r.primary == best_val for r in feasible)
    )
    tied = [r for r in feasible if r.primary == best_val]
    best = min(tied, key=_lex_key)
    return (SolverStatus.OPTIMAL if optimal else SolverStatus.FEASIBLE), best, ub


def _lex_key(r: ConfigResult) -> tuple:
    return (
        r.opex_pkr if r.opex_pkr is not None else 2**62,
        r.capex_pkr if r.capex_pkr is not None else 2**62,
        r.withdrawal_q if r.withdrawal_q is not None else 2**62,
        r.config_id,
    )


def solve_problem(
    p: Problem,
    *,
    time_limit_s: float = 10.0,
    workers: int = 2,
    seed: int = 0,
    token: CancelToken = NEVER,
) -> SolveOutcome:
    t0 = time.monotonic()
    configs = [c for c in p.configs]
    primary_budget = time_limit_s * PRIMARY_SHARE
    results: list[ConfigResult] = []
    built: dict[str, BuiltModel] = {}
    cancelled = False
    for i, c in enumerate(configs):
        if token.cancelled:
            cancelled = True
            results.append(
                ConfigResult(c.config_id, SolverStatus.UNKNOWN, None, None, 0, reason="cancelled")
            )
            continue
        used = time.monotonic() - t0
        share = max(0.05, (primary_budget - used) / (len(configs) - i))
        r, bm = solve_config(p, c, share, workers, seed, token)
        results.append(r)
        if bm is not None:
            built[c.config_id] = bm
        if token.cancelled:
            cancelled = True
    status, best, ub = global_status(results)
    notes: list[str] = []
    if best is not None and not cancelled:
        tied = [r for r in results if r.primary is not None and r.primary == best.primary]
        remaining = max(0.05, time_limit_s - (time.monotonic() - t0))
        for r in tied:
            if r.config_id in built:
                secondary(built[r.config_id], r, remaining / len(tied), workers, seed, token)
        status, best, ub = global_status(results)
        if len(tied) > 1:
            notes.append(
                f"{len(tied)} configurations tie on the primary objective; lexicographic tie-break applied"
            )
    return SolveOutcome(
        status, best, results, ub, int((time.monotonic() - t0) * 1000), cancelled, notes
    )


def describe(outcome: SolveOutcome) -> dict[str, Any]:
    return {
        "status": outcome.status.value,
        "upper_bound": outcome.upper_bound,
        "wall_ms": outcome.wall_ms,
        "cancelled": outcome.cancelled,
        "notes": outcome.notes,
        "configurations": [
            {
                "shared_configuration_id": r.config_id,
                "status": r.status.value,
                "primary": r.primary,
                "primary_bound": r.primary_bound,
                "wall_ms": r.wall_ms,
                "reason": r.reason,
                "selection": r.selection,
                "instances": r.instances,
                "opex_pkr": r.opex_pkr,
                "capex_pkr": r.capex_pkr,
                "withdrawal_q": r.withdrawal_q,
                "variables": r.n_variables,
                "resource_constraints": r.n_resource_constraints,
                "stages": [
                    {
                        "stage": s.stage,
                        "status": s.status.value,
                        "value": s.value,
                        "bound": s.bound,
                        "wall_ms": s.wall_ms,
                    }
                    for s in r.stages
                ],
            }
            for r in outcome.configs
        ],
    }


def option_lookup(p: Problem) -> dict[tuple[str, str, str], Option]:
    return {
        (c.config_id, f, o.policy_id): o
        for c in p.configs
        for f, os_ in c.options.items()
        for o in os_
    }
