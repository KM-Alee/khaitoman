"""Completed-package ZIP checks against the published pilot-a package.

Hostile archives are synthetic. The round trip reads ``data/pilots`` and writes
only under pytest's temporary directory.
"""

from __future__ import annotations

import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

from aabflow.api.errors import DomainError
from aabflow.domain.hashes import file_sha256, sha256_hex
from aabflow.domain.schemas import ErrorCode
from aabflow.ingestion.packages.validate import ALLOWED_SUFFIXES as PUBLISHED_SUFFIXES
from aabflow.services.packages import export_completed_package, import_completed_package
from aabflow.services.packages.archive import (
    ALLOWED_SUFFIXES,
    LIMITS,
    PackageLimits,
    directory_digest,
    read_archive,
    write_archive,
)
from aabflow.services.pilots import PilotRepository

ROOT = Path(__file__).resolve().parents[2]
PILOTS = ROOT / "data" / "pilots"
SRC = PILOTS / "pilot-a" / "reviewed-v1"


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_sha256(path)
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _zip(members: list[tuple[str, bytes]], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, data in members:
            info = zipfile.ZipInfo(filename=name)
            if symlink == name:
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, data)
    return buf.getvalue()


def _raises(blob: bytes, field: str, tmp_path: Path, **kwargs) -> DomainError:
    with pytest.raises(DomainError) as caught:
        import_completed_package(tmp_path / "pilots", "pilot-z", "v1", blob, **kwargs)
    err = caught.value
    assert err.code == ErrorCode.INVALID_INPUT, err.body()
    assert field in err.fields, err.body()
    assert not (tmp_path / "pilots" / "pilot-z" / "v1").exists()
    assert not (tmp_path / "pilots" / "pilot-z" / "v1.import-partial").exists()
    return err


def test_allowed_formats_match_the_publisher():
    assert ALLOWED_SUFFIXES == set(PUBLISHED_SUFFIXES)
    assert LIMITS.max_file_bytes == 100 * 1024 * 1024
    assert LIMITS.max_expanded_bytes == 256 * 1024 * 1024
    assert LIMITS.max_archive_bytes == 64 * 1024 * 1024


def test_real_package_round_trip_is_immutable(tmp_path, monkeypatch):
    import socket

    def blocked(*_args, **_kwargs):
        raise AssertionError("completed-package import opened a connection")

    monkeypatch.setattr(socket, "create_connection", blocked)
    before = file_sha256(SRC / "manifest.json")
    declared = json.loads((SRC / "pilot.json").read_text())["package_sha256"]
    blob, summary = export_completed_package(PILOTS, "pilot-a", "reviewed-v1")
    assert summary["kind"] == "completed_pilot_package"
    assert summary["state"] == "published"
    assert summary["package_sha256"] == declared
    assert export_completed_package(PILOTS, "pilot-a", "reviewed-v1")[0] == blob
    assert len(blob) < LIMITS.max_archive_bytes

    dest = tmp_path / "pilots"
    published = import_completed_package(dest, "pilot-a", "reviewed-v1", blob)
    imported = dest / "pilot-a" / "reviewed-v1"
    assert published == summary
    assert _hashes(imported) == _hashes(SRC)
    assert file_sha256(SRC / "manifest.json") == before
    package = PilotRepository(dest).package("pilot-a", "reviewed-v1")
    assert package.package_hash == declared
    assert len(package.fields) == 30
    event = json.loads((dest / "completed-package-events.jsonl").read_text().strip())
    assert event["event"] == "completed_package_import"
    assert not (dest / ".intake").exists()
    assert not (tmp_path / "onboarding").exists()

    with pytest.raises(DomainError) as caught:
        import_completed_package(dest, "pilot-a", "reviewed-v1", blob)
    assert caught.value.code == ErrorCode.VERSION_CONFLICT
    assert _hashes(imported) == _hashes(SRC)
    assert (dest / "completed-package-events.jsonl").read_text().count("\n") == 1


def test_index_entry_without_a_directory_is_still_an_existing_version(tmp_path):
    blob, _summary = export_completed_package(PILOTS, "pilot-a", "reviewed-v1")
    dest = tmp_path / "pilots"
    dest.mkdir()
    (dest / "index.json").write_text(
        json.dumps([{"pilot_id": "pilot-a", "pilot_version": "reviewed-v1", "name": "pilot-a"}]),
        encoding="utf-8",
    )
    with pytest.raises(DomainError) as caught:
        import_completed_package(dest, "pilot-a", "reviewed-v1", blob)
    assert caught.value.code == ErrorCode.VERSION_CONFLICT
    assert not (dest / "pilot-a" / "reviewed-v1").exists()


