"""Optimizer core on synthetic TEST FIXTURE problems: T12.2, configurations, budgets, robust."""

import itertools
import random

from aabflow.domain.schemas import SolverStatus
from aabflow.optimizer.configurations import ConfigResult, global_status, solve_problem
from aabflow.optimizer.model import ConfigSpec, InstanceSpec, Option, Problem

S = "typical__nominal"


def opt(pid, f, water, prod, inst=(), opex=0, states=(S,), res="source:src"):
    return Option(
        policy_id=pid,
        field_id=f,
        required_instance_ids=tuple(inst),
        opex_pkr=opex,
        production_kg={s: prod for s in states},
        resources={s: {(res, "t0"): water} for s in states},
        service_credit_m3={s: water for s in states},
        withdrawal_m3={s: water for s in states},
    )


def t122(capital):
    a = [
        opt("A-low", "A", 60, 350),
        opt("A-base", "A", 100, 500),
        opt("A-lev", "A", 80, 550, ["lev-A"]),
    ]
    b = [
        opt("B-low", "B", 50, 300),
        opt("B-base", "B", 90, 450),
        opt("B-lev", "B", 70, 480, ["lev-B"]),
    ]
    cfg = ConfigSpec(
        "cfg:base", options={"A": a, "B": b}, capacities={S: {("source:src", "t0"): 180}}
    )
    inst = {"lev-A": InstanceSpec("lev-A", 60), "lev-B": InstanceSpec("lev-B", 60)}
    return Problem(["A", "B"], [S], [S], [cfg], inst, capital, 10**9, production_quantum_kg=1.0)


def test_t122_unique_optimum_capital_60():
    out = solve_problem(t122(60), workers=1, time_limit_s=5)
    assert out.status is SolverStatus.OPTIMAL
    assert out.selection == {"A": "A-lev", "B": "B-base"}
    assert out.best.primary == 1000 and out.best.capex_pkr == 60


def test_t122_zero_capital_tie_set_and_no_new_assets():
    out = solve_problem(t122(0), workers=1, time_limit_s=5)
    assert out.status is SolverStatus.OPTIMAL and out.best.primary == 800
    assert out.selection in ({"A": "A-base", "B": "B-low"}, {"A": "A-low", "B": "B-base"})
    assert out.best.instances == [] and out.best.capex_pkr == 0  # AT05
    # lexicographic tie-break: lower withdrawal wins among equal production (160 < 140? no: 150 vs 160)
    assert out.best.withdrawal_q == min(100 + 50, 60 + 90) * 10


def brute(p):
    c = p.configs[0]
    best = None
    for combo in itertools.product(*[c.options[f] for f in p.fields]):
        insts = {j for o in combo for j in o.required_instance_ids}
        if sum(p.instances[j].capex_pkr for j in insts) + c.capex_pkr > p.capital_budget_pkr:
            continue
        if sum(o.opex_pkr for o in combo) > p.operating_budget_pkr:
            continue
        ok = all(
            sum(o.resources[S].get(k, 0) for o in combo) <= cap
            for k, cap in c.capacities[S].items()
        )
        if not ok:
            continue
        val = sum(int(o.production_kg[S] / p.production_quantum_kg) for o in combo)
        best = val if best is None else max(best, val)
    return best


def test_random_problems_match_enumeration():
    rng = random.Random(7)
    for trial in range(25):
        fields = [f"f{i}" for i in range(4)]
        options = {}
        for f in fields:
            options[f] = [
                opt(
                    f"{f}-{k}",
                    f,
                    rng.randint(0, 60),
                    rng.randint(0, 900),
                    [f"i-{f}"] if k == 2 else (),
                    opex=rng.randint(0, 30),
                )
                for k in range(3)
            ]
        cfg = ConfigSpec(
            "cfg:base",
            options=options,
            capacities={S: {("source:src", "t0"): rng.randint(40, 200)}},
        )
        inst = {f"i-{f}": InstanceSpec(f"i-{f}", rng.randint(10, 80)) for f in fields}
        p = Problem(
            fields,
            [S],
            [S],
            [cfg],
            inst,
            rng.randint(0, 150),
            rng.randint(20, 100),
            production_quantum_kg=1.0,
        )
        out = solve_problem(p, workers=1, time_limit_s=5)
        exp = brute(p)
        if exp is None:
            assert out.status is SolverStatus.INFEASIBLE, trial
        else:
            assert out.status is SolverStatus.OPTIMAL and out.best.primary == exp, trial


