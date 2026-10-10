"""T3.6 immutable publication and clean-checkout restoration. TEST FIXTURE policies."""

from datetime import UTC, datetime, timedelta

import pytest

from aabflow.domain.schemas import CandidateLibrary, CandidatePolicy
from aabflow.optimizer.candidates import BuildResult, CandidateError, publish_library
from aabflow.science import paths


@pytest.fixture
def publication(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    policy = CandidatePolicy(
        candidate_policy_id="TEST FIXTURE policy",
        candidate_policy_hash="a" * 64,
        field_id="fixture-field",
        crop_profile_id="fixture-crop",
        soil_profile_id="fixture-soil",
        shared_configuration_id="cfg:base",
        family="rainfed",
        application_efficiency=0.6,
        cropped_area_ha=1,
        outcomes=[],
        generator_version="TEST FIXTURE",
    )
    lib = CandidateLibrary(
        candidate_library_hash="b" * 64,
        pilot_id="fixture-pilot",
        pilot_version="fixture-v1",
        season_id="fixture-season",
        state_ids=[],
        configurations=[],
        policies_ref=f"fixture-pilot/fixture-season/{'b' * 64}/policies.jsonl",
        coverage=[],
        generator_version="TEST FIXTURE",
        created_at=datetime(2026, 10, 10, tzinfo=UTC),
        build_stats={"experiments_executed": 1},
    )
    result = BuildResult(lib, [policy], lib.build_stats)
    publish_library(result)
    directory = paths.libraries_dir() / lib.pilot_id / lib.season_id / lib.candidate_library_hash
    return result, directory


def test_rebuild_preserves_original_metadata_and_creation_time(publication):
    result, directory = publication
    metadata = (directory / "library.json").read_bytes()
    rebuilt = result.library.model_copy(
        update={
            "created_at": result.library.created_at + timedelta(hours=1),
            "build_stats": {"experiments_executed": 0, "experiments_cached": 1},
        }
    )
    published = publish_library(BuildResult(rebuilt, result.policies, rebuilt.build_stats))
    assert published.created_at == result.library.created_at
    assert (
        published.build_stats["experiments_executed"] == 0
    )  # current benchmark, not stored metadata
    assert (directory / "library.json").read_bytes() == metadata


def test_clean_checkout_restores_policy_dump_without_rewriting_metadata(publication):
    result, directory = publication
    metadata = (directory / "library.json").read_bytes()
    policies = (directory / "policies.jsonl").read_bytes()
    (directory / "policies.jsonl").unlink()
    publish_library(result)
    assert (directory / "library.json").read_bytes() == metadata
    assert (directory / "policies.jsonl").read_bytes() == policies


@pytest.mark.parametrize("change", ["metadata", "policy"])
def test_same_hash_with_changed_content_is_refused(publication, change):
    result, directory = publication
    original = {path.name: path.read_bytes() for path in directory.iterdir()}
    if change == "metadata":
        result.library = result.library.model_copy(update={"generator_version": "changed"})
    else:
        result.policies = [result.policies[0].model_copy(update={"cropped_area_ha": 2})]
    with pytest.raises(CandidateError, match="immutable"):
        publish_library(result)
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == original
