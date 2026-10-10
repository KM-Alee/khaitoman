"""Real stored denser-library solves and retained publication evidence (T5.7).

Requires make library-adequacy; missing artifacts fail rather than skip.
"""

import json

import pytest

from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import CandidateLibrary
from aabflow.optimizer.candidates import load_library
from aabflow.optimizer.candidates.adequacy import DENSITY_RECIPE, REPRESENTATIVE_SEASONS
from aabflow.science.paths import libraries_dir

pytestmark = pytest.mark.scientific


@pytest.mark.parametrize("pilot", ["pilot-a", "pilot-b"])
@pytest.mark.parametrize("season", REPRESENTATIVE_SEASONS)
def test_density_objective_actions_and_retained_larger_library(pilot, season):
    directory = libraries_dir() / pilot / season
    assert (directory / "adequacy.json").is_file(), "run make library-adequacy"
    report = json.loads((directory / "adequacy.json").read_text())
    recorded_hash = report.pop("evidence_hash")
    report.pop("created_at")
    assert content_hash(report) == recorded_hash
    record = json.loads((directory / "density.json").read_text())
    assert record["evidence_hash"] == recorded_hash
    assert record["recipe"] == DENSITY_RECIPE
    coarse = CandidateLibrary.model_validate_json(
        (directory / record["baseline_hash"] / "library.json").read_text()
    )
    policies_path = directory / record["retained_hash"] / "policies.jsonl"
    assert policies_path.is_file(), f"missing {policies_path}; run make candidates PILOT={pilot}"
    dense, policies = load_library(pilot, season)
    assert dense.candidate_library_hash == record["retained_hash"] == report["retained_hash"]
    assert coarse.candidate_library_hash == report["baseline_hash"]
    assert len(policies) == report["dense_policies"] > report["coarse_policies"]
    assert len(report["comparisons"]) == 5
    assert {r["scenario"] for r in report["comparisons"]} == {
        "no_capital",
        "small_budget",
        "capital",
        "shortage",
        "robust_nine_states",
    }
    for comparison in report["comparisons"]:
        before, after = comparison["coarse"], comparison["dense"]
        assert before["solver_status"] == after["solver_status"] == "OPTIMAL"
        assert before["physical_validation"] == after["physical_validation"] == "passed"
        assert before["states_validated"] == after["states_validated"]
        assert len(after["states_validated"]) == (9 if comparison["plan_kind"] == "R" else 1)
        assert after["primary_quanta"] >= before["primary_quanta"]
        assert after["upper_bound_quanta"] == after["primary_quanta"]
        assert after["capital_pkr"] <= comparison["request"]["capital_budget_pkr"]
        assert after["operating_pkr"] <= comparison["request"]["operating_budget_pkr"]
        assert comparison["objective_delta_kg"] == pytest.approx(
            after["objective_kg"] - before["objective_kg"]
        )
        assert comparison["investment_changed"] == (
            before["investment_ids"] != after["investment_ids"]
        )
        assert report["approximation"]
