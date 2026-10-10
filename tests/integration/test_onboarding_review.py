"""Versioned review, structural publish blocks, and pilot-b reviewed-v2.

The real publish reuses the Delineate cache. It does not start a vision process
and it does not replace ``reviewed-v1``.
"""

from __future__ import annotations

import json
import shutil

import pytest

from aabflow import config
from aabflow.domain.hashes import file_sha256
from aabflow.ingestion.imagery import delineate
from aabflow.ingestion.onboarding.libraries import assess, write_readiness
from aabflow.ingestion.packages.validate import PackageValidationError
from aabflow.ingestion.pilot_aois import PILOT_B
from aabflow.jobs import queue
from aabflow.jobs.worker import JobContext
from aabflow.repositories.sqlite import connect
from aabflow.services.onboarding.jobs import (
    baseline_job,
    candidate_job,
    enqueue_readiness,
    process_job,
)
from tests.fixtures.api_app import settings_for
from tests.integration.test_onboarding_support import (
    PILOT_B_BUNDLE,
    PILOT_B_INFERENCE_KEY,
    POLY,
    onboarding_client,
)

NETWORK = {
    "direction": "downstream",
    "source_feature_id": "osm:way/488499235",
    "capacity_m3_s": 0.10,
    "roster_basis": "declared_cca",
    "outlet": "reach_group",
    "acknowledged": True,
}


def _rewrite(path, **changes):
    document = json.loads(path.read_text())
    document.update(changes)
    path.write_text(json.dumps(document))
    return document


def test_review_rejections_structural_block_and_library_flags(tmp_path, monkeypatch):
    with onboarding_client(tmp_path) as client:
        created = client.post("/api/v2/onboarding", json={"aoi": POLY, "source_mode": "online"})
        assert created.status_code == 201, created.text
        onboarding_id = created.json()["onboarding_id"]
        path = tmp_path / "onboarding" / onboarding_id / "intake.json"
        processed = path.parent / "processed"
        processed.mkdir()
        (processed / "fields_raw.geojson").write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": "m1",
                            "geometry": POLY,
                            "properties": {"model_id": "m1"},
                        }
                    ],
                }
            )
        )
        (processed / "canals.geojson").write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {"type": "Feature", "id": NETWORK["source_feature_id"], "geometry": None}
                    ],
                }
            )
        )
        _rewrite(path, state="needs_review")
        empty_reason = client.patch(
            f"/api/v2/onboarding/{onboarding_id}/review",
            json={
                "expected_version": 0,
                "field_edits": [{"model_id": "m1", "action": "reject", "reason": ""}],
            },
        )
        assert empty_reason.status_code == 422, empty_reason.text
        assert empty_reason.json()["code"] == "INVALID_INPUT"
        assert "reason" in empty_reason.json()["detail"]
        assert json.loads(path.read_text())["review_version"] == 0
        over_capacity = client.patch(
            f"/api/v2/onboarding/{onboarding_id}/review",
            json={
                "expected_version": 0,
                "review_config": {"network": {**NETWORK, "capacity_m3_s": 9}},
            },
        )
        assert over_capacity.status_code == 422, over_capacity.text
        assert "capacity" in over_capacity.json()["detail"]
        assert json.loads(path.read_text())["review_version"] == 0
        _rewrite(
            path,
            state="reviewed",
            review_blockers=["only 4 eligible fields after review; 30 required"],
        )
        blocked = client.post(
            f"/api/v2/onboarding/{onboarding_id}/publish",
            json={"pilot_id": "pilot-b", "pilot_version": "reviewed-v2"},
        )
        assert blocked.status_code == 422, blocked.text
        assert blocked.json()["code"] == "INVALID_INPUT"
        assert "structural" in blocked.json()["fields"]["publish"]
        assert "4 eligible" in blocked.json()["fields"]["publish"]
        _rewrite(path, review_blockers=[], review_summary={"selected": 30})
        missing_network = client.post(
            f"/api/v2/onboarding/{onboarding_id}/publish",
            json={"pilot_id": "pilot-b", "pilot_version": "reviewed-v2"},
        )
        assert missing_network.status_code == 422, missing_network.text
        assert "not reviewed" in missing_network.json()["fields"]["publish"]
        _rewrite(path, network_review=NETWORK)
        assert not (tmp_path / "pilots" / "pilot-b" / "reviewed-v2").exists()

        def fail_structure(*_args, **_kwargs):
            raise PackageValidationError(["manifest: sha256 mismatch fields.geojson"])

        monkeypatch.setattr(
            "aabflow.ingestion.onboarding.pipeline._build_validated_stage", fail_structure
        )
        invalid_package = client.post(
            f"/api/v2/onboarding/{onboarding_id}/publish",
            json={"pilot_id": "pilot-b", "pilot_version": "reviewed-v2"},
        )
        assert invalid_package.status_code == 422, invalid_package.text
        assert invalid_package.json()["fields"]["publish"] == "structural validation failed"
        assert not (tmp_path / "pilots" / "pilot-b" / "reviewed-v2").exists()
        assert not (tmp_path / "pilots" / "pilot-b" / "reviewed-v2.partial").exists()

    latest = tmp_path / "libraries" / "pilot-b" / "wheat-rabi-2027-28" / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text(
        json.dumps(
            {
                "candidate_library_hash": "abc",
                "pilot_version": "reviewed-v1",
                "policies": 3,
            }
        )
    )
    library = latest.parent / "abc"
    library.mkdir()
    (library / "library.json").write_text(
        json.dumps(
            {
                "pilot_version": "reviewed-v1",
                "coverage": [{"families": {"baseline_B0": 1, "rainfed": 1}}],
            }
        )
    )
    before_latest = latest.read_bytes()
    report = write_readiness(tmp_path, "pilot-b", "reviewed-v2")
    assert latest.read_bytes() == before_latest
    assert report["reused_as_current"] is False
    assert report["libraries"][0]["status"] == "flagged_incompatible"
    assert report["libraries"][0]["current"] is False
    assert report["baseline"]["ready"] is False
    assert report["candidates"]["ready"] is False
    flags = json.loads((tmp_path / "pilots" / "pilot-b" / "library_flags.json").read_text())
    assert flags["libraries"][0]["library_pilot_version"] == "reviewed-v1"
    from aabflow.repositories.sqlite import init_db

    settings = settings_for(tmp_path)
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    jobs = enqueue_readiness(conn, "onb_test", "pilot-b", "reviewed-v2", report)
    assert [job["operation"] for job in jobs] == ["onboarding.baseline", "onboarding.candidates"]
    ctx = JobContext(settings, jobs[0]["job_id"], "review", conn)
    baseline = baseline_job(ctx, {"pilot_id": "pilot-b", "pilot_version": "reviewed-v2"})
    candidates = candidate_job(
        ctx, {"pilot_id": "pilot-b", "pilot_version": "reviewed-v2", "kind": "candidates"}
    )
    assert baseline["ready"] is False and baseline["reused_as_current"] is False
    assert candidates["ready"] is False and candidates["built"] is False
    assert latest.read_bytes() == before_latest
    assert assess(tmp_path, "pilot-b", "reviewed-v2")["baseline"]["ready"] is False


