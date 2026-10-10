"""Export and import a completed, published pilot package (T2.6, T9.3).

This is not raw intake. A raw bundle is rejected and left for onboarding.
Publication writes a sibling ``*.import-partial`` directory, validates it, then
renames it into ``pilots/<id>/<version>``. An existing version is left unchanged.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from aabflow.api.errors import conflict, invalid, not_found, unavailable
from aabflow.domain.schemas import CONTRACT_VERSION
from aabflow.ingestion.packages.validate import validate_package
from aabflow.repositories.sqlite import utcnow
from aabflow.services.pilots import safe_id

from .archive import (
    LIMITS,
    PackageLimits,
    contained,
    directory_digest,
    files_from_directory,
    fsync_tree,
    read_archive,
    write_archive,
)
from .validate import (
    check_hashes,
    check_identity,
    check_ownership,
    parse_manifest,
    parse_members,
    reject_fetch_instructions,
    reject_raw_intake,
)

STAGE_SUFFIX = ".import-partial"
EVENT_LOG = "completed-package-events.jsonl"
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(pilots_dir: Path) -> threading.Lock:
    key = str(Path(pilots_dir).resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _summary(
    pilot_id: str, pilot_version: str, name: str, digest: str, file_count: int
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "pilot_id": pilot_id,
        "pilot_version": pilot_version,
        "name": name,
        "state": "published",
        "package_sha256": digest,
        "file_count": file_count,
        "kind": "completed_pilot_package",
    }


def _checked_version_dir(pilots_dir: Path, pilot_id: str, pilot_version: str) -> Path:
    pilot_id = safe_id(pilot_id, "pilot_id")
    pilot_version = safe_id(pilot_version, "pilot_version")
    root = Path(pilots_dir)
    version_dir = root / pilot_id / pilot_version
    if version_dir.is_symlink() or (version_dir.exists() and not contained(root, version_dir)):
        raise invalid("package path escapes the pilots directory", {"path": pilot_id})
    return version_dir


def export_completed_package(
    pilots_dir: Path, pilot_id: str, pilot_version: str
) -> tuple[bytes, dict[str, Any]]:
    """Zip one published version. Reads the directory; does not republish it."""
    version_dir = _checked_version_dir(pilots_dir, pilot_id, pilot_version)
    if not version_dir.is_dir():
        raise not_found("pilot_version", f"{pilot_id}/{pilot_version}")
    files = files_from_directory(version_dir)
    reject_fetch_instructions(files)
    reject_raw_intake(files)
    manifest = parse_manifest(files)
    check_hashes(files, manifest)
    pilot = check_identity(files, manifest, pilot_id, pilot_version)
    digest = directory_digest(files)
    if pilot.package_sha256 and pilot.package_sha256 != digest:
        raise unavailable("published package_sha256 does not match the files on disk")
    blob = write_archive(files)
    return blob, _summary(pilot_id, pilot_version, pilot.name, digest, len(files))


def _read_index(path: Path) -> tuple[str, list[dict[str, Any]]]:
    if not path.is_file():
        return "list", []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise invalid("pilots index.json is not valid JSON", {"index": "invalid"}) from exc
    if isinstance(raw, list):
        rows = raw
        shape = "list"
    elif isinstance(raw, dict) and isinstance(raw.get("pilots"), list):
        rows = raw["pilots"]
        shape = "object"
    else:
        raise invalid("pilots index.json is not a publication list", {"index": "invalid"})
    if not all(isinstance(row, dict) for row in rows):
        raise invalid("pilots index.json has a non-object row", {"index": "invalid"})
    return shape, rows


def _version_recorded(pilots_dir: Path, pilot_id: str, pilot_version: str) -> bool:
    version_dir = pilots_dir / pilot_id / pilot_version
    if version_dir.exists():
        return True
    _, rows = _read_index(pilots_dir / "index.json")
    return any(
        row.get("pilot_id") == pilot_id and row.get("pilot_version") == pilot_version
        for row in rows
    )


def _reject_existing(pilots_dir: Path, pilot_id: str, pilot_version: str) -> None:
    if _version_recorded(pilots_dir, pilot_id, pilot_version):
        raise conflict(
            f"pilot version {pilot_id}/{pilot_version} is already published",
            {"pilot_id": pilot_id, "pilot_version": pilot_version},
        )


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _write_index(pilots_dir: Path, pilot_id: str, pilot_version: str, name: str) -> None:
    path = pilots_dir / "index.json"
    shape, rows = _read_index(path)
    rows = [
        row
        for row in rows
        if not (row.get("pilot_id") == pilot_id and row.get("pilot_version") == pilot_version)
    ]
    rows.append(
        {
            "pilot_id": pilot_id,
            "pilot_version": pilot_version,
            "name": name,
            "published_at": utcnow(),
        }
    )
    rows.sort(key=lambda row: (str(row.get("pilot_id")), str(row.get("pilot_version"))))
    payload: Any = {"pilots": rows} if shape == "object" else rows
    _atomic_write(path, json.dumps(payload, indent=2) + "\n")


def _append_event(pilots_dir: Path, summary: dict[str, Any]) -> None:
    path = pilots_dir / EVENT_LOG
    line = json.dumps({**summary, "event": "completed_package_import", "at": utcnow()}) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _discard_stage(stage: Path, final: Path) -> None:
    if not stage.exists():
        return
    if stage.resolve() == final.resolve() or not stage.name.endswith(STAGE_SUFFIX):
        return
    for path in stage.rglob("*"):
        path.chmod(0o644 if path.is_file() else 0o755)
    shutil.rmtree(stage)


def _write_tree(stage: Path, files: dict[str, bytes]) -> None:
    stage.mkdir(parents=True, exist_ok=False)
    base = stage.resolve()
    for rel, data in files.items():
        dest = stage / rel
        if base not in dest.resolve().parents:
            raise invalid(f"refusing to write outside the staging package: {rel}", {"path": rel})
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
    fsync_tree(stage)


def _publication_errors(stage: Path) -> None:
    errors = validate_package(stage)
    if not errors:
        return
    text = "; ".join(errors[:8])
    field = "package"
    if any("sha256" in item for item in errors):
        field = "sha256"
    elif any("does not belong" in item for item in errors):
        field = "ownership"
    elif any("format not allowed" in item for item in errors):
        field = "format"
    elif any("traversal" in item for item in errors):
        field = "path"
    raise invalid(f"completed package failed validation: {text}", {field: errors[0]})


def import_completed_package(
    pilots_dir: Path,
    pilot_id: str,
    pilot_version: str,
    blob: bytes,
    *,
    limits: PackageLimits = LIMITS,
) -> dict[str, Any]:
    """Validate a completed-package zip and publish it immutably."""
    pilot_id = safe_id(pilot_id, "pilot_id")
    pilot_version = safe_id(pilot_version, "pilot_version")
    files = read_archive(blob, limits)
    reject_fetch_instructions(files)
    reject_raw_intake(files)
    manifest = parse_manifest(files)
    check_hashes(files, manifest)
    pilot = check_identity(files, manifest, pilot_id, pilot_version)
    check_ownership(files, pilot_id)
    parse_members(files)
    digest = directory_digest(files)
    if pilot.package_sha256 and pilot.package_sha256 != digest:
        raise invalid(
            "package_sha256 does not match package contents", {"sha256": "package_sha256"}
        )
    summary = _summary(pilot_id, pilot_version, pilot.name, digest, len(files))
    root = Path(pilots_dir)
    root.mkdir(parents=True, exist_ok=True)
    final = _checked_version_dir(root, pilot_id, pilot_version)
    stage = final.with_name(final.name + STAGE_SUFFIX)
    with _lock_for(root):
        _reject_existing(root, pilot_id, pilot_version)
        _discard_stage(stage, final)
        try:
            _write_tree(stage, files)
            _publication_errors(stage)
            _reject_existing(root, pilot_id, pilot_version)
            if final.exists():
                raise conflict(
                    f"pilot version {pilot_id}/{pilot_version} is already published",
                    {"pilot_id": pilot_id, "pilot_version": pilot_version},
                )
            os.rename(stage, final)
            parent = os.open(final.parent, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            _write_index(root, pilot_id, pilot_version, pilot.name)
            _append_event(root, summary)
        finally:
            _discard_stage(stage, final)
    return summary
