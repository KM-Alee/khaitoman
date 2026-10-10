"""ZIP encode/decode for a completed pilot package.

Archive members are data files. This module never executes a member and never
fetches a URL found in a name or a payload.
"""

from __future__ import annotations

import io
import os
import posixpath
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from aabflow.api.errors import invalid
from aabflow.domain.hashes import content_hash, file_sha256, sha256_hex

MANIFEST_NAME = "manifest.json"
BUNDLE_MANIFEST_NAME = "bundle_manifest.json"
ALLOWED_SUFFIXES = {".json", ".geojson", ".webp", ".png", ".parquet", ".gpkg"}
EXECUTABLE_SUFFIXES = {
    ".py",
    ".pyc",
    ".pyo",
    ".sh",
    ".bash",
    ".exe",
    ".so",
    ".dll",
    ".js",
    ".bat",
    ".command",
    ".ps1",
}
ZIP_DATE = (2026, 1, 1, 0, 0, 0)
_ALLOWED_COMPRESS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}


@dataclass(frozen=True)
class PackageLimits:
    """Production caps. Real published pilots sit far under each one."""

    max_file_bytes: int = 100 * 1024 * 1024
    max_expanded_bytes: int = 256 * 1024 * 1024
    max_archive_bytes: int = 64 * 1024 * 1024
    max_members: int = 512
    max_ratio: float = 200.0


LIMITS = PackageLimits()


def _reject(detail: str, fields: dict[str, str]):
    raise invalid(detail, fields)


def member_path(name: str) -> str:
    """Return a normalized relative member name, or reject traversal and URLs."""
    if not isinstance(name, str) or not name or name in {".", ".."}:
        _reject("archive member path is empty", {"path": name or ""})
    if "\\" in name or "\x00" in name:
        _reject(f"archive member path is not a relative package path: {name}", {"path": name})
    lowered = name.lower()
    if "://" in name or lowered.startswith(("http:", "https:")):
        _reject(
            "archive member names an embedded URL; completed-package import does not fetch it",
            {"fetch_url": name},
        )
    if name.startswith(("~", "/")):
        _reject(f"absolute archive path is not allowed: {name}", {"path": name})
    pure = PurePosixPath(name)
    if pure.is_absolute():
        _reject(f"absolute archive path is not allowed: {name}", {"path": name})
    norm = posixpath.normpath(name)
    if norm != name or norm in {"", ".", ".."} or norm.startswith("../") or "/../" in f"/{norm}/":
        _reject(f"archive path escapes the package: {name}", {"path": name})
    return norm


def _suffix(rel: str) -> str:
    return PurePosixPath(rel).suffix.lower()


def _reject_format(rel: str) -> None:
    suffix = _suffix(rel)
    if suffix in EXECUTABLE_SUFFIXES:
        _reject(
            f"executable archive member {rel} is not a package format and is not run",
            {"format": rel},
        )
    if suffix not in ALLOWED_SUFFIXES:
        _reject(f"format not allowed: {rel}", {"format": rel})


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _declared_members(
    zf: zipfile.ZipFile, limits: PackageLimits
) -> list[tuple[zipfile.ZipInfo, str]]:
    infos = zf.infolist()
    if len(infos) > limits.max_members:
        _reject(
            f"archive has {len(infos)} members; limit is {limits.max_members}",
            {"archive": "too many members"},
        )
    selected: list[tuple[zipfile.ZipInfo, str]] = []
    seen: set[str] = set()
    declared = 0
    for info in infos:
        raw_name = info.orig_filename if hasattr(info, "orig_filename") else info.filename
        if info.flag_bits & 0x1:
            _reject("encrypted archive members are rejected", {"archive": "encrypted"})
        if info.compress_type not in _ALLOWED_COMPRESS:
            _reject(
                f"compression method {info.compress_type} is not allowed",
                {"format": info.filename},
            )
        if _is_symlink(info):
            _reject(f"symlink archive member is rejected: {info.filename}", {"path": info.filename})
        directory = raw_name.endswith("/") or info.is_dir()
        name = raw_name[:-1] if directory and raw_name.endswith("/") else raw_name
        if directory and not name:
            continue
        rel = member_path(name)
        if directory:
            continue
        if rel.lower() in seen:
            _reject(f"duplicate archive member {rel}", {"files": rel})
        seen.add(rel.lower())
        _reject_format(rel)
        if info.file_size > limits.max_file_bytes:
            _reject(
                f"{rel} declares {info.file_size} bytes; file limit is {limits.max_file_bytes}",
                {"expanded_bytes": rel},
            )
        declared += info.file_size
        if declared > limits.max_expanded_bytes:
            _reject(
                f"archive expands past {limits.max_expanded_bytes} bytes",
                {"expanded_bytes": str(declared)},
            )
        compressed = max(info.compress_size, 1)
        if info.file_size > 1024 and (info.file_size / compressed) > limits.max_ratio:
            _reject(
                f"{rel} compression ratio exceeds {limits.max_ratio}",
                {"expanded_bytes": rel},
            )
        selected.append((info, rel))
    return selected


