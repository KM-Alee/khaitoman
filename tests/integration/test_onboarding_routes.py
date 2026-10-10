"""Onboarding HTTP routes: AOI check, raw intake, process enqueue, layers."""

from __future__ import annotations

import json

from aabflow.repositories.sqlite import connect
from tests.fixtures.api_app import settings_for
from tests.integration.test_onboarding_support import POLY, onboarding_client, write_raw_bundle


def test_aoi_check_reports_area_without_starting_a_job(tmp_path):
    with onboarding_client(tmp_path) as client:
        response = client.post("/api/v2/onboarding/aoi-check", json={"aoi": POLY})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["blockers"] == []
        assert body["area_m2"] > 0
        assert body["source_availability"]["online"] == "not_contacted"
        assert client.get("/api/v2/onboarding/does-not-exist").status_code == 404
    conn = connect(settings_for(tmp_path).db_path)
    assert conn.execute("SELECT COUNT(*) FROM onboarding").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_raw_package_list_is_not_the_published_pilot(tmp_path):
    with onboarding_client(tmp_path) as client:
        response = client.get("/api/v2/onboarding/raw-packages")
        assert response.status_code == 200, response.text
        packages = response.json()["packages"]
    refs = [row["bundle_ref"] for row in packages]
    assert any(row["bundle_id"] == "20261010T003841Z-798d10d2" for row in packages)
    assert all("reviewed-v1" not in ref for ref in refs)
    assert all(row["intake_kind"] == "raw_source_bundle" for row in packages)
    assert all("/pilots/" not in ref for ref in refs)


def test_raw_intake_and_process_enqueue_are_persisted(tmp_path):
    bundle = tmp_path / "raw" / "bundles" / "pilot-x" / "b1"
    write_raw_bundle(bundle, POLY)
    with onboarding_client(tmp_path) as client:
        created = client.post(
            "/api/v2/onboarding",
            json={
                "name": "Fixture watercourse",
                "aoi": POLY,
                "source_mode": "raw_package",
                "raw_package_id": "pilot-x/b1",
            },
            headers={"Idempotency-Key": "intake-1"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        replay = client.post(
            "/api/v2/onboarding",
            json={
                "name": "Fixture watercourse",
                "aoi": POLY,
                "source_mode": "raw_package",
                "raw_package_id": "pilot-x/b1",
            },
            headers={"Idempotency-Key": "intake-1"},
        )
        assert replay.status_code == 201
        assert replay.json()["onboarding_id"] == body["onboarding_id"]
        assert replay.headers.get("Idempotent-Replay") == "true"
        oid = body["onboarding_id"]
        assert body["state"] == "created"
        assert body["bundle_ref"].endswith("raw/bundles/pilot-x/b1")
        queued = client.post(f"/api/v2/onboarding/{oid}/process", json={})
        assert queued.status_code == 202, queued.text
        job_id = queued.json()["job_id"]
        assert queued.json()["job"]["state"] == "queued"
        assert queued.json()["job"]["operation"] == "onboarding.process"
        again = client.post(f"/api/v2/onboarding/{oid}/process", json={})
        assert again.status_code == 409
        conn = connect(settings_for(tmp_path).db_path)
        conn.execute(
            "UPDATE jobs SET state = 'interrupted', lease_until = NULL WHERE job_id = ?",
            (job_id,),
        )
        conn.commit()
        resumed = client.post(f"/api/v2/onboarding/{oid}/process", json={})
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["job_id"] != job_id
        current = client.get(f"/api/v2/onboarding/{oid}")
        assert current.json()["job_id"] == resumed.json()["job_id"]
        layers = client.get(f"/api/v2/onboarding/{oid}/layers")
        assert layers.status_code == 200
        assert layers.json()["available"] == ["aoi"]
        assert "canals" in {row["id"] for row in layers.json()["unavailable"]}
        missing = client.get(f"/api/v2/onboarding/{oid}/layers/canals")
        assert missing.status_code == 404


def test_online_intake_accepts_the_ui_shape(tmp_path):
    with onboarding_client(tmp_path) as client:
        created = client.post(
            "/api/v2/onboarding",
            json={"aoi": POLY, "source_mode": "online", "name": "North branch"},
        )
        assert created.status_code == 201, created.text
        oid = created.json()["onboarding_id"]
        assert created.json()["intake_id"] == oid
        record = json.loads((tmp_path / "onboarding" / oid / "intake.json").read_text())
        assert record["source_mode"] == "online"
        assert record["bundle_ref"] is None
