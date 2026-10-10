"""Raw source bundles (T2.6). This is not the finished-pilot ZIP importer."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from aabflow.domain.hashes import file_sha256

from ..common import read_json

_PREFIXES = ("data/raw/bundles/", "raw/bundles/")


class RawIntakeError(ValueError):
    """A raw-package reference is missing, unsafe, or not a raw source bundle."""

    def __init__(self, detail: str, fields: dict[str, str] | None = None):
        super().__init__(detail)
        self.detail = detail
        self.fields = fields or {}


def reject_package_ref(ref: str, field: str = "raw_package_id") -> None:
    """Reject empty refs, archives, absolute paths, and traversal before any read."""
    if not isinstance(ref, str) or not ref or ref != ref.strip():
        raise RawIntakeError("raw package reference is empty", {field: "required"})
    if "\x00" in ref or "\\" in ref or ref.startswith(("/", "~")):
        raise RawIntakeError(
            "raw package path is absolute or contains a forbidden character",
            {field: "path traversal"},
        )
    if any(part in ("", ".", "..") for part in PurePosixPath(ref).parts):
        raise RawIntakeError("raw package path traversal is rejected", {field: "path traversal"})
    if any(ch in ref for ch in "*?[]"):
        raise RawIntakeError("raw package reference cannot contain a glob", {field: ref})
    lower = ref.lower()
    if lower.endswith(".zip") or ".zip" in PurePosixPath(lower).suffixes:
        raise RawIntakeError(
            "raw intake is not the completed-package ZIP importer",
            {field: "finished zip"},
        )
    if "pilots" in PurePosixPath(ref).parts or "reviewed-" in PurePosixPath(ref).name:
        raise RawIntakeError(
            "finished pilot packages are not raw intake; choose a raw source bundle",
            {field: "finished package"},
        )


def raw_roots(data_dir: Path, repo_root: Path) -> list[Path]:
    found: list[Path] = []
    for candidate in (
        Path(data_dir) / "raw" / "bundles",
        Path(repo_root) / "data" / "raw" / "bundles",
    ):
        resolved = candidate.resolve()
        if resolved.is_dir() and resolved not in found:
            found.append(resolved)
    return found


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _bundle_ref(bundle_root: Path, repo_root: Path, data_dir: Path) -> str:
    resolved = bundle_root.resolve()
    try:
        return resolved.relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        return resolved.relative_to(Path(data_dir).resolve()).as_posix()


def iter_bundles(data_dir: Path, repo_root: Path) -> list[dict]:
    """List immutable raw bundles. Published pilot versions are not included."""
    rows: list[dict] = []
    seen: set[Path] = set()
    for root in raw_roots(data_dir, repo_root):
        for manifest in sorted(root.glob("*/*/bundle_manifest.json")):
            bundle_root = manifest.parent.resolve()
            if bundle_root in seen or not _under(bundle_root, root):
                continue
            if len(bundle_root.relative_to(root).parts) != 2:
                continue
            seen.add(bundle_root)
            meta = read_json(manifest)
            rows.append(
                {
                    "bundle_id": meta.get("bundle_id"),
                    "pilot_id": meta.get("pilot_id"),
                    "bundle_ref": _bundle_ref(bundle_root, repo_root, data_dir),
                    "created_at": meta.get("created_at"),
                    "manifest_sha256": file_sha256(manifest),
                    "intake_kind": "raw_source_bundle",
                }
            )
    rows.sort(key=lambda row: (str(row["pilot_id"]), str(row["bundle_id"])))
    return rows


def _candidates(ref: str, data_dir: Path, repo_root: Path) -> list[Path]:
    roots = raw_roots(data_dir, repo_root)
    found: list[Path] = []
    remainder = ref
    for prefix in _PREFIXES:
        if ref.startswith(prefix):
            remainder = ref[len(prefix) :]
            break
    parts = PurePosixPath(remainder).parts
    if len(parts) == 2:
        found.extend(root / remainder for root in roots)
    elif len(parts) == 1 and "/" not in remainder:
        for root in roots:
            if not root.is_dir():
                continue
            for pilot in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
                found.append(pilot / remainder)
    return found


def resolve_raw_package(ref: str, *, data_dir: Path, repo_root: Path) -> tuple[Path, str]:
    """Return the bundle directory and the ref stored on the intake."""
    reject_package_ref(ref)
    if not raw_roots(data_dir, repo_root):
        raise RawIntakeError("no raw source bundles are available", {"raw_package_id": ref})
    seen: set[Path] = set()
    for candidate in _candidates(ref, data_dir, repo_root):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if not any(_under(resolved, root) for root in raw_roots(data_dir, repo_root)):
            raise RawIntakeError(
                "raw package path escapes the raw bundle store",
                {"raw_package_id": "path traversal"},
            )
        manifest = resolved / "bundle_manifest.json"
        if manifest.is_file() and not manifest.is_symlink():
            return resolved, _bundle_ref(resolved, repo_root, data_dir)
    raise RawIntakeError(f"unknown raw source bundle {ref!r}", {"raw_package_id": ref})


def resolve_stored_bundle(ref: str, repo_root: Path, data_dir: Path | None = None) -> Path:
    """Resolve an intake's stored bundle ref. Refuses traversal and pilot packages."""
    data = Path(data_dir) if data_dir is not None else Path(repo_root) / "data"
    root, _stored = resolve_raw_package(ref, data_dir=data, repo_root=Path(repo_root))
    return root
