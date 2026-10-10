"""Copy real data and a SQLite online backup into a new, independently writable store.

Run inside Docker. Quiesce writers first; active jobs/turns are rejected rather than
duplicated into a second dispatcher. Existing destinations are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


def snapshot(source: Path, destination: Path) -> dict:
    source = source.resolve()
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("snapshot destination must be outside the source")
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    db_path = source / "app.sqlite"
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    staging = destination.with_name(destination.name + ".partial")
    # Keep failed copies for diagnosis; never silently reuse one.
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as original:
        active = original.execute(
            "SELECT count(*) FROM jobs WHERE state IN ('queued','running','cancel_requested')"
        ).fetchone()[0]
        turns = original.execute(
            "SELECT count(*) FROM copilot_turns WHERE status IN ('queued','running')"
        ).fetchone()[0]
        if active or turns:
            raise ValueError(f"quiesce writers first: {active} active jobs, {turns} active turns")
        staging.mkdir(parents=True, exist_ok=False)
        with closing(sqlite3.connect(staging / "app.sqlite")) as copied:
            original.backup(copied)
            check = copied.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise ValueError(f"SQLite integrity check: {check}")
    for item in source.iterdir():
        if item.name.startswith("app.sqlite") or item.name == "snapshot.json":
            continue
        target = staging / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "source": str(source),
        "sqlite_integrity_check": "ok",
        "data_kind": "copied real runtime data; not a test fixture",
    }
    (staging / "snapshot.json").write_text(json.dumps(manifest, indent=2) + "\n")
    staging.rename(destination)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(snapshot(args.source, args.destination), indent=2))


if __name__ == "__main__":
    main()
