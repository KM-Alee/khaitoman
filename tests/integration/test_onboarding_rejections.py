"""Structural rejections: unknown fields, nonfinite numbers, traversal, immutable publish."""

from __future__ import annotations

import pytest

from aabflow.ingestion.onboarding import pipeline
from aabflow.ingestion.onboarding.layers import LayerError, reject_layer_id
from tests.fixtures.api_app import settings_for
from tests.integration.test_onboarding_support import POLY, onboarding_client


def _intake(client):
    response = client.post(
        "/api/v2/onboarding",
        json={"aoi": POLY, "source_mode": "online"},
    )
    assert response.status_code == 201, response.text
    return response.json()["onboarding_id"]


def test_unknown_fields_and_nonfinite_numbers_are_rejected(tmp_path):
    with onboarding_client(tmp_path) as client:
        unknown = client.post(
            "/api/v2/onboarding/aoi-check",
            json={"aoi": POLY, "unexpected": 1},
        )
        assert unknown.status_code == 422
        assert unknown.json()["code"] == "INVALID_INPUT"
        assert "unexpected" in unknown.json()["fields"]
        # Raw JSON: the test client refuses nonfinite numbers before they reach the API.
        infinite = client.post(
            "/api/v2/onboarding",
            content=(
                b'{"aoi":{"type":"Polygon","coordinates":[[[72.25,30.66],[72.26,Infinity],'
                b'[72.26,30.67],[72.25,30.66]]]},"source_mode":"online"}'
            ),
            headers={"content-type": "application/json"},
        )
        assert infinite.status_code == 422, infinite.text
        assert infinite.json()["code"] == "INVALID_INPUT"
        assert any("nonfinite" in message for message in infinite.json()["fields"].values())


def test_path_traversal_zip_and_finished_package_are_rejected(tmp_path):
    with onboarding_client(tmp_path) as client:
        oid = _intake(client)
        for ref in (
            "../../pilots/pilot-b/reviewed-v1",
            "/etc/passwd",
            "data/raw/bundles/pilot-b/../../../etc/passwd",
            "finished.zip",
            "data/pilots/pilot-b/reviewed-v1",
            r"raw\bundles\pilot-b",
        ):
            response = client.post(
                "/api/v2/onboarding",
                json={"aoi": POLY, "source_mode": "raw_package", "raw_package_id": ref},
            )
            assert response.status_code == 422, (ref, response.text)
            assert response.json()["code"] == "INVALID_INPUT"
        with pytest.raises(LayerError, match="traversal"):
            reject_layer_id("../intake.json")
        # A single path segment that still spells traversal. `layers/..` is
        # normalized by the HTTP client before the handler sees it.
        escaped = client.get(f"/api/v2/onboarding/{oid}/layers/.secret")
        assert escaped.status_code == 422
        assert escaped.json()["fields"]["layer_id"] == "path traversal"
        hidden = client.get(f"/api/v2/onboarding/{oid}/layers/..%2Fintake.json")
        assert hidden.status_code == 404
        assert hidden.json()["code"] == "NOT_FOUND"


def test_stale_review_returns_409_and_keeps_the_version(tmp_path):
    with onboarding_client(tmp_path) as client:
        oid = _intake(client)
        path = tmp_path / "onboarding" / oid / "intake.json"
        record = json_load(path)
        record["state"] = "needs_review"
        record["review_version"] = 2
        path.write_text(__import__("json").dumps(record))
        stale = client.patch(
            f"/api/v2/onboarding/{oid}/review",
            json={"expected_version": 0, "field_edits": []},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["code"] == "VERSION_CONFLICT"
        assert stale.json()["dependency_diff"]["review_version"] == 2
        assert json_load(path)["review_version"] == 2


def test_second_publish_of_an_existing_version_is_rejected(tmp_path, monkeypatch):
    published = tmp_path / "pilots" / "pilot-b" / "reviewed-v1"
    published.mkdir(parents=True)
    marker = published / "marker.txt"
    marker.write_text("keep")
    before = marker.read_bytes()

    def refuse(*_args, **_kwargs):
        raise AssertionError("publish wrote through an existing version")

    monkeypatch.setattr(pipeline, "publish", refuse)
    with onboarding_client(tmp_path) as client:
        oid = _intake(client)
        response = client.post(
            f"/api/v2/onboarding/{oid}/publish",
            json={"pilot_id": "pilot-b", "pilot_version": "reviewed-v1"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "VERSION_CONFLICT"
        assert response.json()["dependency_diff"]["immutable"] is True
        slipped = client.post(
            f"/api/v2/onboarding/{oid}/publish",
            json={"pilot_id": "pilot-b", "pilot_version": "../reviewed-v1"},
        )
        assert slipped.status_code == 422
        assert slipped.json()["fields"]["pilot_version"] == "path traversal"
    assert marker.read_bytes() == before
    assert not (tmp_path / "pilots" / "pilot-b" / "reviewed-v2").exists()
    real = settings_for(tmp_path)
    assert real.pilots_dir == tmp_path / "pilots"


def json_load(path):
    import json

    return json.loads(path.read_text())