def test_shared_repair_configuration_charged_once_and_global_optimal():
    # tail fields gain only under the repair configuration; capex counted once for both fields
    base = ConfigSpec(
        "cfg:base", options={"t1": [opt("t1-b", "t1", 10, 100)], "t2": [opt("t2-b", "t2", 10, 100)]}
    )
    rep = ConfigSpec(
        "cfg:rep",
        repair_instance_ids=("rep",),
        capex_pkr=500,
        options={"t1": [opt("t1-r", "t1", 10, 300)], "t2": [opt("t2-r", "t2", 10, 300)]},
    )
    p = Problem(
        ["t1", "t2"],
        [S],
        [S],
        [base, rep],
        {"rep": InstanceSpec("rep", 500)},
        500,
        0,
        production_quantum_kg=1.0,
    )
    out = solve_problem(p, workers=1, time_limit_s=5)
    assert out.status is SolverStatus.OPTIMAL and out.best.config_id == "cfg:rep"
    assert out.best.capex_pkr == 500 and out.best.primary == 600  # AT12: once, not 1000
    p.capital_budget_pkr = 499
    out = solve_problem(p, workers=1, time_limit_s=5)
    assert out.best.config_id == "cfg:base" and out.best.primary == 200


def test_mutually_exclusive_and_forced_excluded():
    f = [
        opt("s", "f", 0, 200, ["pond-s"]),
        opt("l", "f", 0, 260, ["pond-l"]),
        opt("n", "f", 0, 100),
    ]
    cfg = ConfigSpec("cfg:base", options={"f": f})
    inst = {
        "pond-s": InstanceSpec("pond-s", 10, exclusive_group="g"),
        "pond-l": InstanceSpec("pond-l", 20, exclusive_group="g"),
    }
    p = Problem(["f"], [S], [S], [cfg], inst, 100, 100, production_quantum_kg=1.0)
    assert solve_problem(p, workers=1).selection == {"f": "l"}
    p.excluded_instance_ids = {"pond-l"}
    assert solve_problem(p, workers=1).selection == {"f": "s"}
    p.excluded_instance_ids = set()
    p.forced_instance_ids = {"pond-s"}
    assert solve_problem(p, workers=1).selection == {"f": "s"}
    p.capital_budget_pkr = 5
    assert solve_problem(p, workers=1).status is SolverStatus.INFEASIBLE


def test_operating_budget_limits_pumping():
    f = [opt("pump", "f", 0, 500, opex=100), opt("canal", "f", 0, 300)]
    p = Problem(
        ["f"],
        [S],
        [S],
        [ConfigSpec("cfg:base", options={"f": f})],
        {},
        0,
        99,
        production_quantum_kg=1.0,
    )
    assert solve_problem(p, workers=1).selection == {"f": "canal"}
    p.operating_budget_pkr = 100
    assert solve_problem(p, workers=1).selection == {"f": "pump"}


def test_robust_maximizes_worst_state():
    W, D = "wet__n", "dry__n"
    f = [
        Option(
            "risky", "f", production_kg={W: 900, D: 100}, resources={}, withdrawal_m3={W: 0, D: 0}
        ),
        Option(
            "safe", "f", production_kg={W: 500, D: 400}, resources={}, withdrawal_m3={W: 0, D: 0}
        ),
    ]
    cfg = ConfigSpec("cfg:base", options={"f": f})
    typical = Problem(["f"], [W], [W], [cfg], {}, 0, 0, production_quantum_kg=1.0)
    robust = Problem(["f"], [W, D], [W, D], [cfg], {}, 0, 0, production_quantum_kg=1.0)
    assert solve_problem(typical, workers=1).selection == {"f": "risky"}
    out = solve_problem(robust, workers=1)
    assert out.selection == {"f": "safe"} and out.best.primary == 400


def test_empty_option_set_is_infeasible_with_reason():
    cfg = ConfigSpec(
        "cfg:base", options={"f": []}, empty_fields={"f": "service floor unmet by every candidate"}
    )
    out = solve_problem(Problem(["f"], [S], [S], [cfg], {}, 0, 0), workers=1)
    assert out.status is SolverStatus.INFEASIBLE
    assert "service floor" in out.configs[0].reason


def test_global_status_rules():
    def r(cid, st, prim, bound):
        return ConfigResult(cid, st, prim, bound, 0, opex_pkr=0, capex_pkr=0, withdrawal_q=0)

    st, best, ub = global_status(
        [r("a", SolverStatus.OPTIMAL, 10, 10), r("b", SolverStatus.INFEASIBLE, None, None)]
    )
    assert st is SolverStatus.OPTIMAL and best.config_id == "a" and ub == 10
    st, _, ub = global_status(
        [r("a", SolverStatus.OPTIMAL, 10, 10), r("b", SolverStatus.UNKNOWN, None, 12)]
    )
    assert st is SolverStatus.FEASIBLE and ub == 12
    st, _, _ = global_status(
        [r("a", SolverStatus.OPTIMAL, 10, 10), r("b", SolverStatus.UNKNOWN, None, None)]
    )
    assert st is SolverStatus.FEASIBLE
    st, _, _ = global_status(
        [r("a", SolverStatus.INFEASIBLE, None, None), r("b", SolverStatus.UNKNOWN, None, 5)]
    )
    assert st is SolverStatus.UNKNOWN
    st, _, _ = global_status([r("a", SolverStatus.INFEASIBLE, None, None)])
    assert st is SolverStatus.INFEASIBLE
