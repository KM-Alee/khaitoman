"""Surrogate preview -> exact confirmation through the API on the real trained model (AT11)."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aabflow.config import DATA_DIR, Settings
from aabflow.main import create_app
from tests.integration.test_api_solve import wait

pytestmark = pytest.mark.scientific


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sur")
    s = Settings(
        data_dir=Path(DATA_DIR), db_path=tmp / "app.sqlite", web_dist=tmp / "nowd", workers=1
    )
    with TestClient(create_app(s)) as c:
        yield c


def body(depth=45.0, step=10):
    planting = date(2026, 11, 15)
    return {
        "crop_profile_id": "wheat-punjab-gdd-v1",
        "soil_profile_id": "aquacrop-loam-pct50",
        "application_efficiency": 0.75,
        "season_id": "wheat-rabi-2026-27",
        "weather_scenario_id": "dry",
        "schedule": [
            {"date": (planting + timedelta(days=d)).isoformat(), "gross_depth_mm": depth}
            for d in range(7, 112, step)
        ],
    }


def test_preview_then_exact_confirmation(client):
    gate = client.get("/api/v2/capabilities").json()["surrogate_gate"]
    r = client.post("/api/v2/surrogate/previews", json=body())
    if gate != "passed":
        assert r.status_code == 503
        pytest.skip(f"surrogate gate {gate}")
    assert r.status_code == 201, r.text
    pv = r.json()
    assert (
        pv["estimate_kind"] == "surrogate_preview" and pv["physical_precheck_status"] == "not_run"
    )
    again = client.post("/api/v2/surrogate/previews", json=body()).json()
    assert again["preview_id"] == pv["preview_id"]
    v = client.post(f"/api/v2/surrogate/previews/{pv['preview_id']}/verify")
    assert v.status_code == 202
    j = wait(client, v.json()["job_id"], timeout=300)
    assert j["state"] == "succeeded", j
    got = client.get(f"/api/v2/surrogate/previews/{pv['preview_id']}").json()
    ver = got["verification"]
    assert ver["estimate_kind"] == "exact_crop_model" and ver["exact_yield_kg_ha"] > 0
    if pv["estimated_yield_kg_ha"] is not None:
        assert ver["preview_minus_exact_kg_ha"] == pytest.approx(
            pv["estimated_yield_kg_ha"] - ver["exact_yield_kg_ha"]
        )
    assert got["exact_confirmation_job_id"] == v.json()["job_id"]


def test_out_of_domain_and_invalid(client):
    gate = client.get("/api/v2/capabilities").json()["surrogate_gate"]
    if gate != "passed":
        pytest.skip(f"surrogate gate {gate}")
    r = client.post("/api/v2/surrogate/previews", json=body(depth=400.0, step=3))
    assert r.status_code == 201
    pv = r.json()
    if pv["domain_status"] == "out_of_domain":
        assert pv["estimated_yield_kg_ha"] is None
        assert pv["message"] == "Outside validated preview range—run crop model."
    bad = client.post("/api/v2/surrogate/previews", json={**body(), "season_id": "nope"})
    assert bad.status_code == 422
    assert client.get("/api/v2/surrogate/previews/pv_nope").status_code == 404
