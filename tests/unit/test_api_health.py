from fastapi.testclient import TestClient

from aabflow.main import create_app
from tests.fixtures.api_app import settings_for


def test_health_and_json_404(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        r = client.get("/api/v2/health")
        assert r.status_code == 200
        body = r.json()
        assert body["contract_version"] == "2.0.0"
        assert body["schema_version"] == "2"
        assert body["database"] == "ok"
        assert body["pilots_published"] == 0
        missing = client.get("/api/v2/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["code"] == "NOT_FOUND"
        assert client.post("/api/v2/nope", json={}).json()["code"] == "NOT_FOUND"
        assert client.get("/assets/pilots/x/y/z.png").status_code == 404


def test_capabilities_are_honest_without_data(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        caps = client.get("/api/v2/capabilities").json()
        assert caps["pilots"] == []
        assert caps["features"]["F07"]["status"] == "not_available"
        assert caps["features"]["copilot"]["status"] == "not_available"
        assert caps["surrogate_gate"] == "not_run"