def test_failed_publication_removes_the_partial_tree(tmp_path):
    blob, _summary = export_completed_package(PILOTS, "pilot-a", "reviewed-v1")
    files = read_archive(blob)
    files.pop("roster.json")
    manifest = json.loads(files["manifest.json"])
    manifest["files"] = [item for item in manifest["files"] if item["path"] != "roster.json"]
    digest = directory_digest(files)
    pilot = files["pilot.json"]
    declared = json.loads(pilot)["package_sha256"].encode()
    files["pilot.json"] = pilot.replace(declared, digest.encode())
    for item in manifest["files"]:
        if item["path"] == "pilot.json":
            item["size_bytes"] = len(files["pilot.json"])
            item["sha256"] = sha256_hex(files["pilot.json"])
    files["manifest.json"] = json.dumps(manifest).encode()
    broken = write_archive(files)
    dest = tmp_path / "pilots"
    with pytest.raises(DomainError) as caught:
        import_completed_package(dest, "pilot-a", "reviewed-v1", broken)
    assert caught.value.code == ErrorCode.INVALID_INPUT
    assert "roster.json" in caught.value.detail
    assert list(dest.rglob("*.import-partial")) == []
    assert not (dest / "pilot-a" / "reviewed-v1").exists()
    assert not (dest / "index.json").exists()


def test_hash_mismatch_and_wrong_manifest_version(tmp_path):
    blob, _summary = export_completed_package(PILOTS, "pilot-a", "reviewed-v1")
    files = read_archive(blob)
    needle = b"FeatureCollection"
    assert needle in files["aoi.geojson"]
    files["aoi.geojson"] = files["aoi.geojson"].replace(needle, b"FeatureCollectioX", 1)
    mismatched = write_archive(files)
    err = _raises(mismatched, "sha256", tmp_path)
    assert "aoi.geojson" in err.detail

    files = read_archive(blob)
    manifest = json.loads(files["manifest.json"])
    manifest["manifest_version"] = "9"
    files["manifest.json"] = json.dumps(manifest).encode()
    err = _raises(write_archive(files), "manifest_version", tmp_path)
    assert err.fields["manifest_version"] == "9"


def test_ownership_rejects_a_foreign_entity_and_a_foreign_path(tmp_path):
    blob, _summary = export_completed_package(PILOTS, "pilot-a", "reviewed-v1")
    dest = tmp_path / "pilots"
    with pytest.raises(DomainError) as caught:
        import_completed_package(dest, "pilot-b", "reviewed-v1", blob)
    assert caught.value.code == ErrorCode.VERSION_CONFLICT
    assert caught.value.extra["dependency_diff"]["path_pilot_id"] == "pilot-b"
    assert not (dest / "pilot-b").exists()
    assert not (dest / "pilot-a").exists()

    files = read_archive(blob)
    files["network.json"] = files["network.json"].replace(
        b"pilot-a:node-source", b"pilot-b:node-source"
    )
    manifest = json.loads(files["manifest.json"])
    for item in manifest["files"]:
        if item["path"] == "network.json":
            item["size_bytes"] = len(files["network.json"])
            item["sha256"] = sha256_hex(files["network.json"])
    files["manifest.json"] = json.dumps(manifest).encode()
    with pytest.raises(DomainError) as caught:
        import_completed_package(dest, "pilot-a", "reviewed-v1", write_archive(files))
    assert caught.value.code == ErrorCode.INVALID_INPUT
    assert "ownership" in caught.value.fields
    assert not (dest / "pilot-a" / "reviewed-v1").exists()


