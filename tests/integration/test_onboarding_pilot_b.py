"""One real pilot-b raw-bundle process. Reuses the Delineate cache and does not start vision."""

from __future__ import annotations

import json
import shutil

from aabflow import config
from aabflow.domain.hashes import file_sha256
from aabflow.ingestion.imagery import delineate
from aabflow.jobs import queue
from aabflow.jobs.worker import JobContext
from aabflow.repositories.sqlite import connect
from aabflow.services.onboarding.jobs import process_job
from tests.fixtures.api_app import settings_for
from tests.integration.test_onboarding_support import (
    PILOT_B_BUNDLE,
    PILOT_B_INFERENCE_KEY,
    onboarding_client,
)


def test_pilot_b_raw_bundle_reuses_the_delineate_cache(tmp_path, monkeypatch):
    manifest = config.ROOT / "data" / "pilots" / "pilot-b" / "reviewed-v1" / "manifest.json"
    published = config.ROOT / "data" / "pilots" / "pilot-b"
    before_manifest = file_sha256(manifest)
    v2_manifest = published / "reviewed-v2" / "manifest.json"
    v2_manifest_before = file_sha256(v2_manifest) if v2_manifest.is_file() else None
    run_record = config.ROOT / "vision" / "runs" / PILOT_B_INFERENCE_KEY / "run.json"
    batch = config.ROOT / "vision" / "batches" / f"{PILOT_B_INFERENCE_KEY}.yaml"
    before_run = run_record.read_bytes()
    before_batch = batch.read_bytes()
    runs = config.ROOT / "vision" / "runs"
    batches = config.ROOT / "vision" / "batches"
    runs_before = {path.name for path in runs.iterdir()}
    batches_before = {path.name for path in batches.iterdir()}

    def no_new_vision(*args, **_kwargs):
        raise AssertionError(f"a new vision process was started: {args!r}")

    monkeypatch.setattr(delineate.subprocess, "run", no_new_vision)
    aoi = json.loads((config.ROOT / PILOT_B_BUNDLE / "aoi.geojson").read_text())
    try:
        with onboarding_client(tmp_path) as client:
            created = client.post(
                "/api/v2/onboarding",
                json={
                    "name": "Pilot B raw reprocess",
                    "aoi": aoi,
                    "source_mode": "raw_package",
                    "raw_package_ref": PILOT_B_BUNDLE,
                },
            )
            assert created.status_code == 201, created.text
            onboarding_id = created.json()["onboarding_id"]
            assert created.json()["pilot_id"] == "pilot-b"
        settings = settings_for(tmp_path)
        conn = connect(settings.db_path)
        job_id = queue.enqueue(
            conn,
            "onboarding.process",
            {"onboarding_id": onboarding_id},
            "pilot-b-process",
            subject_id=onboarding_id,
        )
        result = process_job(
            JobContext(settings, job_id, "pilot-b-cache", conn),
            {"onboarding_id": onboarding_id},
        )
        assert result["cache_hit"] is True, result
        assert result["device"] == "cpu"
        assert result["inference_completed"] is True
        assert result["inference_key"] == PILOT_B_INFERENCE_KEY
        assert result["state"] == "needs_review"
        recorded = json.loads(before_run)
        assert result["gpkg_sha256"] == recorded["outputs"]["scene.gpkg"]["sha256"]
        assert result["input_sha256"] == recorded["inputs"]["scene/scene.tif"]
        assert f"delineate:{PILOT_B_INFERENCE_KEY}" in result["cache_hits"]
        assert file_sha256(manifest) == before_manifest
        v2 = published / "reviewed-v2"
        if v2.exists():
            assert (v2 / "manifest.json").is_file()
            assert file_sha256(v2 / "manifest.json") == v2_manifest_before
        else:
            assert not v2.exists()
        assert not (published / "reviewed-v1.partial").exists()
        assert not (published / "reviewed-v2.partial").exists()
        assert manifest.is_file()
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
