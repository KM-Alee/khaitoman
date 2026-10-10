"""Completed-package checks that sit on top of the zip reader.

Raw source bundles (``bundle_manifest.json``) are refused here. They stay on
the onboarding intake path and are never published by this importer.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from aabflow.api.errors import conflict, invalid
from aabflow.domain.hashes import sha256_hex
from aabflow.domain.schemas import Pilot, PilotManifest

from .archive import ALLOWED_SUFFIXES, BUNDLE_MANIFEST_NAME, MANIFEST_NAME

FETCH_KEYS = {"fetch_url", "download_url", "remote_fetch", "fetch"}
OWNED_FILES = (
    ("fields.geojson", ("field_id",)),
    ("network.json", ("node_id", "edge_id")),
    ("assets.json", ("asset_id",)),
    ("interventions.json", ("instance_id",)),
)
RAW_DETAIL = (
    "this archive is a raw source bundle, not a completed pilot package. "
    "Raw intake uses onboarding acquire/process/review/publish and is a different path."
)


def _reject(detail: str, fields: dict[str, str]):
    raise invalid(detail, fields)


def reject_raw_intake(files: dict[str, bytes]) -> None:
    has_bundle = BUNDLE_MANIFEST_NAME in files
    has_manifest = MANIFEST_NAME in files
    if has_bundle and not has_manifest:
        _reject(RAW_DETAIL, {"kind": "raw_intake"})
    if has_bundle and has_manifest:
        _reject(
            "archive mixes a raw bundle manifest with a completed package; " + RAW_DETAIL,
            {"kind": "raw_intake"},
        )
    if not has_manifest:
        _reject("completed package manifest.json is missing", {"manifest_version": "missing"})


def parse_manifest(files: dict[str, bytes]) -> PilotManifest:
    try:
        raw = json.loads(files[MANIFEST_NAME])
    except json.JSONDecodeError as exc:
        _reject(f"manifest.json is not valid JSON: {exc}", {"format": MANIFEST_NAME})
    if not isinstance(raw, dict):
        _reject("manifest.json must be an object", {"format": MANIFEST_NAME})
    version = raw.get("manifest_version")
    if version != "1":
        _reject(
            f"unsupported manifest_version {version!r}; completed packages use version 1",
            {"manifest_version": str(version)},
        )
    try:
        return PilotManifest.model_validate(raw)
    except ValidationError as exc:
        _reject(
            f"manifest.json failed validation: {exc.errors()[0]['msg']}", {"manifest_version": "1"}
        )


def check_hashes(files: dict[str, bytes], manifest: PilotManifest) -> None:
    listed: dict[str, tuple[int, str]] = {}
    seen: set[str] = set()
    for entry in manifest.files:
        rel = entry.path
        if rel != entry.path or "\\" in rel or rel.startswith("/") or ".." in rel.split("/"):
            _reject(f"manifest path is not a relative package path: {rel}", {"path": rel})
        if rel.lower() in seen:
            _reject(f"duplicate manifest path {rel}", {"files": rel})
        seen.add(rel.lower())
        if not rel.lower().endswith(tuple(ALLOWED_SUFFIXES)):
            _reject(f"format not allowed: {rel}", {"format": rel})
        listed[rel] = (entry.size_bytes, entry.sha256)
    present = {rel for rel in files if rel != MANIFEST_NAME}
    missing = [rel for rel in listed if rel not in files]
    if missing:
        _reject(f"manifest lists missing file {missing[0]}", {"sha256": missing[0]})
    extra = sorted(present - set(listed))
    if extra:
        _reject(f"archive contains unlisted file {extra[0]}", {"files": extra[0]})
    for rel, (size, digest) in listed.items():
        data = files[rel]
        if len(data) != size:
            _reject(
                f"size mismatch for {rel}: archive {len(data)} manifest {size}",
                {"sha256": rel},
            )
        actual = sha256_hex(data)
        if actual != digest:
            _reject(f"sha256 mismatch for {rel}", {"sha256": rel})


def reject_fetch_instructions(files: dict[str, bytes]) -> None:
    """Citation URLs (``source_url``) stay stored. Fetch-instruction keys do not."""
    for rel, data in files.items():
        if not rel.endswith((".json", ".geojson")):
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            _reject(f"{rel} is not valid JSON: {exc}", {"format": rel})
        found = _find_fetch_key(parsed)
        if found:
            _reject(
                f"{rel} contains fetch instruction {found}; import does not request that URL",
                {"fetch_url": found},
            )


def _find_fetch_key(node: Any) -> str | None:
    if isinstance(node, dict):
        for key in node:
            if key in FETCH_KEYS:
                return key
        for value in node.values():
            found = _find_fetch_key(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_fetch_key(value)
            if found:
                return found
    return None


def load_pilot(files: dict[str, bytes]) -> Pilot:
    raw = files.get("pilot.json")
    if raw is None:
        _reject("pilot.json is missing", {"package": "pilot.json"})
    try:
        return Pilot.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        _reject(f"pilot.json failed validation: {exc}", {"format": "pilot.json"})


def check_identity(
    files: dict[str, bytes], manifest: PilotManifest, pilot_id: str, pilot_version: str
) -> Pilot:
    pilot = load_pilot(files)
    if manifest.state.value != "published" or pilot.state.value != "published":
        _reject(
            "only a published completed package can be imported; raw and in-review bundles use onboarding",
            {"kind": "completed_pilot_package"},
        )
    if (
        len({manifest.pilot_id, pilot.pilot_id, pilot_id}) != 1
        or len({manifest.pilot_version, pilot.pilot_version, pilot_version}) != 1
    ):
        raise conflict(
            f"package identity {manifest.pilot_id}/{manifest.pilot_version} does not belong to "
            f"path {pilot_id}/{pilot_version} (pilot.json is {pilot.pilot_id}/{pilot.pilot_version})",
            {
                "pilot_id": pilot.pilot_id,
                "pilot_version": pilot.pilot_version,
                "path_pilot_id": pilot_id,
                "path_pilot_version": pilot_version,
                "manifest_pilot_id": manifest.pilot_id,
                "manifest_pilot_version": manifest.pilot_version,
            },
        )
    return pilot


def _walk_ids(node: Any, keys: tuple[str, ...], found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and isinstance(value, str):
                found.append(value)
            else:
                _walk_ids(value, keys, found)
    elif isinstance(node, list):
        for value in node:
            _walk_ids(value, keys, found)


def check_ownership(files: dict[str, bytes], pilot_id: str) -> None:
    """Entity ids in the package must belong to this pilot (``{pilot_id}:``)."""
    prefix = f"{pilot_id}:"
    for rel, keys in OWNED_FILES:
        data = files.get(rel)
        if data is None:
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            _reject(f"{rel} is not valid JSON: {exc}", {"format": rel})
        ids: list[str] = []
        _walk_ids(parsed, keys, ids)
        for ident in ids:
            if not ident.startswith(prefix):
                _reject(
                    f"{rel} id {ident} does not belong to {pilot_id}",
                    {"ownership": ident},
                )


def parse_members(files: dict[str, bytes]) -> None:
    """Parse GeoJSON, JSON, rasters, Parquet and GeoPackage with libraries."""
    from PIL import Image

    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 25_000_000
    try:
        for rel, data in files.items():
            suffix = "." + rel.lower().rsplit(".", 1)[-1] if "." in rel else ""
            if suffix in {".json", ".geojson"}:
                _parse_json_member(rel, data)
            elif suffix == ".parquet":
                _parse_parquet(rel, data)
            elif suffix in {".png", ".webp"}:
                _parse_image(rel, data)
            elif suffix == ".gpkg":
                _parse_gpkg(rel, data)
            elif suffix not in ALLOWED_SUFFIXES:
                _reject(f"format not allowed: {rel}", {"format": rel})
    finally:
        Image.MAX_IMAGE_PIXELS = previous


def _parse_json_member(rel: str, data: bytes) -> None:
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        _reject(f"{rel} is not valid JSON: {exc}", {"format": rel})
    if rel.endswith(".geojson"):
        if not isinstance(parsed, dict) or "type" not in parsed:
            _reject(f"{rel} is not GeoJSON", {"format": rel})
        if parsed["type"] not in {
            "FeatureCollection",
            "Feature",
            "Point",
            "LineString",
            "Polygon",
            "MultiPoint",
            "MultiLineString",
            "MultiPolygon",
            "GeometryCollection",
        }:
            _reject(f"{rel} has GeoJSON type {parsed['type']!r}", {"format": rel})


def _parse_parquet(rel: str, data: bytes) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    try:
        pq.read_schema(io.BytesIO(data))
    except (OSError, ValueError, pa.ArrowInvalid) as exc:
        _reject(f"{rel} is not a Parquet file: {exc}", {"format": rel})


def _parse_image(rel: str, data: bytes) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        _reject(f"{rel} is not a readable raster: {exc}", {"format": rel})


def _parse_gpkg(rel: str, data: bytes) -> None:
    if not data.startswith(b"SQLite format 3\x00"):
        _reject(f"{rel} is not a GeoPackage sqlite file", {"format": rel})
    fd, name = tempfile.mkstemp(prefix="aabflow-gpkg-", suffix=".gpkg")
    os.close(fd)
    path = os.fsdecode(name)
    conn: sqlite3.Connection | None = None
    try:
        with open(path, "wb") as handle:
            handle.write(data)
        # Read-only open. The only SQL is ours; archive text is not executed.
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
        row = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        _reject(f"{rel} is not a readable GeoPackage: {exc}", {"format": rel})
    finally:
        if conn is not None:
            conn.close()
        os.unlink(path)
    if row is None:
        _reject(f"{rel} has no GeoPackage catalog", {"format": rel})
