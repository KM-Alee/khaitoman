"""Onboarding HTTP routes: AOI check, raw intake, process enqueue, layers."""

from __future__ import annotations

import json

from aabflow.repositories.sqlite import connect
from aabflow.services.onboarding import store
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


def test_malformed_aoi_ring_is_invalid_input_not_a_server_error(tmp_path):
    two_points = {"type": "Polygon", "coordinates": [[[72.0, 30.0], [72.2, 30.0]]]}
    with onboarding_client(tmp_path) as client:
        checked = client.post("/api/v2/onboarding/aoi-check", json={"aoi": two_points})
        assert checked.status_code == 422, checked.text
        assert checked.json()["code"] == "INVALID_INPUT"
        assert "aoi" in checked.json()["fields"]
        created = client.post(
            "/api/v2/onboarding", json={"aoi": two_points, "source_mode": "online"}
        )
        assert created.status_code == 422, created.text
        assert created.json()["code"] == "INVALID_INPUT"


def test_raw_package_listing_carries_the_bundle_aoi_the_intake_must_use(tmp_path):
    bundle = tmp_path / "raw" / "bundles" / "pilot-x" / "b1"
    write_raw_bundle(bundle, POLY)
    with onboarding_client(tmp_path) as client:
        rows = client.get("/api/v2/onboarding/raw-packages").json()["packages"]
        row = next(item for item in rows if item["bundle_id"] == "b1")
        assert row["aoi"] == POLY
        created = client.post(
            "/api/v2/onboarding",
            json={
                "aoi": row["aoi"],
                "source_mode": "raw_package",
                "raw_package_id": row["bundle_ref"],
            },
        )
        assert created.status_code == 201, created.text
        shifted = {
            "type": "Polygon",
            "coordinates": [[[x + 0.001, y] for x, y in POLY["coordinates"][0]]],
        }
        differs = client.post(
            "/api/v2/onboarding",
            json={
                "aoi": shifted,
                "source_mode": "raw_package",
                "raw_package_id": row["bundle_ref"],
            },
        )
        assert differs.status_code == 422, differs.text
        assert "differs" in differs.json()["detail"]


def test_view_reports_the_applied_review_and_publish_blockers(tmp_path):
    network = {
        "direction": "downstream",
        "source_feature_id": "osm:way/1",
        "capacity_m3_s": 0.1,
        "roster_basis": "declared_cca",
        "outlet": "reach_group",
        "acknowledged": True,
    }
    with onboarding_client(tmp_path) as client:
        created = client.post("/api/v2/onboarding", json={"aoi": POLY, "source_mode": "online"})
        oid = created.json()["onboarding_id"]
        assert created.json()["validation"]["publish_blockers"] == []
        workdir = tmp_path / "onboarding" / oid
        processed = workdir / "processed"
        processed.mkdir()
        raw = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "m1", "geometry": POLY, "properties": {"model_id": "m1"}}
            ],
        }
        (processed / "fields_raw.geojson").write_text(json.dumps(raw))
        canals = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "osm:way/1",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[72.24, 30.655], [72.24, 30.675]],
                    },
                    "properties": {"provider": "osm", "waterway": "canal"},
                }
            ],
        }
        (processed / "canals.geojson").write_text(json.dumps(canals))
        record = json.loads((workdir / "intake.json").read_text())
        record["state"] = "needs_review"
        (workdir / "intake.json").write_text(json.dumps(record))
        scene_warning = "S2X_fixture: published offset NOT applied (fixture warning)"
        conn = connect(settings_for(tmp_path).db_path)
        store.patch(
            conn,
            oid,
            status={"inference": {"warnings": [scene_warning]}, "warnings": [scene_warning]},
        )

        before = client.get(f"/api/v2/onboarding/{oid}").json()
        assert before["validation"]["warnings"] == [scene_warning]
        assert before["review"]["version"] == 0
        assert before["review"]["field_edits"] == []
        assert before["review"]["network"] is None
        assert any("not reviewed" in item for item in before["validation"]["publish_blockers"])

        edit = {"model_id": "m1", "action": "reject", "reason": "embankment, not a parcel"}
        reviewed = client.patch(
            f"/api/v2/onboarding/{oid}/review",
            json={
                "expected_version": 0,
                "reviewer": "fixture reviewer",
                "field_edits": [edit],
                "review_config": {"network": network, "min_area_m2": 4000},
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        after = client.get(f"/api/v2/onboarding/{oid}").json()
        assert after["review_version"] == 1
        review = after["review"]
        assert review["version"] == 1
        assert review["reviewer"] == "fixture reviewer"
        assert review["field_edits"] == [{**edit, "other_model_ids": []}]
        assert review["network"] == network
        assert review["parent_canal_feature_id"] == "osm:way/1"
        assert review["review_config"] == {"min_area_m2": 4000}
        assert "publish_blockers" not in review
        # A review keeps the source warnings next to its own.
        assert scene_warning in after["validation"]["warnings"]
        # The fixture has one raw polygon and rejects it, so 30 fields cannot be published.
        blockers = after["validation"]["publish_blockers"]
        assert blockers, after
        assert not any("not reviewed" in item for item in blockers)
        published = client.post(
            f"/api/v2/onboarding/{oid}/publish",
            json={"pilot_id": "pilot-x", "pilot_version": "reviewed-v1"},
        )
        assert published.status_code == 422, published.text
