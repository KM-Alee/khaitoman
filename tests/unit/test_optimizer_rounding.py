"""Conservative integer scaling (T6.2) must not reject a policy that uses exactly a capacity
that is not a multiple of the water quantum (e.g. a pond filled to its usable volume). TEST FIXTURE."""

import pytest

from aabflow.domain.schemas import SolverStatus
from aabflow.optimizer.configurations import solve_problem
from aabflow.optimizer.model import ConfigSpec, Option, Problem, resource_scale, resource_use_quanta

S = "typical__nominal"
POND = ("pond:p1", "season")


def problem(cap: float, uses: dict[str, float]) -> Problem:
    opts = {
        f: [
            Option(policy_id=f"{f}-zero", field_id=f, production_kg={S: 10.0}),
            Option(
                policy_id=f"{f}-pond",
                field_id=f,
                production_kg={S: 100.0},
                resources={S: {POND: v}},
            ),
        ]
        for f, v in uses.items()
    }
    cfg = ConfigSpec("cfg:base", options=opts, capacities={S: {POND: cap}})
    return Problem(sorted(uses), [S], [S], [cfg], {}, None, None, production_quantum_kg=1.0)


@pytest.mark.parametrize("cap", [577.04, 413.987654, 0.15, 1e6 + 0.05])
def test_exact_capacity_use_is_admissible(cap):
    out = solve_problem(problem(cap, {"A": cap}), workers=1, time_limit_s=2)
    assert out.status is SolverStatus.OPTIMAL and out.selection == {"A": "A-pond"}


def test_rounding_stays_conservative_at_original_precision():
    cap = 577.04
    out = solve_problem(problem(cap, {"A": 300.0, "B": 277.05}), workers=1, time_limit_s=2)
    # 300 + 277.05 = 577.05 > 577.04: both cannot fill
    assert (
        sorted(out.selection.values()).count("A-pond")
        + sorted(out.selection.values()).count("B-pond")
        == 1
    )
    # conservative margin is at most one per-resource quantum per sharing field
    out = solve_problem(problem(cap, {"A": 300.0, "B": 276.84}), workers=1, time_limit_s=2)
    assert set(out.selection.values()) == {"A-pond", "B-pond"}


def test_scale_properties():
    for cap in (577.04, 0.3, 12345.678, 0.0):
        q_r, n = resource_scale(cap, 0.1)
        assert q_r >= 0.1 - 1e-12
        assert n * q_r == pytest.approx(cap)
    q_r, n = resource_scale(577.04, 0.1)
    assert resource_use_quanta(577.04, q_r) == n
    assert resource_use_quanta(577.04 + 1e-3, q_r) == n + 1
    assert resource_use_quanta(0.0, q_r) == 0