def test_hostile_zip_cases_write_nothing(tmp_path):
    marker = tmp_path / "archive-was-executed"
    payload = f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\n".encode()
    cases = {
        "path": _zip([("../outside.json", b"{}"), ("foo/../../outside.json", b"{}")]),
        "files": _zip([("a.json", b"{}"), ("a.json", b"{}")]),
        "format": _zip([("run.py", payload)]),
        "path_link": _zip([("link.json", b"../outside.json")], symlink="link.json"),
        "fetch_url": _zip([("https://evil.example/a.json", b"{}")]),
    }
    # The symlink case reports path; the URL case reports fetch_url.
    expected = {
        "path": "path",
        "files": "files",
        "format": "format",
        "path_link": "path",
        "fetch_url": "fetch_url",
    }
    for name, blob in cases.items():
        _raises(blob, expected[name], tmp_path)
    assert not marker.exists()
    assert list(tmp_path.rglob("outside.json")) == []
    assert list(tmp_path.rglob("run.py")) == []

    fetch = write_archive(
        {
            "manifest.json": b'{"manifest_version":"1"}',
            "note.json": b'{"fetch_url":"http://127.0.0.1:9/do-not-get"}',
        }
    )
    err = _raises(fetch, "fetch_url", tmp_path)
    assert "127.0.0.1" not in err.detail
    assert "does not request" in err.detail

    raw = write_archive({"bundle_manifest.json": b'{"bundle_version":"1","files":[]}'})
    err = _raises(raw, "kind", tmp_path)
    assert err.fields["kind"] == "raw_intake"
    assert "onboarding" in err.detail


def test_compressed_and_expanded_oversize(tmp_path):
    small = write_archive({"manifest.json": b'{"manifest_version":"1"}', "note.json": b"{}"})
    _raises(small, "archive_bytes", tmp_path, limits=PackageLimits(max_archive_bytes=16))
    wide = write_archive({"manifest.json": b"{}", "note.json": b"x" * 80})
    _raises(
        wide,
        "expanded_bytes",
        tmp_path,
        limits=PackageLimits(
            max_archive_bytes=10_000, max_expanded_bytes=40, max_file_bytes=10_000
        ),
    )
    zeros = write_archive({"manifest.json": b"{}", "note.json": b"0" * 8000})
    _raises(
        zeros,
        "expanded_bytes",
        tmp_path,
        limits=PackageLimits(
            max_archive_bytes=100_000,
            max_expanded_bytes=1_000_000,
            max_file_bytes=1_000_000,
            max_ratio=3,
        ),
    )


def test_bad_parquet_and_geojson_are_not_executed(tmp_path):
    geo = b"this is not geojson and not code"
    manifest = {
        "manifest_version": "1",
        "pilot_id": "pilot-z",
        "pilot_version": "v1",
        "state": "published",
        "files": [
            {
                "path": "fields.geojson",
                "size_bytes": len(geo),
                "sha256": sha256_hex(geo),
                "kind": "bad",
            }
        ],
        "source_ids": [],
        "licenses": [],
        "processing_versions": {},
        "generated_at": "2026-10-10T00:00:00Z",
    }
    blob = write_archive({"manifest.json": json.dumps(manifest).encode(), "fields.geojson": geo})
    _raises(blob, "format", tmp_path)

    table = b"not parquet"
    aoi = b'{"type":"FeatureCollection","features":[]}'
    pilot = {
        "pilot_id": "pilot-z",
        "pilot_version": "v1",
        "name": "z",
        "geographic_name_basis": "synthetic hostile package",
        "aoi_geojson_ref": "aoi.geojson",
        "aoi_bbox": [0, 0, 1, 1],
        "aoi_area_m2": 1,
        "metric_crs": "EPSG:32643",
        "timezone": "Asia/Karachi",
        "state": "published",
        "review_flags": {
            "geography_reviewed": False,
            "topology_structurally_valid": False,
            "rights_verification": "assumed",
            "cost_evidence": "assumed",
            "crop_calibration": "uncalibrated",
        },
        "created_at": "2026-10-10T00:00:00Z",
    }
    pilot_bytes = json.dumps(pilot).encode()
    listed = {
        "aoi.geojson": aoi,
        "pilot.json": pilot_bytes,
        "weather.parquet": table,
    }
    body = {
        "manifest_version": "1",
        "pilot_id": "pilot-z",
        "pilot_version": "v1",
        "state": "published",
        "files": [
            {"path": rel, "size_bytes": len(data), "sha256": sha256_hex(data), "kind": rel}
            for rel, data in sorted(listed.items())
        ],
        "source_ids": [],
        "licenses": [],
        "processing_versions": {},
        "generated_at": "2026-10-10T00:00:00Z",
    }
    _raises(
        write_archive({"manifest.json": json.dumps(body).encode(), **listed}),
        "format",
        tmp_path,
    )
    assert list(tmp_path.rglob("*.parquet")) == []
    assert list(tmp_path.rglob("run.py")) == []
