"""Raw source bundles (T2.6): immutable acquisition output that processing reads.

Online acquisition and the offline "prepared raw package" path both produce and
consume the same layout, so the second pilot re-enters the real processing,
review and publication code::

    data/raw/bundles/<pilot_id>/<bundle_id>/
        bundle_manifest.json   # files with sha256/size/kind/source/license
        aoi.geojson
        stac/…  sentinel2/<scene>/…  osm/…  grain/…  weather/…  terrain/…

Import checks: manifest version, relative paths without traversal, duplicate
names, per-file and total size limits, allowed formats, and hashes. Bundles are
parsed with libraries only; nothing from a bundle is executed.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from aabflow.domain.hashes import file_sha256, sha256_hex

from ..common import IngestionError, RawStore, dumps, read_json, utc_now

BUNDLE_VERSION = "1"
ALLOWED_SUFFIXES = {".json", ".geojson", ".tif", ".tiff", ".txt", ".parquet", ".xml"}
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


class BundleError(IngestionError):
    pass


def safe_relpath(p: str) -> str:
    """Reject absolute paths, traversal, backslashes and empty segments."""
    if not p or "\\" in p or "\x00" in p:
        raise BundleError(f"invalid path {p!r}")
    pp = PurePosixPath(p)
    if pp.is_absolute() or p.startswith("~"):
        raise BundleError(f"absolute path not allowed: {p}")
    norm = posixpath.normpath(p)
    if norm != p or norm.startswith("..") or "/../" in f"/{norm}/" or norm == ".":
        raise BundleError(f"path traversal or non-normalized path: {p}")
    return norm


@dataclass
class BundleFile:
    path: str
    kind: str
    sha256: str
    size_bytes: int
    source_url: str | None = None
    retrieved_at: str | None = None
    license_id: str | None = None
    note: str | None = None


@dataclass
class BundleWriter:
    store: RawStore
    pilot_id: str
    bundle_id: str
    files: list[BundleFile] = field(default_factory=list)
    sources: dict[str, Any] = field(default_factory=dict)

    @property
    def prefix(self) -> str:
        return f"bundles/{self.pilot_id}/{self.bundle_id}"

    @property
    def root(self) -> Path:
        return self.store.path(self.prefix)

    def add_bytes(self, rel: str, content: bytes, kind: str, **meta) -> BundleFile:
        rel = safe_relpath(rel)
        if any(f.path == rel for f in self.files):
            raise BundleError(f"duplicate bundle path {rel}")
        _, digest = self.store.put(f"{self.prefix}/{rel}", content)
        bf = BundleFile(rel, kind, digest, len(content), **meta)
        self.files.append(bf)
        return bf

    def add_json(self, rel: str, obj: Any, kind: str, **meta) -> BundleFile:
        return self.add_bytes(rel, dumps(obj).encode(), kind, **meta)

    def add_file(self, rel: str, path: Path, kind: str, **meta) -> BundleFile:
        return self.add_bytes(rel, Path(path).read_bytes(), kind, **meta)

    def finalize(self, aoi_gj: dict, extra: dict | None = None) -> Path:
        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "bundle_id": self.bundle_id,
            "pilot_id": self.pilot_id,
            "created_at": utc_now(),
            "aoi": aoi_gj,
            "files": [vars(f) for f in sorted(self.files, key=lambda f: f.path)],
            "sources": self.sources,
            **(extra or {}),
        }
        p, _ = self.store.put(f"{self.prefix}/bundle_manifest.json", dumps(manifest).encode())
        return p


@dataclass
class Bundle:
    root: Path
    manifest: dict

    def path(self, rel: str) -> Path:
        return self.root / safe_relpath(rel)

    def files_of(self, kind: str) -> list[dict]:
        return [f for f in self.manifest["files"] if f["kind"] == kind]

    def one(self, kind: str) -> dict:
        fs = self.files_of(kind)
        if len(fs) != 1:
            raise BundleError(f"expected exactly one {kind!r} file, found {len(fs)}")
        return fs[0]

    def read_json(self, rel: str) -> Any:
        return read_json(self.path(rel))

    @property
    def created_at(self) -> datetime:
        return datetime.fromisoformat(str(self.manifest["created_at"]).replace("Z", "+00:00"))


def validate_bundle(root: Path, *, check_hashes: bool = True) -> Bundle:
    """Validate a raw bundle before any parsing (T2.6 import rules)."""
    root = Path(root)
    mp = root / "bundle_manifest.json"
    if not mp.is_file():
        raise BundleError(f"{root}: no bundle_manifest.json")
    if mp.stat().st_size > 16 * 1024 * 1024:
        raise BundleError("bundle manifest too large")
    m = read_json(mp)
    if m.get("bundle_version") != BUNDLE_VERSION:
        raise BundleError(f"unsupported bundle_version {m.get('bundle_version')!r}")
    for key in ("bundle_id", "pilot_id", "files", "aoi", "created_at"):
        if key not in m:
            raise BundleError(f"bundle manifest missing {key!r}")
    seen: set[str] = set()
    total = 0
    for f in m["files"]:
        rel = safe_relpath(f["path"])
        if rel.lower() in seen:
            raise BundleError(f"duplicate file {rel}")
        seen.add(rel.lower())
        if PurePosixPath(rel).suffix.lower() not in ALLOWED_SUFFIXES:
            raise BundleError(f"format not allowed: {rel}")
        if not (isinstance(f.get("size_bytes"), int) and 0 <= f["size_bytes"] <= MAX_FILE_BYTES):
            raise BundleError(f"file size out of bounds: {rel}")
        total += f["size_bytes"]
        p = (root / rel).resolve()
        if not str(p).startswith(str(root.resolve()) + "/"):
            raise BundleError(f"path escapes bundle: {rel}")
        if p.is_symlink() or not p.is_file():
            raise BundleError(f"missing or non-regular file: {rel}")
        if p.stat().st_size != f["size_bytes"]:
            raise BundleError(f"size mismatch: {rel}")
        if check_hashes and file_sha256(p) != f["sha256"]:
            raise BundleError(f"sha256 mismatch: {rel}")
    if total > MAX_TOTAL_BYTES:
        raise BundleError(f"bundle expands to {total} bytes > limit {MAX_TOTAL_BYTES}")
    listed = seen | {"bundle_manifest.json"}
    for p in root.rglob("*"):
        if p.is_file() and str(p.relative_to(root)).lower() not in listed:
            raise BundleError(f"unlisted file in bundle: {p.relative_to(root)}")
    return Bundle(root=root, manifest=m)


def bundle_id_for(pilot_id: str, aoi_gj: dict, when: datetime) -> str:
    return f"{when:%Y%m%dT%H%M%SZ}-{sha256_hex(dumps(aoi_gj))[:8]}"
