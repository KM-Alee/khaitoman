"""Package evidence IDs repeat across pilots (``ev:aoi``): detail lookups scope to the viewed pilot.

Reads the published ``data/pilots`` packages read-only; the app database is a tmp file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aabflow.config import DATA_DIR, Settings
from aabflow.main import create_app

PILOTS = Path(DATA_DIR) / "pilots"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    if not (PILOTS / "pilot-a" / "reviewed-v1").exists() or not (PILOTS / "pilot-b").exists():
        pytest.skip("published pilot-a and pilot-b packages are required")
    tmp = tmp_path_factory.mktemp("ev")
    data = tmp / "data"
    data.mkdir()
    (data / "pilots").symlink_to(PILOTS, target_is_directory=True)
    s = Settings(data_dir=data, db_path=tmp / "app.sqlite", web_dist=tmp / "nowd", workers=1)
    with TestClient(create_app(s)) as c:
        yield c


def test_shared_evidence_id_resolves_per_pilot(client):
    a = client.get("/api/v2/evidence/ev:aoi", params={"pilot_id": "pilot-a"})
    b = client.get(
        "/api/v2/evidence/ev:aoi", params={"pilot_id": "pilot-b", "pilot_version": "reviewed-v1"}
    )
    assert a.status_code == 200 and b.status_code == 200
    assert "pilot A" in a.json()["record"]["source_title"]
    assert "pilot B" in b.json()["record"]["source_title"]
    assert a.json()["pilot_ids"] == ["pilot-a"]


def test_evidence_absent_from_the_viewed_pilot_is_404(client):
    r = client.get("/api/v2/evidence/ev:aoi", params={"pilot_id": "pilot-zz"})
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
