"""Flag candidate libraries that belong to an older pilot version (PRD §5.3).

An older library stays on disk for the version it was built for. Publishing a
new pilot version records it as flagged and not current. Readiness for baseline
and candidate jobs follows that flag; this module does not rebuild libraries
and does not rewrite ``latest.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..common import write_json


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _families(library: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for row in library.get("coverage") or []:
        found.update((row.get("families") or {}).keys())
    return found


def library_flags(libraries_dir: Path, pilot_id: str, pilot_version: str) -> list[dict[str, Any]]:
    root = Path(libraries_dir) / pilot_id
    if not root.is_dir():
        return []
    flags: list[dict[str, Any]] = []
    for season in sorted(path for path in root.iterdir() if path.is_dir()):
        latest_path = season / "latest.json"
        if not latest_path.is_file():
            continue
        latest = _load(latest_path)
        library_hash = latest.get("candidate_library_hash")
        library_version = latest.get("pilot_version")
        families: set[str] = set()
        library_path = season / str(library_hash) / "library.json" if library_hash else None
        if library_path is not None and library_path.is_file():
            document = _load(library_path)
            library_version = document.get("pilot_version") or library_version
            families = _families(document)
        current = library_version == pilot_version
        flags.append(
            {
                "season_id": season.name,
                "candidate_library_hash": library_hash,
                "library_pilot_version": library_version,
                "published_pilot_version": pilot_version,
                "status": "current" if current else "flagged_incompatible",
                "current": current,
                "has_baseline": "baseline_B0" in families,
                "has_candidates": bool(families - {"baseline_B0"}),
            }
        )
    return flags


def assess(data_dir: Path, pilot_id: str, pilot_version: str) -> dict[str, Any]:
    flags = library_flags(Path(data_dir) / "libraries", pilot_id, pilot_version)
    matching = [row for row in flags if row["current"]]
    if not flags:
        baseline = {"ready": False, "reason": "no candidate library is published for this pilot"}
        candidates = {"ready": False, "reason": "no candidate library is published for this pilot"}
    elif not matching:
        baseline = {
            "ready": False,
            "reason": "older libraries are flagged and are not the current baseline",
        }
        candidates = {
            "ready": False,
            "reason": "older libraries are flagged and are not the current candidate library",
        }
    else:
        baseline_ready = all(row["has_baseline"] for row in matching)
        candidate_ready = all(row["has_candidates"] for row in matching)
        baseline = {
            "ready": baseline_ready,
            "reason": "baseline policies match this pilot version"
            if baseline_ready
            else "matching library has no baseline_B0 policies",
        }
        candidates = {
            "ready": candidate_ready,
            "reason": "candidate policies match this pilot version"
            if candidate_ready
            else "matching library has no non-baseline candidates",
        }
    return {
        "pilot_id": pilot_id,
        "pilot_version": pilot_version,
        "reused_as_current": False,
        "libraries": flags,
        "baseline": baseline,
        "candidates": candidates,
        "jobs": [
            {
                "operation": "onboarding.baseline",
                "ready": baseline["ready"],
                "reason": baseline["reason"],
            },
            {
                "operation": "onboarding.candidates",
                "ready": candidates["ready"],
                "reason": candidates["reason"],
            },
        ],
    }


def write_readiness(data_dir: Path, pilot_id: str, pilot_version: str) -> dict[str, Any]:
    """Record flags beside the pilot, not inside an immutable version directory."""
    report = assess(data_dir, pilot_id, pilot_version)
    root = Path(data_dir) / "pilots" / pilot_id
    write_json(root / "library_flags.json", report)
    write_json(root / f"readiness-{pilot_version}.json", report)
    return report
