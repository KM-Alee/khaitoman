"""Scenario + candidate library -> finite optimization problem (T6.1, T5.7, T7.2).

Responsibilities:
* choose the evaluated states (typical state, robust uncertainty-set states, or an
  explicit stress state) and derive ad-hoc states for a scenario's extra uniform
  reduction / blocked edges through the science stream's evaluation entry points;
* filter candidates by admissibility (instances allowed/excluded/eligible by date and
  cost, groundwater permission, deliverability in every evaluated state, service floor);
* build per-configuration capacities and the plan-kind specific problem (B0/B1/P/R);
* record candidate coverage and rejection reasons per field (AT07).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aabflow.api.errors import DomainError, conflict, invalid
from aabflow.domain.schemas import (
    ActionCategory,
    CandidateLibrary,
    CandidatePolicy,
    ErrorCode,
    OptimizationMode,
    PlanKind,
    ScenarioRequest,
    StateOutcome,
)
from aabflow.optimizer.model import ConfigSpec, InstanceSpec, Option, Problem, service_ok
from aabflow.services.catalog import Catalog
from aabflow.services.interventions import eligibility
from aabflow.services.pilots import PilotPackage

BASELINE_FAMILY = "baseline_B0"
SEASON_START = datetime(1970, 1, 1, tzinfo=UTC)
SEASON_END = datetime(2100, 1, 1, tzinfo=UTC)


_LIB_CACHE: dict[tuple, tuple[CandidateLibrary, list[CandidatePolicy]]] = {}


def load_library_cached(bindings, pilot_id: str, season_id: str, library_hash: str | None):
    """Immutable libraries are cached by hash (bounded); ``None`` resolves the latest each time."""
    if library_hash is None:
        return bindings.load_library(pilot_id, season_id, None)
    key = (id(bindings), pilot_id, season_id, library_hash)
    hit = _LIB_CACHE.get(key)
    if hit is None:
        hit = bindings.load_library(pilot_id, season_id, library_hash)
        if len(_LIB_CACHE) >= 4:
            _LIB_CACHE.pop(next(iter(_LIB_CACHE)))
        _LIB_CACHE[key] = hit
    return hit


def state_id(weather: str, supply: str) -> str:
    return f"{weather}__{supply}"


def split_state(sid: str) -> tuple[str, str]:
    w, _, s = sid.partition("__")
    return w, s


@dataclass
class EvalState:
    """One evaluated state; ``base_state`` is the library state it derives from."""

    state_id: str
    base_state: str
    weather_scenario_id: str
    supply_profile_id: str
    uniform_reduction: float = 0.0
    blocked_edge_ids: tuple[str, ...] = ()
    resolved_supply: Any = None  # science ResolvedSupply when ad-hoc
    extra_closures: tuple = ()

    @property
    def adhoc(self) -> bool:
        return self.uniform_reduction > 0 or bool(self.blocked_edge_ids)


@dataclass
class Prepared:
    request: ScenarioRequest
    plan_kind: PlanKind
    library: CandidateLibrary
    policies: dict[str, CandidatePolicy]
    states: list[EvalState]
    typical_state: EvalState
    problem: Problem
    outcomes: dict[tuple[str, str], StateOutcome]  # (policy, state) effective outcomes
    coverage: dict[str, Any]
    max_attainable_service: dict[str, float | None]
    reference_m3: dict[str, float]
    warnings: list[str] = field(default_factory=list)
    infeasibility_hint: dict[str, Any] = field(default_factory=dict)
    field_groups: dict[str, str] = field(default_factory=dict)

    def library_config(self, cid: str) -> list[str]:
        cfg = next(
            (c for c in self.library.configurations if c.shared_configuration_id == cid), None
        )
        return list(cfg.repair_instance_ids) if cfg else []

    def state(self, sid: str) -> EvalState:
        return next(s for s in self.states if s.state_id == sid)


def typical_weather(catalog: Catalog, req: ScenarioRequest) -> str:
    ws = {w.weather_scenario_id: w for w in catalog.weather_scenarios(req.pilot_id, req.season_id)}
    typ = [w for w in req.weather_scenario_ids if w in ws and ws[w].is_typical]
    if typ:
        return typ[0]
    if len(req.weather_scenario_ids) == 1:
        return req.weather_scenario_ids[0]
    raise invalid(
        "weather_scenario_ids must include the designated typical member (is_typical) or name one scenario",
        {"weather_scenario_ids": "no typical member"},
    )


def evaluation_states(
    bindings,
    catalog: Catalog,
    req: ScenarioRequest,
    plan_kind: PlanKind,
    library: CandidateLibrary,
    states_override: list[str] | None = None,
) -> tuple[list[EvalState], EvalState, list[str]]:
    warnings: list[str] = []
    lib_states = set(library.state_ids)
    robust = plan_kind is PlanKind.R or req.optimization_mode is OptimizationMode.worst_case
    typ_w = typical_weather(catalog, req)
    if states_override is not None:
        sids = list(states_override)
    elif robust:
        if not req.uncertainty_set_id:
            raise invalid(
                "robust plan (R / worst_case) requires uncertainty_set_id",
                {"uncertainty_set_id": "missing"},
            )
        us = catalog.uncertainty_set(req.uncertainty_set_id)
        if us is None or us.pilot_id != req.pilot_id or us.season_id != req.season_id:
            raise invalid(
                "unknown uncertainty set for this pilot/season",
                {"uncertainty_set_id": req.uncertainty_set_id},
            )
        sids = [s.state_id for s in us.states]
        if req.uniform_reduction_fraction > 0:
            warnings.append(
                "uniform_reduction_fraction is not applied on top of published uncertainty-set states"
            )
    else:
        sids = [state_id(typ_w, req.supply_profile_id)]
    missing = [s for s in sids if s not in lib_states]
    if missing:
        raise DomainError(
            ErrorCode.ASSET_UNAVAILABLE,
            f"candidate library {library.candidate_library_hash[:12]} has no outcomes for states {missing}",
        )
    out: list[EvalState] = []
    adhoc = (
        not robust
        and states_override is None
        and (req.uniform_reduction_fraction > 0 or req.blocked_edge_ids)
    )
    for sid in sids:
        w, s = split_state(sid)
        if adhoc:
            prof = catalog.supply_profile(req.pilot_id, req.season_id, s)
            if prof is None:
                raise invalid("unknown supply profile", {"supply_profile_id": s})
            try:
                resolved = bindings.resolve_supply(prof, req.uniform_reduction_fraction)
            except ValueError as exc:
                raise invalid(str(exc), {"uniform_reduction_fraction": str(exc)}) from exc
            closures = tuple(
                bindings.closure(SEASON_START, SEASON_END, frozenset({e}), f"blocked:{e}")
                for e in sorted(req.blocked_edge_ids)
            )
            tag = f"r{req.uniform_reduction_fraction:g}" + (
                "+blocked:" + ",".join(sorted(req.blocked_edge_ids)) if req.blocked_edge_ids else ""
            )
            out.append(
                EvalState(
                    f"{sid}+{tag}",
                    sid,
                    w,
                    s,
                    req.uniform_reduction_fraction,
                    tuple(sorted(req.blocked_edge_ids)),
                    resolved,
                    closures,
                )
            )
        else:
            out.append(EvalState(sid, sid, w, s))
    typ_sid = state_id(typ_w, req.supply_profile_id)
    typical = next((e for e in out if e.base_state == typ_sid), None)
    if typical is None:
        typical = next((e for e in out if e.weather_scenario_id == typ_w), out[0])
    return out, typical, warnings


class OutcomeResolver:
    """Effective per-state outcome of a policy, including ad-hoc derived states."""

    def __init__(
        self,
        bindings,
        pkg: PilotPackage,
        library: CandidateLibrary,
        catalog: Catalog,
        req: ScenarioRequest,
    ):
        self.bindings = bindings
        self.pkg = pkg
        self.library = library
        self.catalog = catalog
        self.req = req
        self._ctx = None

    def ctx(self):
        if self._ctx is None:
            self._ctx = self.bindings.season_context(
                self.library.pilot_id, self.library.season_id, self.library.pilot_version
            )
        return self._ctx

    def outcome(self, p: CandidatePolicy, st: EvalState) -> StateOutcome | None:
        base = next((o for o in p.outcomes if o.state_id == st.base_state), None)
        if not st.adhoc:
            return base
        if base is None or not base.deliverable:
            return base
        prof = self.catalog.supply_profile(
            self.req.pilot_id, self.req.season_id, st.supply_profile_id
        )
        has_closure = prof is not None and any(t.kind == "closure" for t in prof.transformations)
        frac = p.attributes.get("max_window_take_fraction")
        if (
            not st.blocked_edge_ids
            and not has_closure
            and frac is not None
            and st.resolved_supply is not None
        ):
            ok = float(st.resolved_supply.multiplier) + 1e-12 >= float(frac)
            if ok:
                return base.model_copy(update={"state_id": st.state_id})
            return base.model_copy(
                update={
                    "state_id": st.state_id,
                    "deliverable": False,
                    "yield_kg_ha": None,
                    "production_kg": None,
                    "crop_outcome_hash": None,
                    "service_credit_m3": 0.0,
                    "violations": [
                        (
                            f"policy takes {float(frac):.3f} of nominal window volume; supply multiplier is "
                            f"{float(st.resolved_supply.multiplier):.3f}"
                        )
                    ],
                }
            )
        return self.bindings.evaluate_policy(
            p,
            self.ctx(),
            st.resolved_supply,
            st.weather_scenario_id,
            p.shared_configuration_id,
            state_id=st.state_id,
            extra_closures=st.extra_closures,
        )


def _instance_admissible(
    pkg: PilotPackage, inst_id: str, req: ScenarioRequest, planting
) -> str | None:
    inst = pkg.instances.get(inst_id)
    if inst is None:
        return f"{inst_id} is not in pilot version {pkg.pilot_version}"
    _, reasons = eligibility(pkg, inst, req.decision_at, planting)
    return "; ".join(reasons) if reasons else None


def references(pkg: PilotPackage, season_id: str) -> dict[str, float]:
    return {
        r.field_id: r.reference_receipt_m3
        for r in pkg.service_references
        if r.season_id == season_id
    }


def group_fields(pkg: PilotPackage, group: str | None) -> list[str]:
    if group is None:
        return []
    if group == "all":
        return sorted(pkg.fields)
    return sorted(f for f, rec in pkg.fields.items() if rec.group == group)


def prepare(
    bindings,
    pkg: PilotPackage,
    catalog: Catalog,
    req: ScenarioRequest,
    plan_kind: PlanKind,
    *,
    library_hash: str | None,
    states_override: list[str] | None = None,
    fixed_selection: dict[str, str] | None = None,
    fixed_instances: set[str] | None = None,
    fixed_config_id: str | None = None,
    hint: dict[str, str] | None = None,
    library: tuple[CandidateLibrary, list[CandidatePolicy]] | None = None,
) -> Prepared:
    lib, pols = library or load_library_cached(bindings, req.pilot_id, req.season_id, library_hash)
    if lib.pilot_version != req.pilot_version:
        raise conflict(
            "candidate library was built for a different pilot version",
            {
                "library_pilot_version": lib.pilot_version,
                "request_pilot_version": req.pilot_version,
            },
        )
    season = catalog.season(req.season_id)
    planting = (season.planting_date or season.start) if season else None
    states, typical, warnings = evaluation_states(
        bindings, catalog, req, plan_kind, lib, states_override
    )
    resolver = OutcomeResolver(bindings, pkg, lib, catalog, req)
    policies = {p.candidate_policy_id: p for p in pols}
    refs = references(pkg, req.season_id)
    floor_fields = (
        set(group_fields(pkg, req.service_group))
        if req.minimum_service_ratio is not None
        else set()
    )
    allowed = (
        set(req.allowed_intervention_instance_ids)
        if req.allowed_intervention_instance_ids is not None
        else None
    )
    excluded = set(req.excluded_instance_ids)
    forced = set(req.forced_instance_ids)
    no_capital = plan_kind in (PlanKind.B0, PlanKind.B1)

    inst_reason: dict[str, str | None] = {}

    def inst_bad(j: str) -> str | None:
        if j not in inst_reason:
            why = _instance_admissible(pkg, j, req, planting)
            if why is None and j in lib.excluded_instances:
                why = f"candidate library excluded it: {lib.excluded_instances[j]}"
            inst_reason[j] = why
        if fixed_instances is not None and j not in fixed_instances:
            return f"{j} is not among the plan's fixed investments"
        if no_capital:
            return "new capital is fixed at zero for this plan kind"
        if j in excluded:
            return f"{j} excluded by the scenario"
        if allowed is not None and j not in allowed and j not in forced:
            return f"{j} not in allowed_intervention_instance_ids"
        return inst_reason[j]

    outcomes: dict[tuple[str, str], StateOutcome] = {}
    configs: list[ConfigSpec] = []
    coverage_fields: dict[str, dict[str, Any]] = {
        f: {
            "field_id": f,
            "library_candidates": 0,
            "retained": 0,
            "rejections": defaultdict(int),
            "families": defaultdict(int),
        }
        for f in sorted(pkg.fields)
    }
    best_service: dict[str, dict[str, float]] = defaultdict(dict)  # config -> field -> best ratio
    by_config: dict[str, list[CandidatePolicy]] = defaultdict(list)
    for p in pols:
        by_config[p.shared_configuration_id].append(p)
    lib_fields = {p.field_id for p in pols}
    missing_fields = sorted(set(pkg.fields) - lib_fields)
    for cfg in sorted(
        lib.configurations, key=lambda c: (len(c.repair_instance_ids), c.shared_configuration_id)
    ):
        cid = cfg.shared_configuration_id
        spec = ConfigSpec(cid, tuple(cfg.repair_instance_ids), cfg.capex_pkr, cfg.seasonal_opex_pkr)
        bad = [inst_bad(j) for j in cfg.repair_instance_ids]
        bad = [b for b in bad if b]
        if fixed_config_id is not None and cid != fixed_config_id:
            spec.excluded_reason = f"configuration fixed to {fixed_config_id}"
        elif bad:
            spec.excluded_reason = "; ".join(bad)
        missing_forced = [
            j for j in forced if j in _repairs(lib) and j not in cfg.repair_instance_ids
        ]
        if missing_forced and spec.excluded_reason is None:
            spec.excluded_reason = f"forced repair(s) {missing_forced} not in this configuration"
        for f in pkg.fields:
            spec.options[f] = []
        for p in sorted(by_config.get(cid, []), key=lambda p: p.candidate_policy_id):
            cov = coverage_fields.setdefault(
                p.field_id,
                {
                    "field_id": p.field_id,
                    "library_candidates": 0,
                    "retained": 0,
                    "rejections": defaultdict(int),
                    "families": defaultdict(int),
                },
            )
            cov["library_candidates"] += 1
            reason = None
            if spec.excluded_reason:
                reason = "configuration inadmissible"
            if reason is None:
                for j in p.required_instance_ids:
                    why = inst_bad(j)
                    if why:
                        reason = "instance unavailable"
                        break
            if (
                reason is None
                and not req.permit_groundwater
                and (p.pump_volume_m3 > 0 or p.pump_events)
            ):
                reason = "groundwater not permitted"
            if reason is None and plan_kind is PlanKind.B0 and p.family != BASELINE_FAMILY:
                reason = "not the fixed-roster baseline"
            st_out: dict[str, StateOutcome] = {}
            if reason is None:
                for st in states:
                    o = resolver.outcome(p, st)
                    if o is None:
                        reason = "no outcome for evaluated state"
                        break
                    outcomes[(p.candidate_policy_id, st.state_id)] = o
                    if not o.deliverable or o.production_kg is None and o.yield_kg_ha is None:
                        reason = "undeliverable in an evaluated state"
                        break
                    st_out[st.state_id] = o
            if reason is None and p.field_id in refs and refs[p.field_id] > 0:
                ratio = min(o.service_credit_m3 for o in st_out.values()) / refs[p.field_id]
                prev = best_service[cid].get(p.field_id)
                best_service[cid][p.field_id] = ratio if prev is None else max(prev, ratio)
            if reason is None and p.field_id in floor_fields and refs.get(p.field_id, 0) > 0:
                need = req.minimum_service_ratio * refs[p.field_id]
                if not all(service_ok(o.service_credit_m3, need) for o in st_out.values()):
                    reason = "below service floor"
            if reason is not None:
                cov["rejections"][reason] += 1
                continue
            cov["retained"] += 1
            cov["families"][p.family] += 1
            spec.options[p.field_id].append(_option(p, st_out))
        for f in pkg.fields:
            if not spec.options[f] and spec.excluded_reason is None:
                if f in missing_fields:
                    spec.empty_fields[f] = f"field {f} has no candidate policies in the library"
                elif f in floor_fields:
                    best = best_service[cid].get(f)
                    spec.empty_fields[f] = (
                        f"no retained candidate for {f} meets the service floor {req.minimum_service_ratio:.2f}"
                        + (f" (best attainable {best:.3f})" if best is not None else "")
                    )
                else:
                    spec.empty_fields[f] = f"no admissible candidate for field {f} in {cid}"
        spec.capacities = _capacities(lib, cid, states)
        configs.append(spec)

    instances = {
        j: InstanceSpec(j, i.capex_pkr, i.seasonal_opex_pkr, i.mutually_exclusive_group)
        for j, i in pkg.instances.items()
        if i.category is not ActionCategory.shared_repair
    }
    for j in forced:
        if j not in pkg.instances:
            raise invalid("forced instance is not in the pilot", {"forced_instance_ids": j})
    price = None
    if req.objective.value == "irrigation_contribution_pkr":
        price = catalog_price(catalog, req, season)
    sel = fixed_selection
    if plan_kind is PlanKind.B0 and sel is None:
        sel = _baseline_selection(configs)
    robust = plan_kind is PlanKind.R or req.optimization_mode is OptimizationMode.worst_case
    sids = [s.state_id for s in states]
    problem = Problem(
        fields=sorted(pkg.fields),
        states=sids,
        objective_states=sids if robust else [typical.state_id],
        configs=configs,
        instances=instances,
        capital_budget_pkr=0 if no_capital else req.capital_budget_pkr,
        operating_budget_pkr=req.operating_budget_pkr,
        forced_instance_ids=forced,
        excluded_instance_ids=excluded,
        objective=req.objective.value,
        price_pkr_per_kg=price,
        fixed_selection=sel,
        hint=hint,
        apply_budgets=plan_kind is not PlanKind.B0 and fixed_selection is None,
        tie_state=typical.state_id,
    )
    groups: dict[str, float | None] = {}
    for g in ("head", "middle", "tail", "all"):
        fs = [f for f in group_fields(pkg, g) if refs.get(f, 0) > 0]
        if not fs:
            groups[g] = None
            continue
        per_cfg = []
        for cid, best in best_service.items():
            if all(f in best for f in fs):
                per_cfg.append(min(best[f] for f in fs))
        groups[g] = max(per_cfg) if per_cfg else 0.0
    coverage = {
        "candidate_library_hash": lib.candidate_library_hash,
        "generator_version": lib.generator_version,
        "states": sids,
        "fields": [
            {**c, "rejections": dict(c["rejections"]), "families": dict(c["families"])}
            for c in coverage_fields.values()
        ],
        "library_coverage": [c.model_dump() for c in lib.coverage],
        "excluded_instances": dict(lib.excluded_instances),
        "proof_scope": "finite_candidate_library",
        "note": "Solver statuses concern the finite candidate library only; missing candidates are not evidence "
        "of physical impossibility.",
    }
    limited = [c["field_id"] for c in coverage["fields"] if 0 < c["retained"] < 3]
    if limited:
        warnings.append(
            f"CANDIDATE_COVERAGE_LIMITED: fewer than 3 admissible candidates for {limited}"
        )
    if missing_fields:
        warnings.append(f"fields without library candidates: {missing_fields}")
    return Prepared(
        req,
        plan_kind,
        lib,
        policies,
        states,
        typical,
        problem,
        outcomes,
        coverage,
        groups,
        refs,
        warnings,
        field_groups={f: r.group for f, r in pkg.fields.items()},
    )


def _repairs(lib: CandidateLibrary) -> set[str]:
    return {j for c in lib.configurations for j in c.repair_instance_ids}


def _option(p: CandidatePolicy, st_out: dict[str, StateOutcome]) -> Option:
    prod, res, svc, wd, gw = {}, {}, {}, {}, {}
    base_res = {(r.resource_id, r.interval_id): r.volume_m3 for r in p.resources}
    for sid, o in st_out.items():
        prod[sid] = (
            o.production_kg
            if o.production_kg is not None
            else p.cropped_area_ha * (o.yield_kg_ha or 0.0)
        )
        use = (
            {(r.resource_id, r.interval_id): r.volume_m3 for r in o.resources}
            if o.resources
            else base_res
        )
        res[sid] = use
        svc[sid] = o.service_credit_m3
        wd[sid] = sum(v for (rid, _), v in use.items() if rid.startswith("source:"))
        gw[sid] = o.groundwater_m3
    return Option(
        policy_id=p.candidate_policy_id,
        field_id=p.field_id,
        family=p.family,
        required_instance_ids=tuple(sorted(p.required_instance_ids)),
        opex_pkr=p.seasonal_opex_pkr,
        production_kg=prod,
        resources=res,
        service_credit_m3=svc,
        withdrawal_m3=wd,
        groundwater_m3=gw,
    )


def _capacities(lib: CandidateLibrary, cid: str, states: list[EvalState]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    iv_ids = [i.interval_id for i in lib.intervals]
    for st in states:
        caps: dict[tuple[str, str], float] = {}
        for c in lib.capacities:
            if c.state_id not in (None, st.base_state):
                continue
            if c.shared_configuration_id not in (None, cid):
                continue
            k = (c.resource_id, c.interval_id)
            caps[k] = min(caps.get(k, c.capacity_m3), c.capacity_m3)
        for e in st.blocked_edge_ids:
            for iv in iv_ids:
                caps[(f"edge:{e}", iv)] = 0.0
        out[st.state_id] = caps
    return out


def _baseline_selection(configs: list[ConfigSpec]) -> dict[str, str]:
    base = next((c for c in configs if not c.repair_instance_ids), None)
    sel: dict[str, str] = {}
    if base is None:
        return sel
    for f, opts in base.options.items():
        b0 = [o for o in opts if o.family == BASELINE_FAMILY]
        if b0:
            pick = max(b0, key=lambda o: (sum(o.service_credit_m3.values()), o.policy_id))
            sel[f] = pick.policy_id
    return sel


def catalog_price(catalog: Catalog, req: ScenarioRequest, season) -> str:
    rec = catalog.price(season.crop.value if season else None, req.season_id)
    if rec is None:
        raise invalid(
            "irrigation_contribution_pkr requires a dated crop price record with evidence; none is published",
            {"objective": "absent price"},
        )
    return str(rec["price_pkr_per_kg"])
