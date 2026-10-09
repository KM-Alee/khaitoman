"""T12.2 enumerable two-field fixture: CP-SAT must find the hand-computed optimum."""

from ortools.sat.python import cp_model

OPTIONS = {
    "A": {"low": (60, 350, 0), "base": (100, 500, 0), "leveled": (80, 550, 60)},
    "B": {"low": (50, 300, 0), "base": (90, 450, 0), "leveled": (70, 480, 60)},
}


def solve(water_cap: int, capital: int) -> tuple[int, dict[str, str]]:
    m = cp_model.CpModel()
    x = {(f, o): m.new_bool_var(f"{f}_{o}") for f, opts in OPTIONS.items() for o in opts}
    for f, opts in OPTIONS.items():
        m.add_exactly_one(x[f, o] for o in opts)
    m.add(sum(OPTIONS[f][o][0] * v for (f, o), v in x.items()) <= water_cap)
    m.add(sum(OPTIONS[f][o][2] * v for (f, o), v in x.items()) <= capital)
    m.maximize(sum(OPTIONS[f][o][1] * v for (f, o), v in x.items()))
    s = cp_model.CpSolver()
    s.parameters.num_workers = 1
    s.parameters.random_seed = 0
    assert s.solve(m) == cp_model.OPTIMAL
    pick = {f: o for (f, o), v in x.items() if s.value(v)}
    return int(s.objective_value), pick


def test_capital_60_unique_optimum():
    assert solve(180, 60) == (1000, {"A": "leveled", "B": "base"})


def test_zero_capital_tie_set():
    value, pick = solve(180, 0)
    assert value == 800
    assert pick in ({"A": "base", "B": "low"}, {"A": "low", "B": "base"})