def _manifest_ok(root):
    manifest = json.loads((root / "manifest.json").read_text())
    for item in manifest["files"]:
        path = root / item["path"]
        assert path.is_file(), item["path"]
        assert not path.is_symlink()
        assert file_sha256(path) == item["sha256"]
        assert path.stat().st_size == item["size_bytes"]
    return manifest


def test_pilot_b_review_publishes_reviewed_v2(tmp_path, monkeypatch):
    published = config.ROOT / "data" / "pilots" / "pilot-b"
    v1 = published / "reviewed-v1"
    v2 = published / "reviewed-v2"
    v1_before = file_sha256(v1 / "manifest.json")
    index_path = config.ROOT / "data" / "pilots" / "index.json"
    index_before = json.loads(index_path.read_text())
    v1_index = next(
        row
        for row in index_before
        if row["pilot_id"] == "pilot-b" and row["pilot_version"] == "reviewed-v1"
    )
    latest = config.ROOT / "data" / "libraries" / "pilot-b" / "wheat-rabi-2027-28" / "latest.json"
    latest_before = latest.read_bytes()
    run_record = config.ROOT / "vision" / "runs" / PILOT_B_INFERENCE_KEY / "run.json"
    batch = config.ROOT / "vision" / "batches" / f"{PILOT_B_INFERENCE_KEY}.yaml"
    before_run = run_record.read_bytes()
    before_batch = batch.read_bytes()
    runs = config.ROOT / "vision" / "runs"
    batches = config.ROOT / "vision" / "batches"
    runs_before = {path.name for path in runs.iterdir()}
    batches_before = {path.name for path in batches.iterdir()}
    existed = v2.exists()

    def no_new_vision(*args, **_kwargs):
        raise AssertionError(f"a new vision process was started: {args!r}")

    monkeypatch.setattr(delineate.subprocess, "run", no_new_vision)
    aoi = json.loads((config.ROOT / PILOT_B_BUNDLE / "aoi.geojson").read_text())
    saved_edits = json.loads(
        (config.ROOT / "data" / "pilots" / "review_edits" / "pilot-b.json").read_text()
    )
    try:
        with onboarding_client(tmp_path) as client:
            created = client.post(
                "/api/v2/onboarding",
                json={
                    "name": PILOT_B.name,
                    "aoi": aoi,
                    "source_mode": "raw_package",
                    "raw_package_ref": PILOT_B_BUNDLE,
                    "pilot_id": "pilot-b",
                    "geographic_name_basis": PILOT_B.geographic_name_basis,
                    "parent_canal_feature_id": f"osm:way/{PILOT_B.parent_canal_osm_way}",
                },
            )
            assert created.status_code == 201, created.text
            onboarding_id = created.json()["onboarding_id"]
        settings = settings_for(tmp_path)
        conn = connect(settings.db_path)
        job_id = queue.enqueue(
            conn,
            "onboarding.process",
            {"onboarding_id": onboarding_id},
            "pilot-b-review-publish",
            subject_id=onboarding_id,
        )
        result = process_job(
            JobContext(settings, job_id, "p07-review", conn),
            {"onboarding_id": onboarding_id},
        )
        assert result["cache_hit"] is True, result
        assert result["device"] == "cpu"
        assert result["inference_key"] == PILOT_B_INFERENCE_KEY
        assert result["state"] == "needs_review"
        recorded = json.loads(before_run)
        assert result["gpkg_sha256"] == recorded["outputs"]["scene.gpkg"]["sha256"]
        with onboarding_client(tmp_path) as client:
            stale = client.patch(
                f"/api/v2/onboarding/{onboarding_id}/review",
                json={"expected_version": 99, "field_edits": []},
            )
            assert stale.status_code == 409, stale.text
            assert stale.json()["code"] == "VERSION_CONFLICT"
            assert stale.json()["dependency_diff"]["review_version"] == 0
            unknown = client.patch(
                f"/api/v2/onboarding/{onboarding_id}/review",
                json={
                    "expected_version": 0,
                    "field_edits": [
                        {
                            "model_id": "da:not-a-real-polygon",
                            "action": "reject",
                            "reason": "not in the raw inference",
                        }
                    ],
                },
            )
            assert unknown.status_code == 422, unknown.text
            assert "unknown model id" in unknown.json()["detail"]
            view = client.get(f"/api/v2/onboarding/{onboarding_id}")
            assert view.json()["review_version"] == 0
            early = client.post(
                f"/api/v2/onboarding/{onboarding_id}/publish",
                json={"pilot_id": "pilot-b", "pilot_version": "reviewed-v2"},
            )
            assert early.status_code == 422, early.text
            parent = result["parent_canal_feature_id"]
            reviewed = client.patch(
                f"/api/v2/onboarding/{onboarding_id}/review",
                json={
                    "expected_version": 0,
                    "reviewer": saved_edits["reviewer"],
                    "field_edits": saved_edits["field_edits"],
                    "review_config": {"network": {**NETWORK, "source_feature_id": parent}},
                },
            )
            assert reviewed.status_code == 200, reviewed.text
            body = reviewed.json()
            assert body["review_version"] == 1
            assert body["blockers"] == [], body
            assert body["state"] == "reviewed"
            workdir = tmp_path / "onboarding" / onboarding_id
            from aabflow.ingestion.onboarding import pipeline

            if not existed:
                manifest = pipeline.publish(
                    workdir,
                    "pilot-b",
                    "reviewed-v2",
                    data_dir=config.DATA_DIR,
                    repo_root=config.ROOT,
                )
                assert manifest.pilot_version == "reviewed-v2"
            else:
                with pytest.raises(FileExistsError):
                    pipeline.publish(
                        workdir,
                        "pilot-b",
                        "reviewed-v2",
                        data_dir=config.DATA_DIR,
                        repo_root=config.ROOT,
                    )
        assert v2.is_dir()
        assert file_sha256(v1 / "manifest.json") == v1_before
        assert not (published / "reviewed-v1.partial").exists()
        assert not (published / "reviewed-v2.partial").exists()
        manifest_doc = _manifest_ok(v2)
        assert manifest_doc["pilot_id"] == "pilot-b"
        assert manifest_doc["pilot_version"] == "reviewed-v2"
        assert manifest_doc["state"] == "published"
        index = json.loads(index_path.read_text())
        versions = {(row["pilot_id"], row["pilot_version"]): row["published_at"] for row in index}
        assert ("pilot-b", "reviewed-v1") in versions
        assert ("pilot-b", "reviewed-v2") in versions
        assert versions[("pilot-b", "reviewed-v1")] == v1_index["published_at"]
        flags = json.loads((published / "library_flags.json").read_text())
        assert flags["reused_as_current"] is False
        assert flags["libraries"]
        assert all(row["current"] is False for row in flags["libraries"])
        assert all(row["library_pilot_version"] == "reviewed-v1" for row in flags["libraries"])
        assert flags["baseline"]["ready"] is False
        assert flags["candidates"]["ready"] is False
        assert latest.read_bytes() == latest_before
        pilot = json.loads((v2 / "pilot.json").read_text())
        assert pilot["pilot_version"] == "reviewed-v2"
        assert len(json.loads((v2 / "fields.geojson").read_text())["features"]) == 30
    finally:
        if batch.exists() and batch.read_bytes() != before_batch:
            batch.write_bytes(before_batch)
        if run_record.exists() and run_record.read_bytes() != before_run:
            run_record.write_bytes(before_run)
        for name in {path.name for path in runs.iterdir()} - runs_before:
            shutil.rmtree(runs / name)
        for name in {path.name for path in batches.iterdir()} - batches_before:
            extra = batches / name
            if extra.is_file():
                extra.unlink()
            elif extra.is_dir():
                shutil.rmtree(extra)
