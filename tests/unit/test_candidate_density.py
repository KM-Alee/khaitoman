"""Density recipe refusal and real comparison failure paths; TEST FIXTURE solves only."""

import json
from types import SimpleNamespace

import pytest

from aabflow.domain.schemas import SolverStatus
from aabflow.optimizer.candidates import CandidateError, adequacy


def test_retained_recipe_refuses_unknown_generator(tmp_path, monkeypatch):
    monkeypatch.setattr(adequacy, "libraries_dir", lambda: tmp_path)
    directory = tmp_path / "TEST-FIXTURE" / "season"
    directory.mkdir(parents=True)
    assert adequacy.retained_templates("TEST-FIXTURE", "season") is None
    (directory / "density.json").write_text(json.dumps({"recipe": "unknown"}))
    with pytest.raises(CandidateError, match="unsupported"):
        adequacy.retained_templates("TEST-FIXTURE", "season")


@pytest.mark.parametrize(
    "status", [SolverStatus.FEASIBLE, SolverStatus.UNKNOWN, SolverStatus.INFEASIBLE]
)
def test_stability_rejects_unproved_comparison(status, monkeypatch):
    monkeypatch.setattr(adequacy, "prepare", lambda *args, **kw: SimpleNamespace(problem=None))
    monkeypatch.setattr(
        adequacy, "solve_problem", lambda *args, **kw: SimpleNamespace(status=status, best=None)
    )
    library = SimpleNamespace(candidate_library_hash="TEST-FIXTURE")
    with pytest.raises(CandidateError, match="proved optimum"):
        adequacy.solve_comparison(None, None, None, None, None, (library, []), 1)


@pytest.mark.parametrize("bad_ledger", [True, False])
def test_stability_rejects_physical_and_budget_violation(bad_ledger, monkeypatch):
    prepared = SimpleNamespace(
        problem=None, states=[SimpleNamespace(state_id="TEST-FIXTURE")], policies={}
    )
    best = SimpleNamespace(selection={}, config_id="TEST-FIXTURE")
    monkeypatch.setattr(adequacy, "prepare", lambda *args, **kw: prepared)
    monkeypatch.setattr(
        adequacy,
        "solve_problem",
        lambda *args, **kw: SimpleNamespace(status=SolverStatus.OPTIMAL, best=best),
    )
    monkeypatch.setattr(adequacy, "verify_selection", lambda *args: [SimpleNamespace(passed=False)])
    bindings = SimpleNamespace(
        reconstruct=lambda *args, **kw: (
            [],
            SimpleNamespace(status="failed" if bad_ledger else "passed"),
        )
    )
    library = SimpleNamespace(candidate_library_hash="TEST-FIXTURE")
    with pytest.raises(
        CandidateError, match="invalid physical ledger" if bad_ledger else "invalid budget/service"
    ):
        adequacy.solve_comparison(bindings, None, None, None, None, (library, []), 1)
