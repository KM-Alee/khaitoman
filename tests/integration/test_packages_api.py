"""HTTP export/import of a completed pilot package.

The production app does not include this router until the parent registers it.
These tests mount the same router in front of the unknown-path catch-all.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from aabflow.api.packages import router as packages_router
from aabflow.domain.hashes import file_sha256
from aabflow.main import create_app
from tests.fixtures.api_app import settings_for

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "pilots" / "pilot-a" / "reviewed-v1"
ROUTE = "/api/v2/pilots/pilot-a/versions/reviewed-v1/package"


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_sha256(path)
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _mount(app):
    """Register the package router before the unknown-API catch-all.

    Production registration is a parent edit to ``main.py``. Until that lands,
    tests insert the same router into the included ``/api/v2`` router.
    """
    included = next(
        route
        for route in app.router.routes
        if getattr(getattr(route, "original_router", None), "prefix", None) == "/api/v2"
    )
    api = included.original_router
    wanted = "/api/v2/pilots/{pilot_id}/versions/{version}/package"
    if any(getattr(route, "path", None) == wanted for route in api.routes):
        return app
    catch_at = next(
        index
        for index, route in enumerate(api.routes)
        if getattr(route, "path", None) == "/api/v2/{path:path}"
    )
    before = len(api.routes)
    api.include_router(packages_router)
    added = api.routes[before:]
    del api.routes[before:]
    for offset, route in enumerate(added):
        api.routes.insert(catch_at + offset, route)
    included._effective_candidates_version = None
    included._effective_low_priority_routes_version = None
    return app


def _seed(tmp: Path) -> None:
    dest = tmp / "pilots" / "pilot-a" / "reviewed-v1"
    shutil.copytree(SRC, dest)
    (tmp / "pilots" / "index.json").write_text(
        json.dumps(
            [
                {
                    "pilot_id": "pilot-a",
                    "pilot_version": "reviewed-v1",
                    "name": "Lower Chenab representative pilot A",
                    "published_at": "2026-10-10T00:52:42Z",
                }
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _client(tmp: Path) -> TestClient:
    _seed(tmp)
    return TestClient(_mount(create_app(settings_for(tmp))))


def _wipe(tmp: Path) -> None:
    shutil.rmtree(tmp / "pilots" / "pilot-a" / "reviewed-v1")
    (tmp / "pilots" / "index.json").write_text("[]\n", encoding="utf-8")


def test_http_round_trip_idempotency_and_existing_version(tmp_path):
    with _client(tmp_path) as client:
        exported = client.get(ROUTE)
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-type"].startswith("application/zip")
        assert exported.headers["x-aabflow-package-kind"] == "completed_pilot_package"
        blob = exported.content
        declared = json.loads((SRC / "pilot.json").read_text())["package_sha256"]
        assert exported.headers["x-package-sha256"] == declared
        _wipe(tmp_path)
        first = client.post(
            ROUTE,
            data={"contract_version": "2.0.0"},
            files={"package": ("../../evil.zip", blob, "application/zip")},
            headers={"Idempotency-Key": "pkg-1"},
        )
        assert first.status_code == 201, first.text
        body = first.json()
        assert body["kind"] == "completed_pilot_package"
        assert body["package_sha256"] == declared
        imported = tmp_path / "pilots" / "pilot-a" / "reviewed-v1"
        assert _hashes(imported) == _hashes(SRC)
        assert not (tmp_path / "evil.zip").exists()
        assert not list(tmp_path.rglob("evil.zip"))
        replay = client.post(
            ROUTE,
            data={"contract_version": "2.0.0"},
            files={"package": ("pilot.zip", blob, "application/zip")},
            headers={"Idempotency-Key": "pkg-1"},
        )
        assert replay.status_code == 201, replay.text
        assert replay.headers["idempotent-replay"] == "true"
        assert replay.json() == body
        events = (tmp_path / "pilots" / "completed-package-events.jsonl").read_text()
        assert events.count("completed_package_import") == 1
        conflict = client.post(
            ROUTE,
            data={"contract_version": "2.0.0"},
            files={"package": ("pilot.zip", blob + b"x", "application/zip")},
            headers={"Idempotency-Key": "pkg-1"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
        again = client.post(
            ROUTE,
            data={"contract_version": "2.0.0"},
            files={"package": ("pilot.zip", blob, "application/zip")},
        )
        assert again.status_code == 409
        assert again.json()["code"] == "VERSION_CONFLICT"
        assert _hashes(imported) == _hashes(SRC)


def test_unknown_nonfinite_path_and_ownership(tmp_path):
    with _client(tmp_path) as client:
        blob = client.get(ROUTE).content
        extra = client.post(
            ROUTE,
            data={"contract_version": "2.0.0", "extra": "1"},
            files={"package": ("pilot.zip", blob, "application/zip")},
        )
        assert extra.status_code == 422
        assert extra.json()["code"] == "INVALID_INPUT"
        assert extra.json()["fields"]["extra"] == "unknown field"
        queried = client.post(
            ROUTE + "?surprise=1",
            data={"contract_version": "2.0.0"},
            files={"package": ("pilot.zip", blob, "application/zip")},
        )
        assert queried.status_code == 422
        assert "surprise" in queried.json()["fields"]
        nonfinite = client.post(
            ROUTE,
            content=b'{"contract_version":"2.0.0","ratio":NaN}',
            headers={"content-type": "application/json"},
        )
        assert nonfinite.status_code == 422
        assert nonfinite.json()["fields"]["ratio"] == "nonfinite"
        unknown = client.post(
            ROUTE,
            content=b'{"contract_version":"2.0.0","extra":1}',
            headers={"content-type": "application/json"},
        )
        assert unknown.status_code == 422
        assert "extra" in unknown.json()["fields"]
        unsafe = client.get("/api/v2/pilots/bad%20id/versions/reviewed-v1/package")
        assert unsafe.status_code == 404
        assert unsafe.json()["code"] == "NOT_FOUND"
        foreign = client.post(
            "/api/v2/pilots/pilot-b/versions/reviewed-v9/package",
            data={"contract_version": "2.0.0"},
            files={"package": ("pilot.zip", blob, "application/zip")},
        )
        assert foreign.status_code == 409, foreign.text
        assert foreign.json()["code"] == "VERSION_CONFLICT"
        assert not (tmp_path / "pilots" / "pilot-b").exists()
        missing = client.get("/api/v2/pilots/pilot-a/versions/missing-v1/package")
        assert missing.status_code == 404