def _read_member(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, rel: str, limits: PackageLimits
) -> bytes:
    chunks: list[bytes] = []
    got = 0
    try:
        with zf.open(info, "r") as src:
            while True:
                block = src.read(1 << 20)
                if not block:
                    break
                got += len(block)
                if got > limits.max_file_bytes:
                    _reject(
                        f"{rel} exceeds the {limits.max_file_bytes} byte file limit",
                        {"expanded_bytes": rel},
                    )
                chunks.append(block)
    except zipfile.BadZipFile as exc:
        _reject(f"archive member {rel} is not a valid zip payload: {exc}", {"format": rel})
    data = b"".join(chunks)
    if info.file_size and len(data) != info.file_size:
        _reject(
            f"{rel} expanded to {len(data)} bytes, header declared {info.file_size}",
            {"expanded_bytes": rel},
        )
    return data


def read_archive(blob: bytes, limits: PackageLimits = LIMITS) -> dict[str, bytes]:
    """Validate zip structure and return member bytes. Writes nothing."""
    if not blob:
        _reject("package archive is empty", {"archive": "empty"})
    if len(blob) > limits.max_archive_bytes:
        _reject(
            f"compressed archive is {len(blob)} bytes; limit is {limits.max_archive_bytes}",
            {"archive_bytes": str(len(blob))},
        )
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        _reject(f"package is not a valid zip archive: {exc}", {"format": "zip"})
    with zf:
        selected = _declared_members(zf, limits)
        files: dict[str, bytes] = {}
        expanded = 0
        for info, rel in selected:
            data = _read_member(zf, info, rel, limits)
            expanded += len(data)
            if expanded > limits.max_expanded_bytes:
                _reject(
                    f"archive expands past {limits.max_expanded_bytes} bytes",
                    {"expanded_bytes": str(expanded)},
                )
            files[rel] = data
    if MANIFEST_NAME not in files and BUNDLE_MANIFEST_NAME not in files:
        _reject(
            "archive has no completed-package manifest.json",
            {"manifest_version": "missing"},
        )
    return files


def write_archive(files: dict[str, bytes]) -> bytes:
    """Build a deterministic deflated zip of relative package files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for rel in sorted(files):
            member_path(rel)
            _reject_format(rel)
            info = zipfile.ZipInfo(filename=rel, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            zf.writestr(info, files[rel])
    return buf.getvalue()


def files_from_directory(root: Path) -> dict[str, bytes]:
    """Read a published package directory. Symlinks and escapes are rejected."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        _reject(f"package directory is not a real directory: {root.name}", {"path": root.name})
    base = root.resolve()
    files: dict[str, bytes] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink()):
        if path.is_symlink():
            _reject(f"package contains a symlink: {path.name}", {"path": path.name})
        rel = path.relative_to(root).as_posix()
        member_path(rel)
        resolved = path.resolve()
        if base != resolved and base not in resolved.parents:
            _reject(f"package file escapes the version directory: {rel}", {"path": rel})
        files[rel] = path.read_bytes()
    return files


def directory_digest(files: dict[str, bytes]) -> str:
    """Hash of path/content pairs excluding pilot.json and manifest.json.

    This is the publisher's ``package_sha256`` (content hashed before those two
    files were written).
    """
    rows = sorted(
        (rel, sha256_hex(data))
        for rel, data in files.items()
        if rel not in {"pilot.json", MANIFEST_NAME}
    )
    return content_hash(rows)


def disk_package_hash(root: Path) -> str:
    excluded = {"pilot.json", MANIFEST_NAME}
    rows = sorted(
        (path.relative_to(root).as_posix(), file_sha256(path))
        for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.relative_to(root).as_posix() not in excluded
    )
    return content_hash(rows)


def contained(parent: Path, child: Path) -> bool:
    parent_r = parent.resolve()
    child_r = child.resolve()
    return child_r == parent_r or parent_r in child_r.parents


def fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    dir_fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
