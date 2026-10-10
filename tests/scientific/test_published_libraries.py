"""P01: real reviewed pilot packages and exact, published crop libraries (T5.5–T5.7).

Requires `make candidates PILOT=pilot-a` and `make candidates PILOT=pilot-b`.
Missing artifacts fail this gate; they never become skipped acceptance evidence.
"""

import json
from collections import defaultdict

import pytest

from aabflow.optimizer.candidates import load_library
from aabflow.science import crop_profiles
from aabflow.science.experiments import experiment_dir, load_outcome, load_trajectory
from aabflow.science.paths import experiments_dir, libraries_dir
from aabflow.water.context import load_pilot
from aabflow.water.ledger import build_season_context, reconstruct

pytestmark = pytest.mark.scientific


@pytest.fixture(
    scope="module",
    params=[
        (pilot, season) for pilot in ("pilot-a", "pilot-b") for season in crop_profiles.SEASONS
    ],
    ids=lambda pair: "/".join(pair),
)
def published(request):
    pilot, season = request.param
    latest_path = libraries_dir() / pilot / season / "latest.json"
    assert latest_path.is_file(), f"run make candidates PILOT={pilot}"
    latest = json.loads(latest_path.read_text())
    lib, policies = load_library(pilot, season)
    ctx = build_season_context(load_pilot(pilot, lib.pilot_version), season)
    groups = defaultdict(list)
    for policy in policies:
        groups[(policy.field_id, policy.shared_configuration_id)].append(policy)
    return latest, lib, policies, ctx, groups


def test_published_field_configuration_and_state_coverage(published):
    latest, lib, policies, ctx, groups = published
    assert not ctx.pilot.is_test_fixture
    assert len(ctx.pilot.fields) >= 30
    assert latest["candidate_library_hash"] == lib.candidate_library_hash
    assert latest["pilot_version"] == lib.pilot_version == ctx.pilot.pilot_version
    assert latest["policies"] == len(policies) == lib.build_stats["policies_retained"]
    assert set(groups) == {(fid, cid) for fid in ctx.pilot.fields for cid in ctx.configs}
    assert set(lib.state_ids) == set(ctx.state_ids())
    expected_weather = {"dry", "typical", "wet"}
    if ctx.season.weather_basis == "actual":
        expected_weather.add("actual")
    assert set(lib.weather_scenario_ids) == expected_weather
    assert len(lib.state_ids) == len(expected_weather) * 3
    assert len({p.candidate_policy_id for p in policies}) == len(policies)
    assert sum(row.retained for row in lib.coverage) == len(policies)
    for group in groups.values():
        assert any(p.family == "baseline_B0" for p in group)
        rain = next(p for p in group if p.family == "rainfed")
        assert not rain.receipt_events and not rain.pump_events and not rain.required_instance_ids
        assert rain.gross_application_mm == 0
        assert all(o.deliverable for o in rain.outcomes)
        for policy in group:
            assert {o.state_id for o in policy.outcomes} == set(lib.state_ids)
            assert policy.crop_profile_id == ctx.crop.crop_profile_id
            assert not set(policy.required_instance_ids) & set(lib.excluded_instances)
            for outcome in policy.outcomes:
                if outcome.deliverable:
                    assert outcome.crop_outcome_hash and outcome.yield_kg_ha is not None
                    assert outcome.production_kg == pytest.approx(
                        policy.cropped_area_ha * outcome.yield_kg_ha
                    )
                else:
                    assert outcome.violations
                    assert outcome.yield_kg_ha is None and outcome.production_kg is None


def test_published_exact_outcomes_and_raw_artifacts(published):
    _, _, policies, ctx, _ = published
    checked = set()
    for policy in policies:
        for state in policy.outcomes:
            if not state.deliverable:
                continue
            outcome = load_outcome(state.crop_outcome_hash)
            assert outcome is not None, "rebuild candidates to restore the exact experiment cache"
            assert outcome.has_finished and outcome.actual_harvest_date
            assert outcome.yield_kg_ha == pytest.approx(state.yield_kg_ha)
            assert outcome.seasonal_irrigation_mm == pytest.approx(policy.gross_application_mm)
            assert outcome.crop_profile_id == policy.crop_profile_id
            assert outcome.soil_profile_id == policy.soil_profile_id
            assert (
                outcome.weather_sha256 == ctx.weather[state.weather_scenario_id].transformed_sha256
            )
            if outcome.experiment_hash in checked:
                continue
            checked.add(outcome.experiment_hash)
            assert (experiment_dir(outcome.experiment_hash) / "experiment.json").is_file()
            assert outcome.raw_output_refs
            assert all((experiments_dir() / ref).is_file() for ref in outcome.raw_output_refs)
    # Audit trajectories for distinct rainfed/irrigated policies at each soil/efficiency.
    sampled = set()
    for policy in policies:
        key = (
            policy.soil_profile_id,
            policy.application_efficiency,
            bool(policy.application_schedule),
        )
        if key in sampled:
            continue
        state = next(o for o in policy.outcomes if o.deliverable)
        trajectory = load_trajectory(load_outcome(state.crop_outcome_hash))
        assert trajectory.gross_irrigation_mm.sum() == pytest.approx(policy.gross_application_mm)
        sampled.add(key)
    assert {key[2] for key in sampled} == {False, True}


def test_published_portfolios_reconstruct_at_original_precision(published):
    _, lib, policies, ctx, groups = published
    policy_map = {p.candidate_policy_id: p for p in policies}
    for cid in ctx.configs:
        selected = {
            fid: next(p for p in groups[(fid, cid)] if p.family == "rainfed")
            for fid in ctx.pilot.fields
        }
        # One irrigating field plus rainfed peers: checks routing without assuming a
        # collection of individually valid policies meets aggregate capacity.
        irrigated = next(
            p
            for p in policies
            if p.shared_configuration_id == cid
            and p.receipt_events
            and not p.pump_events
            and not p.pond_events
            and next(o.deliverable for o in p.outcomes if o.state_id == lib.typical_state_id)
        )
        selected[irrigated.field_id] = irrigated
        events, report = reconstruct(
            [p.candidate_policy_id for p in selected.values()],
            lib,
            lib.typical_state_id,
            cid,
            ctx=ctx,
            policies=policy_map,
        )
        assert events
        assert report.status == "passed", [r for r in report.residuals if not r.passed]
