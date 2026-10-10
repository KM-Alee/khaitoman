"""Executed finite-library density comparison on real pilot portfolios (T5.7)."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta

from aabflow.config import settings_from_env
from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import PlanKind, ScenarioRequest, SolverStatus
from aabflow.optimizer.candidates import (
    CandidateError,
    build_from_context,
    floor_grid,
    load_library,
    make_templates,
    publish_library,
)
from aabflow.optimizer.configurations import solve_problem
from aabflow.science.paths import atomic_write_text, libraries_dir
from aabflow.services.catalog import Catalog
from aabflow.services.pilots import PilotRepository
from aabflow.services.runs import verify_selection
from aabflow.services.runs.prepare import prepare
from aabflow.services.science import get_bindings
from aabflow.water.context import load_pilot
from aabflow.water.ledger import build_season_context

DENSITY_RECIPE = "depth-timing-v1"
REPRESENTATIVE_SEASONS = ("wheat-rabi-2027-28", "cotton-kharif-2027")


def denser_templates(ctx, fv, config_id):
    """Add depth midpoints across timing/investment families, plus shifted stored/pumped water.

    Receipt dates remain inside their declared roster windows. Storage releases
    and pump applications can shift seven days; the normal generator validates
    every variant and executes its exact crop inputs before retaining it.
    """
    for base in make_templates(ctx, fv, config_id):
        if base.family in ("rainfed", "baseline_B0"):
            continue
        variant = copy.deepcopy(base)
        variant.tags = [*base.tags, f"density:{DENSITY_RECIPE}"]
        variant.params = {**base.params, "density_recipe": DENSITY_RECIPE, "depth_scale": 0.85}
        variant.receipts_direct_mm = {
            w: floor_grid(d * 0.85) for w, d in base.receipts_direct_mm.items()
        }
        variant.fills_m3 = {w: v * 0.85 for w, v in base.fills_m3.items()}
        variant.releases_mm = [(d, floor_grid(v * 0.85)) for d, v in base.releases_mm]
        variant.pumps_mm = [(d, floor_grid(v * 0.85)) for d, v in base.pumps_mm]
        yield variant
        if base.releases_mm or base.pumps_mm:
            shifted = copy.deepcopy(base)
            shifted.tags = [*base.tags, f"density:{DENSITY_RECIPE}", "shift:+7d"]
            shifted.params = {**base.params, "density_recipe": DENSITY_RECIPE, "shift_days": 7}
            shifted.releases_mm = [(d + timedelta(days=7), v) for d, v in base.releases_mm]
            shifted.pumps_mm = [(d + timedelta(days=7), v) for d, v in base.pumps_mm]
            yield shifted


def retained_templates(pilot_id: str, season_id: str):
    path = libraries_dir() / pilot_id / season_id / "density.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if record["recipe"] != DENSITY_RECIPE:
        raise CandidateError("unsupported retained candidate density recipe")
    return denser_templates


def comparison_requests(pilot_id: str, season_id: str, pilot_version: str):
    common = {
        "pilot_id": pilot_id,
        "pilot_version": pilot_version,
        "season_id": season_id,
        "planning_mode": "capital_planning",
        "decision_at": "2026-10-10T08:00:00+05:00",
        "weather_scenario_ids": ["dry", "typical", "wet"],
        "operating_budget_pkr": 400000,
        "uncertainty_set_id": f"{pilot_id}:{season_id}:release-9",
    }
    for label, budget, supply, kind in (
        ("no_capital", 0, "nominal-roster-v1", PlanKind.P),
        ("small_budget", 400000, "nominal-roster-v1", PlanKind.P),
        ("capital", 3000000, "nominal-roster-v1", PlanKind.P),
        ("shortage", 3000000, "shortage-22pct-v1", PlanKind.P),
        ("robust_nine_states", 3000000, "nominal-roster-v1", PlanKind.R),
    ):
        yield (
            label,
            ScenarioRequest.model_validate(
                {**common, "capital_budget_pkr": budget, "supply_profile_id": supply}
            ),
            kind,
        )


def solve_comparison(bindings, pkg, catalog, request, kind, library, time_limit_s):
    prepared = prepare(
        bindings,
        pkg,
        catalog,
        request,
        kind,
        library_hash=library[0].candidate_library_hash,
        library=library,
    )
    solved = solve_problem(prepared.problem, time_limit_s=time_limit_s, workers=2, seed=0)
    if solved.status is not SolverStatus.OPTIMAL or solved.best is None:
        raise CandidateError(f"density comparison requires a proved optimum: {solved.status}")
    best = solved.best
    for state in prepared.states:
        _, report = bindings.reconstruct(
            list(best.selection.values()),
            library[0],
            state.state_id,
            best.config_id,
            policies=prepared.policies,
        )
        if report.status != "passed":
            raise CandidateError(f"density comparison has invalid physical ledger: {report}")
    violations = [r for r in verify_selection(prepared, best, best.config_id) if not r.passed]
    if violations:
        raise CandidateError(
            f"density comparison has invalid budget/service selection: {violations}"
        )
    cfg = next(c for c in prepared.problem.configs if c.config_id == best.config_id)
    output = {
        state: sum(
            prepared.outcomes[(policy, state)].production_kg for policy in best.selection.values()
        )
        for state in prepared.problem.objective_states
    }
    return {
        "solver_status": solved.status.value,
        "primary_quanta": best.primary,
        "upper_bound_quanta": solved.upper_bound,
        "production_quantum_kg": prepared.problem.production_quantum_kg,
        "objective_kg": min(output.values()),
        "by_state_production_kg": output,
        "configuration_id": best.config_id,
        "investment_ids": sorted(set(best.instances) | set(cfg.repair_instance_ids)),
        "selection": best.selection,
        "capital_pkr": best.capex_pkr,
        "operating_pkr": best.opex_pkr,
        "physical_validation": "passed",
        "states_validated": [s.state_id for s in prepared.states],
    }


def compare_density(pilot_id: str, season_id: str, *, workers=None, time_limit_s=120):
    """Publish/retain the larger exact library and its reproducible stability evidence."""
    directory = libraries_dir() / pilot_id / season_id
    record_path = directory / "density.json"
    previous = json.loads(record_path.read_text()) if record_path.exists() else None
    # On a fresh checkout the baseline's ignored policy dump is absent. Rebuild
    # it using the coarse generator explicitly, without a transient latest switch.
    try:
        coarse = load_library(pilot_id, season_id, previous["baseline_hash"] if previous else None)
    except FileNotFoundError:
        from aabflow.domain.schemas import CandidateLibrary

        if previous is None:
            raise
        baseline = CandidateLibrary.model_validate_json(
            (directory / previous["baseline_hash"] / "library.json").read_text()
        )
        ctx = build_season_context(load_pilot(pilot_id, baseline.pilot_version), season_id)
        rebuilt = build_from_context(ctx, workers=workers, progress=True)
        if rebuilt.library.candidate_library_hash != previous["baseline_hash"]:
            raise CandidateError("baseline density comparison no longer reproduces")
        coarse = rebuilt.library, rebuilt.policies
    ctx = build_season_context(load_pilot(pilot_id, coarse[0].pilot_version), season_id)
    result = build_from_context(
        ctx, extra_templates=denser_templates, workers=workers, progress=True
    )
    dense = result.library, result.policies
    if len(dense[1]) <= len(coarse[1]):
        raise CandidateError("denser comparison did not enlarge the retained candidate set")
    settings = settings_from_env()
    bindings = get_bindings(settings)
    pkg = PilotRepository(settings.pilots_dir).package(pilot_id, coarse[0].pilot_version)
    catalog = Catalog(settings.libraries_dir)
    comparisons = []
    for label, request, kind in comparison_requests(pilot_id, season_id, coarse[0].pilot_version):
        before = solve_comparison(bindings, pkg, catalog, request, kind, coarse, time_limit_s)
        after = solve_comparison(bindings, pkg, catalog, request, kind, dense, time_limit_s)
        if after["primary_quanta"] < before["primary_quanta"]:
            raise CandidateError("enlarged library degraded the proved finite-model objective")
        comparisons.append(
            {
                "scenario": label,
                "request": request.model_dump(mode="json"),
                "plan_kind": kind.value,
                "coarse": before,
                "dense": after,
                "objective_delta_kg": after["objective_kg"] - before["objective_kg"],
                "investment_changed": before["investment_ids"] != after["investment_ids"],
                "configuration_changed": before["configuration_id"] != after["configuration_id"],
                "policy_changes": sum(
                    before["selection"][f] != p for f, p in after["selection"].items()
                ),
            }
        )
        print(
            json.dumps(
                {
                    "pilot": pilot_id,
                    "season": season_id,
                    "scenario": label,
                    "objective_delta_kg": comparisons[-1]["objective_delta_kg"],
                    "investment_changed": comparisons[-1]["investment_changed"],
                }
            ),
            flush=True,
        )
    report = {
        "pilot_id": pilot_id,
        "season_id": season_id,
        "recipe": DENSITY_RECIPE,
        "baseline_hash": coarse[0].candidate_library_hash,
        "retained_hash": dense[0].candidate_library_hash,
        "coarse_policies": len(coarse[1]),
        "dense_policies": len(dense[1]),
        "comparisons": comparisons,
        "approximation": "Optimal within a finite exact candidate library. The larger library is retained for these scenarios; measured schedule and investment changes are reported per comparison. This does not prove a continuous-schedule optimum.",
    }
    report["evidence_hash"] = content_hash(report)
    report["created_at"] = datetime.now(UTC).isoformat()
    publish_library(result)
    atomic_write_text(directory / "adequacy.json", json.dumps(report, indent=1))
    atomic_write_text(
        record_path,
        json.dumps(
            {k: report[k] for k in ("recipe", "baseline_hash", "retained_hash", "evidence_hash")},
            indent=1,
        ),
    )
    return report
