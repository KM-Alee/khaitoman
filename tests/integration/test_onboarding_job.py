"""Process-job contract: progress, cancellation, acquisition errors, cache lineage."""

from __future__ import annotations

import pytest

from aabflow.ingestion.common import IngestionError
from aabflow.ingestion.onboarding.acquire import Cancelled
from aabflow.jobs import queue
from aabflow.jobs.cancellation import JobCancelled
from aabflow.jobs.worker import HANDLERS, JobContext
from aabflow.repositories.sqlite import connect, loads
from aabflow.services.onboarding import jobs as job_mod
from aabflow.services.onboarding import process_job
from tests.fixtures.api_app import settings_for
from tests.integration.test_onboarding_support import POLY, onboarding_client


def _intake(tmp_path):
    settings = settings_for(tmp_path)
    with onboarding_client(tmp_path) as client:
        response = client.post(
            "/api/v2/onboarding",
            json={"aoi": POLY, "source_mode": "online"},
        )
        assert response.status_code == 201, response.text
        onboarding_id = response.json()["onboarding_id"]
    conn = connect(settings.db_path)
    job_id = queue.enqueue(
        conn,
        "onboarding.process",
        {"onboarding_id": onboarding_id},
        "hash",
        subject_id=onboarding_id,
    )
    return settings, conn, JobContext(settings, job_id, "test-owner", conn), onboarding_id


def test_handler_is_the_registered_process_job():
    assert HANDLERS["onboarding.process"] == "aabflow.services.onboarding:process_job"
    assert process_job is job_mod.process_job


def test_progress_cancel_and_acquisition_errors_are_honest(tmp_path, monkeypatch):
    _settings, conn, ctx, onboarding_id = _intake(tmp_path)

    def pending(*_args, progress, should_cancel, **_kwargs):
        assert should_cancel() is False
        progress("process:imagery", 0.1, "display, NDVI, Delineate input")
        return {
            "state": "awaiting_inference",
            "inference": {
                "state": "pending",
                "cache_hit": False,
                "device": "cuda",
                "inference_key": "missing",
            },
            "cache_hits": [],
            "blockers": ["inference_pending: not started"],
            "warnings": [],
        }

    monkeypatch.setattr(job_mod.pipeline, "process", pending)
    result = process_job(ctx, {"onboarding_id": onboarding_id})
    assert result["inference_completed"] is False
    assert result["cache_hit"] is False
    assert result["device"] is None
    job = queue.get(conn, ctx.job_id)
    assert job["stage"] == "process:imagery"
    assert job["progress"] == 0.1

    def cancel(*_args, **_kwargs):
        raise Cancelled("processing cancelled")

    monkeypatch.setattr(job_mod.pipeline, "process", cancel)
    with pytest.raises(JobCancelled):
        process_job(ctx, {"onboarding_id": onboarding_id})
    row = conn.execute(
        "SELECT state, status FROM onboarding WHERE onboarding_id = ?", (onboarding_id,)
    ).fetchone()
    assert row["state"] == "cancelled"
    assert loads(row["status"])["error"]["code"] == "CANCELLED"

    def acquire(*_args, **_kwargs):
        raise IngestionError("no Sentinel-2 L2A items fully covering the AOI")

    monkeypatch.setattr(job_mod.pipeline, "process", acquire)
    with pytest.raises(IngestionError):
        process_job(ctx, {"onboarding_id": onboarding_id})
    row = conn.execute(
        "SELECT state, status FROM onboarding WHERE onboarding_id = ?", (onboarding_id,)
    ).fetchone()
    assert row["state"] == "failed"
    detail = loads(row["status"])["error"]["detail"]
    assert "Sentinel-2" in detail
    assert loads(row["status"])["progress"] is None


def test_cache_hit_lineage_keeps_the_recorded_device(tmp_path, monkeypatch):
    _settings, conn, ctx, onboarding_id = _intake(tmp_path)

    def cached(*_args, **_kwargs):
        return {
            "state": "needs_review",
            "inference": {
                "state": "done",
                "cache_hit": True,
                "device": "cpu",
                "inference_key": "50ca220c256bbf74",
                "gpkg_sha256": "34c4f40f3968d573232fcc6a71d62048941a89917380c86b33f1293ad41dceaa",
                "input_sha256": "4733c68cfc3a1dcd45070824d38b8890323f005a0f349e261a707c0e85db205e",
            },
            "cache_hits": ["delineate:50ca220c256bbf74"],
            "blockers": [],
            "warnings": [],
            "review_summary": {"selected": 30},
        }

    monkeypatch.setattr(job_mod.pipeline, "process", cached)
    result = process_job(ctx, {"onboarding_id": onboarding_id})
    assert result["cache_hit"] is True
    assert result["device"] == "cpu"
    assert result["inference_key"] == "50ca220c256bbf74"
    assert result["inference_completed"] is True
    status = loads(
        conn.execute(
            "SELECT status FROM onboarding WHERE onboarding_id = ?", (onboarding_id,)
        ).fetchone()["status"]
    )
    assert status["inference"]["cache_hit"] is True
    assert status["inference"]["device"] == "cpu"
    assert status["progress"] == 1.0
