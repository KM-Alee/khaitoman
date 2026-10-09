from fastapi.testclient import TestClient


def test_health_and_json_404(tmp_path, monkeypatch):
    monkeypatch.setenv("AABFLOW_DB_PATH", str(tmp_path / "app.sqlite"))
    import importlib

    from aabflow import config

    importlib.reload(config)
    from aabflow import main

    importlib.reload(main)
    with TestClient(main.app) as client:
        r = client.get("/api/v2/health")
        assert r.status_code == 200
        assert r.json()["contract_version"] == "2.0.0"
        assert r.json()["schema_version"] == "1"
        missing = client.get("/api/v2/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["code"] == "NOT_FOUND"
