"""Finite portfolio model for one shared configuration (T6.1, T6.2).

The problem is expressed over pure in-memory structures so the same code path
serves the T12.2 enumerable fixture, synthetic tests and real candidate
libraries. Coefficients are conservative integers:

* resource use ``ceil(use/q)`` against ``floor(capacity/q)``;
* service credit ``floor(credit/q)`` against ``ceil(required/q)``;
* production ``floor(production/qp)`` (objective quantization bound = fields x qp).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal

from ortools.sat.python import cp_model

from aabflow.domain.units import (
    DEFAULT_PRODUCTION_QUANTUM_KG,
    DEFAULT_WATER_QUANTUM_M3,
    capacity_quanta,
    consumption_quanta,
    credited_service_quanta,
    required_service_quanta,
)

INT_SAFE = 2**53  # keep every linear expression far below int64 limits

ResKey = tuple[str, str]  # (resource_id, interval_id)


@dataclass
class Option:
    """One candidate policy for one field under one configuration (all values exact)."""

    policy_id: str
    field_id: str
    family: str = ""
    required_instance_ids: tuple[str, ...] = ()
    opex_pkr: int = 0
    production_kg: dict[str, float] = field(
        default_factory=dict
    )  # state -> kg (deliverable states)
    resources: dict[str, dict[ResKey, float]] = field(default_factory=dict)  # state -> use
    service_credit_m3: dict[str, float] = field(default_factory=dict)
    withdrawal_m3: dict[str, float] = field(default_factory=dict)
    groundwater_m3: dict[str, float] = field(default_factory=dict)


@dataclass
class InstanceSpec:
    instance_id: str
    capex_pkr: int
    opex_pkr: int = 0
    exclusive_group: str | None = None


@dataclass
class ConfigSpec:
    config_id: str
    repair_instance_ids: tuple[str, ...] = ()
    capex_pkr: int = 0
    opex_pkr: int = 0
    options: dict[str, list[Option]] = field(default_factory=dict)  # field -> options
    capacities: dict[str, dict[ResKey, float]] = field(default_factory=dict)  # state -> caps
    excluded_reason: str | None = None  # set when the config is inadmissible for this scenario
    empty_fields: dict[str, str] = field(default_factory=dict)  # field -> why no option survived


@dataclass
class Problem:
    fields: list[str]
    states: list[
        str
    ]  # states in which every selected option must be deliverable and capacities hold
    objective_states: list[str]  # one (typical) or all (robust worst case)
    configs: list[ConfigSpec]
    instances: dict[str, InstanceSpec]
    capital_budget_pkr: int | None
    operating_budget_pkr: int | None
    forced_instance_ids: set[str] = field(default_factory=set)
    excluded_instance_ids: set[str] = field(default_factory=set)
    objective: str = "production_kg"  # or irrigation_contribution_pkr
    price_pkr_per_kg: str | None = None
    water_quantum_m3: float = DEFAULT_WATER_QUANTUM_M3
    production_quantum_kg: float = DEFAULT_PRODUCTION_QUANTUM_KG
    fixed_selection: dict[str, str] | None = None  # field -> policy id (B0 / fixed-plan checks)
    hint: dict[str, str] | None = None
    apply_budgets: bool = True
    tie_state: str | None = None  # state whose withdrawal is the last tie-break


def add_le(m: cp_model.CpModel, expr, bound: int) -> None:
    """``expr <= bound`` that also handles constant (int) expressions."""
    if isinstance(expr, int):
        if expr > bound:
            m.add_bool_or([])
        return
    m.add(expr <= bound)


def objective_coef(p: Problem, o: Option, state: str) -> int:
    prod = o.production_kg[state]
    if p.objective == "irrigation_contribution_pkr":
        if p.price_pkr_per_kg is None:
            raise ValueError("contribution objective requires a crop price")
        value = (Decimal(p.price_pkr_per_kg) * Decimal(repr(prod))).to_integral_value(ROUND_FLOOR)
        return int(value) - o.opex_pkr
    return int(
        (Decimal(repr(prod)) / Decimal(repr(p.production_quantum_kg))).to_integral_value(
            ROUND_FLOOR
        )
    )


@dataclass
class BuiltModel:
    model: cp_model.CpModel
    x: dict[tuple[str, str], cp_model.IntVar]  # (field, policy) -> var
    z: dict[str, cp_model.IntVar]
    primary: cp_model.LinearExpr | cp_model.IntVar
    opex_expr: cp_model.LinearExpr
    capex_expr: cp_model.LinearExpr
    withdrawal_expr: cp_model.LinearExpr
    options: dict[tuple[str, str], Option]
    constant_capex: int
    constant_opex: int
    n_resource_constraints: int
    infeasible_reason: str | None = None


def build(p: Problem, c: ConfigSpec) -> BuiltModel:
    m = cp_model.CpModel()
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    opts: dict[tuple[str, str], Option] = {}
    reason = c.excluded_reason
    for f in p.fields:
        olist = c.options.get(f, [])
        if p.fixed_selection is not None:
            olist = [o for o in olist if o.policy_id == p.fixed_selection.get(f)]
        if not olist and reason is None:
            reason = (
                c.empty_fields.get(f) or f"field {f} has no admissible candidate in {c.config_id}"
            )
        for o in sorted(olist, key=lambda o: o.policy_id):
            v = m.new_bool_var(f"x[{f}|{o.policy_id}]")
            x[(f, o.policy_id)] = v
            opts[(f, o.policy_id)] = o
        m.add_exactly_one([x[(f, o.policy_id)] for o in olist] or [m.new_constant(0)])
    if reason is not None:
        m.add_bool_or([])  # an empty clause: the finite model is infeasible by construction
    # instance purchase variables (field-level instances; repairs are fixed by the configuration)
    users: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    for key, o in opts.items():
        for j in o.required_instance_ids:
            users[j].append(x[key])
    z: dict[str, cp_model.IntVar] = {}
    for j in sorted(users):
        z[j] = m.new_bool_var(f"z[{j}]")
        for xv in users[j]:
            m.add_implication(xv, z[j])  # x <= z
        m.add(z[j] <= sum(users[j]))  # no unused purchases
        if j in p.excluded_instance_ids:
            m.add(z[j] == 0)
    for j in p.forced_instance_ids:
        if j in c.repair_instance_ids:
            continue
        if j in z:
            m.add(z[j] == 1)
        else:
            m.add_bool_or([])  # forced instance unusable in this configuration
            reason = reason or f"forced instance {j} has no admissible candidate in {c.config_id}"
    groups: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    for j, zv in z.items():
        g = p.instances[j].exclusive_group if j in p.instances else None
        if g:
            groups[g].append(zv)
    for g, zs in groups.items():
        if len(zs) > 1:
            m.add_at_most_one(zs)
    capex_terms = [(p.instances[j].capex_pkr if j in p.instances else 0, zv) for j, zv in z.items()]
    capex_expr = sum(cv * zv for cv, zv in capex_terms if cv)
    inst_opex = sum(
        (p.instances[j].opex_pkr if j in p.instances else 0) * zv for j, zv in z.items()
    )
    pol_opex = sum(o.opex_pkr * x[k] for k, o in opts.items() if o.opex_pkr)
    opex_expr = pol_opex + inst_opex
    if p.apply_budgets and p.capital_budget_pkr is not None:
        add_le(m, capex_expr + c.capex_pkr, p.capital_budget_pkr)
    if p.apply_budgets and p.operating_budget_pkr is not None:
        add_le(m, opex_expr + c.opex_pkr, p.operating_budget_pkr)
    # shared resources in every required state
    q = p.water_quantum_m3
    n_res = 0
    for s in p.states:
        caps = c.capacities.get(s, {})
        if not caps:
            continue
        use_terms: dict[ResKey, list[tuple[int, cp_model.IntVar]]] = defaultdict(list)
        per_field_max: dict[ResKey, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for k, o in opts.items():
            for rk, vol in o.resources.get(s, {}).items():
                if rk not in caps or vol <= 0:
                    continue
                cq = consumption_quanta(vol, q)
                use_terms[rk].append((cq, x[k]))
                fm = per_field_max[rk]
                fm[o.field_id] = max(fm[o.field_id], cq)
        for rk, terms in use_terms.items():
            capq = capacity_quanta(caps[rk], q)
            if sum(per_field_max[rk].values()) <= capq:
                continue  # cannot bind; omit (slack by construction)
            if sum(a for a, _ in terms) > INT_SAFE:
                raise OverflowError(
                    f"resource {rk} coefficients exceed safe integer range; increase quantum"
                )
            add_le(m, sum(a * v for a, v in terms), capq)
            n_res += 1
    # objective
    wq = {
        k: consumption_quanta(
            sum(o.withdrawal_m3.get(s, 0.0) for s in [p.tie_state or p.objective_states[0]]), q
        )
        for k, o in opts.items()
    }
    withdrawal_expr = sum(wq[k] * x[k] for k in opts if wq[k])
    exprs = []
    for s in p.objective_states:
        exprs.append(sum(objective_coef(p, o, s) * x[k] for k, o in opts.items()))
    if len(exprs) == 1:
        primary = exprs[0]
    else:
        lo = min(
            0,
            *(
                sum(min(0, objective_coef(p, o, s)) for o in opts.values())
                for s in p.objective_states
            ),
        )
        hi = max(
            sum(max(0, objective_coef(p, o, s)) for o in opts.values()) for s in p.objective_states
        )
        v = m.new_int_var(lo, max(hi, lo), "worst_case_objective")
        for e in exprs:
            m.add(v <= e)
        primary = v
    if p.hint:
        for (f, pid), xv in x.items():
            m.add_hint(xv, 1 if p.hint.get(f) == pid else 0)
    return BuiltModel(
        model=m,
        x=x,
        z=z,
        primary=primary,
        opex_expr=opex_expr,
        capex_expr=capex_expr,
        withdrawal_expr=withdrawal_expr,
        options=opts,
        constant_capex=c.capex_pkr,
        constant_opex=c.opex_pkr,
        n_resource_constraints=n_res,
        infeasible_reason=reason,
    )


def service_ok(credit_m3: float, required_m3: float, q: float = DEFAULT_WATER_QUANTUM_M3) -> bool:
    """Conservative lower-bound service check (T6.2)."""
    return credited_service_quanta(credit_m3, q) >= required_service_quanta(required_m3, q)
