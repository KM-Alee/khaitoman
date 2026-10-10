"""Shared helpers for onboarding route tests. Not a test module of its own."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

import aabflow.main as main_mod
from aabflow.main import create_app
from tests.fixtures.api_app import settings_for

POLY = {
    "type": "Polygon",
    "coordinates": [
        [[72.25, 30.66], [72.26, 30.66], [72.26, 30.67], [72.25, 30.67], [72.25, 30.66]]
    ],
}

PILOT_B_BUNDLE = "data/raw/bundles/pilot-b/20261010T003841Z-798d10d2"
PILOT_B_INFERENCE_KEY = "50ca220c256bbf74"


@contextmanager
def onboarding_client(tmp: Path, *, dispatcher: bool = False):
    """Mount the onboarding router without editing ``main._routers`` on disk."""
    original = main_mod._routers

    def routers():
        from aabflow.api.onboarding import router as onboarding_router

        current = original()
        if onboarding_router in current:
            return current
        return [*current, onboarding_router]

    main_mod._routers = routers
    try:
        with TestClient(create_app(settings_for(tmp, dispatcher=dispatcher))) as client:
            yield client
    finally:
        main_mod._routers = original


def write_raw_bundle(root: Path, aoi: dict) -> None:
    """TEST FIXTURE: a tiny valid raw bundle, not a finished pilot package."""
    root.mkdir(parents=True)
    collection = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": aoi, "properties": {}}],
    }
    text = json.dumps(collection)
    target = root / "aoi.geojson"
    target.write_text(text)
    raw = target.read_bytes()
    manifest = {
        "bundle_version": "1",
        "bundle_id": root.name,
        "pilot_id": root.parent.name,
        "created_at": "2026-10-10T00:00:00+00:00",
        "aoi": collection,
        "files": [
            {
                "path": "aoi.geojson",
                "kind": "aoi",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        ],
        "sources": {},
    }
    (root / "bundle_manifest.json").write_text(json.dumps(manifest))
