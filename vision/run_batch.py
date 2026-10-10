"""Timed Delineate Anything batch runner (executes inside the vision image).

Runs the exact upstream command ``python delineate.py -b <batch.yaml>`` from the
pinned checkout in /opt/delineate and writes a JSON run record with wall time,
device, upstream commit, checkpoint hashes, input hashes and output hashes.

Usage (from the host):
    docker compose -f compose.yaml -f vision/compose.vision.yaml --profile vision \
        run --rm --no-deps -T vision python /app/vision/run_batch.py \
        /app/vision/batches/<name>.yaml --record /app/evidence/benchmarks/<name>.json

Standard library + PyYAML only (PyYAML is an upstream requirement).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import yaml

UPSTREAM = Path("/opt/delineate")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def gpkg_count(path: Path) -> int | None:
    """Feature count of the first feature table (a GeoPackage is SQLite)."""
    import sqlite3  # noqa: PLC0415

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' LIMIT 1"
        ).fetchone()
        return None if row is None else con.execute(f'SELECT count(*) FROM "{row[0]}"').fetchone()[0]
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--record", required=True, help="where to write the JSON run record")
    ap.add_argument("--label", default=None)
    args = ap.parse_args()

    batch_path = Path(args.batch)
    batch = yaml.safe_load(batch_path.read_text())
    base = yaml.safe_load(Path(batch["base_config"]).read_text())
    models = base["model"] if isinstance(base["model"], list) else [base["model"]]

    data_root = Path(batch["data_root"])
    entries = [
        p.name
        for p in sorted(data_root.iterdir())
        if p.is_dir() and (not batch.get("include") or p.name in batch["include"])
    ]
    inputs = {
        f"{e}/{t.name}": sha256(t)
        for e in entries
        for t in sorted((data_root / e).iterdir())
        if t.suffix in (".tif", ".tiff")
    }

    import torch  # noqa: PLC0415 (vision image only)

    commit = subprocess.run(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    started = dt.datetime.now(dt.UTC)
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "delineate.py", "-b", str(batch_path.resolve())],
        cwd=UPSTREAM,
        capture_output=True,
        text=True,
    )
    wall = time.perf_counter() - t0
    finished = dt.datetime.now(dt.UTC)

    out_root = Path(batch["output_root"])
    outputs = {}
    for e in entries:
        for suffix in (".gpkg", ".simp.gpkg"):
            p = out_root / f"{e}{suffix}"
            if p.exists():
                outputs[p.name] = {
                    "sha256": sha256(p),
                    "size_bytes": p.stat().st_size,
                    "feature_count": gpkg_count(p),
                }

    log_path = Path(args.record).with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
    failed_markers = [m for m in ("Traceback", "RuntimeError", "Error:") if m in proc.stderr]

    record = {
        "label": args.label or batch_path.stem,
        "command": f"python delineate.py -b {batch_path}",
        "cwd": str(UPSTREAM),
        "upstream_commit": commit,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "wall_seconds": round(wall, 3),
        "returncode": proc.returncode,
        "stderr_error_markers": failed_markers,
        "ok": proc.returncode == 0 and not failed_markers and bool(outputs),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "torch": torch.__version__,
        "torch_threads": torch.get_num_threads(),
        "cpu_count": os.cpu_count(),
        "platform": platform.platform(),
        "shm_bytes": os.statvfs("/dev/shm").f_blocks * os.statvfs("/dev/shm").f_frsize,
        "batch_config": batch,
        "base_config_path": batch["base_config"],
        "base_config_sha256": sha256(Path(batch["base_config"])),
        "checkpoints": {m: sha256(Path(m)) for m in models if Path(m).exists()},
        "inputs": inputs,
        "outputs": outputs,
        "log": str(log_path),
    }
    Path(args.record).write_text(json.dumps(record, indent=2, default=str))
    print(json.dumps({k: record[k] for k in ("ok", "wall_seconds", "outputs", "device")}))
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
